"""Phase 3 — the voice channel: tool-less, streaming, conversational (KRC item 12, fork ②).

Registered as the bus's command handler. For each accepted command it:

  1. Stand-in fast path (item 17) — a deterministic, pre-LLM answer to "any updates from
     people who couldn't make it". No model touches stand-in text.
  2. Talk-vs-dispatch — one streaming Groq call (tool-less). The model either answers
     conversationally (streamed sentence-by-sentence into TTS) or emits the dispatch
     token alone, meaning "this needs a tool" → the command goes to the agent channel.
  3. Narration — on the agent's `done` it speaks a condensed result + posts the full text
     to chat; on `blocked` it says the capability isn't connected. A chat ack ("⏳ on it")
     fires only if the agent hasn't finished within ~1.5s (item 23, fork ③) — no spoken
     filler, ever.

Voice replies stream via Groq with NO tools in that call path — the exit criterion. The
agent channel round-trip is the ONLY way an action or lookup happens (voice reads results,
never calls tools). from_chat commands are answered in chat only — never spoken.

Speaking goes through `voice.bridge.speak`, which no-ops (returns False) when no live
pipeline is attached, so this module is safe to run in tests / without Recall audio.
"""

from __future__ import annotations

import asyncio
import os
import time

from voice import bus, prompts
from voice.prompts import DISPATCH_TOKEN
from voice_pipeline import StreamingSegmenter, TtsDispatcher

_VOICE_MODEL = os.getenv("PRISM_VOICE_MODEL", "llama-3.3-70b-versatile")
_ACK_DELAY_S = float(os.getenv("PRISM_CHAT_ACK_DELAY_S", "1.5"))
_DISPATCH_DECIDE_CHARS = len(DISPATCH_TOKEN) + 3  # buffer this many chars before deciding


def _rr():
    import realtime_routes as rr
    return rr


def _is_dispatch_reply(text: str) -> bool:
    """True when the voice LLM emitted the dispatch token alone (→ agent channel), False
    for a real conversational reply. Tolerant of trailing punctuation/whitespace and case;
    a reply that merely STARTS with 'act' (e.g. 'Action items are…') is NOT a dispatch."""
    return (text or "").strip().rstrip(" .!").upper() == DISPATCH_TOKEN


# ── delivery helpers ──────────────────────────────────────────────────────────

async def _speak(bot_id: str, text: str) -> None:
    from voice import bridge
    try:
        await bridge.speak(bot_id, text)
    except Exception as exc:
        print(f"[voice] speak failed: {exc}")


async def _finalize(bot_id: str, command: str, speaker: str, reply: str, tools_used=None) -> None:
    """Record the bot's reply into the transcript + command log + conversational memory —
    the same bookkeeping the fused path did, shared by the talk and act paths."""
    rr = _rr()
    import perception_state
    state = rr._get_bot_state(bot_id)
    bot_name = rr._BOT_WAKE_ALIAS.get(bot_id, "") or rr.DEFAULT_BOT_NAME
    _turns = state.setdefault("recent_turns", [])
    _turns.append({"command": command, "reply": reply})
    del _turns[:-4]
    cmd_entry = {"command": command, "speaker": speaker, "tools": tools_used or [],
                 "reply": reply, "ts": time.time()}
    if bot_id in rr.bot_store:
        rr.bot_store[bot_id].setdefault("commands", []).append(cmd_entry)
    rr._db_append_command(bot_id, cmd_entry)
    try:
        async with perception_state.get_memory_lock(state):
            rr._record_bot_line(bot_id, state, reply, bot_name)
    except Exception as exc:
        print(f"[voice] record bot line failed: {exc}")


# ── stand-in fast path (deterministic, pre-LLM) ───────────────────────────────

async def _maybe_standin(bot_id: str, command: str, from_chat: bool) -> bool:
    rr = _rr()
    explicit = bool(rr._STANDIN_QUERY_RE.search(command))
    person_shaped = bool(rr._STANDIN_PERSON_RE.search(command))
    if not (explicit or person_shaped):
        return False
    updates = (rr.bot_store.get(bot_id) or {}).get("standin_updates")
    if not updates:
        try:
            from recall_routes import standin_updates_for_bot
            updates = standin_updates_for_bot(bot_id)
        except Exception as exc:
            print(f"[standin] db read failed: {exc}")
            updates = []
    chosen = updates
    if person_shaped and not explicit:
        chosen = rr._updates_for_named(command, updates)
        if not chosen:
            return False  # person-shaped but names nobody with an update → normal flow
    summary = (rr._standin_spoken_summary(chosen) if chosen
               else "No one left a stand-in update for this meeting.")
    if not from_chat:
        await _speak(bot_id, rr._spoken_version(summary))
    await rr._send_chat_response(bot_id, summary)
    return True


# ── chat ack ──────────────────────────────────────────────────────────────────

def _start_ack(bot_id: str, command: str) -> asyncio.Task:
    """Post '⏳ on it — <echo>' only if the agent hasn't finished by _ACK_DELAY_S.
    Cancelled the moment the result is ready (sub-second actions post no ack)."""
    rr = _rr()

    async def _ack():
        try:
            await asyncio.sleep(_ACK_DELAY_S)
            echo = command.strip()
            echo = echo if len(echo) <= 60 else echo[:57] + "…"
            await rr._send_chat_response(bot_id, f"⏳ on it — {echo}")
        except asyncio.CancelledError:
            pass
    return asyncio.create_task(_ack())


# ── the handler ───────────────────────────────────────────────────────────────

async def handle_command(bot_id: str, command: str, speaker: str = "", from_chat: bool = False) -> None:
    rr = _rr()
    state = rr._get_bot_state(bot_id)
    if state.get("muted"):
        bus.emit_status(bot_id, "muted_skip")
        return
    if await _maybe_standin(bot_id, command, from_chat):
        return

    decided, full = await _stream_talk_or_dispatch(bot_id, command, speaker, from_chat)

    if decided == "talk":
        reply = (full or "").strip() or f"Got it — {command}."
        await rr._send_chat_response(bot_id, reply)
        await _finalize(bot_id, command, speaker, reply)
        return

    # dispatch → agent channel, with a chat ack if it's slow.
    from voice import agent_channel
    ack = _start_ack(bot_id, command)
    try:
        result = await agent_channel.run(bot_id, command, speaker)
    finally:
        ack.cancel()

    blocked = result.get("blocked_cap")
    if blocked:
        msg = rr._CAP_TERSE.get(blocked, "That isn't connected here yet.")
        await rr._send_chat_response(bot_id, msg)
        if not from_chat:
            await _speak(bot_id, rr._spoken_version(msg))
        return

    reply = (result.get("reply") or "").strip()
    if not reply:
        return
    await rr._send_chat_response(bot_id, reply)
    if not from_chat:
        await _speak(bot_id, rr._spoken_condense(reply))
    await _finalize(bot_id, command, speaker, reply, result.get("tools_used"))


async def _stream_talk_or_dispatch(bot_id: str, command: str, speaker: str, from_chat: bool):
    """One streaming Groq call. Returns ('talk', full_text) or ('dispatch', '').

    Buffers the first few chars to tell the dispatch token apart from a real reply; a
    talk reply streams into TTS sentence-by-sentence as it generates (unless from_chat)."""
    rr = _rr()
    import meeting_memory
    import perception_state
    from datetime import datetime
    from zoneinfo import ZoneInfo

    user_settings = await rr._get_settings_for_bot(bot_id)
    persona_text = user_settings.get("persona_text", "")
    bot_name = user_settings.get("bot_name", rr.DEFAULT_BOT_NAME)
    tools = rr.get_available_tools(user_settings)
    has_gmail = any(t["function"]["name"].startswith("gmail") for t in tools)
    has_calendar = any(t["function"]["name"].startswith("calendar") for t in tools)

    memory_context = meeting_memory.build_memory_context(rr._get_bot_state(bot_id), command)
    now = datetime.now(ZoneInfo("America/New_York"))
    hour_12 = now.hour % 12 or 12
    now_str = (f"{now.strftime('%A, %B')} {now.day}, {now.year} at "
               f"{hour_12}:{now.strftime('%M %p')} {now.strftime('%Z')} (IANA timezone: America/New_York)")

    owner_full = (rr.bot_store.get(bot_id) or {}).get("owner_name", "")
    is_owner = perception_state.is_owner_speaker(speaker, owner_full)
    owner_email = rr._owner_email_for_bot(bot_id)

    messages = prompts.build_voice_messages(
        has_gmail=has_gmail, has_calendar=has_calendar, now_str=now_str,
        memory_context=memory_context, speaker=speaker, command=command, is_owner=is_owner,
        persona_text=persona_text, bot_name=bot_name, owner_name=owner_full, owner_email=owner_email,
        recent_turns=rr._get_bot_state(bot_id).get("recent_turns", []),
    )

    from clients import get_groq, get_openai
    client = get_groq()
    model = _VOICE_MODEL
    if client is None:  # Groq not configured → fall back to gpt-4o-mini streaming.
        client = get_openai()
        model = "gpt-4o-mini"

    speak_ok = not from_chat
    seg = StreamingSegmenter()
    dispatcher = TtsDispatcher(min_chars=25)
    full_parts: list[str] = []
    decided = None
    tail = ""

    async def _emit(seg_text_chunks):
        for sent in seg_text_chunks:
            for chunk in dispatcher.push(sent):
                await _speak(bot_id, chunk)

    try:
        stream = await client.chat.completions.create(
            model=model, temperature=0.4, messages=messages, stream=True,
        )
    except Exception as exc:
        print(f"[voice] talk stream failed ({model}): {exc}")
        return "talk", ""

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if not delta:
            continue
        # Leak scanner (voice channel owns this): the tool-less voice call should never
        # emit tool syntax; if it does, stop and route to dispatch rather than speak it.
        tail, leak = rr._scan_delta_for_leak(tail, delta)
        if leak:
            bus.emit_status(bot_id, "voice_leak_dispatch")
            return "dispatch", ""
        full_parts.append(delta)
        acc_raw = "".join(full_parts)  # feed the segmenter the RAW text (keep spacing)
        if decided is None:
            if len(acc_raw.strip()) < _DISPATCH_DECIDE_CHARS:
                continue  # not enough to tell "ACT" from a real reply yet
            if _is_dispatch_reply(acc_raw):
                return "dispatch", ""
            decided = "talk"
            if speak_ok:
                await _emit(seg.feed(acc_raw))
        elif speak_ok:
            await _emit(seg.feed(delta))

    acc_raw = "".join(full_parts)
    if decided is None:  # short reply that never crossed the decide threshold
        if _is_dispatch_reply(acc_raw):
            return "dispatch", ""
        decided = "talk"
        if speak_ok:
            await _emit(seg.feed(acc_raw))
    if speak_ok:
        await _emit(seg.flush())
        for chunk in dispatcher.flush():
            await _speak(bot_id, chunk)
    return "talk", acc_raw.strip()


# Register with the bus at import so dispatch sites only need `voice.bus.submit`.
bus.set_command_handler(handle_command)


# ── self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    assert _is_dispatch_reply("ACT")
    assert _is_dispatch_reply("act.")
    assert _is_dispatch_reply("  ACT ! ")
    assert not _is_dispatch_reply("Action items are due Friday.")
    assert not _is_dispatch_reply("The meeting decided to ship.")
    assert not _is_dispatch_reply("ok")
    assert not _is_dispatch_reply("")
    print("voice_channel dispatch-parse self-check OK")

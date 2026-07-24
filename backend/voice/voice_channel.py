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

from voice import bus, prompts, tuning
from voice import stopwatch as _sw
from voice.prompts import DISPATCH_TOKEN
from voice_pipeline import StreamingSegmenter, TtsDispatcher

_VOICE_MODEL = os.getenv("PRISM_VOICE_MODEL", "llama-3.3-70b-versatile")
_ACK_DELAY_S = tuning.ACK_DELAY_S
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
    """Politeness gap (§2) then mouth. `wait_for_gap` returns immediately when the bot is
    already mid-utterance, so it gates the START of a reply, not each streamed chunk."""
    from voice import barge, bridge
    try:
        await barge.wait_for_gap(bot_id)
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


async def _build_voice_messages(bot_id: str, command: str, speaker: str) -> list[dict]:
    """Assemble the tool-less voice prompt (persona, memory, roster, owner identity).
    Split out of the streaming loop so the speculative path (§3) can build and fire the
    same call early, from the eager transcript."""
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

    return prompts.build_voice_messages(
        has_gmail=has_gmail, has_calendar=has_calendar, now_str=now_str,
        memory_context=memory_context, speaker=speaker, command=command, is_owner=is_owner,
        persona_text=persona_text, bot_name=bot_name, owner_name=owner_full, owner_email=owner_email,
        recent_turns=rr._get_bot_state(bot_id).get("recent_turns", []),
    )


async def _open_deltas(messages: list[dict]):
    """Open the voice-channel stream and yield content deltas. Groq when configured
    (its time-to-first-token is the whole reason it's here), gpt-4o-mini otherwise."""
    from clients import get_groq, get_openai
    client = get_groq()
    model = _VOICE_MODEL
    if client is None:  # Groq not configured → fall back to gpt-4o-mini streaming.
        client = get_openai()
        model = "gpt-4o-mini"
    stream = await client.chat.completions.create(
        model=model, temperature=0.4, messages=messages, stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ── speculative call (§3) ─────────────────────────────────────────────────────

class _Speculation:
    """One in-flight voice-channel call started from Flux's EagerEndOfTurn transcript.

    It runs the LLM early but NEVER speaks: deltas land in a queue, and only the real
    post-EndOfTurn path can adopt them (`take`) and let them reach TTS. If the human keeps
    talking (TurnResumed), or the confirmed transcript differs, the whole thing is thrown
    away — a wasted LLM call, which is the price the eager threshold is trading for.
    """

    def __init__(self, bot_id: str, command: str, speaker: str):
        self.bot_id = bot_id
        self.command = command
        self.speaker = speaker
        self.norm = _norm_cmd(command)
        self.error: Exception | None = None
        self._q: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        try:
            async with asyncio.timeout(tuning.SPECULATION_TTL_S):
                messages = await _build_voice_messages(self.bot_id, self.command, self.speaker)
                async for delta in _open_deltas(messages):
                    await self._q.put(delta)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # incl. TimeoutError — nobody adopted it in time
            self.error = exc
        await self._q.put(None)

    async def deltas(self):
        while True:
            delta = await self._q.get()
            if delta is None:
                if self.error is not None:
                    raise self.error
                return
            yield delta

    def cancel(self) -> None:
        if not self.task.done():
            self.task.cancel()


_SPECS: dict[str, _Speculation] = {}


def _norm_cmd(text: str) -> str:
    try:
        return _rr()._normalize_cmd(text)
    except Exception:
        return " ".join((text or "").lower().split())


async def on_eager_turn(bot_id: str, transcript: str, speaker: str = "") -> None:
    """Flux thinks the turn is probably over. Start the talk brain now, on that text.

    Only speculates when a reply is plausible (`gate.might_engage` — a read-only sibling
    of the real decision; the gate stays the sole authority on whether we actually speak)
    and only on the two-channel path, which is the only consumer of a speculation."""
    transcript = (transcript or "").strip()
    if not transcript or os.getenv("PRISM_TWO_CHANNEL", "0") != "1":
        return
    rr = _rr()
    state = rr._get_bot_state(bot_id)
    if state.get("muted"):
        return
    from voice import gate
    if not gate.might_engage(bot_id, state, transcript, speaker):
        return
    prev = _SPECS.get(bot_id)
    if prev is not None and prev.norm == _norm_cmd(transcript):
        return  # same eager text re-fired — the call is already running
    cancel_speculation(bot_id, "superseded")
    _SPECS[bot_id] = _Speculation(bot_id, transcript, speaker)
    bus.emit_status(bot_id, "speculation_started", text=transcript[:60])


def cancel_speculation(bot_id: str, reason: str = "") -> None:
    spec = _SPECS.pop(bot_id, None)
    if spec is not None:
        spec.cancel()
        bus.emit_status(bot_id, "speculation_cancelled", reason=reason)


def _take_speculation(bot_id: str, command: str) -> _Speculation | None:
    """Adopt the in-flight call iff it was started on the same words the turn actually
    ended with. # ponytail: exact normalized match — if the hit rate turns out low in the
    §6 loop, loosen to "eager text is a prefix of the final"."""
    spec = _SPECS.pop(bot_id, None)
    if spec is None:
        return None
    if spec.norm != _norm_cmd(command):
        spec.cancel()
        bus.emit_status(bot_id, "speculation_missed", eager=spec.command[:40])
        return None
    bus.emit_status(bot_id, "speculation_hit")
    return spec


def cleanup_bot(bot_id: str) -> None:
    cancel_speculation(bot_id, "bot_teardown")


async def _stream_talk_or_dispatch(bot_id: str, command: str, speaker: str, from_chat: bool):
    """One streaming voice-channel call. Returns ('talk', full_text) or ('dispatch', '').

    Buffers the first few chars to tell the dispatch token apart from a real reply; a
    talk reply streams into TTS sentence-by-sentence as it generates (unless from_chat).
    Adopts a speculative call started at EagerEndOfTurn when one matches (§3)."""
    from voice import barge
    rr = _rr()
    speak_ok = not from_chat
    seg = StreamingSegmenter()
    dispatcher = TtsDispatcher(min_chars=25)
    full_parts: list[str] = []
    decided = None
    tail = ""
    seq0 = barge.interrupt_seq(bot_id)  # barge-in fired after this ⇒ stop mid-reply

    async def _emit(seg_text_chunks):
        for sent in seg_text_chunks:
            for chunk in dispatcher.push(sent):
                await _speak(bot_id, chunk)

    spec = _take_speculation(bot_id, command)
    try:
        if spec is not None:
            deltas = spec.deltas()          # already streaming since EagerEndOfTurn
        else:
            deltas = _open_deltas(await _build_voice_messages(bot_id, command, speaker))
        async for delta in deltas:
            if speak_ok and barge.interrupted_since(bot_id, seq0):
                # Someone talked over us. Keep the text (chat still gets the full reply);
                # stop putting sentences in the mouth.
                bus.emit_status(bot_id, "reply_cut_by_bargein")
                return "talk", "".join(full_parts).strip()
            if not full_parts:
                # t2 = brain started replying. Stamped where the REAL turn first sees a
                # token, so a speculative hit shows up as a genuinely shorter t1→t2 rather
                # than as a negative interval measured from before the turn even ended.
                _sw.mark_turn(bot_id, "t2")
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
    except Exception as exc:
        # A speculation that died (TTL, TurnResumed race, provider hiccup) must not take
        # the turn down with it — fall back to a plain call unless we already spoke.
        print(f"[voice] talk stream failed ({'speculative' if spec else 'direct'}): {exc}")
        if spec is not None and decided is None:
            return await _stream_talk_or_dispatch(bot_id, command, speaker, from_chat)
        return "talk", "".join(full_parts).strip()

    acc_raw = "".join(full_parts)
    if decided is None:  # short reply that never crossed the decide threshold
        if _is_dispatch_reply(acc_raw):
            return "dispatch", ""
        decided = "talk"
        if speak_ok:
            await _emit(seg.feed(acc_raw))
    if speak_ok and not barge.interrupted_since(bot_id, seq0):
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

    # Speculation (§3): started early, adopted only on an exact-text confirmation.
    import sys, types

    class _FakeRR(types.ModuleType):
        _bot_state: dict = {}
        def _normalize_cmd(self, text): return " ".join((text or "").lower().split())
        def _get_bot_state(self, bot_id): return self._bot_state.setdefault(bot_id, {})
        def _looks_like_bot_participant(self, name, raw): return False
        def _detect_command(self, text, bot_id): return text if "prism" in text.lower() else None
        def _has_trigger_word(self, text, bot_id): return "prism" in text.lower()
        def _solo_mode_active(self, state): return True
        def _solo_freeflow_text_eligible(self, text): return len(text.split()) >= 3
    sys.modules["realtime_routes"] = _FakeRR("realtime_routes")

    _built: list[str] = []

    async def _fake_build(bot_id, command, speaker):
        _built.append(command)
        return [{"role": "user", "content": command}]

    async def _fake_deltas(messages):
        for piece in ("Sure", ", ", "here it is."):
            await asyncio.sleep(0)
            yield piece

    _build_voice_messages, _open_deltas = _fake_build, _fake_deltas
    os.environ["PRISM_TWO_CHANNEL"] = "1"

    async def _spec_demo():
        # Eager transcript starts the call before the turn is confirmed.
        await on_eager_turn("b1", "what did we decide about pricing", "Dana")
        assert "b1" in _SPECS
        # Confirmed with the SAME words → adopted, and nothing is rebuilt.
        spec = _take_speculation("b1", "What did we decide about pricing")
        assert spec is not None and "b1" not in _SPECS
        assert "".join([d async for d in spec.deltas()]) == "Sure, here it is."
        assert _built == ["what did we decide about pricing"], _built

        # Confirmed with DIFFERENT words → discarded, caller falls back to a fresh call.
        await on_eager_turn("b2", "should we ship on", "Dana")
        assert _take_speculation("b2", "should we ship on friday or monday") is None
        assert "b2" not in _SPECS

        # TurnResumed cancels; a turn the gate would never answer never speculates.
        await on_eager_turn("b3", "prism summarize", "Dana")
        assert "b3" in _SPECS
        cancel_speculation("b3", "turn_resumed")
        assert "b3" not in _SPECS
        _FakeRR._bot_state["b4"] = {"muted": True}
        await on_eager_turn("b4", "prism summarize", "Dana")
        assert "b4" not in _SPECS

    asyncio.run(_spec_demo())
    print("voice_channel dispatch-parse + speculation self-check OK")

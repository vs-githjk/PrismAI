"""
Real-time webhook: receives live transcript + chat messages from Recall.ai,
detects PrismAI commands, executes tools, and optionally responds via TTS.
"""

import asyncio
import base64
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

import meeting_memory
from agents.utils import llm_call, strip_fences
from clients import get_groq, get_http
from tools.registry import get_available_tools, execute_tool, confirm_and_execute, is_tainted
from voice_pipeline import StreamingSegmenter, TtsDispatcher
from tools.tts import text_to_speech
from recall_routes import bot_store, _db_append_command, _db_save_memory
from auth import supabase
from cross_meeting_service import looks_like_blocker, extract_significant_terms

router = APIRouter(tags=["realtime"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")

# In-memory state per bot
# bot_id -> { transcript_buffer: [], last_command_ts: float, user_settings: dict }
_bot_state: dict = {}

# Trigger patterns — "prism" or "prismai" followed by a command
TRIGGER_PATTERN = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:]?\s*(.+)",
    re.IGNORECASE,
)

# Proactive intervention patterns live in meeting_memory.py (canonical definitions).
# _run_proactive_checker uses the integer counter fields in state, not pattern objects.

TRIGGER_WORD_PATTERN = re.compile(r"\b(?:prism|prismai|prism ai)\b", re.IGNORECASE)

# Seconds to wait for the command after a bare trigger word
PENDING_TRIGGER_WINDOW = 8

# ── Malformed tool-call recovery ──────────────────────────────────────────────
# Llama 3.3 occasionally emits tool calls as raw `<function=NAME {json}>` text
# inside the assistant content instead of in the structured `tool_calls` field.
# Groq's server detects this and rejects with 400 tool_use_failed, returning the
# offending text in `error.failed_generation`. These helpers parse that text so
# we can synthesise proper tool_calls and continue the conversation.

_FUNCTION_TAG_RE = re.compile(
    r"<function\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*",
    re.IGNORECASE,
)


def _find_matching_brace(s: str, start: int) -> int:
    """Return the index just past the '}' that closes s[start]='{'. -1 if unbalanced."""
    if start >= len(s) or s[start] != "{":
        return -1
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _parse_function_tags(text: str) -> list[dict]:
    """Extract <function=NAME {args}> calls from a string.

    Returns a list of {"name": str, "arguments": str-of-json} dicts. Skips calls
    whose JSON braces are unmatched. Defaults arguments to "{}" when missing or
    malformed so downstream tool execution can decide whether to error.
    """
    if not text:
        return []
    out = []
    pos = 0
    while pos < len(text):
        m = _FUNCTION_TAG_RE.search(text, pos)
        if not m:
            break
        name = m.group(1)
        body_start = m.end()
        # Skip leading whitespace between name and the JSON body
        while body_start < len(text) and text[body_start].isspace():
            body_start += 1
        if body_start < len(text) and text[body_start] == "{":
            body_end = _find_matching_brace(text, body_start)
            if body_end == -1:
                # Truncated JSON — skip this call entirely so we don't fabricate args.
                pos = m.end()
                continue
            args_str = text[body_start:body_end]
            try:
                json.loads(args_str)
            except json.JSONDecodeError:
                args_str = "{}"
            pos = body_end
        else:
            # Tag with no args body — treat as zero-arg call.
            args_str = "{}"
            pos = body_start if body_start > m.end() else m.end()
        out.append({"name": name, "arguments": args_str})
    return out


def _extract_failed_generation(exc: Exception) -> str:
    """Pull `error.failed_generation` from a Groq tool_use_failed exception."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            gen = err.get("failed_generation")
            if isinstance(gen, str):
                return gen
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            data = response.json()
            err = (data or {}).get("error") or {}
            gen = err.get("failed_generation")
            if isinstance(gen, str):
                return gen
        except Exception:
            pass
    return ""


def _recover_tool_calls(text: str, valid_tool_names: set) -> list[dict]:
    """Parse `text` for <function=...> tags and keep only those naming known tools."""
    calls = _parse_function_tags(text)
    return [c for c in calls if c["name"] in valid_tool_names]


def _strip_tools_if_tainted(call_kwargs: dict, executed_tool_names) -> bool:
    """If any just-executed tool taints context (e.g. web_search), remove `tools` and
    `tool_choice` from `call_kwargs` so the next LLM call this turn cannot dispatch
    further tools. Canonical defence against prompt-injection-via-tool-result: a
    web search whose page tells the model to "now call gmail_send..." cannot win.
    Called from both the structured tool_calls path and the recovered/synth path.
    Returns True if tools were stripped.
    """
    if any(is_tainted(name) for name in executed_tool_names):
        call_kwargs.pop("tools", None)
        call_kwargs.pop("tool_choice", None)
        return True
    return False


# ── Idea Engine constants ─────────────────────────────────────────────────────

# System prompt shared by all five insight types.
# Priority order (gap → drift → pattern → acceleration → synthesis) lets the model
# pick the most impactful insight rather than the first one it notices.
_IDEA_SYSTEM_PROMPT = """\
You are PrismAI's meeting intelligence engine. You silently observe a live meeting and surface \
insights that a smart participant would NOT already be thinking about.

Examine the meeting context and detect ONE of these insight types, in priority order:
1. gap         — An important dimension has not been discussed (cost, timeline, ownership, risk, \
testing, rollback, dependencies, success_criteria, communication, security). Only flag if the \
meeting is > 20 min old AND the category is NOT listed under GAP CATEGORIES ALREADY FLAGGED.
2. drift       — An action item was committed to but has not been revisited. If DRIFTING \
COMMITMENT is present in context, use that item — it was detected by rule-based logic. Focus on \
the oldest un-flagged item whose owner has not spoken recently.
3. pattern     — The current discussion overlaps with an unresolved topic from a PAST MEETING \
listed under UNRESOLVED TOPICS. Only flag if keyword overlap is clear and specific.
4. acceleration — The group has been discussing the same topic in the recent transcript \
repeatedly without reaching a decision or conclusion.
5. synthesis   — Two or more decisions or proposals in this meeting conflict with each other \
and could be reconciled. Only flag if you can cite two specific conflicting statements.

Rules:
- Return the FIRST type you are genuinely confident about (confidence ≥ 7 out of 10).
- The insight must be SPECIFIC to what was actually said — never generic advice.
- Do NOT repeat anything already listed under IDEAS ALREADY SHARED.
- Keep the message to 1–2 sentences, direct and actionable.
- If nothing genuinely important stands out, return type "none".

Respond ONLY with valid JSON on a single line — no markdown, no extra text:
{"type": "gap|drift|pattern|acceleration|synthesis|none", "confidence": <0-10>, "message": "<text>", \
"gap_category": "<only when type==gap: one word from: cost/timeline/ownership/risk/testing/rollback/dependencies/success_criteria/communication/security — omit for all other types>"}\
"""

# Chat prefix for each insight type — makes the origin immediately clear to participants
_IDEA_TYPE_PREFIX: dict[str, str] = {
    "gap":          "💡 [Gap]",
    "drift":        "⏳ [Follow-up]",
    "pattern":      "🔄 [Pattern]",
    "acceleration": "🔁 [Looping]",
    "synthesis":    "🔀 [Synthesis]",
}


def _get_bot_state(bot_id: str) -> dict:
    if bot_id not in _bot_state:
        _bot_state[bot_id] = {
            "transcript_buffer": [],
            "last_command_ts": 0,
            "last_command_text": "",
            "last_command_norm": "",
            "processing": False,
            "pending_trigger_ts": 0,
            "pending_trigger_speaker": "",
            "pending_command_parts": [],
            # Proactive intervention state
            "meeting_start_ts": None,
            "intervention_last_ts": 0,
            "decisions_detected": 0,
            "action_items_detected": 0,
            "owners_detected": 0,
            "sent_30min_nudge": False,
            "sent_55min_nudge": False,
            "sent_no_owners_nudge": False,
            "recurring_blocker_checked": False,
            "historical_blockers": [],
            # Memory system fields (Layers 1-3) — managed by meeting_memory.py
            **meeting_memory.get_initial_memory_state(),
        }
    return _bot_state[bot_id]


def _normalize_cmd(text: str) -> str:
    return re.sub(r'\W+', ' ', text.lower()).strip()


def _detect_command(text: str) -> str | None:
    """Return the command portion if text contains a trigger + actionable command, else None."""
    match = TRIGGER_PATTERN.search(text)
    if match:
        cmd = match.group(1).strip()
        if cmd:
            return cmd
    return None


def _has_trigger_word(text: str) -> bool:
    """Return True if text contains the trigger word."""
    return bool(TRIGGER_WORD_PATTERN.search(text))


async def _get_settings_for_bot(bot_id: str) -> dict:
    """Look up the user who started this bot, then fetch their tool tokens from Supabase."""
    settings = {}

    # Env-level fallbacks
    if SLACK_BOT_TOKEN:
        settings["slack_bot_token"] = SLACK_BOT_TOKEN
    if LINEAR_API_KEY:
        settings["linear_api_key"] = LINEAR_API_KEY

    # Look up user_id from the bot record, then fetch their per-user tokens
    user_id = (bot_store.get(bot_id) or {}).get("user_id")
    if user_id and supabase:
        try:
            resp = supabase.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            row = (resp.data if resp is not None else None) or {}
            if row.get("google_access_token"):
                # Use get_valid_token to refresh if expired (tokens last 1 hour)
                from calendar_routes import get_valid_token
                try:
                    fresh_token = await get_valid_token(user_id)
                    settings["google_access_token"] = fresh_token
                except Exception:
                    settings["google_access_token"] = row["google_access_token"]
            if row.get("slack_bot_token") and not settings.get("slack_bot_token"):
                settings["slack_bot_token"] = row["slack_bot_token"]
            if row.get("linear_api_key") and not settings.get("linear_api_key"):
                settings["linear_api_key"] = row["linear_api_key"]
        except Exception as exc:
            print(f"[realtime] failed to load user settings for bot {bot_id}: {exc}")

    return settings


async def _send_chat_response(bot_id: str, message: str):
    """Send a chat message back into the meeting via the Recall.ai bot."""
    if not RECALL_API_KEY:
        return
    try:
        async with get_http() as client:
            await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/send_chat_message/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"message": message},
                timeout=10,
            )
    except Exception as exc:
        print(f"[realtime] failed to send chat response: {exc}")


async def _upload_audio_to_recall(bot_id: str, audio_bytes: bytes) -> bool:
    """Upload a single audio blob to Recall's output_audio endpoint. Returns True on 2xx."""
    if not RECALL_API_KEY or not audio_bytes:
        return False
    try:
        async with get_http() as client:
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/output_audio/",
                headers={"Authorization": f"Token {RECALL_API_KEY}", "Content-Type": "application/json"},
                json={"kind": "mp3", "b64_data": base64.b64encode(audio_bytes).decode()},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                return True
            print(f"[realtime] output_audio failed ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as exc:
        print(f"[realtime] voice upload failed: {exc}")
        return False


async def _send_voice_response(bot_id: str, text: str):
    """Convert text to speech and play it in the meeting via Recall.ai bot.
    Buffered (default) path: one TTS call, one upload."""
    if not RECALL_API_KEY:
        return
    audio_bytes = await text_to_speech(text)
    if not audio_bytes:
        print(f"[realtime] TTS produced no audio for bot {bot_id}, skipping voice")
        return
    await _upload_audio_to_recall(bot_id, audio_bytes)


def _chunk_reply(text: str, min_chars: int = 25) -> list[str]:
    """Segment the full reply into sentences, then concat-dispatch into TTS-sized chunks."""
    seg = StreamingSegmenter()
    sentences = list(seg.feed(text))
    sentences.extend(seg.flush())
    dispatcher = TtsDispatcher(min_chars=min_chars)
    chunks = []
    for s in sentences:
        chunks.extend(dispatcher.push(s))
    chunks.extend(dispatcher.flush())
    return chunks


_FUNCTION_TAG_MARKER = "<function="
_LEAK_TAIL_WINDOW = 30


def _scan_delta_for_leak(tail: str, delta: str, window: int = _LEAK_TAIL_WINDOW) -> tuple[str, bool]:
    """Rolling-tail scan for `<function=` across stream-delta boundaries.

    Returns `(new_tail, leak_detected)`. Detection covers (1) the marker fully
    inside `delta`, (2) the marker straddling tail+delta, and (3) the marker
    inside the new tail itself. The new tail is the last `window` chars of
    `tail + delta` — small enough that 30 chars is sufficient for an 11-char
    marker, big enough to survive whitespace/punctuation between fragments.
    """
    combined = tail + delta
    return combined[-window:], _FUNCTION_TAG_MARKER in combined


async def _stream_llm_to_voice(
    groq_client,
    call_kwargs: dict,
    bot_id: str,
    cmd_detected_ts: float,
) -> str:
    """Layer 3 (B) — gated by PRISM_STREAMED_LLM=1 (requires PRISM_STREAMED_TTS=1).

    Calls Groq with `stream=True`, feeds token deltas into the segmenter as they
    arrive, dispatches TTS chunks in parallel, and uploads sequentially so
    playback ordering is preserved. Returns the full accumulated reply text.

    Salvage (bounded drain): on first upload failure we wait up to 2.5s for the
    LLM stream to finish; whatever has been buffered (chunks not yet uploaded
    + dispatcher residuals) is consolidated into one TTS + one upload IF the
    text is > 20 chars; otherwise we give up (P1, log `salvage_skipped_too_little_text`).
    A second upload failure hard-aborts (log `salvage_skipped_recall_dead`).
    """
    stream_kwargs = dict(call_kwargs)
    stream_kwargs["stream"] = True

    # Without Recall there's no audio path — just drain the stream for the text.
    if not RECALL_API_KEY:
        stream = await groq_client.chat.completions.create(**stream_kwargs)
        parts = []
        async for event in stream:
            if event.choices and event.choices[0].delta.content:
                parts.append(event.choices[0].delta.content)
        return "".join(parts)

    state = _get_bot_state(bot_id)
    segmenter = StreamingSegmenter()
    dispatcher = TtsDispatcher(min_chars=25)
    chunks_dispatched: list[str] = []
    tts_tasks: list[asyncio.Task] = []
    full_text_parts: list[str] = []
    tail = ""
    leak_detected = False
    stream_done = asyncio.Event()
    new_chunk_event = asyncio.Event()

    uploaded_idx = 0
    upload_failures = 0
    salvage_invoked = False
    first_upload_logged = False

    def _dispatch(new_chunks: list[str]) -> bool:
        """Spawn TTS tasks for new chunks. Returns False if a chunk contains
        the function-tag marker (the cross-delta tail scan should make this
        impossible, but it's the last line of defence before TTS)."""
        for c in new_chunks:
            if _FUNCTION_TAG_MARKER in c:
                return False
            chunks_dispatched.append(c)
            tts_tasks.append(asyncio.create_task(text_to_speech(c)))
        if new_chunks:
            new_chunk_event.set()
        return True

    async def _stream_consumer():
        nonlocal tail, leak_detected
        try:
            stream = await groq_client.chat.completions.create(**stream_kwargs)
            async for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta.content or ""
                if not delta:
                    continue
                tail, leak = _scan_delta_for_leak(tail, delta)
                if leak:
                    leak_detected = True
                    return
                full_text_parts.append(delta)
                new_sentences = segmenter.feed(delta)
                new_chunks = []
                for s in new_sentences:
                    new_chunks.extend(dispatcher.push(s))
                if not _dispatch(new_chunks):
                    leak_detected = True
                    return
            # Stream exhausted — flush segmenter + dispatcher residuals.
            tail_chunks = []
            for s in segmenter.flush():
                tail_chunks.extend(dispatcher.push(s))
            tail_chunks.extend(dispatcher.flush())
            if not _dispatch(tail_chunks):
                leak_detected = True
        finally:
            stream_done.set()
            new_chunk_event.set()

    stream_task = asyncio.create_task(_stream_consumer())

    try:
        i = 0
        while True:
            if leak_detected:
                print(f"[realtime] function_tag_leak_detected bot={bot_id[:8]}; aborting streamed LLM voice")
                stream_task.cancel()
                for t in tts_tasks[i:]:
                    t.cancel()
                break
            if i >= len(tts_tasks):
                if stream_done.is_set():
                    break
                new_chunk_event.clear()
                await new_chunk_event.wait()
                continue
            try:
                audio = await tts_tasks[i]
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[realtime] TTS failed for chunk {i}: {exc}")
                audio = None
            if not audio:
                i += 1
                continue
            if await _upload_audio_to_recall(bot_id, audio):
                uploaded_idx = i + 1
                if not first_upload_logged:
                    ttfw_ms = int((time.time() - cmd_detected_ts) * 1000)
                    print(f"[realtime] time_to_first_word_ms={ttfw_ms} bot={bot_id[:8]}")
                    first_upload_logged = True
                i += 1
                continue
            upload_failures += 1
            if upload_failures >= 2:
                print(f"[realtime] salvage_skipped_recall_dead failures={upload_failures} bot={bot_id[:8]}")
                stream_task.cancel()
                for t in tts_tasks[i:]:
                    t.cancel()
                break
            # First failure: bounded drain of remaining stream, then salvage.
            salvage_invoked = True
            state["last_command_ts"] = 0
            try:
                await asyncio.wait_for(stream_done.wait(), timeout=2.5)
            except asyncio.TimeoutError:
                stream_task.cancel()
            for t in tts_tasks[i:]:
                t.cancel()
            unuploaded = list(chunks_dispatched[uploaded_idx:])
            for s in segmenter.flush():
                unuploaded.extend(dispatcher.push(s))
            unuploaded.extend(dispatcher.flush())
            salvage_text = " ".join(c for c in unuploaded if c).strip()
            if len(salvage_text) > 20:
                print(f"[realtime] salvage_invoked drained_chars={len(salvage_text)} bot={bot_id[:8]}")
                try:
                    salvage_audio = await text_to_speech(salvage_text)
                except Exception as exc:
                    print(f"[realtime] salvage TTS failed: {exc}")
                    salvage_audio = None
                if salvage_audio:
                    if not await _upload_audio_to_recall(bot_id, salvage_audio):
                        upload_failures += 1
                        if upload_failures >= 2:
                            print(f"[realtime] salvage_skipped_recall_dead failures={upload_failures} bot={bot_id[:8]}")
            else:
                print(f"[realtime] salvage_skipped_too_little_text drained_chars={len(salvage_text)} bot={bot_id[:8]}")
            break
    finally:
        if not stream_task.done():
            try:
                await asyncio.wait_for(stream_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    full_text = "".join(full_text_parts).strip()
    print(
        f"[realtime] streamed_llm_done chunker_sentences_emitted={len(chunks_dispatched)} "
        f"ordered_upload_failures={upload_failures} salvage_invoked={salvage_invoked} "
        f"uploaded={uploaded_idx}/{len(chunks_dispatched)} chars={len(full_text)} bot={bot_id[:8]}"
    )
    return full_text


async def _send_voice_response_streamed(bot_id: str, text: str, cmd_detected_ts: float):
    """Streamed TTS variant (Layer 3 A) gated by PRISM_STREAMED_TTS=1.

    LLM call has already returned the full reply. We segment it, dispatch each
    chunk to TTS in parallel, and upload sequentially so playback ordering is
    preserved. On a Recall upload failure we salvage once (consolidate remaining
    sentences into one TTS + one upload). Two failures => hard abort.
    """
    if not RECALL_API_KEY:
        return

    chunks = _chunk_reply(text)
    if not chunks:
        return

    # Belt-and-suspenders: PR-1 ensures the synthesis turn (post-tool) has no
    # tools=, so the LLM can't emit a `<function=...` tag. If one ever leaks
    # we hard-abort before TTS — never let the model's tag get spoken aloud.
    for chunk in chunks:
        if "<function=" in chunk:
            print(f"[realtime] function_tag_leak_detected bot={bot_id[:8]}; aborting streamed voice")
            return

    state = _get_bot_state(bot_id)
    print(f"[realtime] chunker_sentences_emitted={len(chunks)} bot={bot_id[:8]}")

    tts_tasks = [asyncio.create_task(text_to_speech(c)) for c in chunks]

    uploaded_idx = 0
    upload_failures = 0
    salvage_invoked = False
    first_upload_logged = False

    i = 0
    while i < len(tts_tasks):
        try:
            audio = await tts_tasks[i]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[realtime] TTS failed for chunk {i}: {exc}")
            audio = None

        if not audio:
            i += 1
            continue

        if await _upload_audio_to_recall(bot_id, audio):
            uploaded_idx = i + 1
            if not first_upload_logged:
                ttfw_ms = int((time.time() - cmd_detected_ts) * 1000)
                print(f"[realtime] time_to_first_word_ms={ttfw_ms} bot={bot_id[:8]}")
                first_upload_logged = True
            i += 1
            continue

        # Upload failed — count, then either hard-abort or salvage.
        upload_failures += 1
        if upload_failures >= 2:
            print(f"[realtime] salvage_skipped_recall_dead failures={upload_failures} bot={bot_id[:8]}")
            for t in tts_tasks[i:]:
                t.cancel()
            break

        # First failure: salvage. Consolidate remaining unuploaded chunks into
        # one TTS + one upload, in parallel with sentence n-1's playback at Recall.
        # Reset debounce so a follow-up command isn't blocked while salvage runs.
        salvage_invoked = True
        state["last_command_ts"] = 0
        for t in tts_tasks[i:]:
            t.cancel()
        remaining_text = " ".join(chunks[uploaded_idx:])
        print(f"[realtime] salvage_invoked remaining_chars={len(remaining_text)} bot={bot_id[:8]}")
        try:
            salvage_audio = await text_to_speech(remaining_text)
        except Exception as exc:
            print(f"[realtime] salvage TTS failed: {exc}")
            salvage_audio = None
        if salvage_audio:
            if not await _upload_audio_to_recall(bot_id, salvage_audio):
                upload_failures += 1
                if upload_failures >= 2:
                    print(f"[realtime] salvage_skipped_recall_dead failures={upload_failures} bot={bot_id[:8]}")
        break

    print(
        f"[realtime] streamed_voice_done ordered_upload_failures={upload_failures} "
        f"salvage_invoked={salvage_invoked} uploaded={uploaded_idx}/{len(chunks)} bot={bot_id[:8]}"
    )


async def _fetch_historical_blockers(user_id: str | None) -> list[dict]:
    """Pull blocker-flagged items from the user's last 10 meetings for recurring-topic detection."""
    if not supabase or not user_id:
        return []
    try:
        res = (
            supabase.table("meetings")
            .select("date,result")
            .eq("user_id", user_id)
            .order("id", desc=True)
            .limit(10)
            .execute()
        )
        blockers = []
        for row in (res.data or []):
            result = row.get("result") or {}
            date = row.get("date") or "a previous meeting"
            for item in (result.get("action_items") or []):
                if not item.get("completed") and looks_like_blocker(item.get("task", "")):
                    kws = extract_significant_terms(item.get("task", ""), minimum_length=4)
                    if kws:
                        blockers.append({"keywords": kws[:6], "date": date})
            summary = result.get("summary", "")
            if summary and looks_like_blocker(summary):
                kws = extract_significant_terms(summary, minimum_length=5)
                if kws:
                    blockers.append({"keywords": kws[:5], "date": date})
        return blockers[:10]
    except Exception as exc:
        print(f"[realtime] failed to fetch historical blockers for user {user_id}: {exc}")
        return []


def _find_drifting_commitment(state: dict, elapsed_min: float) -> dict | None:
    """
    Rule-based detection of the most drifted action item.

    An item is considered drifting if ALL of:
        - Not already drift_flagged
        - Age (minutes since capture) > max(20, elapsed_min / 3)
          The scaled threshold prevents false positives in short meetings:
          20-min meeting → 7 min threshold; 60-min meeting → 20 min; 2-hr → 40 min
        - Owner's name does not appear in the last 30 transcript lines
          (i.e. owner hasn't spoken recently to update the group)

    Returns the single worst offender (largest age), or None if no item qualifies.
    Pure logic, no I/O — called synchronously before the async LLM call.
    """
    action_items = state.get("live_action_items") or []
    if not action_items:
        return None

    now = time.time()
    threshold_min = max(20.0, elapsed_min / 3.0)
    recent_text = "\n".join((state.get("transcript_buffer") or [])[-30:]).lower()

    best: dict | None = None
    best_age = 0.0

    for item in action_items:
        if item.get("drift_flagged"):
            continue
        age_min = (now - item["ts"]) / 60
        if age_min < threshold_min:
            continue
        owner_lower = (item.get("owner") or "").lower().strip()
        # Skip if the owner name appears in recent transcript (they're still active)
        if owner_lower and owner_lower in recent_text:
            continue
        if age_min > best_age:
            best = item
            best_age = age_min

    return best


async def _compress_and_persist(bot_id: str, state: dict) -> None:
    """
    Wrapper around meeting_memory.maybe_compress that also persists the updated summary
    to Supabase after a successful compression cycle.
    Called via asyncio.create_task() on every new transcript line — exits immediately
    when the COMPRESS_EVERY threshold has not been reached or compression is already running.
    """
    cursor_before = state["compression_cursor"]
    await meeting_memory.maybe_compress(bot_id, state)
    if state["compression_cursor"] > cursor_before:
        # Compression ran and advanced the cursor — persist to Supabase, then check for ideas.
        # Idea check is deliberately after persist so any crash in _maybe_generate_idea
        # does not prevent the memory snapshot from being saved.
        snapshot = meeting_memory.get_memory_snapshot(state)
        _db_save_memory(bot_id, snapshot["memory_summary"], snapshot["live_state_payload"])
        asyncio.create_task(_maybe_generate_idea(bot_id, state))

    # Proactive knowledge check — additive, isolated, never raises
    try:
        from knowledge_proactive import maybe_proactive_knowledge_check
        await maybe_proactive_knowledge_check(bot_id, state)
    except Exception as exc:
        print(f"[proactive-knowledge] hook error for {bot_id}: {exc}")


async def _maybe_generate_idea(bot_id: str, state: dict) -> None:
    """
    Idea Engine: surfaces proactive insights from the full meeting memory.

    Triggered by every compression cycle (every ~20 new transcript lines).
    Guards inside meeting_memory._should_run_ideas enforce:
        — 12-minute minimum meeting age
        — 8-minute cooldown between checks
        — entity richness threshold (substance check)
        — mutex (_idea_generating) for single concurrent execution per bot
        — no fire while a user command is being processed

    Insight types handled by a single LLM call (see _IDEA_SYSTEM_PROMPT):
        gap          — missing discussion dimension (cost, timeline, ownership…)
        drift        — action item committed but not revisited
        pattern      — current topic overlaps an unresolved past-meeting blocker
        acceleration — group circling same topic without a decision
        synthesis    — two captured decisions or proposals conflict

    Output: posts to meeting chat with a type-labelled prefix; appends to
    state["idea_history"] for API exposure via /live/{token}.
    Never blocks command processing — always called via asyncio.create_task().
    """
    now = time.time()
    if not meeting_memory._should_run_ideas(state, now):
        return

    state["_idea_generating"] = True
    state["idea_last_check_ts"] = now  # always advance cooldown once we commit to a check

    raw = ""
    try:
        elapsed_min = (now - state["meeting_start_ts"]) / 60

        # Feature 2: Rule-based drift detection runs before the LLM call so we can
        # inject the found item explicitly into context — more reliable than asking
        # the LLM to discover it from raw ages.
        drifting_item = _find_drifting_commitment(state, elapsed_min)

        context = meeting_memory.build_idea_context(state, elapsed_min, drifting_item)

        raw = await llm_call(_IDEA_SYSTEM_PROMPT, context, temperature=0.5)
        parsed = json.loads(strip_fences(raw))

        idea_type = parsed.get("type", "none")
        confidence = int(parsed.get("confidence", 0))
        message = (parsed.get("message") or "").strip()

        if idea_type == "none" or confidence < 7 or not message:
            print(f"[idea] bot={bot_id[:8]} SILENT (type={idea_type}, confidence={confidence})")
            return

        # Feature 1: Python guard for gap type — enforced in code, not just prompt text.
        # Also checks gaps_flagged set so the same category cannot be surfaced twice.
        if idea_type == "gap":
            if elapsed_min < 20:
                print(f"[idea] bot={bot_id[:8]} gap skipped — elapsed={elapsed_min:.0f}min < 20")
                return
            gap_category = (parsed.get("gap_category") or "").strip().lower()
            if gap_category and gap_category in (state.get("gaps_flagged") or set()):
                print(f"[idea] bot={bot_id[:8]} gap category '{gap_category}' already flagged, skipping")
                return

        # Feature 5: Python guards for synthesis — prevents hallucinated synthesis on thin evidence.
        # The LLM must cite conflicting statements, but code guards prevent it from even trying
        # when the meeting lacks enough decisions or history.
        if idea_type == "synthesis":
            decisions = state.get("live_decisions") or []
            summary_words = len((state.get("memory_summary") or "").split())
            if len(decisions) < 3 or summary_words < 200 or elapsed_min < 35:
                print(
                    f"[idea] bot={bot_id[:8]} synthesis guards not met — "
                    f"decisions={len(decisions)}, summary_words={summary_words}, elapsed={elapsed_min:.0f}min"
                )
                return

        prefix = _IDEA_TYPE_PREFIX.get(idea_type, "💡")
        await _send_chat_response(bot_id, f"{prefix} {message}")

        # Feature 1: Record gap category so it won't be re-flagged this meeting.
        if idea_type == "gap":
            gap_category = (parsed.get("gap_category") or "").strip().lower()
            if gap_category:
                if not isinstance(state.get("gaps_flagged"), set):
                    state["gaps_flagged"] = set()
                state["gaps_flagged"].add(gap_category)

        # Feature 2: Mark drift item as flagged using the rule-found reference — exact match,
        # not a fragile string search. Falls back to name matching only when the rule-based
        # helper returned None but the LLM still classified the idea as drift.
        if idea_type == "drift":
            if drifting_item is not None:
                drifting_item["drift_flagged"] = True
            else:
                for item in state.get("live_action_items") or []:
                    if not item.get("drift_flagged") and item["owner"].lower() in message.lower():
                        item["drift_flagged"] = True
                        break

        # Persist the idea in state
        state["idea_history"].append({
            "type": idea_type,
            "message": message,
            "confidence": confidence,
            "ts": now,
        })
        if len(state["idea_history"]) > 20:
            state["idea_history"] = state["idea_history"][-20:]

        # One-line summary injected into future prompts to prevent repetition
        state["previous_idea_summaries"].append(f"[{idea_type}] {message[:120]}")
        if len(state["previous_idea_summaries"]) > 5:
            state["previous_idea_summaries"] = state["previous_idea_summaries"][-5:]

        print(
            f"[idea] bot={bot_id[:8]} type={idea_type} confidence={confidence} "
            f"posted='{message[:80]}'"
        )

    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[idea] bot={bot_id[:8]} JSON parse error: {exc} — raw={raw[:200]!r}")
    except Exception as exc:
        print(f"[idea] bot={bot_id[:8]} error: {exc}")
    finally:
        state["_idea_generating"] = False


async def _run_proactive_checker(bot_id: str):
    """Background task: monitor triggers and post proactive nudges during a live meeting."""
    await asyncio.sleep(120)  # grace period — let the bot settle before first check

    while True:
        await asyncio.sleep(60)

        status = (bot_store.get(bot_id) or {}).get("status", "")
        if status not in ("joining", "recording"):
            break

        state = _get_bot_state(bot_id)
        if state["meeting_start_ts"] is None:
            continue  # no transcript yet — meeting hasn't truly started

        now = time.time()
        elapsed_min = (now - state["meeting_start_ts"]) / 60

        # Throttle: at most one proactive message per 10 minutes
        if now - state["intervention_last_ts"] < 600:
            continue

        # Trigger 1: No decisions logged after 30 minutes
        if elapsed_min >= 30 and state["decisions_detected"] == 0 and not state["sent_30min_nudge"]:
            state["sent_30min_nudge"] = True
            state["intervention_last_ts"] = now
            await _send_chat_response(
                bot_id,
                "📋 30 minutes in — no decisions logged yet. Say 'Prism, summarize what's been decided' to capture them.",
            )
            continue

        # Trigger 4: Action items detected but no explicit owners
        if (
            state["action_items_detected"] >= 3
            and state["owners_detected"] == 0
            and elapsed_min >= 15
            and not state["sent_no_owners_nudge"]
        ):
            state["sent_no_owners_nudge"] = True
            state["intervention_last_ts"] = now
            await _send_chat_response(
                bot_id,
                "👤 Some action items may not have clear owners yet. Say 'Prism, who owns what?' to clarify.",
            )
            continue

        # Trigger 3: Meeting approaching 1 hour
        if elapsed_min >= 55 and not state["sent_55min_nudge"]:
            state["sent_55min_nudge"] = True
            state["intervention_last_ts"] = now
            await _send_chat_response(
                bot_id,
                "⏱️ Meeting approaching 1 hour. Say 'Prism, list the action items so far' to make sure everything is captured before wrapping up.",
            )
            continue

        # Fetch historical blockers once per meeting so the idea engine can use them.
        # Matching and surfacing is handled by _maybe_generate_idea (LLM-based, richer reasoning).
        if not state["recurring_blocker_checked"]:
            user_id = (bot_store.get(bot_id) or {}).get("user_id")
            state["historical_blockers"] = await _fetch_historical_blockers(user_id)
            state["recurring_blocker_checked"] = True


async def _process_command(bot_id: str, command: str, speaker: str = ""):
    """Process a detected command: use LLM to pick tools, execute, respond."""
    state = _get_bot_state(bot_id)

    # Debounce — don't process commands within 15 seconds of each other
    now = time.time()
    if now - state["last_command_ts"] < 15:
        return
    if state["processing"]:
        return
    # Dedup — skip if this command is just an extension of the last one (rolling transcript)
    cmd_norm = _normalize_cmd(command)
    last_norm = state.get("last_command_norm", "")
    if last_norm and (cmd_norm.startswith(last_norm) or last_norm.startswith(cmd_norm)):
        return

    state["last_command_ts"] = now
    state["last_command_text"] = command
    state["last_command_norm"] = cmd_norm
    state["processing"] = True

    messages = None  # ensure always in scope for haiku fallback
    try:
        user_settings = await _get_settings_for_bot(bot_id)
        tools = get_available_tools(user_settings)

        tool_names = [t["function"]["name"] for t in tools]
        print(f"[realtime] available tools for bot {bot_id[:8]}: {tool_names}")

        if not GROQ_API_KEY:
            await _send_chat_response(bot_id, "Sorry, I can't process commands right now.")
            return

        groq_client = get_groq()

        # Build full three-layer memory context for this command
        memory_context = meeting_memory.build_memory_context(state, command)
        now = datetime.now(ZoneInfo("America/New_York"))
        hour_12 = now.hour % 12 or 12
        tz_abbr = now.strftime("%Z")  # "EST" or "EDT"
        now_str = f"{now.strftime('%A, %B')} {now.day}, {now.year} at {hour_12}:{now.strftime('%M %p')} {tz_abbr}"

        has_gmail = any(t["function"]["name"].startswith("gmail") for t in tools)
        has_calendar = any(t["function"]["name"].startswith("calendar") for t in tools)

        email_note = (
            "You have Gmail access. Only call gmail_send when the user explicitly says to send an email and "
            "provides a recipient and intent. If asked whether you can send emails, answer YES directly — "
            "do not call a tool just to answer that question. "
        ) if has_gmail else (
            "You do NOT have Gmail access right now. If the user asks you to send an email, "
            "respond: 'I need Google access to send emails — please connect Google in your account settings.' "
        )

        calendar_note = (
            "You have full Google Calendar access: use calendar_list_events to read/check upcoming events, "
            "calendar_create_event to schedule (only if the user provides title AND date/time), "
            "and calendar_update_event to reschedule. "
            "If asked whether you can access the calendar, answer YES directly — do not call a tool just to answer that question. "
        ) if has_calendar else (
            "You do NOT have Calendar access right now. If asked about calendar, "
            "respond: 'I need Google access — please connect Google in your account settings.' "
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are PrismAI, an AI meeting assistant that is LIVE in this meeting. "
                    "A participant just gave you a command. "
                    "You have access to the full meeting memory below — use it to answer questions "
                    "about anything discussed during the meeting, no matter how long ago it was said. "
                    "Answer directly from the meeting memory or your knowledge whenever possible. "
                    "NEVER call a tool unless the user is explicitly asking you to perform that action right now "
                    "(e.g. 'send an email to X', 'check my calendar', 'create a ticket'). "
                    "Questions about your capabilities, access, or what you can do must be answered in words — never by calling a tool. "
                    f"{email_note}"
                    f"{calendar_note}"
                    "Be concise — responses will be spoken aloud. Keep responses under 3 sentences.\n"
                    f"Current date and time: {now_str}.\n\n"
                    f"{memory_context}"
                ),
            },
            {"role": "user", "content": f"{speaker}: {command}" if speaker else command},
        ]

        tools_used = []
        valid_tool_names = {t["function"]["name"] for t in tools}
        call_kwargs = {
            "model": "llama-3.3-70b-versatile",
            "temperature": 0.3,
            "messages": messages,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        reply = None
        actual_user_id = (bot_store.get(bot_id) or {}).get("user_id")
        user_id = actual_user_id or bot_id  # bot_id used only as rate-limit key when unauthed
        # Pass bot_id through so tools like knowledge_lookup can scope audit logs.
        tool_settings = dict(user_settings)
        tool_settings["bot_id"] = bot_id

        async def _run_tool_calls(tc_specs):
            """Execute a list of (id, name, arguments_json_str) and append tool messages.
            `tc_specs` is shaped the same regardless of whether the call came from a
            structured tool_calls field or was recovered from a malformed generation.
            """
            for tc_id, tc_name, tc_args in tc_specs:
                result = await execute_tool(
                    tc_name,
                    tc_args,
                    user_id=user_id,
                    user_settings=tool_settings,
                )
                if result.get("requires_confirmation"):
                    # In live meeting context, the spoken/typed command is the confirmation
                    result = await confirm_and_execute(
                        tc_name,
                        result["preview"],
                        user_settings=user_settings,
                    )
                if result.get("external_ref") and supabase and actual_user_id:
                    try:
                        supabase.table("action_refs").insert({
                            "user_id": actual_user_id,
                            "action_item": command,
                            "tool": result["external_ref"]["tool"],
                            "external_id": result["external_ref"]["external_id"],
                        }).execute()
                    except Exception:
                        pass
                tools_used.append(tc_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(result),
                })

        # Streamed-LLM gate: requires both flags; only fires on synthesis turns
        # (when `tools` is no longer in call_kwargs — either because the user has
        # no tools available, or PR-1 taint enforcement stripped them, or the
        # tools-format retry stripped them).
        streamed_voice_active = (
            os.getenv("PRISM_STREAMED_TTS") == "1"
            and os.getenv("PRISM_STREAMED_LLM") == "1"
        )
        voice_already_streamed = False

        # Tool loop (max 3 iterations)
        for iteration in range(3):
            if streamed_voice_active and "tools" not in call_kwargs:
                # PR-5: stream the synthesis turn directly into TTS+upload.
                try:
                    streamed_reply = await _stream_llm_to_voice(
                        groq_client, call_kwargs, bot_id, state["last_command_ts"] or now,
                    )
                except Exception as stream_exc:
                    print(f"[realtime] streamed LLM failed, falling back: {stream_exc}")
                    streamed_reply = None
                if streamed_reply:
                    reply = streamed_reply
                    voice_already_streamed = True
                    break
                # Stream failed entirely (no text produced) — fall through to buffered retry below.

            response = None
            synth_calls = None

            try:
                response = await groq_client.chat.completions.create(**call_kwargs)
            except Exception as groq_exc:
                # Llama 3.3 occasionally emits tool calls as raw `<function=NAME {json}>`
                # text instead of structured tool_calls; Groq rejects with 400
                # tool_use_failed. Try to recover by parsing the failed generation.
                err_str = str(groq_exc)
                is_400 = "400" in err_str or "tool_use_failed" in err_str
                if is_400 and "tools" in call_kwargs:
                    failed_gen = _extract_failed_generation(groq_exc)
                    recovered = _recover_tool_calls(failed_gen, valid_tool_names)
                    if recovered:
                        print(
                            f"[realtime] recovered {len(recovered)} tool call(s) from malformed generation: "
                            f"{[c['name'] for c in recovered]}"
                        )
                        synth_calls = recovered

                if synth_calls is None:
                    # Couldn't recover. Strip tools and retry once for a plain-text answer.
                    if "tools" in call_kwargs:
                        print(f"[realtime] tool call format error, retrying without tools: {groq_exc}")
                        call_kwargs.pop("tools", None)
                        call_kwargs.pop("tool_choice", None)
                        try:
                            response = await groq_client.chat.completions.create(**call_kwargs)
                        except Exception as retry_exc:
                            print(f"[realtime] retry-without-tools also failed: {retry_exc}")
                            reply = "Sorry, I had trouble processing that."
                            break
                    else:
                        print(f"[realtime] command failed without tools: {groq_exc}")
                        reply = "Sorry, I had trouble processing that."
                        break

            # Belt-and-suspenders: a 200 response may still leak <function=...> in
            # content (Groq sometimes lets these through). Parse and treat as a call.
            if synth_calls is None and response is not None and "tools" in call_kwargs:
                msg = response.choices[0].message
                if not msg.tool_calls and msg.content and "<function=" in msg.content:
                    leaked = _recover_tool_calls(msg.content, valid_tool_names)
                    if leaked:
                        print(
                            f"[realtime] recovered {len(leaked)} leaked tool call(s) from 200 content: "
                            f"{[c['name'] for c in leaked]}"
                        )
                        synth_calls = leaked

            if synth_calls is not None:
                # Synthesise a proper assistant message with tool_calls and execute.
                tc_payload = []
                ts_ms = int(time.time() * 1000)
                for idx, call in enumerate(synth_calls):
                    tc_payload.append({
                        "id": f"call_synth_{iteration}_{idx}_{ts_ms}",
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    })
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tc_payload,
                })
                await _run_tool_calls([
                    (tc["id"], tc["function"]["name"], tc["function"]["arguments"])
                    for tc in tc_payload
                ])
                if _strip_tools_if_tainted(call_kwargs, [tc["function"]["name"] for tc in tc_payload]):
                    print(f"[realtime] tainted tool executed (recovery path); disabling further tool use this turn")
                call_kwargs["messages"] = messages
                continue  # Re-prompt the model with the tool results.

            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                reply = choice.message.content or f"Got it — {command}."
                break

            messages.append(choice.message)
            executed_names = [tc.function.name for tc in choice.message.tool_calls]
            await _run_tool_calls([
                (tc.id, tc.function.name, tc.function.arguments)
                for tc in choice.message.tool_calls
            ])
            if _strip_tools_if_tainted(call_kwargs, executed_names):
                print(f"[realtime] tainted tool executed; disabling further tool use this turn")
            call_kwargs["messages"] = messages
        else:
            # Tool loop exhausted without a text summary — ask LLM to summarise what was done
            try:
                summary_resp = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    temperature=0.3,
                    messages=messages + [{"role": "user", "content": "Summarise in one sentence what you just did."}],
                )
                reply = summary_resp.choices[0].message.content or "Done."
            except Exception:
                reply = "Done."

        # Log command to bot_store and Supabase
        cmd_entry = {
            "command": command,
            "speaker": speaker,
            "tools": tools_used,
            "reply": reply,
            "ts": time.time(),
        }
        if bot_id in bot_store:
            bot_store[bot_id].setdefault("commands", []).append(cmd_entry)
        _db_append_command(bot_id, cmd_entry)

        # Respond via voice + chat
        print(f"[realtime] command='{command}' tools={tools_used} reply='{reply}'")
        await _send_chat_response(bot_id, f"✓ {reply}")
        if voice_already_streamed:
            # PR-5 streamed-LLM path already produced and uploaded audio in parallel
            # with token generation. Nothing more to do.
            pass
        elif os.getenv("PRISM_STREAMED_TTS") == "1":
            await _send_voice_response_streamed(bot_id, reply, cmd_detected_ts=state["last_command_ts"] or now)
        else:
            await _send_voice_response(bot_id, reply)

    except Exception as exc:
        err_str = str(exc)
        status_code = getattr(exc, "status_code", None)
        is_transient = (
            status_code in {429, 500, 502, 503, 504}
            or any(kw in err_str for kw in ("rate_limit", "overloaded", "capacity"))
        )
        if is_transient:
            from agents.utils import _get_anthropic
            anthropic_client = _get_anthropic()
            msgs = messages
            if anthropic_client and msgs:
                try:
                    haiku_resp = await anthropic_client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=256,
                        system=msgs[0]["content"],
                        messages=[{"role": "user", "content": f"{speaker}: {command}" if speaker else command}],
                    )
                    reply = haiku_resp.content[0].text
                    cmd_entry = {"command": command, "speaker": speaker, "tools": [], "reply": reply, "ts": time.time()}
                    if bot_id in bot_store:
                        bot_store[bot_id].setdefault("commands", []).append(cmd_entry)
                    _db_append_command(bot_id, cmd_entry)
                    print(f"[realtime] haiku fallback reply={reply!r}")
                    await _send_chat_response(bot_id, f"✓ {reply}")
                    await _send_voice_response(bot_id, reply)
                    return
                except Exception as haiku_exc:
                    print(f"[realtime] haiku fallback failed: {haiku_exc}")
        print(f"[realtime] command processing error: {exc}")
        await _send_chat_response(bot_id, f"Sorry, I ran into an error: {str(exc)[:100]}")
    finally:
        state["processing"] = False


@router.post("/realtime-events")
async def realtime_events(request: Request):
    """Receive real-time transcript and chat events from Recall.ai."""
    payload = await request.json()

    event_type = payload.get("event") or payload.get("type") or ""
    data_field = payload.get("data") or {}
    bot_id = (
        payload.get("bot_id")
        or data_field.get("bot_id")
        or (data_field.get("bot") or {}).get("id")
        or ""
    )

    print(f"[realtime] event={event_type!r} bot={bot_id[:8] if bot_id else 'none'} data_keys={list(data_field.keys()) if isinstance(data_field, dict) else type(data_field).__name__}")

    if not bot_id:
        return {"ok": True}

    if bot_id and bot_id not in _bot_state and bot_id not in bot_store:
        from recall_routes import _db_load
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    state = _get_bot_state(bot_id)

    # Handle transcript data
    if event_type in ("transcript.data", "transcript_data"):
        # data_field["transcript"] is a reference object {id, metadata} — not the words.
        # The actual transcript segment (words + speaker) is in data_field["data"].
        segment = data_field.get("data") or data_field

        if isinstance(segment, dict):
            words = segment.get("words", [])
            speaker = segment.get("speaker") or (segment.get("participant") or {}).get("name") or "Speaker"
            text = " ".join(w.get("text", "") for w in words) if words else segment.get("text", "")
        else:
            print(f"[realtime] segment not a dict: type={type(segment).__name__} preview={str(segment)[:200]}")
            words, speaker, text = [], "Speaker", ""

        if text.strip():
            print(f"[realtime] extracted speaker={speaker!r} text={text[:120]!r}")

        if text.strip():
            line = f"{speaker}: {text.strip()}"
            state["transcript_buffer"].append(line)
            # Cap buffer at MAX_BUFFER_LINES (old lines are already compressed into the summary)
            if len(state["transcript_buffer"]) > meeting_memory.MAX_BUFFER_LINES:
                state["transcript_buffer"] = state["transcript_buffer"][-meeting_memory.TRIM_TO:]
                # Cursor must not point past the new (shorter) buffer
                state["compression_cursor"] = min(
                    state["compression_cursor"], len(state["transcript_buffer"])
                )
            # Mirror to bot_store so _process_bot_transcript can use it at meeting end
            if bot_id in bot_store:
                bot_store[bot_id]["realtime_transcript_lines"] = state["transcript_buffer"]

            # Mark meeting start and run all Layer-3 structured extraction + counter updates
            if state["meeting_start_ts"] is None:
                state["meeting_start_ts"] = time.time()
            meeting_memory.update_structured_state(text, speaker, state)

            # Trigger async Layer-2 compression (non-blocking; exits immediately if not ready)
            asyncio.create_task(_compress_and_persist(bot_id, state))

            # Check for command trigger
            command = _detect_command(text)
            if command:
                print(f"[realtime] command={command!r} detected from speaker={speaker!r}")
                state["pending_trigger_ts"] = 0
                state["pending_command_parts"] = []
                asyncio.create_task(_process_command(bot_id, command, speaker))
            elif _has_trigger_word(text):
                # Trigger word seen but no command yet — wait for the next utterance
                state["pending_trigger_ts"] = time.time()
                state["pending_trigger_speaker"] = speaker
                state["pending_command_parts"] = []
                print(f"[realtime] trigger word detected, awaiting command from {speaker!r}")
            elif state["pending_trigger_ts"] and time.time() - state["pending_trigger_ts"] < PENDING_TRIGGER_WINDOW:
                # Within the wake-word window — accumulate parts until we have enough words
                pending_speaker = state["pending_trigger_speaker"]
                if not pending_speaker or pending_speaker == speaker:
                    state["pending_command_parts"].append(text.strip())
                    accumulated = " ".join(state["pending_command_parts"])
                    if len(re.findall(r'\b\w+\b', accumulated)) >= 2:
                        state["pending_trigger_ts"] = 0
                        state["pending_command_parts"] = []
                        print(f"[realtime] deferred command={accumulated!r} from speaker={speaker!r}")
                        asyncio.create_task(_process_command(bot_id, accumulated, speaker))
                    else:
                        print(f"[realtime] accumulating deferred command: {accumulated!r}")
            else:
                state["pending_trigger_ts"] = 0
                state["pending_command_parts"] = []
                print(f"[realtime] no command trigger in text")

    # Handle chat messages from the meeting
    elif event_type in ("participant_events.chat_message", "chat_message"):
        # Payload shape (Google Meet): data.data.action_obj, data.data.data.text, data.data.participant.name
        outer = payload.get("data", {})
        action_obj = outer.get("data") or outer  # {"action", "participant", "data": {"text":...}}
        chat_data = action_obj.get("data") or {}
        message_text = chat_data.get("text") or action_obj.get("text") or action_obj.get("message", "")
        sender_obj = action_obj.get("participant") or action_obj.get("sender") or {}
        sender = sender_obj.get("name") or action_obj.get("name") or "Someone"

        print(f"[realtime] chat message sender={sender!r} text={message_text[:120]!r}")

        if message_text.strip():
            # Check for command trigger in chat
            command = _detect_command(message_text)
            if command:
                print(f"[realtime] chat command={command!r} from={sender!r}")
                asyncio.create_task(_process_command(bot_id, command, sender))

    return {"ok": True}


def init_bot_realtime(bot_id: str):
    """Initialize real-time state for a bot. Called when a bot is created."""
    _get_bot_state(bot_id)


def cleanup_bot_state(bot_id: str) -> None:
    _bot_state.pop(bot_id, None)

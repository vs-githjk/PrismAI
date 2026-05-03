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

import httpx
from fastapi import APIRouter, Request
from groq import AsyncGroq

import meeting_memory
from agents.utils import llm_call, strip_fences
from tools.registry import get_available_tools, execute_tool, confirm_and_execute
from tools.tts import text_to_speech
from recall_routes import bot_store, _db_append_command, _db_save_memory
from auth import supabase
from cross_meeting_service import looks_like_blocker, extract_significant_terms

router = APIRouter(tags=["realtime"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-east-1.recall.ai/api/v1")
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
            row = resp.data or {}
            if row.get("google_access_token"):
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
        async with httpx.AsyncClient() as client:
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


async def _send_voice_response(bot_id: str, text: str):
    """Convert text to speech and play it in the meeting via Recall.ai bot."""
    audio_bytes = await text_to_speech(text)
    if not audio_bytes:
        print(f"[realtime] TTS produced no audio for bot {bot_id}, skipping voice")
        return

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/output_audio/",
                headers={"Authorization": f"Token {RECALL_API_KEY}", "Content-Type": "application/json"},
                json={"kind": "mp3", "b64_data": base64.b64encode(audio_bytes).decode()},
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                print(f"[realtime] output_audio failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as exc:
        print(f"[realtime] voice response failed: {exc}")


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

        if not GROQ_API_KEY:
            await _send_chat_response(bot_id, "Sorry, I can't process commands right now.")
            return

        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

        # Build full three-layer memory context for this command
        memory_context = meeting_memory.build_memory_context(state, command)
        now = datetime.now()
        hour_12 = now.hour % 12 or 12
        now_str = f"{now.strftime('%A, %B')} {now.day}, {now.year} at {hour_12}:{now.strftime('%M %p')}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are PrismAI, an AI meeting assistant that is LIVE in this meeting. "
                    "A participant just gave you a command. "
                    "You have access to the full meeting memory below — use it to answer questions "
                    "about anything discussed during the meeting, no matter how long ago it was said. "
                    "Answer directly from the meeting memory or your knowledge whenever possible. "
                    "Do NOT call a tool unless the command explicitly asks for an external action "
                    "(e.g. 'send an email', 'check my calendar', 'create a ticket'). "
                    "For gmail_send: ONLY send if the user explicitly states the recipient's full email address. "
                    "For calendar_create_event: ONLY create an event if the user has stated the title AND date/time. "
                    "Be concise — responses will be spoken aloud. Keep responses under 3 sentences.\n"
                    f"Current date and time: {now_str}.\n\n"
                    f"{memory_context}"
                ),
            },
            {"role": "user", "content": f"{speaker}: {command}" if speaker else command},
        ]

        tools_used = []
        call_kwargs = {
            "model": "llama-3.3-70b-versatile",
            "temperature": 0.3,
            "messages": messages,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        # Tool loop (max 3 iterations)
        for _ in range(3):
            try:
                response = await groq_client.chat.completions.create(**call_kwargs)
            except Exception as groq_exc:
                # Llama sometimes generates malformed tool calls (400). Retry without tools.
                if "400" in str(groq_exc) and "tools" in call_kwargs:
                    print(f"[realtime] tool call format error, retrying without tools: {groq_exc}")
                    call_kwargs.pop("tools", None)
                    call_kwargs.pop("tool_choice", None)
                    response = await groq_client.chat.completions.create(**call_kwargs)
                else:
                    raise

            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                reply = choice.message.content or f"Got it — {command}."
                break

            messages.append(choice.message)
            actual_user_id = (bot_store.get(bot_id) or {}).get("user_id")
            user_id = actual_user_id or bot_id  # bot_id used only as rate-limit key when unauthed
            for tool_call in choice.message.tool_calls:
                result = await execute_tool(
                    tool_call.function.name,
                    tool_call.function.arguments,
                    user_id=user_id,
                    user_settings=user_settings,
                )
                if result.get("requires_confirmation"):
                    # In live meeting context, the spoken/typed command is the confirmation
                    result = await confirm_and_execute(
                        tool_call.function.name,
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
                tools_used.append(tool_call.function.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })
            call_kwargs["messages"] = messages
        else:
            reply = f"Done — completed {command}."

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

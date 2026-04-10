"""
Real-time webhook: receives live transcript + chat messages from Recall.ai,
detects PrismAI commands, executes tools, and optionally responds via TTS.
"""

import asyncio
import json
import os
import re
import time

import httpx
from fastapi import APIRouter, Request
from groq import AsyncGroq

from tools.registry import get_available_tools, execute_tool, confirm_and_execute
from tools.tts import text_to_speech
from recall_routes import bot_store, _db_append_command
from auth import supabase

router = APIRouter(tags=["realtime"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"
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


def _get_bot_state(bot_id: str) -> dict:
    if bot_id not in _bot_state:
        _bot_state[bot_id] = {
            "transcript_buffer": [],
            "last_command_ts": 0,
            "processing": False,
        }
    return _bot_state[bot_id]


def _detect_command(text: str) -> str | None:
    """Check if text contains a PrismAI command trigger. Returns the command part or None."""
    match = TRIGGER_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


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
        print(f"[realtime] TTS failed for bot {bot_id}, falling back to chat")
        await _send_chat_response(bot_id, text)
        return

    try:
        async with httpx.AsyncClient() as client:
            # Recall.ai output_audio endpoint
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/output_audio/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "audio/mpeg",
                },
                content=audio_bytes,
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                print(f"[realtime] output_audio failed ({resp.status_code}), falling back to chat")
                await _send_chat_response(bot_id, text)
    except Exception as exc:
        print(f"[realtime] voice response failed: {exc}, falling back to chat")
        await _send_chat_response(bot_id, text)


async def _process_command(bot_id: str, command: str, speaker: str = ""):
    """Process a detected command: use LLM to pick tools, execute, respond."""
    state = _get_bot_state(bot_id)

    # Debounce — don't process commands within 5 seconds of each other
    now = time.time()
    if now - state["last_command_ts"] < 5:
        return
    if state["processing"]:
        return

    state["last_command_ts"] = now
    state["processing"] = True

    try:
        user_settings = await _get_settings_for_bot(bot_id)
        tools = get_available_tools(user_settings)

        if not GROQ_API_KEY:
            await _send_chat_response(bot_id, "Sorry, I can't process commands right now.")
            return

        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

        # Build recent transcript context
        recent_transcript = "\n".join(state["transcript_buffer"][-30:])

        messages = [
            {
                "role": "system",
                "content": (
                    "You are PrismAI, an AI meeting assistant that is LIVE in this meeting. "
                    "A participant just gave you a command. Execute it using the available tools. "
                    "Be concise in your response — you'll be speaking aloud in the meeting. "
                    "Keep responses under 2 sentences. "
                    "Do NOT ask for confirmation — the user gave a direct command, execute it. "
                    f"\n\nRecent transcript for context:\n{recent_transcript}"
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
            response = await groq_client.chat.completions.create(**call_kwargs)
            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                reply = choice.message.content or "Done."
                break

            messages.append(choice.message)
            for tool_call in choice.message.tool_calls:
                # In live mode, skip confirmation and execute directly
                result = await confirm_and_execute(
                    tool_call.function.name,
                    tool_call.function.arguments,
                    user_settings=user_settings,
                )
                tools_used.append(tool_call.function.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })
            call_kwargs["messages"] = messages
        else:
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
        await _send_voice_response(bot_id, reply)

    except Exception as exc:
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
            # Keep buffer manageable
            if len(state["transcript_buffer"]) > 500:
                state["transcript_buffer"] = state["transcript_buffer"][-400:]
            # Also write to bot_store so _process_bot_transcript can use it
            if bot_id in bot_store:
                bot_store[bot_id]["realtime_transcript_lines"] = state["transcript_buffer"]

            # Check for command trigger
            command = _detect_command(text)
            if command:
                print(f"[realtime] command={command!r} detected from speaker={speaker!r}")
                asyncio.create_task(_process_command(bot_id, command, speaker))
            else:
                print(f"[realtime] no command trigger in text")

    # Handle chat messages from the meeting
    elif event_type in ("participant_events.chat_message", "chat_message"):
        data = payload.get("data", {})
        message_text = data.get("text") or data.get("message", "")
        sender = data.get("sender", {}).get("name") or data.get("name") or "Someone"

        if message_text.strip():
            # Check for command trigger in chat
            command = _detect_command(message_text)
            if command:
                asyncio.create_task(_process_command(bot_id, command, sender))

    return {"ok": True}


def init_bot_realtime(bot_id: str):
    """Initialize real-time state for a bot. Called when a bot is created."""
    _get_bot_state(bot_id)

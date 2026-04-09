import asyncio
import json
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from analysis_service import run_full_analysis
from auth import supabase, require_user_id


router = APIRouter(tags=["recall"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")

# In-memory cache (always used for fast access; synced to Supabase when available)
bot_store: dict = {}


def _db_save(bot_id: str, fields: dict):
    """Persist bot state to Supabase (best-effort, non-blocking)."""
    if not supabase:
        return
    try:
        fields["bot_id"] = bot_id
        fields["updated_at"] = "now()"
        supabase.table("bot_sessions").upsert(fields, on_conflict="bot_id").execute()
    except Exception as exc:
        print(f"[recall] db save failed for {bot_id}: {exc}")


def _db_load(bot_id: str) -> dict | None:
    """Load bot state from Supabase."""
    if not supabase:
        return None
    try:
        res = supabase.table("bot_sessions").select("*").eq("bot_id", bot_id).maybe_single().execute()
        if res and res.data:
            row = res.data
            return {
                "status": row.get("status", "joining"),
                "result": row.get("result"),
                "error": row.get("error"),
                "transcript": row.get("transcript"),
                "commands": row.get("commands") or [],
                "user_id": row.get("user_id"),
            }
    except Exception as exc:
        print(f"[recall] db load failed for {bot_id}: {exc}")
    return None


def _db_append_command(bot_id: str, command: dict):
    """Append a command log entry to the bot session."""
    if not supabase:
        return
    try:
        res = supabase.table("bot_sessions").select("commands").eq("bot_id", bot_id).maybe_single().execute()
        commands = ((res.data if res else None) or {}).get("commands") or []
        commands.append(command)
        supabase.table("bot_sessions").update({"commands": commands, "updated_at": "now()"}).eq("bot_id", bot_id).execute()
    except Exception as exc:
        print(f"[recall] db append command failed: {exc}")

STATUS_MAP = {
    "joining_call": "joining",
    "in_call_not_recording": "joining",
    "in_call_recording": "recording",
    "call_ended": "processing",
    "done": "done",
    "fatal_error": "error",
}


class JoinMeetingRequest(BaseModel):
    meeting_url: str


def _extract_recall_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail

    text = (resp.text or "").strip()
    return text or f"Recall.ai request failed with status {resp.status_code}"


async def _send_bot_intro(bot_id: str):
    await asyncio.sleep(20)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/send_chat_message/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"message": "Hi, I'm PrismAI 👋 I'm here to observe and help you get the most out of this meeting. I'll send you a full analysis when we're done."},
                timeout=10,
            )
    except Exception:
        pass


async def _fetch_transcript(bot_id: str):
    """Fetch transcript via bot recordings → media_shortcuts → transcript download URL."""
    for attempt in range(12):
        print(f"[recall] fetch transcript attempt {attempt + 1}/12 for bot {bot_id}")
        async with httpx.AsyncClient() as client:
            # Get bot details which include recordings
            resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if resp.status_code != 200:
            print(f"[recall] bot fetch failed, status={resp.status_code}")
            await asyncio.sleep(3 * (attempt + 1))
            continue

        bot_data = resp.json()
        recordings = bot_data.get("recordings") or []
        print(f"[recall] bot has {len(recordings)} recording(s)")

        # Look for transcript download URL in recordings
        download_url = None
        for rec in recordings:
            shortcuts = rec.get("media_shortcuts") or {}
            download_url = shortcuts.get("transcript.data.download_url")
            if download_url:
                break

        if not download_url:
            wait = min(10 * (attempt + 1), 60)
            print(f"[recall] no transcript download URL yet, waiting {wait}s...")
            await asyncio.sleep(wait)
            continue

        # Download the actual transcript data
        print(f"[recall] downloading transcript from {download_url[:80]}...")
        async with httpx.AsyncClient() as client:
            transcript_resp = await client.get(download_url, timeout=30)

        if transcript_resp.status_code == 200:
            return transcript_resp
        print(f"[recall] transcript download failed, status={transcript_resp.status_code}")
        await asyncio.sleep(3 * (attempt + 1))

    return None


def _transcript_from_recall_data(raw) -> str:
    """Parse transcript from Recall's transcript data format."""
    # Handle list of segments with words (legacy + new format)
    if isinstance(raw, list):
        transcript_lines = []
        for segment in raw:
            speaker = segment.get("speaker") or "Speaker"
            # New format: words as list of dicts with "text"
            words = segment.get("words") or []
            if words:
                text = " ".join(w.get("text", "") for w in words)
            else:
                # Fallback: segment might have direct "text" field
                text = segment.get("text", "")
            if text.strip():
                transcript_lines.append(f"{speaker}: {text.strip()}")
        return "\n".join(transcript_lines)

    # Handle dict format (e.g., { "transcript": "..." })
    if isinstance(raw, dict):
        if "transcript" in raw:
            return raw["transcript"]
        # Try to find any text content
        for key in ("text", "content", "data"):
            if key in raw and isinstance(raw[key], str):
                return raw[key]

    # Handle plain string
    if isinstance(raw, str):
        return raw

    return ""


async def _process_bot_transcript(bot_id: str):
    try:
        print(f"[recall] starting transcript processing for bot {bot_id}")
        await asyncio.sleep(15)
        resp = await _fetch_transcript(bot_id)

        if resp is None:
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = "Failed to fetch transcript from Recall.ai"
            _db_save(bot_id, {"status": "error", "error": bot_store[bot_id]["error"]})
            print(f"[recall] ERROR: failed to fetch transcript")
            return

        raw = resp.json()
        print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:500]}")
        transcript = _transcript_from_recall_data(raw)
        if not transcript.strip():
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = "No transcript content found — the meeting may have been too short or had no speech"
            _db_save(bot_id, {"status": "error", "error": bot_store[bot_id]["error"]})
            print(f"[recall] ERROR: empty transcript")
            return

        print(f"[recall] transcript OK, {len(transcript)} chars. Running analysis...")
        bot_store[bot_id]["transcript"] = transcript
        bot_store[bot_id]["result"] = await run_full_analysis(transcript)
        bot_store[bot_id]["status"] = "done"
        _db_save(bot_id, {"status": "done", "transcript": transcript, "result": bot_store[bot_id]["result"]})
        print(f"[recall] analysis complete for bot {bot_id}")
    except Exception as exc:
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = str(exc)
        _db_save(bot_id, {"status": "error", "error": str(exc)})
        print(f"[recall] ERROR processing bot {bot_id}: {exc}")


async def _optional_user_id(request: Request) -> str | None:
    """Try to extract user_id from auth header, return None if not authenticated."""
    try:
        return await require_user_id(request)
    except HTTPException:
        return None


@router.post("/join-meeting")
async def join_meeting(req: JoinMeetingRequest, request: Request):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    if not req.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL cannot be empty")

    # Optionally link bot to authenticated user (enables live tool access)
    user_id = await _optional_user_id(request)

    webhook_url = f"{WEBHOOK_BASE_URL}/recall-webhook"

    realtime_url = f"{WEBHOOK_BASE_URL}/realtime-events"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RECALL_API_BASE}/bot/",
            headers={
                "Authorization": f"Token {RECALL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "meeting_url": req.meeting_url,
                "bot_name": "PrismAI",
                "webhook_url": webhook_url,
                "recording_config": {
                    "transcript": {
                        "provider": {
                            "gladia": {}
                        }
                    },
                    "realtime_endpoints": [
                        {
                            "type": "webhook",
                            "url": realtime_url,
                            "events": [
                                "transcript.data",
                                "participant_events.chat_message",
                            ],
                        }
                    ],
                },
            },
            timeout=15,
        )

    if resp.status_code not in (200, 201):
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai error: {detail}")

    data = resp.json()
    bot_id = data["id"]
    bot_store[bot_id] = {"status": "joining", "result": None, "error": None, "commands": [], "user_id": user_id}
    _db_save(bot_id, {"status": "joining", "user_id": user_id})

    from realtime_routes import init_bot_realtime
    init_bot_realtime(bot_id)

    asyncio.create_task(_send_bot_intro(bot_id))
    return {"bot_id": bot_id, "status": "joining"}


@router.delete("/remove-bot/{bot_id}")
async def remove_bot(bot_id: str):
    """Stop and remove a Recall.ai bot from the call."""
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    try:
        async with httpx.AsyncClient() as client:
            # Use leave_call for active bots (DELETE only works for scheduled/unjoined bots)
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/leave_call/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
            print(f"[recall] leave_call for bot {bot_id}: status={resp.status_code}")
            # If leave_call fails (bot not in call), try DELETE as fallback
            if resp.status_code not in (200, 201, 204):
                await client.delete(
                    f"{RECALL_API_BASE}/bot/{bot_id}/",
                    headers={"Authorization": f"Token {RECALL_API_KEY}"},
                    timeout=10,
                )
    except httpx.HTTPError:
        pass  # Best-effort — don't block the client reset
    bot_store.pop(bot_id, None)
    return {"ok": True}


@router.get("/bot-status/{bot_id}")
async def bot_status(bot_id: str):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")

    # Try loading from DB if not in memory (handles server restart)
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RECALL_API_BASE}/bot/{bot_id}/",
            headers={"Authorization": f"Token {RECALL_API_KEY}"},
            timeout=10,
        )

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Bot not found")
    if resp.status_code != 200:
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai status check failed: {detail}")

    recall_data = resp.json()
    recall_status = recall_data.get("status_changes", [{}])[-1].get("code", "") if recall_data.get("status_changes") else ""
    our_status = STATUS_MAP.get(recall_status, bot_store.get(bot_id, {}).get("status", "joining"))

    if recall_status in ("call_ended", "done"):
        if bot_id not in bot_store:
            bot_store[bot_id] = {"status": "processing", "result": None, "error": None, "commands": []}
            _db_save(bot_id, {"status": "processing"})
            asyncio.create_task(_process_bot_transcript(bot_id))
        elif bot_store[bot_id].get("status") not in ("processing", "done", "error"):
            bot_store[bot_id]["status"] = "processing"
            _db_save(bot_id, {"status": "processing"})
            asyncio.create_task(_process_bot_transcript(bot_id))

    entry = bot_store.get(bot_id, {"status": our_status, "result": None, "error": None, "commands": []})
    # Don't let Recall's "done" override our internal "processing"
    entry["status"] = our_status if entry.get("status") not in ("done", "error", "processing") else entry["status"]
    return entry


@router.post("/recall-webhook")
async def recall_webhook(request: Request):
    payload = await request.json()

    bot_id = (
        payload.get("data", {}).get("bot", {}).get("id")
        or payload.get("bot_id")
        or payload.get("id")
    )
    event = (
        payload.get("event")
        or payload.get("data", {}).get("status", {}).get("code")
        or ""
    )

    if not bot_id:
        return {"ok": True}

    if bot_id not in bot_store:
        bot_store[bot_id] = {"status": "unknown", "result": None, "error": None, "commands": []}

    if event in ("bot.joining_call", "joining_call"):
        bot_store[bot_id]["status"] = "joining"
        _db_save(bot_id, {"status": "joining"})
    elif event in ("bot.in_call_recording", "in_call_recording"):
        bot_store[bot_id]["status"] = "recording"
        _db_save(bot_id, {"status": "recording"})
    elif event in ("bot.call_ended", "call_ended", "bot.done", "done"):
        if bot_store[bot_id].get("status") not in ("processing", "done"):
            bot_store[bot_id]["status"] = "processing"
            _db_save(bot_id, {"status": "processing"})
            asyncio.create_task(_process_bot_transcript(bot_id))
    elif event in ("bot.fatal_error", "fatal_error"):
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = "Bot encountered a fatal error"
        _db_save(bot_id, {"status": "error", "error": "Bot encountered a fatal error"})

    return {"ok": True}

import asyncio
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from analysis_service import run_full_analysis


router = APIRouter(tags=["recall"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")

# In-memory store: bot_id → { status, result, error, transcript }
bot_store: dict = {}

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
    resp = None
    for attempt in range(5):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/transcript/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if resp.status_code == 200:
            return resp
        await asyncio.sleep(5 * (attempt + 1))
    return resp


def _transcript_from_recall_words(words: list) -> str:
    transcript_lines = []
    for segment in words:
        speaker = segment.get("speaker") or "Speaker"
        text = " ".join(w.get("text", "") for w in segment.get("words", []))
        if text.strip():
            transcript_lines.append(f"{speaker}: {text.strip()}")
    return "\n".join(transcript_lines)


async def _process_bot_transcript(bot_id: str):
    try:
        await asyncio.sleep(5)
        resp = await _fetch_transcript(bot_id)

        if resp is None or resp.status_code != 200:
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = "Failed to fetch transcript from Recall.ai"
            return

        raw = resp.json()
        print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:300]}")
        transcript = _transcript_from_recall_words(raw)
        if not transcript.strip():
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = f"No transcript content found (raw had {len(raw) if isinstance(raw, list) else type(raw).__name__} items)"
            return

        bot_store[bot_id]["transcript"] = transcript
        bot_store[bot_id]["result"] = await run_full_analysis(transcript)
        bot_store[bot_id]["status"] = "done"
    except Exception as exc:
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = str(exc)


@router.post("/join-meeting")
async def join_meeting(req: JoinMeetingRequest):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    if not req.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL cannot be empty")

    webhook_url = f"{WEBHOOK_BASE_URL}/recall-webhook"

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
                "transcription_options": {"provider": "meeting_captions"},
            },
            timeout=15,
        )

    if resp.status_code not in (200, 201):
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai error: {detail}")

    data = resp.json()
    bot_id = data["id"]
    bot_store[bot_id] = {"status": "joining", "result": None, "error": None}
    asyncio.create_task(_send_bot_intro(bot_id))
    return {"bot_id": bot_id, "status": "joining"}


@router.delete("/remove-bot/{bot_id}")
async def remove_bot(bot_id: str):
    """Stop and remove a Recall.ai bot."""
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    try:
        async with httpx.AsyncClient() as client:
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
            bot_store[bot_id] = {"status": "processing", "result": None, "error": None}
            asyncio.create_task(_process_bot_transcript(bot_id))
        elif bot_store[bot_id].get("status") not in ("processing", "done", "error"):
            # Webhook never fired — trigger processing via polling fallback
            bot_store[bot_id]["status"] = "processing"
            asyncio.create_task(_process_bot_transcript(bot_id))

    entry = bot_store.get(bot_id, {"status": our_status, "result": None, "error": None})
    # Don't let Recall's "done" override our internal "processing" — our analysis may still be running
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
        bot_store[bot_id] = {"status": "unknown", "result": None, "error": None}

    if event in ("bot.joining_call", "joining_call"):
        bot_store[bot_id]["status"] = "joining"
    elif event in ("bot.in_call_recording", "in_call_recording"):
        bot_store[bot_id]["status"] = "recording"
    elif event in ("bot.call_ended", "call_ended", "bot.done", "done"):
        if bot_store[bot_id].get("status") not in ("processing", "done"):
            bot_store[bot_id]["status"] = "processing"
            asyncio.create_task(_process_bot_transcript(bot_id))
    elif event in ("bot.fatal_error", "fatal_error"):
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = "Bot encountered a fatal error"

    return {"ok": True}

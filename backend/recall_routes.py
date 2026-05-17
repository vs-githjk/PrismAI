import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from analysis_service import build_analysis_transcript, run_full_analysis
from auth import supabase, require_user_id
from cross_meeting_service import looks_like_blocker, build_blocker_snippet


router = APIRouter(tags=["recall"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8001")
RECALL_WEBHOOK_SECRET = os.getenv("RECALL_WEBHOOK_SECRET", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

# In-memory cache (always used for fast access; synced to Supabase when available)
bot_store: dict = {}

# live_token → bot_id index for public live-share lookups
_live_token_index: dict = {}

# Tracks bots whose proactive checker has been re-spawned after a server restart,
# so repeated /bot-status polls don't keep creating new tasks.
_proactive_respawned: set[str] = set()


def _db_save(bot_id: str, fields: dict):
    """Persist bot state to Supabase (best-effort, non-blocking)."""
    if not supabase:
        return
    try:
        fields["bot_id"] = bot_id
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
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
            # Restore memory state into _bot_state so live-share and command processing
            # have the compressed summary after a server restart.
            if row.get("memory_summary") or row.get("live_state"):
                try:
                    from realtime_routes import _get_bot_state
                    import meeting_memory
                    rt_state = _get_bot_state(bot_id)
                    meeting_memory.restore_memory_state(row, rt_state)
                except Exception as mem_exc:
                    print(f"[recall] memory restore failed for {bot_id}: {mem_exc}")
            if row.get("status") in ("joining", "recording") and bot_id not in _proactive_respawned:
                _proactive_respawned.add(bot_id)
                try:
                    from realtime_routes import _run_proactive_checker
                    asyncio.create_task(_run_proactive_checker(bot_id))
                except Exception as exc:
                    print(f"[recall] failed to re-spawn proactive checker: {exc}")
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


def _db_save_memory(bot_id: str, memory_summary: str, live_state: dict):
    """Persist memory columns to bot_sessions after each successful compression cycle."""
    _db_save(bot_id, {"memory_summary": memory_summary, "live_state": live_state})


def _db_append_command(bot_id: str, command: dict):
    """Append a command log entry atomically using Postgres jsonb_insert."""
    if not supabase:
        return
    try:
        # Use rpc to atomically append — avoids read-modify-write race when two
        # commands arrive simultaneously for the same bot.
        supabase.rpc(
            "append_bot_command",
            {"p_bot_id": bot_id, "p_command": command},
        ).execute()
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
    owner_name: str | None = None


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


def _build_pre_meeting_brief(user_id: str | None) -> dict | None:
    """Return open action items, recent decisions, and blockers from the owner's meeting history.
    Pure Python — no LLM. Returns None when there is nothing noteworthy to surface."""
    if not supabase or not user_id:
        return None
    try:
        res = (
            supabase.table("meetings")
            .select("date,title,result")
            .eq("user_id", user_id)
            .order("id", desc=True)
            .limit(10)
            .execute()
        )
        meetings = [r for r in (res.data or []) if r.get("result")]
        if not meetings:
            return None

        open_items: list[dict] = []
        recent_decisions: list[dict] = []
        blockers: list[dict] = []

        for meeting in meetings[:5]:
            result = meeting.get("result") or {}
            date = meeting.get("date") or "recent meeting"
            title = meeting.get("title") or "Untitled"

            for item in (result.get("action_items") or []):
                if not item.get("completed") and item.get("task", "").strip():
                    open_items.append({
                        "task": item["task"].strip(),
                        "owner": (item.get("owner") or "").strip(),
                        "due": (item.get("due") or "").strip(),
                        "meeting_date": date,
                        "meeting_title": title,
                    })

            # Only pull decisions from the two most recent meetings
            if len(recent_decisions) < 4:
                for decision in (result.get("decisions") or [])[:3]:
                    if decision.get("decision", "").strip():
                        recent_decisions.append({
                            "decision": decision["decision"].strip(),
                            "owner": (decision.get("owner") or "").strip(),
                            "meeting_date": date,
                        })

            for item in (result.get("action_items") or []):
                if looks_like_blocker(item.get("task", "")) and item.get("task", "").strip():
                    blockers.append({
                        "snippet": build_blocker_snippet(item["task"]),
                        "meeting_date": date,
                    })
            summary = result.get("summary", "")
            if summary and looks_like_blocker(summary):
                blockers.append({
                    "snippet": build_blocker_snippet(summary),
                    "meeting_date": date,
                })

        try:
            refs = (
                supabase.table("action_refs")
                .select("action_item,tool,external_id,created_at")
                .eq("user_id", user_id)
                .eq("resolved", False)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            for ref in (refs.data or []):
                open_items.append({
                    "task": f"{ref['action_item']} [{ref['tool']}: {ref['external_id']}]",
                    "owner": "",
                    "due": "",
                    "meeting_date": (ref.get("created_at") or "")[:10],
                    "meeting_title": "",
                })
        except Exception:
            pass

        open_items = open_items[:5]
        recent_decisions = recent_decisions[:4]
        blockers = blockers[:3]

        if not open_items and not recent_decisions and not blockers:
            return None

        return {
            "open_items": open_items,
            "recent_decisions": recent_decisions,
            "blockers": blockers,
        }
    except Exception as exc:
        print(f"[recall] pre-meeting brief failed for user {user_id}: {exc}")
        return None


async def _send_bot_intro(bot_id: str):
    await asyncio.sleep(20)
    bot_state = bot_store.get(bot_id) or {}
    live_token = bot_state.get("live_token")
    owner_name = bot_state.get("owner_name") or "the meeting owner"
    frontend_url = os.getenv("FRONTEND_URL", "https://agentic-meeting-copilot.vercel.app")
    live_link = f"{frontend_url}/#live/{live_token}" if live_token else None
    message = "Hi, I'm PrismAI 👋 I'm here to observe and help you get the most out of this meeting. I'll send you a full analysis when we're done."
    if live_link:
        message += f"\n\nAnyone can follow along live: {live_link}"
    message += f"\n\n⚠️ If you don't consent to being recorded, please let {owner_name} know or leave the meeting."
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
    except Exception:
        pass


async def _fetch_transcript(bot_id: str):
    """Fetch transcript — tries media_shortcuts download URL first (async providers),
    then falls back to /bot/{id}/transcript/ (streaming providers like recallai_streaming)."""
    for attempt in range(12):
        print(f"[recall] fetch transcript attempt {attempt + 1}/12 for bot {bot_id}")
        async with httpx.AsyncClient() as client:
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
        for i, rec in enumerate(recordings):
            shortcuts = rec.get("media_shortcuts") or {}
            print(f"[recall] recording[{i}] media_shortcuts keys={list(shortcuts.keys())} status={rec.get('status')}")

        # Path 1: download URL in media_shortcuts (try multiple known key names)
        download_url = None
        for rec in recordings:
            shortcuts = rec.get("media_shortcuts") or {}
            transcript_shortcut = shortcuts.get("transcript") or shortcuts.get("transcript.data")
            if isinstance(transcript_shortcut, dict):
                download_url = transcript_shortcut.get("download_url") or transcript_shortcut.get("data", {}).get("download_url")
            elif isinstance(transcript_shortcut, str):
                download_url = transcript_shortcut
            if not download_url:
                download_url = shortcuts.get("transcript.data.download_url")
            if download_url:
                print(f"[recall] found transcript download URL")
                break

        if download_url:
            print(f"[recall] downloading transcript from {download_url[:80]}...")
            async with httpx.AsyncClient() as client:
                transcript_resp = await client.get(download_url, timeout=30)
            if transcript_resp.status_code == 200:
                return transcript_resp
            print(f"[recall] transcript download failed, status={transcript_resp.status_code}")
            await asyncio.sleep(3 * (attempt + 1))
            continue

        # Path 2: streaming providers (recallai_streaming, gladia_v2_streaming, etc.)
        # Transcript is stored directly on the bot via /bot/{id}/transcript/
        print(f"[recall] no download URL, trying /bot/{bot_id}/transcript/ (streaming provider)")
        async with httpx.AsyncClient() as client:
            t_resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/transcript/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if t_resp.status_code == 200:
            data = t_resp.json()
            # Endpoint returns list of segments or empty list
            if data:
                print(f"[recall] got transcript from /transcript/ endpoint, {len(data)} segments")
                return t_resp
            print(f"[recall] /transcript/ endpoint returned empty list")
        else:
            print(f"[recall] /transcript/ endpoint returned {t_resp.status_code}")

        wait = min(10 * (attempt + 1), 60)
        print(f"[recall] no transcript yet, waiting {wait}s...")
        await asyncio.sleep(wait)

    return None


def _transcript_from_recall_data(raw) -> str:
    """Parse transcript from Recall's transcript data format."""
    # Handle list of segments with words (legacy + new format)
    if isinstance(raw, list):
        transcript_lines = []
        for segment in raw:
            speaker = segment.get("speaker") or segment.get("participant", {}).get("name") or "Speaker"
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
    # Guarantee bot_store[bot_id] exists for the full duration of processing.
    # remove_bot() can pop the entry at any time; setdefault re-establishes it so
    # the status writes below never raise KeyError inside the except block.
    bot_store.setdefault(bot_id, {"status": "processing", "result": None, "error": None, "commands": []})
    try:
        print(f"[recall] starting transcript processing for bot {bot_id}")
        resp = await _fetch_transcript(bot_id)

        transcript = ""
        if resp is not None:
            raw = resp.json()
            print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:500]}")
            transcript = _transcript_from_recall_data(raw)

        # Fallback: use realtime-streamed transcript lines accumulated during the meeting
        if not transcript.strip():
            rt_lines = bot_store.get(bot_id, {}).get("realtime_transcript_lines") or []
            if rt_lines:
                transcript = "\n".join(rt_lines)
                print(f"[recall] using realtime transcript buffer: {len(rt_lines)} lines, {len(transcript)} chars")

        if not transcript.strip():
            error_msg = "No transcript content found — the meeting may have been too short or had no speech"
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = error_msg
            _db_save(bot_id, {"status": "error", "error": error_msg})
            print(f"[recall] ERROR: empty transcript")
            return

        print(f"[recall] transcript OK, {len(transcript)} chars. Running analysis...")
        owner_name = (bot_store.get(bot_id) or {}).get("owner_name")
        analysis_transcript = build_analysis_transcript(transcript, owner_name=owner_name)
        result = await run_full_analysis(analysis_transcript)
        bot_store[bot_id]["transcript"] = transcript
        bot_store[bot_id]["result"] = result
        bot_store[bot_id]["status"] = "done"
        _db_save(bot_id, {"status": "done", "transcript": transcript, "result": result})
        print(f"[recall] analysis complete for bot {bot_id}")
        from realtime_routes import cleanup_bot_state
        cleanup_bot_state(bot_id)
    except Exception as exc:
        # re-establish entry in case remove_bot() popped it during an await
        bot_store.setdefault(bot_id, {"status": "error", "result": None, "error": None, "commands": []})
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = str(exc)
        _db_save(bot_id, {"status": "error", "error": str(exc)})
        print(f"[recall] ERROR processing bot {bot_id}: {exc}")
        from realtime_routes import cleanup_bot_state
        cleanup_bot_state(bot_id)


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

    # Generate a one-time webhook auth token for the realtime stream.
    # 32 URL-safe bytes = 256 bits of entropy — unguessable. The token
    # binds this specific bot's events to a verified URL path; without it,
    # an attacker who knows or guesses the bot_id can POST forged events
    # to the public webhook endpoint.
    realtime_token = secrets.token_urlsafe(32)
    realtime_url = f"{WEBHOOK_BASE_URL}/realtime-events/{realtime_token}"

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
                            # endpointing=500 → wait 500ms of silence before finalizing
                            #   (default 10ms makes Deepgram emit one "final" per word).
                            # utterance_end_ms=1000 → bounded fallback in case endpointing under-fires.
                            # smart_format + punctuate + diarize → better readability, fewer mishears,
                            #   and Recall already attaches speaker labels separately.
                            # Note: Recall.ai validates Deepgram params as URL-style strings
                            # (booleans must be "true"/"false", not JSON true/false). Numeric
                            # params can stay as integers.
                            # endpointing=300: 30x longer than the 10ms default (which
                            #   was causing one-word "finals"), but lower than 500 to
                            #   reduce TTFB. The same-fragment-completion heuristic +
                            #   accumulator in realtime_routes handles the rare split case.
                            "deepgram_streaming": {
                                "model": "nova-3",
                                "language": "en",
                                "smart_format": "true",
                                "punctuate": "true",
                                "diarize": "true",
                                "endpointing": 300,
                                "utterance_end_ms": 1000,
                                "interim_results": "true",
                            }
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
    live_token = secrets.token_hex(16)
    bot_store[bot_id] = {
        "status": "joining",
        "result": None,
        "error": None,
        "commands": [],
        "user_id": user_id,
        "live_token": live_token,
        "owner_name": req.owner_name,
        "realtime_token": realtime_token,
    }
    _live_token_index[live_token] = bot_id
    _db_save(bot_id, {"status": "joining", "user_id": user_id, "live_token": live_token})

    from realtime_routes import init_bot_realtime, _run_proactive_checker, register_realtime_token
    # Bind the webhook token AFTER Recall confirmed the bot id. The mapping
    # in realtime_routes lets the tokenized webhook handler resolve token →
    # bot_id and reject any forged or stale tokens.
    register_realtime_token(realtime_token, bot_id)
    init_bot_realtime(bot_id)

    asyncio.create_task(_send_bot_intro(bot_id))
    asyncio.create_task(_run_proactive_checker(bot_id))
    return {"bot_id": bot_id, "status": "joining", "live_token": live_token}


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
    from realtime_routes import cleanup_bot_state
    cleanup_bot_state(bot_id)
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
        elif bot_store[bot_id].get("status") == "processing" and not bot_store[bot_id].get("result"):
            # Zombie state: server restarted mid-processing — task died but DB still says "processing".
            # Re-trigger so the transcript gets fetched and saved.
            asyncio.create_task(_process_bot_transcript(bot_id))
        elif bot_store[bot_id].get("status") not in ("processing", "done", "error"):
            bot_store[bot_id]["status"] = "processing"
            _db_save(bot_id, {"status": "processing"})
            asyncio.create_task(_process_bot_transcript(bot_id))

    entry = bot_store.get(bot_id, {"status": our_status, "result": None, "error": None, "commands": []})
    # Don't let Recall's "done" override our internal "processing"
    entry["status"] = our_status if entry.get("status") not in ("done", "error", "processing") else entry["status"]
    return entry


@router.get("/live/{live_token}")
async def live_meeting(live_token: str):
    """Public endpoint for live-share viewers. Returns safe bot state by live_token."""
    bot_id = _live_token_index.get(live_token)

    # Fall back to DB if server restarted and index was lost
    if not bot_id and supabase:
        try:
            res = supabase.table("bot_sessions").select("bot_id").eq("live_token", live_token).maybe_single().execute()
            if res.data:
                bot_id = res.data["bot_id"]
                _live_token_index[live_token] = bot_id
        except Exception:
            pass

    if not bot_id:
        raise HTTPException(status_code=404, detail="Live session not found")

    # Load from DB into memory if needed
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    entry = bot_store.get(bot_id, {})
    from realtime_routes import _bot_state
    rt = _bot_state.get(bot_id, {})

    # Build pre-meeting brief lazily — compute once, cache in bot_store
    status = entry.get("status", "joining")
    if bot_id in bot_store and "brief" not in bot_store[bot_id] and status not in ("done", "error"):
        bot_store[bot_id]["brief"] = await asyncio.to_thread(
            _build_pre_meeting_brief, entry.get("user_id")
        )

    import meeting_memory as _mm
    memory_snapshot = _mm.get_memory_snapshot(rt) if rt else {}

    # Operational counters (Phase A pre-perception observability). Safe to
    # expose on this possession-based endpoint: dedup_hits / partial_drops /
    # cancel_count / replace_depth_hits / cousin_hit_no_match are operational
    # signal, not security signal. Security counters live on a separate
    # require_user_id-gated endpoint below.
    import perception_state as _pp
    op_counters = _pp.operational_counters(rt) if rt else {}

    return {
        "status": status,
        "commands": entry.get("commands", []),
        "transcript_lines": rt.get("transcript_buffer", [])[-100:],
        "result": entry.get("result"),
        "error": entry.get("error"),
        "brief": entry.get("brief"),
        # Memory and idea engine fields — consumed by the live-share frontend panel
        "memory_summary": memory_snapshot.get("memory_summary", ""),
        "live_decisions": memory_snapshot.get("live_decisions", []),
        "live_action_items": memory_snapshot.get("live_action_items", []),
        "top_entities": memory_snapshot.get("top_entities", []),
        "idea_history": memory_snapshot.get("idea_history", []),
        # Include transcript when done so signed-in viewers can save a copy
        "transcript": entry.get("transcript") if status == "done" else None,
        "counters": op_counters,
    }


@router.get("/bot-counters/{bot_id}")
async def bot_counters(bot_id: str, user_id: str = Depends(require_user_id)):
    """Owner-only counters for a bot. Returns 404 on ownership mismatch so we
    don't confirm bot existence to a non-owner.

    Operational counters live on /live/{token}. This endpoint exposes the
    security-signal counters (injection_redactions, owner_gate_blocks) that
    would leak attack-attempt feedback to non-owners.
    """
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry
    rec = bot_store.get(bot_id)
    if not rec or rec.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Bot not found")
    from realtime_routes import _bot_state
    import perception_state as _pp
    rt = _bot_state.get(bot_id, {})
    return {
        "bot_id": bot_id,
        "counters": _pp.security_counters(rt),
        "recent_drops": _pp.get_drops(bot_id),
        # Latency timeline for the most recent cancellation. Three monotonic
        # timestamps + a reason. Diff (last_upload_aborted_mono - detected_mono)
        # is the "interrupt-utterance-detected → last-audio-uploaded" number
        # that's the whole point of Phase B.
        "last_cancel_timeline": rt.get("last_cancel_timeline"),
    }


@router.post("/recall-webhook")
async def recall_webhook(request: Request):
    body = await request.body()
    if RECALL_WEBHOOK_SECRET:
        sig = request.headers.get("x-recall-signature", "")
        expected = hmac.new(RECALL_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {"ok": True}

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

import asyncio
import hashlib
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from urllib.parse import urlparse, parse_qs

from auth import require_user_id, supabase
from caches import is_workspace_member
from cross_meeting_service import derive_cross_meeting_insights, has_meaningful_result
from calendar_routes import get_valid_token
from knowledge_transcript import index_meeting_transcript
from tools.gmail import gmail_send


def parse_expires_hint(url: str | None) -> int | None:
    """Extract the X-Amz-Expires hint from an S3 presigned URL.

    Returns None when the param is missing, non-integer, or input is empty.
    The hint is approximate — clients should treat it as a cache TTL guide,
    not a precise countdown.
    """
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
        value = qs.get("X-Amz-Expires", [None])[0]
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")

router = APIRouter(tags=["storage"])


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


class UserToolSettings(BaseModel):
    linear_api_key: str | None = None
    slack_bot_token: str | None = None
    persona_preset: str | None = None
    persona_custom_prompt: str | None = None


class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int | None = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""
    workspace_id: str | None = None
    recorded_by_user_id: str | None = None
    persona_used: str | None = None
    recall_bot_id: str | None = None


class MeetingPatch(BaseModel):
    result: dict | None = None
    share_token: str | None = None
    title: str | None = None
    workspace_id: str | None = None


class ChatEntry(BaseModel):
    messages: list


@router.get("/user-settings")
async def get_user_settings(user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = client.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
    row = (res.data if res is not None else None) or {}
    # Only return non-sensitive fields relevant to the frontend
    return {
        "linear_api_key": row.get("linear_api_key") or "",
        "slack_bot_token": row.get("slack_bot_token") or "",
        "calendar_connected": row.get("calendar_connected", False),
        "persona_preset": row.get("persona_preset") or "default",
        "persona_custom_prompt": row.get("persona_custom_prompt") or "",
    }


@router.post("/user-settings")
async def save_user_settings(settings: UserToolSettings, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    upsert_data: dict = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    if settings.linear_api_key is not None:
        upsert_data["linear_api_key"] = settings.linear_api_key or None
    if settings.slack_bot_token is not None:
        upsert_data["slack_bot_token"] = settings.slack_bot_token or None
    persona_touched = False
    if settings.persona_preset is not None:
        upsert_data["persona_preset"] = settings.persona_preset
        persona_touched = True
        # D3: if the user picked anything other than 'custom', drop any stale
        # custom prompt so it can't silently re-activate when they switch back.
        if settings.persona_preset != "custom":
            upsert_data["persona_custom_prompt"] = None
        elif settings.persona_custom_prompt is not None:
            upsert_data["persona_custom_prompt"] = settings.persona_custom_prompt or None
    elif settings.persona_custom_prompt is not None:
        # Custom prompt update without preset change — only honored when the
        # existing preset is already 'custom' (the DB row is the source of
        # truth for that; we just write the value and let the user discover
        # the mismatch when they next look).
        upsert_data["persona_custom_prompt"] = settings.persona_custom_prompt or None
        persona_touched = True
    client.table("user_settings").upsert(upsert_data, on_conflict="user_id").execute()
    if persona_touched:
        from personas import invalidate_persona
        invalidate_persona(user_id=user_id)
    return {"ok": True}


@router.get("/meetings")
async def get_meetings(
    q: str = Query(default=""),
    workspace_id: str = Query(default=""),
    user_id: str = Depends(require_user_id),
):
    client = _require_storage()

    if workspace_id.strip():
        # Workspace mode: return all meetings in this workspace across all members
        # Verify the requester is a member first
        if not is_workspace_member(client, user_id, workspace_id):
            raise HTTPException(status_code=403, detail="Not a member of this workspace")

        query = (
            client.table("meetings")
            .select("id,date,title,score,transcript,result,share_token,workspace_id,recorded_by_user_id,user_id,recall_bot_id,recording_provider")
            .eq("workspace_id", workspace_id)
            .order("id", desc=True)
            .limit(400)
        )
    else:
        # Personal mode: only the user's own meetings with no workspace
        query = (
            client.table("meetings")
            .select("id,date,title,score,transcript,result,share_token,workspace_id,recorded_by_user_id,recall_bot_id,recording_provider")
            .eq("user_id", user_id)
            .is_("workspace_id", None)
            .order("id", desc=True)
            .limit(200)
        )

    if q.strip():
        query = query.ilike("title", f"%{q}%")
    res = query.execute()

    if workspace_id.strip():
        # Within a single workspace, two rows at the same minute are the same logical meeting —
        # collapse them and prefer the current user's own copy. This handles both fan-out
        # duplicates and the bot-dedup case where two users independently POST the same meeting.
        dedup_map: dict = {}
        for row in res.data:
            key = row.get("date", "")[:16]
            if key not in dedup_map or row.get("user_id") == user_id:
                dedup_map[key] = row
        rows = sorted(dedup_map.values(), key=lambda r: r.get("id", 0), reverse=True)
        for row in rows:
            row.pop("user_id", None)
    else:
        rows = res.data

    meaningful = [entry for entry in rows if has_meaningful_result(entry.get("result"))]
    return meaningful[:50]


@router.get("/insights")
async def get_cross_meeting_insights(
    workspace_id: str = Query(default=""),
    user_id: str = Depends(require_user_id),
):
    client = _require_storage()

    if workspace_id.strip():
        if not is_workspace_member(client, user_id, workspace_id):
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
        all_res = (
            client.table("meetings")
            .select("id,date,title,score,result,recorded_by_user_id,user_id")
            .eq("workspace_id", workspace_id)
            .order("id", desc=True)
            .limit(200)
            .execute()
        )
        # Deduplicate fan-out copies same as the meetings endpoint — collapse by date[:16]
        # within the workspace so insights aren't double-counted across fan-out duplicates.
        dedup_map: dict = {}
        for row in (all_res.data or []):
            key = row.get("date", "")[:16]
            if key not in dedup_map or row.get("user_id") == user_id:
                dedup_map[key] = row
        deduped = sorted(dedup_map.values(), key=lambda r: r.get("id", 0), reverse=True)
        for row in deduped:
            row.pop("user_id", None)
            row.pop("recorded_by_user_id", None)
        res_data = deduped[:50]
    else:
        res = (
            client.table("meetings")
            .select("id,date,title,score,result")
            .eq("user_id", user_id)
            .is_("workspace_id", None)
            .order("id", desc=True)
            .limit(50)
            .execute()
        )
        res_data = res.data

    return derive_cross_meeting_insights(res_data, user_id=user_id)


def _fan_out_id(original_id: int, member_user_id: str) -> int:
    """Deterministic meeting ID for a fan-out copy — avoids collisions and is idempotent."""
    return int(hashlib.md5(f"{original_id}-{member_user_id}".encode()).hexdigest()[:12], 16)


async def _fan_out_to_workspace(client, entry: "MeetingEntry", recorder_user_id: str, workspace_id: str):
    """Write a copy of this meeting to every other workspace member's history."""
    try:
        members = (
            client.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", workspace_id)
            .neq("user_id", recorder_user_id)
            .execute()
        )
        for member in (members.data or []):
            member_id = member["user_id"]
            fan_id = _fan_out_id(entry.id, member_id)
            client.table("meetings").upsert({
                "id": fan_id,
                "user_id": member_id,
                "date": entry.date,
                "title": entry.title,
                "score": entry.score,
                "transcript": entry.transcript,
                "result": entry.result,
                "share_token": None,
                "workspace_id": workspace_id,
                "recorded_by_user_id": recorder_user_id,
                "persona_used": entry.persona_used or None,
                # Recording fields propagate so every teammate sees the same player.
                # The owner-only segments are safe to fan out: workspace_members are
                # the access boundary, and the player auth already gates by membership.
                # _resolved_segments / _resolved_provider are set by save_meeting in Task 5.
                # When the test calls _fan_out_to_workspace directly (no save_meeting
                # pre-call), these fall back to entry.recall_bot_id / "recall" — same
                # final shape, no behaviour change.
                "recall_bot_id": entry.recall_bot_id,
                "recording_provider": entry.__dict__.get("_resolved_provider")
                                       or ("recall" if entry.recall_bot_id else None),
                "transcript_segments": entry.__dict__.get("_resolved_segments"),
            }).execute()
            print(f"[fanout] wrote meeting {fan_id} to member {member_id} in workspace {workspace_id}")
    except Exception as exc:
        print(f"[fanout] failed for meeting {entry.id}: {exc}")


@router.post("/meetings")
async def save_meeting(entry: MeetingEntry, user_id: str = Depends(require_user_id)):
    client = _require_storage()

    # Server-side enrichment from bot_sessions — the trust boundary.
    # The frontend sends recall_bot_id as a reference; we look up the structured
    # transcript segments server-side and only attach them if the caller owns the
    # bot. If they don't own it (stale local state, bad client), the save still
    # succeeds with nulls instead of 403 — silent degradation preserves UX.
    recall_bot_id = entry.recall_bot_id or None
    recording_provider: str | None = None
    transcript_segments = None
    if recall_bot_id:
        try:
            bs = (
                client.table("bot_sessions")
                .select("user_id, transcript_segments")
                .eq("bot_id", recall_bot_id)
                .maybe_single()
                .execute()
            )
            row = bs.data if bs else None
            if row and row.get("user_id") == user_id:
                recording_provider = "recall"
                transcript_segments = row.get("transcript_segments")
            else:
                # Caller doesn't own this bot — drop the reference rather than 403
                recall_bot_id = None
        except Exception as exc:
            print(f"[storage] bot_sessions lookup failed for {recall_bot_id}: {exc}")
            recall_bot_id = None

    # Mutate the entry so _fan_out_to_workspace (called below) sees the same
    # resolved values — it uses these to populate teammate rows in Task 6.
    entry.recall_bot_id = recall_bot_id
    entry.__dict__["_resolved_segments"] = transcript_segments
    entry.__dict__["_resolved_provider"] = recording_provider

    client.table("meetings").upsert({
        "id": entry.id,
        "user_id": user_id,
        "date": entry.date,
        "title": entry.title,
        "score": entry.score,
        "transcript": entry.transcript,
        "result": entry.result,
        "share_token": entry.share_token or None,
        "workspace_id": entry.workspace_id or None,
        "recorded_by_user_id": entry.recorded_by_user_id or None,
        "persona_used": entry.persona_used or None,
        "recall_bot_id": recall_bot_id,
        "recording_provider": recording_provider,
        "transcript_segments": transcript_segments,
    }).execute()

    # Fan out to all other workspace members when a workspace is set.
    # actual_recorder is the bot owner (if the saver's bot was dedup'd) or the saver themselves —
    # this keeps all four rows for one shared meeting under the same dedup key.
    if entry.workspace_id:
        actual_recorder = entry.recorded_by_user_id or user_id
        asyncio.create_task(_fan_out_to_workspace(client, entry, actual_recorder, entry.workspace_id))

    # Index the transcript for cross-source RAG. Fire-and-forget — failures are
    # logged in index_meeting_transcript itself and must not block the save.
    #
    # Only the primary recorder's POST triggers indexing. When the caller is a
    # workspace-dedup'd teammate (their `recorded_by_user_id` points elsewhere),
    # the recorder's POST already created — or will create — the doc. Skipping
    # here prevents N duplicate knowledge_docs rows per shared meeting.
    if entry.recorded_by_user_id in (None, "", user_id):
        indexer_user = entry.recorded_by_user_id or user_id
        asyncio.create_task(index_meeting_transcript(
            meeting_id=entry.id,
            user_id=indexer_user,
            workspace_id=entry.workspace_id or None,
            date=entry.date,
            title=entry.title,
            transcript=entry.transcript,
        ))

    return {"ok": True}


@router.get("/share/{token}")
async def get_shared_meeting(token: str):
    client = _require_storage()
    res = client.table("meetings").select("title,date,result,score,transcript").eq("share_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Share link not found")
    return res.data[0]


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: int, user_id: str = Depends(require_user_id)):
    """Fetch a single meeting by id. The caller must either own the meeting or be a member
    of its workspace. Used by the workspace brief so clicking an open item opens its source
    meeting without having to be in the workspace's history view first."""
    client = _require_storage()
    res = (
        client.table("meetings")
        .select("id,date,title,score,transcript,result,share_token,workspace_id,user_id,recorded_by_user_id,recall_bot_id,recording_provider,transcript_segments")
        .eq("id", meeting_id)
        .maybe_single()
        .execute()
    )
    meeting = res.data if res else None
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Authorize: owner of the row, or member of its workspace
    if meeting.get("user_id") != user_id:
        ws_id = meeting.get("workspace_id")
        if not ws_id or not is_workspace_member(client, user_id, ws_id):
            raise HTTPException(status_code=403, detail="Not authorized for this meeting")

    meeting.pop("user_id", None)
    return meeting


@router.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("meetings").delete().eq("id", meeting_id).eq("user_id", user_id).execute()
    return {"ok": True}


@router.patch("/meetings/{meeting_id}")
async def patch_meeting(meeting_id: int, patch: MeetingPatch, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    update = {}
    if patch.result is not None:
        update["result"] = patch.result
    if patch.share_token is not None:
        update["share_token"] = patch.share_token
    if patch.title is not None:
        update["title"] = patch.title
    if update:
        client.table("meetings").update(update).eq("id", meeting_id).eq("user_id", user_id).execute()
    return {"ok": True}


@router.post("/meetings/{meeting_id}/claim-email")
async def claim_email(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = (
        client.table("meetings")
        .select("workspace_id, date, email_claimed_by")
        .eq("id", meeting_id)
        .maybe_single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting = res.data
    current_claimer = meeting.get("email_claimed_by")

    if current_claimer and current_claimer != user_id:
        return {"claimed": False, "claimed_by": current_claimer}

    # Claim on all workspace copies sharing same workspace + date
    if meeting.get("workspace_id") and meeting.get("date"):
        client.table("meetings").update({"email_claimed_by": user_id}) \
            .eq("workspace_id", meeting["workspace_id"]) \
            .eq("date", meeting["date"]) \
            .is_("email_claimed_by", None) \
            .execute()
    else:
        client.table("meetings").update({"email_claimed_by": user_id}) \
            .eq("id", meeting_id) \
            .execute()

    return {"claimed": True, "claimed_by": user_id}


@router.get("/chats")
async def get_all_chats(user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = client.table("chats").select("meeting_id,messages").eq("user_id", user_id).execute()
    return {str(row["meeting_id"]): row["messages"] for row in res.data}


@router.get("/chats/{meeting_id}")
async def get_chat(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = client.table("chats").select("messages").eq("meeting_id", meeting_id).eq("user_id", user_id).limit(1).execute()
    if res.data:
        return {"messages": res.data[0]["messages"]}
    return {"messages": []}


@router.post("/chats/{meeting_id}")
async def save_chat(meeting_id: int, entry: ChatEntry, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("chats").upsert(
        {"meeting_id": meeting_id, "user_id": user_id, "messages": entry.messages},
        on_conflict="meeting_id,user_id",
    ).execute()
    return {"ok": True}


@router.delete("/chats/{meeting_id}")
async def delete_chat(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("chats").delete().eq("meeting_id", meeting_id).eq("user_id", user_id).execute()
    return {"ok": True}


# --- Per-meeting ephemeral chat sessions (max 3 saved per meeting) ---

CHAT_SESSIONS_CAP = 3


@router.get("/chat-sessions/{meeting_id}")
async def list_chat_sessions(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = (
        client.table("chat_sessions")
        .select("id,messages,created_at")
        .eq("meeting_id", meeting_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(CHAT_SESSIONS_CAP)
        .execute()
    )
    return {"sessions": res.data or []}


@router.post("/chat-sessions/{meeting_id}")
async def save_chat_session(meeting_id: int, entry: ChatEntry, user_id: str = Depends(require_user_id)):
    if not entry.messages or not any(
        isinstance(m, dict) and m.get("role") == "user" for m in entry.messages
    ):
        raise HTTPException(status_code=400, detail="Chat must contain at least one user message")
    client = _require_storage()
    insert_res = (
        client.table("chat_sessions")
        .insert({"meeting_id": meeting_id, "user_id": user_id, "messages": entry.messages})
        .execute()
    )
    inserted = (insert_res.data or [None])[0]

    # Prune to the CHAT_SESSIONS_CAP most recent for this (meeting, user)
    existing = (
        client.table("chat_sessions")
        .select("id,created_at")
        .eq("meeting_id", meeting_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = existing.data or []
    if len(rows) > CHAT_SESSIONS_CAP:
        stale_ids = [r["id"] for r in rows[CHAT_SESSIONS_CAP:]]
        client.table("chat_sessions").delete().in_("id", stale_ids).eq("user_id", user_id).execute()
    return {"session": inserted}


@router.delete("/chat-sessions/{session_id}")
async def delete_chat_session(session_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("chat_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
    return {"ok": True}


class SendFollowupRequest(BaseModel):
    to: list[str]
    subject: str
    body: str


@router.post("/send-followup-email")
async def send_followup_email(req: SendFollowupRequest, user_id: str = Depends(require_user_id)):
    if not req.to:
        raise HTTPException(status_code=400, detail="At least one recipient is required")
    token = await get_valid_token(user_id)
    result = await gmail_send(
        {"to": req.to, "subject": req.subject, "body": req.body},
        {"google_access_token": token},
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"ok": True}


def _caller_can_access_meeting(client, meeting_row: dict, user_id: str) -> bool:
    """Same auth model as GET /meetings/{id}: owner OR workspace member."""
    if meeting_row.get("user_id") == user_id:
        return True
    workspace_id = meeting_row.get("workspace_id")
    if not workspace_id:
        return False
    try:
        res = (
            client.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return bool(res and res.data)
    except Exception:
        return False


@router.get("/meetings/{meeting_id}/recording")
async def get_meeting_recording(meeting_id: int, user_id: str = Depends(require_user_id)):
    """Return a fresh signed download URL for the meeting's Recall.ai recording.

    Auth: caller must own the meeting OR be a member of its workspace. Non-members
    get a 404 (we never confirm existence to non-members).

    Response shapes (see spec for full contract):
      { "url": "...", "expires_hint_seconds": N, "kind": "video" | "audio" }
      { "url": None, "reason": "not_ready" | "no_recording" | "expired" |
                               "not_found" | "not_a_bot_meeting" }
    """
    client = _require_storage()

    # Load meeting row
    try:
        res = (
            client.table("meetings")
            .select("id, user_id, workspace_id, recall_bot_id, recording_provider")
            .eq("id", meeting_id)
            .maybe_single()
            .execute()
        )
        meeting = res.data if res else None
    except Exception:
        meeting = None

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not _caller_can_access_meeting(client, meeting, user_id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    bot_id = meeting.get("recall_bot_id")
    if not bot_id:
        return {"url": None, "reason": "not_a_bot_meeting"}

    if not RECALL_API_KEY:
        raise HTTPException(status_code=503, detail="Recall.ai not configured")

    # Fetch fresh signed URL from Recall (URLs expire ~24h, can't cache)
    try:
        async with httpx.AsyncClient() as recall:
            resp = await recall.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Recall.ai unreachable: {exc}")

    if resp.status_code == 404:
        return {"url": None, "reason": "expired"}
    if resp.status_code == 403:
        return {"url": None, "reason": "not_found"}
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Recall.ai error: {resp.status_code}")

    data = resp.json()
    recordings = data.get("recordings") or []
    if not recordings:
        return {"url": None, "reason": "no_recording"}

    shortcuts = (recordings[0] or {}).get("media_shortcuts") or {}
    video_url = (
        ((shortcuts.get("video_mixed") or {}).get("data") or {}).get("download_url")
    )
    audio_url = (
        ((shortcuts.get("audio_mixed") or {}).get("data") or {}).get("download_url")
    )

    if video_url:
        payload = {"url": video_url, "kind": "video"}
        hint = parse_expires_hint(video_url)
        if hint is not None:
            payload["expires_hint_seconds"] = hint
        return payload
    if audio_url:
        payload = {"url": audio_url, "kind": "audio"}
        hint = parse_expires_hint(audio_url)
        if hint is not None:
            payload["expires_hint_seconds"] = hint
        return payload

    return {"url": None, "reason": "not_ready"}

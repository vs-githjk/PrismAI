import asyncio
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import require_user_id, supabase
from cross_meeting_service import derive_cross_meeting_insights, has_meaningful_result
from calendar_routes import get_valid_token
from tools.gmail import gmail_send


router = APIRouter(tags=["storage"])


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


class UserToolSettings(BaseModel):
    linear_api_key: str | None = None
    slack_bot_token: str | None = None


class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int | None = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""
    workspace_id: str | None = None


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
    }


@router.post("/user-settings")
async def save_user_settings(settings: UserToolSettings, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    upsert_data: dict = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    if settings.linear_api_key is not None:
        upsert_data["linear_api_key"] = settings.linear_api_key or None
    if settings.slack_bot_token is not None:
        upsert_data["slack_bot_token"] = settings.slack_bot_token or None
    client.table("user_settings").upsert(upsert_data, on_conflict="user_id").execute()
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
        membership = (
            client.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not membership.data:
            raise HTTPException(status_code=403, detail="Not a member of this workspace")

        query = (
            client.table("meetings")
            .select("id,date,title,score,transcript,result,share_token,workspace_id,recorded_by_user_id,user_id")
            .eq("workspace_id", workspace_id)
            .order("id", desc=True)
            .limit(400)
        )
    else:
        # Personal mode: only the user's own meetings with no workspace
        query = (
            client.table("meetings")
            .select("id,date,title,score,transcript,result,share_token,workspace_id,recorded_by_user_id")
            .eq("user_id", user_id)
            .is_("workspace_id", None)
            .order("id", desc=True)
            .limit(200)
        )

    if q.strip():
        query = query.ilike("title", f"%{q}%")
    res = query.execute()

    if workspace_id.strip():
        # Deduplicate: fan-out creates copies for each member (same date+recorder, different user_id).
        # Keep one per logical meeting, preferring the current user's own copy.
        dedup_map: dict = {}
        for row in res.data:
            recorder = row.get("recorded_by_user_id") or row.get("user_id", "")
            key = (row.get("date", "")[:16], recorder)
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
        membership = (
            client.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not membership.data:
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
        all_res = (
            client.table("meetings")
            .select("id,date,title,score,result,recorded_by_user_id,user_id")
            .eq("workspace_id", workspace_id)
            .order("id", desc=True)
            .limit(200)
            .execute()
        )
        # Deduplicate fan-out copies same as the meetings endpoint
        dedup_map: dict = {}
        for row in (all_res.data or []):
            recorder = row.get("recorded_by_user_id") or row.get("user_id", "")
            key = (row.get("date", "")[:16], recorder)
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
            }).execute()
            print(f"[fanout] wrote meeting {fan_id} to member {member_id} in workspace {workspace_id}")
    except Exception as exc:
        print(f"[fanout] failed for meeting {entry.id}: {exc}")


@router.post("/meetings")
async def save_meeting(entry: MeetingEntry, user_id: str = Depends(require_user_id)):
    client = _require_storage()
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
    }).execute()

    # Fan out to all other workspace members when a workspace is set
    if entry.workspace_id:
        asyncio.create_task(_fan_out_to_workspace(client, entry, user_id, entry.workspace_id))

    return {"ok": True}


@router.get("/share/{token}")
async def get_shared_meeting(token: str):
    client = _require_storage()
    res = client.table("meetings").select("title,date,result,score,transcript").eq("share_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Share link not found")
    return res.data[0]


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

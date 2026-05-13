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


class MeetingPatch(BaseModel):
    result: dict | None = None
    share_token: str | None = None
    title: str | None = None


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
async def get_meetings(q: str = Query(default=""), user_id: str = Depends(require_user_id)):
    client = _require_storage()
    # Fetch more rows than the target cap (50) so the Python meaningfulness filter
    # doesn't silently drop real meetings when a few recent saves are partial.
    query = (
        client.table("meetings")
        .select("id,date,title,score,transcript,result,share_token")
        .eq("user_id", user_id)
        .order("id", desc=True)
        .limit(200)
    )
    if q.strip():
        query = query.ilike("title", f"%{q}%")
    res = query.execute()
    meaningful = [entry for entry in res.data if has_meaningful_result(entry.get("result"))]
    return meaningful[:50]


@router.get("/insights")
async def get_cross_meeting_insights(user_id: str = Depends(require_user_id)):
    client = _require_storage()
    res = (
        client.table("meetings")
        .select("id,date,title,score,result")
        .eq("user_id", user_id)
        .order("id", desc=True)
        .limit(50)
        .execute()
    )
    return derive_cross_meeting_insights(res.data, user_id=user_id)


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
    }).execute()
    return {"ok": True}


@router.get("/share/{token}")
async def get_shared_meeting(token: str):
    client = _require_storage()
    res = client.table("meetings").select("title,date,result,score").eq("share_token", token).limit(1).execute()
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

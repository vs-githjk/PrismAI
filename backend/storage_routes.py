from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import require_user_id, supabase
from cross_meeting_service import derive_cross_meeting_insights, has_meaningful_result


router = APIRouter(tags=["storage"])


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int | None = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""


class MeetingPatch(BaseModel):
    result: dict


class ChatEntry(BaseModel):
    messages: list


@router.get("/meetings")
async def get_meetings(q: str = Query(default=""), user_id: str = Depends(require_user_id)):
    client = _require_storage()
    query = (
        client.table("meetings")
        .select("id,date,title,score,transcript,result,share_token")
        .eq("user_id", user_id)
        .order("id", desc=True)
        .limit(50)
    )
    if q.strip():
        query = query.ilike("title", f"%{q}%")
    res = query.execute()
    return [entry for entry in res.data if has_meaningful_result(entry.get("result"))]


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
    return derive_cross_meeting_insights(res.data)


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
    client.table("meetings").update({"result": patch.result}).eq("id", meeting_id).eq("user_id", user_id).execute()
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
    existing = client.table("chats").select("id").eq("meeting_id", meeting_id).eq("user_id", user_id).limit(1).execute()
    if existing.data:
        client.table("chats").update({"messages": entry.messages}).eq("meeting_id", meeting_id).eq("user_id", user_id).execute()
    else:
        client.table("chats").insert({"meeting_id": meeting_id, "user_id": user_id, "messages": entry.messages}).execute()
    return {"ok": True}


@router.delete("/chats/{meeting_id}")
async def delete_chat(meeting_id: int, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("chats").delete().eq("meeting_id", meeting_id).eq("user_id", user_id).execute()
    return {"ok": True}

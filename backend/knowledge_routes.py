"""Knowledge Base REST API."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import require_user_id, supabase as auth_supabase
from caches import get_user_workspace_ids
from knowledge_service import (
    ingest_doc,
    soft_delete_doc,
    search_knowledge,
    _execute,
    DocNotFound,
    DeletePermissionDenied,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_EXT = {"pdf", "docx", "txt", "md"}


def _supabase():
    return auth_supabase


async def _user_settings(user_id: str) -> dict:
    sb = _supabase()
    if not sb:
        return {}
    try:
        resp = await _execute(
            sb.table("user_settings").select("*").eq("user_id", user_id).maybe_single()
        )
        return (resp.data if resp else None) or {}
    except Exception:
        # Brand-new users have no row yet — non-fatal.
        return {}


class UploadUrlRequest(BaseModel):
    url: str
    meeting_id: Optional[str] = None
    workspace_id: Optional[str] = None
    sensitivity: str = "internal"


class ConnectSourceRequest(BaseModel):
    source_type: str  # 'notion' | 'gdrive'
    source_id: str
    name: str
    meeting_id: Optional[str] = None
    workspace_id: Optional[str] = None
    sensitivity: str = "internal"


class UpdateDocRequest(BaseModel):
    name: Optional[str] = None
    sensitivity: Optional[str] = None
    meeting_id: Optional[str] = None
    workspace_id: Optional[str] = None


def _coerce_meeting_id(value) -> Optional[int]:
    """meetings.id is bigint; convert string IDs from the frontend, drop bad input."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _sibling_meeting_ids(sb, meeting_id: int) -> list[int]:
    """All meeting-row ids that are the SAME logical meeting as `meeting_id`.

    In a workspace each member holds their own fan-out copy of a meeting, each with a
    DIFFERENT id. A doc pinned by the owner carries the owner's copy id — so a teammate
    viewing their own copy (a different id) wouldn't see the pin. Resolve every copy that
    shares the recall_bot_id (bot meetings) or the (workspace_id, date) pair (uploads), so
    a pin surfaces on all copies. Always includes the original id. Best-effort → [id]."""
    ids = {meeting_id}
    try:
        resp = await _execute(
            sb.table("meetings").select("recall_bot_id,workspace_id,date")
            .eq("id", meeting_id).limit(1)
        )
        row = (resp.data or [None])[0] if resp else None
        if not row:
            return list(ids)
        bot_id = row.get("recall_bot_id")
        ws_id = row.get("workspace_id")
        date = row.get("date")
        if bot_id:
            sib = await _execute(
                sb.table("meetings").select("id").eq("recall_bot_id", bot_id)
            )
        elif ws_id and date:
            sib = await _execute(
                sb.table("meetings").select("id").eq("workspace_id", ws_id).eq("date", date)
            )
        else:
            sib = None
        for r in ((sib.data if sib else None) or []):
            if r.get("id") is not None:
                ids.add(int(r["id"]))
    except Exception as exc:
        print(f"[knowledge] sibling meeting resolve failed for {meeting_id}: {exc}")
    return list(ids)


async def _insert_doc_row(sb, *, user_id: str, name: str, source_type: str,
                          source_url: Optional[str] = None, file_path: Optional[str] = None,
                          size_bytes: Optional[int] = None, meeting_id: Optional[str] = None,
                          workspace_id: Optional[str] = None,
                          sensitivity: str = "internal") -> str:
    doc_id = str(uuid.uuid4())
    await _execute(
        sb.table("knowledge_docs").insert({
            "id": doc_id,
            "user_id": user_id,
            "name": name,
            "source_type": source_type,
            "source_url": source_url,
            "file_path": file_path,
            "size_bytes": size_bytes,
            "meeting_id": _coerce_meeting_id(meeting_id),
            "workspace_id": (workspace_id or None),
            "sensitivity": sensitivity,
            "status": "processing",
        })
    )
    return doc_id


@router.post("/upload")
async def upload_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    meeting_id: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
    sensitivity: str = Form("internal"),
    user_id: str = Depends(require_user_id),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FILE_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    source_type = "pdf" if ext == "pdf" else "docx" if ext == "docx" else "txt"
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")

    file_path = f"{user_id}/{uuid.uuid4()}.{ext}"
    try:
        # Storage uploads can be 50MB → seconds of blocking I/O. Off the loop
        # so concurrent chat/webhook requests don't stall.
        await asyncio.to_thread(
            sb.storage.from_("knowledge").upload,
            file_path,
            content,
            {"content-type": file.content_type or "application/octet-stream"},
        )
    except Exception as exc:
        msg = str(exc)
        if "Bucket not found" in msg:
            raise HTTPException(status_code=503,
                detail="Storage bucket 'knowledge' is missing — create it in Supabase Storage.")
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {msg[:200]}")

    try:
        doc_id = await _insert_doc_row(
            sb, user_id=user_id, name=file.filename or "Untitled",
            source_type=source_type, file_path=file_path, size_bytes=len(content),
            meeting_id=meeting_id, workspace_id=workspace_id, sensitivity=sensitivity,
        )
    except Exception as exc:
        msg = str(exc)
        if "knowledge_docs" in msg and "schema cache" in msg:
            raise HTTPException(status_code=503,
                detail="knowledge_docs table is missing — run supabase/knowledge_migration.sql first.")
        raise

    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, content, source_type, settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.post("/upload-url")
async def upload_url(req: UploadUrlRequest, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    doc_id = await _insert_doc_row(
        sb, user_id=user_id, name=req.url, source_type="url",
        source_url=req.url, meeting_id=req.meeting_id,
        workspace_id=req.workspace_id, sensitivity=req.sensitivity,
    )
    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, req.url, "url", settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.post("/connect-source")
async def connect_source(req: ConnectSourceRequest, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    if req.source_type not in ("notion", "gdrive"):
        raise HTTPException(status_code=400, detail="source_type must be 'notion' or 'gdrive'")
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    doc_id = await _insert_doc_row(
        sb, user_id=user_id, name=req.name, source_type=req.source_type,
        source_url=req.source_id, meeting_id=req.meeting_id,
        workspace_id=req.workspace_id, sensitivity=req.sensitivity,
    )
    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, req.source_id, req.source_type, settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.get("/docs")
async def list_docs(
    meeting_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    user_id: str = Depends(require_user_id),
):
    """Scope mirrors the rest of the app:
    - meeting_id set  → docs pinned to that meeting (MeetingView panel)
    - workspace_id set → that workspace's shared docs (member-gated)
    - neither          → the caller's personal docs (own, not shared to any workspace)
    """
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    q = sb.table("knowledge_docs").select("*").is_("deleted_at", "null")
    mid = _coerce_meeting_id(meeting_id)
    if mid is not None:
        # Pinned docs for a meeting — still scoped to docs the caller can access
        # (their own, or shared into a workspace they belong to).
        ws_ids = get_user_workspace_ids(sb, user_id)
        # A pin carries the pinner's meeting-copy id; teammates hold other copies of the
        # same logical meeting. Match every sibling id so the pin shows on all copies.
        sib_ids = await _sibling_meeting_ids(sb, mid)
        if len(sib_ids) > 1:
            q = q.in_("meeting_id", sib_ids)
        else:
            q = q.eq("meeting_id", mid)
        if ws_ids:
            q = q.or_(f"user_id.eq.{user_id},workspace_id.in.({','.join(ws_ids)})")
        else:
            q = q.eq("user_id", user_id)
    elif workspace_id and workspace_id.strip():
        # Workspace library — verify membership before exposing shared docs.
        member = (
            sb.table("workspace_members").select("user_id")
            .eq("workspace_id", workspace_id).eq("user_id", user_id).execute()
        )
        if not (member.data or []):
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
        q = q.eq("workspace_id", workspace_id)
    else:
        # Personal library — own docs not shared into any workspace.
        q = q.eq("user_id", user_id).is_("workspace_id", "null")
    try:
        rows = q.order("created_at", desc=True).execute().data or []
    except Exception as exc:
        msg = str(exc)
        if "knowledge_docs" in msg and "schema cache" in msg:
            raise HTTPException(status_code=503,
                detail="knowledge_docs table is missing — run supabase/knowledge_migration.sql first.")
        raise
    return {"docs": rows}


def _signed_original_url(sb, doc: dict) -> Optional[str]:
    """A link to the doc's source: a short-lived signed URL for uploaded files,
    or the original source_url for url/notion/gdrive docs. None if neither."""
    file_path = doc.get("file_path")
    if file_path:
        try:
            res = sb.storage.from_("knowledge").create_signed_url(file_path, 3600)
            # supabase-py has returned both 'signedURL' and 'signedUrl' across versions
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        except Exception:
            return None
    return doc.get("source_url")


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str, user_id: str = Depends(require_user_id)):
    """Single doc + its extracted text (what Prism actually indexed). Access mirrors
    list_docs: the caller's own doc, or one shared into a workspace they belong to."""
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")

    doc_resp = await _execute(
        sb.table("knowledge_docs").select("*").eq("id", doc_id).is_("deleted_at", "null").single()
    )
    doc = doc_resp.data
    if not doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    # Authorize: own doc, or a doc shared into a workspace the caller is a member of.
    if doc.get("user_id") != user_id:
        ws_id = doc.get("workspace_id")
        if not (ws_id and ws_id in get_user_workspace_ids(sb, user_id)):
            raise HTTPException(status_code=403, detail="Not allowed to view this document")

    chunks_resp = await _execute(
        sb.table("knowledge_chunks").select("content,chunk_index")
        .eq("doc_id", doc_id).order("chunk_index", desc=False)
    )
    chunks = chunks_resp.data or []
    content = "\n\n".join((c.get("content") or "").strip() for c in chunks if c.get("content"))

    doc["content"] = content
    doc["original_url"] = _signed_original_url(sb, doc)
    return {"doc": doc}


@router.patch("/docs/{doc_id}")
async def update_doc(doc_id: str, req: UpdateDocRequest, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    update = {k: v for k, v in req.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "meeting_id" in update:
        update["meeting_id"] = _coerce_meeting_id(update["meeting_id"])
    # Empty-string workspace_id means "move back to personal" → store NULL.
    if "workspace_id" in update:
        update["workspace_id"] = update["workspace_id"] or None
    sb.table("knowledge_docs").update(update).eq("id", doc_id).eq("user_id", user_id).execute()
    # Chunks denormalize workspace_id for retrieval scoping — keep them in sync.
    if "workspace_id" in update:
        sb.table("knowledge_chunks").update(
            {"workspace_id": update["workspace_id"]}
        ).eq("doc_id", doc_id).eq("user_id", user_id).execute()
    return {"ok": True}


@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, user_id: str = Depends(require_user_id)):
    try:
        await soft_delete_doc(doc_id, user_id)
    except DocNotFound:
        raise HTTPException(status_code=404, detail="Document not found")
    except DeletePermissionDenied:
        raise HTTPException(
            status_code=403,
            detail="Permission denied. Only the uploader or workspace owner can delete this document.",
        )
    return {"ok": True}


@router.post("/docs/{doc_id}/resync")
async def resync_doc(doc_id: str, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    doc_resp = await _execute(
        sb.table("knowledge_docs").select("*").eq("id", doc_id).eq("user_id", user_id).single()
    )
    doc = doc_resp.data
    if not doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    settings = await _user_settings(user_id)
    await _execute(sb.table("knowledge_chunks").delete().eq("doc_id", doc_id))
    await _execute(
        sb.table("knowledge_docs").update({"status": "processing"}).eq("id", doc_id)
    )

    src = doc["source_type"]
    if src in ("url", "notion", "gdrive"):
        content = doc.get("source_url") or ""
    else:
        file_path = doc["file_path"]
        # Storage downloads can be large — off the event loop.
        content = await asyncio.to_thread(sb.storage.from_("knowledge").download, file_path)
    background.add_task(ingest_doc, doc_id, content, src, settings)
    return {"ok": True}


@router.get("/queries")
async def list_queries(bot_id: Optional[str] = None, limit: int = 50, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    if not sb:
        raise HTTPException(status_code=503, detail="Storage not configured")
    q = sb.table("knowledge_queries").select("*").eq("user_id", user_id)
    if bot_id:
        q = q.eq("bot_id", bot_id)
    rows = q.order("created_at", desc=True).limit(limit).execute().data or []
    return {"queries": rows}

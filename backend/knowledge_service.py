"""Core knowledge service: ingestion orchestration + similarity search."""

import asyncio
import os
import uuid
from typing import Optional

from supabase import Client, create_client

from caches import get_user_workspace_ids
from embeddings import embed_text, embed_batch
from knowledge_ingest.chunker import chunk_text
from knowledge_ingest.loaders_base import LoaderError

MIN_SCORE_DEFAULT = 0.75
CONFLICT_THRESHOLD = 0.05
MAX_CHUNKS_PER_USER = 50_000
INSERT_BATCH_SIZE = 50  # 50 chunks × 1536 floats ≈ ~3 MB per request, well under PostgREST limits

_sb_client: Optional[Client] = None


def _supabase() -> Client:
    global _sb_client
    if _sb_client is None:
        url = os.getenv("SUPABASE_URL", "")
        # This project stores the service-role key as SUPABASE_KEY (see auth.py).
        # Accept SUPABASE_SERVICE_ROLE_KEY too in case it's set that way on Render.
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")
        _sb_client = create_client(url, key)
    return _sb_client


async def _execute(query):
    """Run a built Supabase query off the FastAPI event loop.

    Supabase's Python SDK is synchronous (it wraps a sync httpx.Client). Calling
    `.execute()` directly from an async function blocks the entire loop for the
    duration of the HTTP round-trip — under load, every other coroutine stalls.
    `asyncio.to_thread` dispatches the call to the default thread pool so the
    loop keeps serving requests.

    Use for any chain ending in `.execute()`:
        await _execute(sb.table("x").update({...}).eq("id", n))

    For storage I/O (.upload, .download) call `asyncio.to_thread` directly —
    that API isn't query-shaped.
    """
    return await asyncio.to_thread(query.execute)


class QuotaExceeded(Exception):
    pass


async def check_user_quota(user_id: str, new_chunks: int) -> None:
    sb = _supabase()
    res = await _execute(
        sb.table("knowledge_chunks").select("id", count="exact").eq("user_id", user_id)
    )
    current = getattr(res, "count", 0) or 0
    if current + new_chunks > MAX_CHUNKS_PER_USER:
        raise QuotaExceeded(
            f"Quota exceeded: you have {current} chunks, this would add {new_chunks} "
            f"(limit {MAX_CHUNKS_PER_USER}). Delete some documents first."
        )


# `_caller_workspace_ids` was inlined here historically; it now lives in
# caches.py as `get_user_workspace_ids` and is shared across knowledge_*,
# recall_*, and storage_* routers. See caches.py for cache semantics.


async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
) -> list[dict]:
    """Embed query, run pgvector similarity search, return matches with conflict flag.
    Scoped to the caller's own docs plus any docs shared into their workspaces."""
    query_vec = await embed_text(query)
    sb = _supabase()
    # meetings.id is bigint; coerce string IDs so PostgREST doesn't bounce them.
    meeting_filter: Optional[int]
    try:
        meeting_filter = int(meeting_id) if meeting_id not in (None, "") else None
    except (TypeError, ValueError):
        meeting_filter = None
    workspace_ids = get_user_workspace_ids(sb, user_id)
    resp = await _execute(
        sb.rpc(
            "knowledge_search",
            {
                "query_embedding": query_vec,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": k,
                "min_score": min_score,
            },
        )
    )
    rows = resp.data or []
    if len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True
    return rows


async def _record_doc_error(sb, doc_id: str, message: str) -> None:
    """Write an error status for the doc. Wrapped in its own try/except so a
    DB failure DURING error reporting doesn't propagate out of `ingest_doc`
    (which is a background task — uncaught raises would just become opaque
    log noise, leaving the doc stuck in "processing" forever).
    """
    try:
        await _execute(
            sb.table("knowledge_docs")
            .update({"status": "error", "error_message": message})
            .eq("id", doc_id)
        )
    except Exception as inner:
        print(f"[knowledge] failed to write error status for doc {doc_id}: {inner}")


async def ingest_doc(doc_id: str, content: bytes | str, source_type: str, user_settings: dict) -> None:
    """Background worker. Loads → chunks → embeds → inserts.
    Updates status field at each phase. Never raises — errors written to error_message.

    Every Supabase HTTP call runs on a worker thread (via _execute) so the
    FastAPI event loop stays responsive even for big PDFs (~7-8 blocking
    calls per ingestion, ~50-200ms each).
    """
    sb = _supabase()
    try:
        await _execute(
            sb.table("knowledge_docs").update({"status": "processing"}).eq("id", doc_id)
        )

        doc_resp = await _execute(
            sb.table("knowledge_docs").select("*").eq("id", doc_id).single()
        )
        doc_row = doc_resp.data
        if not doc_row:
            return
        user_id = doc_row["user_id"]

        if source_type == "pdf":
            from knowledge_ingest import pdf_loader
            loaded = await pdf_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "docx":
            from knowledge_ingest import docx_loader
            loaded = await docx_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "txt":
            from knowledge_ingest import text_loader
            loaded = await text_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "url":
            from knowledge_ingest import url_loader
            loaded = await url_loader.load(content if isinstance(content, str) else content.decode())
        elif source_type == "notion":
            from knowledge_ingest import notion_loader
            token = user_settings.get("notion_access_token", "")
            loaded = await notion_loader.load(content if isinstance(content, str) else content.decode(), token=token)
        elif source_type == "gdrive":
            from knowledge_ingest import gdrive_loader
            token = user_settings.get("google_access_token", "")
            loaded = await gdrive_loader.load(content if isinstance(content, str) else content.decode(), token=token)
        else:
            raise LoaderError(f"Unknown source_type: {source_type}")

        base_meta = (loaded.page_metadata or [{}])[0]
        chunks = chunk_text(loaded.text, base_metadata=base_meta)

        await check_user_quota(user_id, len(chunks))

        contents = [c["content"] for c in chunks]
        vectors = await embed_batch(contents)

        # Propagate workspace_id from the doc onto each chunk so the similarity
        # search can scope by workspace without joining back to knowledge_docs.
        doc_workspace_id = doc_row.get("workspace_id")
        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "workspace_id": doc_workspace_id,
                "content": chunks[i]["content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
        # Sequential inserts (not gathered) — keeps DB load predictable and makes
        # any per-batch failure recoverable without dangling tasks.
        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            await _execute(
                sb.table("knowledge_chunks").insert(rows[i : i + INSERT_BATCH_SIZE])
            )

        await _execute(
            sb.table("knowledge_docs").update({
                "status": "ready",
                "chunk_count": len(rows),
                "last_synced_at": "now()",
                "error_message": None,
            }).eq("id", doc_id)
        )

    except LoaderError as exc:
        await _record_doc_error(sb, doc_id, str(exc))
    except QuotaExceeded as exc:
        await _record_doc_error(sb, doc_id, str(exc))
    except Exception as exc:
        await _record_doc_error(sb, doc_id, f"Unexpected error: {str(exc)[:200]}")


async def soft_delete_doc(doc_id: str, user_id: str) -> None:
    """Mark the doc deleted AND hard-delete its chunks so the user's quota recovers.
    The doc row stays (with deleted_at set) for the 30-day audit/undelete window."""
    sb = _supabase()
    await _execute(
        sb.table("knowledge_chunks").delete().eq("doc_id", doc_id).eq("user_id", user_id)
    )
    await _execute(
        sb.table("knowledge_docs")
        .update({"deleted_at": "now()", "chunk_count": 0})
        .eq("id", doc_id).eq("user_id", user_id)
    )

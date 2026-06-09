"""Core knowledge service: ingestion orchestration + similarity search."""

import asyncio
import os
import uuid
from typing import Optional

from supabase import Client, create_client

from caches import get_user_workspace_ids
from embeddings import embed_text, embed_batch, is_transient_connection_error
from knowledge_ingest.chunker import chunk_text
from knowledge_ingest.context_preprocessor import add_context
from knowledge_ingest.loaders_base import LoaderError

MIN_SCORE_DEFAULT = 0.75
CONFLICT_THRESHOLD = 0.05
MAX_CHUNKS_PER_USER = 50_000
INSERT_BATCH_SIZE = 50  # 50 chunks × 1536 floats ≈ ~3 MB per request, well under PostgREST limits
_EXECUTE_MAX_RETRIES = 2  # connection-level transients only; see _execute

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

    Connection-level transients (a stale keep-alive socket reaped by Render's
    upstream → httpx.RemoteProtocolError "Server disconnected") are retried with
    backoff. The Supabase SDK's httpx pool evicts the dead connection on failure,
    so the next attempt opens a fresh one. Was the root cause of the proactive-
    knowledge "Server disconnected" failures (diagnose 2026-06-08).
    """
    delay = 0.5
    for attempt in range(_EXECUTE_MAX_RETRIES + 1):
        try:
            return await asyncio.to_thread(query.execute)
        except Exception as exc:
            if attempt < _EXECUTE_MAX_RETRIES and is_transient_connection_error(exc):
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if is_transient_connection_error(exc):
                print(f"[knowledge] Supabase connection error after "
                      f"{attempt + 1} attempt(s): {type(exc).__name__}: {exc}")
            raise


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


def _rrf_merge(
    vector_hits: list[dict],
    bm25_hits: list[dict],
    k_rrf: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion.

    Combines two ranked result lists by summing 1/(k_rrf + rank) per document.
    Rank-based, so it ignores absolute score scales (cosine ∈ [0,1] vs
    unbounded BM25), which is why this replaces the min-max normalization
    approach used in the original smart-RAG plan.

    Returns a single ranked list. Each row's `score` is overwritten with the
    fused score and `match_type` is set to "hybrid".

    NOTE: input row dicts are mutated in place (consistent with the rest of
    knowledge_service — see e.g. `possible_conflict` writes in `search_knowledge`).
    Pass copies if the caller still needs the originals.
    """
    by_id: dict[str, dict] = {}
    fused: dict[str, float] = {}
    for rank, row in enumerate(vector_hits, start=1):
        rid = row["id"]
        by_id[rid] = row
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (k_rrf + rank)
    for rank, row in enumerate(bm25_hits, start=1):
        rid = row["id"]
        by_id.setdefault(rid, row)
        fused[rid] = fused.get(rid, 0.0) + 1.0 / (k_rrf + rank)
    merged = sorted(by_id.values(), key=lambda r: fused[r["id"]], reverse=True)
    for r in merged:
        r["score"] = fused[r["id"]]
        r["match_type"] = "hybrid"
    return merged


async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
    hybrid: bool = True,
    rerank: bool = False,
    rewrite_query: bool = False,
    conversation_history: Optional[list[str]] = None,
) -> list[dict]:
    """Embed query, run pgvector + (optionally) BM25, fuse with RRF, return matches.

    Args:
        hybrid: vector + BM25 RRF (default). When False, vector-only with raw
            cosine min_score semantics — preserved for back-compat.
        rerank: Phase 4 — run a Groq LLM reranker on the fused top-N to
            reorder by relevance. Adds ~300-500ms. Opt-in (default OFF) so the
            proactive surfacing path stays light at ~150ms.
        rewrite_query: Phase 5 — rewrite terse / follow-up queries into
            standalone form via Groq before embedding+BM25. Heuristic gate
            avoids the call when the query is already clear. Opt-in.
        conversation_history: prior turns (most recent last) used by the
            query rewriter to resolve references like "and engineering?". Only
            consulted when rewrite_query=True.
    """
    sb = _supabase()
    # meetings.id is bigint; coerce string IDs so PostgREST doesn't bounce them.
    meeting_filter: Optional[int]
    try:
        meeting_filter = int(meeting_id) if meeting_id not in (None, "") else None
    except (TypeError, ValueError):
        meeting_filter = None
    workspace_ids = get_user_workspace_ids(sb, user_id)

    # Phase 5: query rewriting (lazy import keeps proactive path free of the
    # extra module load — and avoids any circular-import surprises since both
    # modules sit in the backend package and reach for agents.utils).
    effective_query = query
    if rewrite_query:
        from knowledge_query_rewriter import maybe_rewrite_query
        effective_query = await maybe_rewrite_query(query, conversation_history)

    if not hybrid:
        # Vector-only path — preserves raw cosine `min_score` semantics.
        query_vec = await embed_text(effective_query)
        resp = await _execute(
            sb.rpc(
                "knowledge_search",
                {
                    "query_embedding": query_vec,
                    "caller_user_id": user_id,
                    "caller_workspace_ids": workspace_ids,
                    "meeting_filter": meeting_filter,
                    "match_limit": k if not rerank else max(30, k * 3),
                    "min_score": min_score,
                },
            )
        )
        rows = resp.data or []
    else:
        # Hybrid path — vector + BM25 in parallel, RRF-fused.
        # Wider top-N (30) per branch so RRF has enough candidates to work with.
        # `return_exceptions=True` so a missing BM25 RPC (e.g., migration not
        # yet applied) or a transient Supabase outage degrades to vector-only
        # instead of crashing the whole tool call.
        query_vec = await embed_text(effective_query)
        vec_resp, bm25_resp = await asyncio.gather(
            _execute(sb.rpc(
                "knowledge_search",
                {
                    "query_embedding": query_vec,
                    "caller_user_id": user_id,
                    "caller_workspace_ids": workspace_ids,
                    "meeting_filter": meeting_filter,
                    "match_limit": 30,
                    "min_score": min_score,
                },
            )),
            _execute(sb.rpc(
                "knowledge_search_bm25",
                {
                    "query_text": effective_query,
                    "caller_user_id": user_id,
                    "caller_workspace_ids": workspace_ids,
                    "meeting_filter": meeting_filter,
                    "match_limit": 30,
                },
            )),
            return_exceptions=True,
        )
        if isinstance(vec_resp, Exception):
            # Vector failure is fatal — without it we have no semantic signal.
            # Log the type so the proactive/on-demand "search failed" surfaces
            # the real culprit (APIConnectionError=OpenAI, RemoteProtocolError=Supabase).
            print(f"[knowledge] vector search failed: {type(vec_resp).__name__}: {vec_resp}")
            raise vec_resp
        bm25_rows = [] if isinstance(bm25_resp, Exception) else (bm25_resp.data or [])
        rows = _rrf_merge(vec_resp.data or [], bm25_rows)[: k * 3]

    # Phase 4: reranking. Skipped on proactive (rerank=False default).
    # When reranking, we trust the LLM's relevance judgment over the
    # transcript-count heuristic, so the transcript cap is bypassed —
    # the reranker should already deprioritize over-long transcript hits
    # if they're not actually the best answer.
    if rerank and len(rows) > 1:
        from knowledge_reranker import rerank as _rerank
        return await _rerank(effective_query, rows, top_k=k)

    # Cap meeting-transcript results in top-k (transcripts are long and
    # otherwise dominate retrieval). Tunable.
    MAX_TRANSCRIPT_HITS = 2
    capped: list[dict] = []
    transcript_count = 0
    for r in rows:
        if r.get("source_type") == "meeting_transcript":
            if transcript_count >= MAX_TRANSCRIPT_HITS:
                continue
            transcript_count += 1
        capped.append(r)
        if len(capped) >= k:
            break
    rows = capped

    # Conflict detection is calibrated against raw cosine scores (0..1) — in
    # hybrid mode every score is an RRF value bounded by 2/(k_rrf+1) ≈ 0.033,
    # so CONFLICT_THRESHOLD=0.05 would fire on every result. Skip in hybrid
    # mode until a rank-aware heuristic exists.
    if not hybrid and len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True
    # TODO(post-AWS): rerank `rows` here with BGE once we have the RAM headroom.
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

        # Phase 2: add contextual preamble before embedding. Failure here falls
        # back to embedding the raw chunk content (per add_context contract).
        chunks = await add_context(
            chunks,
            doc_name=doc_row.get("name") or "document",
            doc_summary="",
        )

        contents = [c["embedded_content"] for c in chunks]
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
                "embedded_content": chunks[i].get("embedded_content") or chunks[i]["content"],
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

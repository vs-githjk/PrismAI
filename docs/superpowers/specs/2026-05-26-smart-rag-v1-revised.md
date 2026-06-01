# Smart-RAG v1 (Revised) — Design Spec

**Date:** 2026-05-26
**Branch:** `fixed-changes`
**Status:** Approved (section-by-section), ready for implementation plan
**Supersedes:** `docs/superpowers/plans/2026-05-25-smart-rag-implementation.md` (Phases 3–5 portion only — Phases 1+2 commits are kept and patched)

---

## Why this revision exists

The original smart-RAG plan was paused after Phases 1+2 shipped. An edge-case audit surfaced design gaps (workspace fan-out duplication, missing quota guard, unbounded Groq fan-out, wasted LLM calls on transcripts) plus an environment mismatch: the BGE reranker (~280MB) doesn't fit on Render free tier. The fusion math (min-max normalization) was also fragile.

This spec keeps the committed Phase 1+2 work, patches the gaps, replaces the fusion math with RRF, and defers Phases 4–5 to post-AWS migration.

---

## Scope

**Ship now (on Render):**

| Phase | What | Notes |
|-------|------|-------|
| 1 (kept) | Transcript indexing | + 2 critical fixes |
| 2 (kept) | Contextual preprocessing | + 2 important fixes |
| 3 (new) | BM25 hybrid with **RRF fusion** | Replaces old plan's normalized hybrid |

**Deferred to post-AWS:**

| Phase | What | Why deferred |
|-------|------|--------------|
| 4 | BGE reranker | Needs ~2GB RAM; revisit once AWS migration is live |
| 5 | Query rewriting | Better after conversation-history threading lands |

---

## Critical fixes (Phase 1)

### Fix #1 — Transcript fan-out dedup

**Problem.** A workspace-dedup'd bot recording causes two frontends (recorder + dedup'd teammate) to `POST /meetings`. Each POST currently fires its own `index_meeting_transcript` task with different `meeting_id`s, producing duplicate `knowledge_docs` rows. The current idempotency check (`.eq("meeting_id", meeting_id)`) doesn't catch this.

**Fix.** In `storage_routes.save_meeting`, only fire indexing when the caller is the primary recorder:

```python
# storage_routes.py — after fan-out, replace the unconditional create_task
if entry.recorded_by_user_id in (None, "", user_id):
    asyncio.create_task(index_meeting_transcript(
        meeting_id=entry.id,
        user_id=entry.recorded_by_user_id or user_id,
        workspace_id=entry.workspace_id or None,
        date=entry.date,
        title=entry.title,
        transcript=entry.transcript,
    ))
```

Teammates still get search access via the existing workspace_id RLS on `knowledge_chunks`. One transcript = one doc.

### Fix #2 — Quota check for transcripts

**Problem.** `index_meeting_transcript` skips `check_user_quota`. A ~3-hour meeting at ~500 chunks can blow past the 50k-chunk cap mid-insert, leaving the doc stuck in `status="processing"` with a partial chunk set.

**Fix.** In `knowledge_transcript.index_meeting_transcript`, between chunking and embedding:

```python
from knowledge_service import check_user_quota, QuotaExceeded

try:
    await check_user_quota(user_id, len(chunks))
except QuotaExceeded as exc:
    await _execute(
        sb.table("knowledge_docs")
        .update({"status": "error", "error_message": str(exc)})
        .eq("id", doc_id)
    )
    return
```

Same shape as `ingest_doc`'s quota handling.

---

## Important fixes (Phase 2)

### Fix #3 — Bound concurrent Groq calls in `add_context`

**Problem.** `asyncio.gather(*(_preamble_for_chunk(c, ...) for c in chunks))` is unbounded. A 200-chunk PDF triggers 200 simultaneous Groq calls; rate-limit 429s cause every preamble to silently fall back to raw content, wiping out the contextual-retrieval benefit.

**Fix.** Module-level `asyncio.Semaphore(8)` in `context_preprocessor.py`, applied inside `_preamble_for_chunk` around the LLM call:

```python
# backend/knowledge_ingest/context_preprocessor.py
_GROQ_SEM = asyncio.Semaphore(8)

async def _preamble_for_chunk(chunk, doc_name, doc_summary):
    heading = (chunk.get("metadata") or {}).get("heading") or ""
    key = _cache_key(doc_name, chunk["content"], heading)
    if key in _cache:
        return _cache[key]
    try:
        async with _GROQ_SEM:
            preamble = (await _llm_preamble(doc_name, doc_summary, heading=heading)).strip()
    except Exception:
        preamble = ""
    if preamble:
        _cache[key] = preamble
    return preamble
```

8 is well under Groq's default RPS. A 200-chunk doc completes in ~5s instead of hammering the API.

### Fix #4 — Lightweight inline preamble for transcripts (no LLM)

**Problem.** Transcripts currently embed raw chunk content (`embedded_content = content`) — no preamble at all, so they're at a retrieval disadvantage vs. docs that went through Phase 2's contextual preprocessing. Routing transcripts through `add_context` (Groq) would burn LLM budget for essentially-templated preambles, since transcript chunks have no section heading and the only useful context is title + date, both available in the calling args.

**Fix.** `index_meeting_transcript` builds the preamble in-process from a template and skips `add_context` entirely:

```python
# knowledge_transcript.py — between chunking and embedding
preamble = f"From your meeting '{title}' on {date[:10]}."
for c in chunks:
    c["embedded_content"] = f"{preamble} {c['content']}"
```

Zero LLM cost; citation-formatting in `tools/knowledge_lookup.py` already understands the *"From your meeting on {date}: ..."* shape.

---

## Phase 3 — BM25 hybrid with RRF fusion

### Goal

Combine semantic (vector) and lexical (BM25) retrieval so exact-keyword queries (*"Q3 revenue target"*) and conceptual queries (*"how are we tracking against targets"*) both succeed.

### Schema

New migration `supabase/knowledge_bm25_migration.sql`:

```sql
alter table knowledge_chunks
  add column if not exists content_tsv tsvector
  generated always as (to_tsvector('english', coalesce(embedded_content, content))) stored;

create index if not exists knowledge_chunks_tsv_idx
  on knowledge_chunks using gin(content_tsv);
```

Notes:
- Generated column on `embedded_content` (preamble + content) so the preamble's title/section hints participate in lexical match too.
- `coalesce(embedded_content, content)` makes the column safe for legacy rows where `embedded_content` is null (set to `content` by the Phase 2 migration).

### New RPC: `knowledge_search_bm25`

Same parameter shape as `knowledge_search` but accepts `query_text text` instead of `query_embedding`. Internally:

```sql
select c.id, c.doc_id, c.content, c.embedded_content, c.metadata, c.chunk_index,
       d.name as doc_name, d.source_type,
       ts_rank_cd(c.content_tsv, plainto_tsquery('english', query_text)) as score,
       'bm25'::text as match_type
from knowledge_chunks c
join knowledge_docs d on d.id = c.doc_id
where d.deleted_at is null
  and (c.user_id = caller_user_id or d.workspace_id = any(caller_workspace_ids))
  and (meeting_filter is null or d.meeting_id = meeting_filter)
  and c.content_tsv @@ plainto_tsquery('english', query_text)
order by score desc
limit match_limit;
```

No `min_score` filter — BM25 scores are unbounded so a global threshold doesn't generalize. The transcript cap + conflict marker handle quality control downstream.

### Fusion = Reciprocal Rank Fusion (RRF)

```python
# backend/knowledge_service.py
def _rrf_merge(vector_hits: list[dict], bm25_hits: list[dict], k_rrf: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion. Combines two ranked lists by 1/(k_rrf + rank).
    Rank-based, so it ignores absolute score scales (cosine ∈ [0,1] vs unbounded BM25)."""
    by_id: dict[str, dict] = {}
    fused: dict[str, float] = {}
    for rank, row in enumerate(vector_hits, start=1):
        by_id[row["id"]] = row
        fused[row["id"]] = fused.get(row["id"], 0.0) + 1.0 / (k_rrf + rank)
    for rank, row in enumerate(bm25_hits, start=1):
        by_id.setdefault(row["id"], row)
        fused[row["id"]] = fused.get(row["id"], 0.0) + 1.0 / (k_rrf + rank)
    merged = sorted(by_id.values(), key=lambda r: fused[r["id"]], reverse=True)
    for r in merged:
        r["score"] = fused[r["id"]]   # overwrite per-branch score with fused score
        r["match_type"] = "hybrid"
    return merged
```

`k_rrf = 60` is the standard default; sensitivity is low so we don't tune unless metrics complain.

### Updated `search_knowledge` flow

```python
async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
    hybrid: bool = True,   # new param; False keeps the vector-only path
) -> list[dict]:
    sb = _supabase()
    meeting_filter = _coerce_meeting_id(meeting_id)
    workspace_ids = get_user_workspace_ids(sb, user_id)

    if not hybrid:
        # Existing vector-only path — preserves raw cosine `min_score` semantics.
        query_vec = await embed_text(query)
        resp = await _execute(sb.rpc("knowledge_search", {
            "query_embedding": query_vec,
            "caller_user_id": user_id,
            "caller_workspace_ids": workspace_ids,
            "meeting_filter": meeting_filter,
            "match_limit": k,
            "min_score": min_score,
        }))
        rows = resp.data or []
    else:
        # Hybrid: fan out two RPCs in parallel, then RRF.
        query_vec_task = embed_text(query)
        bm25_task = asyncio.to_thread(
            sb.rpc("knowledge_search_bm25", {
                "query_text": query,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": 30,
            }).execute
        )
        query_vec = await query_vec_task
        vec_resp = await _execute(sb.rpc("knowledge_search", {
            "query_embedding": query_vec,
            "caller_user_id": user_id,
            "caller_workspace_ids": workspace_ids,
            "meeting_filter": meeting_filter,
            "match_limit": 30,
            "min_score": min_score,   # applied to vector branch only
        }))
        bm25_resp = await bm25_task
        rows = _rrf_merge(vec_resp.data or [], bm25_resp.data or [])[: k * 3]

    rows = _cap_transcripts(rows, k=k, max_transcripts=2)
    rows = _mark_conflict(rows)
    # TODO(post-AWS): rerank `rows` here once we have the GPU/RAM headroom.
    return rows[:k]
```

`_cap_transcripts` and `_mark_conflict` are existing helpers (already extracted in the Phase 1+2 commits).

### Test plan

| Test | Type | What it verifies |
|------|------|------------------|
| `test_rrf_merge_combines_rankings` | unit | RRF math on synthetic rank lists |
| `test_rrf_handles_one_empty_list` | unit | Single-branch failure doesn't crash |
| `test_search_knowledge_hybrid_calls_both_rpcs` | integration (mocked Supabase) | Vector + BM25 both invoked when `hybrid=True` |
| `test_search_knowledge_vector_only_path` | regression | `hybrid=False` matches the pre-Phase-3 behavior |
| `test_bm25_migration_applies` | smoke | Migration runs cleanly against a snapshot DB |
| Existing `test_knowledge_service` suite | regression | Still green |

---

## Critical-fixes test plan (Phase 1+2)

| Test | Verifies fix |
|------|--------------|
| `test_transcript_skips_indexing_for_fanout_recipient` | #1 — only the recorder's POST creates the doc |
| `test_transcript_index_marks_error_on_quota_exceeded` | #2 — quota guard |
| `test_add_context_bounds_concurrency_at_8` | #3 — Semaphore is in effect |
| `test_transcript_preamble_skips_llm` | #4 — `add_context` not called for transcripts |

---

## Files this work will touch

**Backend (modify):**
- `backend/storage_routes.py` — Fix #1 guard around `create_task`
- `backend/knowledge_transcript.py` — Fix #2 quota call + Fix #4 inline preamble
- `backend/knowledge_ingest/context_preprocessor.py` — Fix #3 Semaphore
- `backend/knowledge_service.py` — Phase 3 hybrid path + `_rrf_merge` + `hybrid` param

**Backend (new):**
- `backend/tests/test_knowledge_transcript.py` — extend (Fixes #1, #2, #4)
- `backend/tests/test_context_preprocessor.py` — extend (Fix #3)
- `backend/tests/test_knowledge_service_hybrid.py` — Phase 3 tests

**Database (new migration):**
- `supabase/knowledge_bm25_migration.sql` — tsvector column + GIN index + `knowledge_search_bm25` RPC

**Docs:**
- This spec
- Implementation plan generated next (`docs/superpowers/plans/2026-05-26-smart-rag-v1-revised.md`)

---

## Open items deferred (tracked for post-AWS)

- **BGE reranker** (Phase 4): rerank top ~30 RRF candidates → top `k`. Insertion point already commented in `search_knowledge`. Library: `FlagEmbedding` BGE-reranker-base.
- **Query rewriting** (Phase 5): pull last 3 turns of conversation, rewrite ambiguous follow-ups (*"what about Q4?"*) into standalone queries. Needs chat-history threading first.

---

## How to resume

1. Implementation plan is written next via `superpowers:writing-plans`.
2. Execution via `superpowers:subagent-driven-development` on branch `fixed-changes`.
3. Run `supabase/knowledge_bm25_migration.sql` manually in Supabase SQL editor before the Phase 3 tasks.

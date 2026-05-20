# Smart RAG Additions — Build on the Knowledge Base Foundation

**Date:** 2026-05-20
**Status:** Design — ready for implementation after `fixed-changes` merge
**Author:** Session with Vidyut + Claude

---

## Context

The teammate's `fixed-changes` branch landed a high-quality **baseline vector RAG**: pgvector + OpenAI embeddings + strict-grounding prompts + Tavily web search + proactive surfacing. The code is production-grade. The architecture is correct for our use case (meeting-context fact-lookup).

But it has two problems:
1. **It's not yet *smart*.** Naive cosine similarity over isolated chunks is "working RAG" — not the "Notion AI / Glean" quality bar users expect when asking questions about their own company docs.
2. **It doesn't account for our workspace fan-out architecture.** Knowledge docs are user-scoped only. Meeting pinning ties to a single `meetings.id` (bigint) which has fan-out copies per workspace member.

This spec adds smart-RAG capabilities on top **without rebuilding** the foundation, and fixes the workspace gaps.

---

## Goal

Bring document Q&A quality from "decent vector RAG" → "production-grade hybrid RAG" while:
- Keeping end-to-end query latency under ~1 second
- Indexing **meeting transcripts alongside docs** so prism answers from both sources
- Sharing knowledge across **workspace members**, not just per-user
- Keeping the proactive surfacing path light (it runs every 20 transcript lines and must not block)

---

## Non-Goals

- **Graph RAG.** Vector RAG is the right architecture for our use case (fact-lookup, low latency). Multi-hop graph reasoning is overkill and slower at both ingest and query time. Skip.
- **Rebuilding what's already there.** The teammate's loaders, chunker, embeddings client, anti-hallucination strategy, and audit log all stay.
- **Real-time voice ID.** The voice pipeline rewrite is groundwork for Phase 6 but the audio capture / embedding / matching work is out of scope here.
- **Self-reflection / answer verification.** Modest quality gain at significant latency cost. Defer.
- **HyDE, multi-query expansion.** Diminishing returns on top of reranking + contextual retrieval. Defer.

---

## Resulting Architecture

### Ingest pipeline (one-time per doc / meeting)

```
Loader → text + metadata
      ↓
   Chunker (existing — 400 tokens, sentence-boundary aware)
      ↓
   CONTEXTUAL PREPROCESS (NEW)
      ↓
      For each chunk, one Groq call (Llama 3.3 70B) generates a
      ~50-100 token context preamble:
        "This chunk is from '<doc_name>', section '<heading or "near top">'."
      The preamble is prepended to the chunk BEFORE embedding,
      so the embedding captures the chunk's role in its document.
      ↓
   Embed (existing — OpenAI text-embedding-3-small)
      ↓
   Insert into knowledge_chunks (existing pgvector)
   ALSO insert into knowledge_chunks_fts (NEW — Postgres tsvector for BM25)
```

### Query pipeline (per lookup)

```
Step 1:  Query rewrite (Groq) — CONDITIONAL                ~150ms
         Only fires if:
           - query is < 5 tokens, OR
           - query contains a follow-up signal ("and X?", "what about Y?")
         Otherwise: skip.

Step 2:  PARALLEL via asyncio.gather:
         ├─ Embed query (OpenAI text-embedding-3-small)    ~50ms
         └─ BM25 keyword search (Postgres tsvector)        ~30ms
         Wall-clock: ~50ms

Step 3:  Vector search (pgvector HNSW)                     ~30ms
Step 4:  Hybrid score fusion                                ~5ms
         combined = 0.7 * normalized_vector_score
                  + 0.3 * normalized_bm25_score
         Take top 20 by combined score.

Step 5:  Rerank top-20 with cross-encoder                  ~100ms
         BGE-reranker-v2-m3 (local, CPU). Returns top-5.

Step 6:  Entity boost                                       ~10ms
         If query contains a name/proper-noun that appears
         in a result's content (case-insensitive match),
         multiply that result's score by 1.2.

Step 7:  Return top-5 with strict-grounding instruction.

Step 8:  LLM generates answer with citation requirement,
         STREAMED back to caller.                          ~600-1000ms

Total wall-clock: ~800ms (no rewrite) / ~950ms (with rewrite)
```

### Cross-source unification

The same `knowledge_chunks` table holds **both document chunks AND meeting transcript chunks**. A `source_type` column distinguishes:
- `pdf`, `docx`, `txt`, `url`, `notion`, `gdrive` (existing — documents)
- `meeting_transcript` (NEW)

After a meeting completes (existing `_compress_and_persist` flow in `realtime_routes.py`), we additionally chunk + embed + index the transcript using the SAME pipeline as docs. The transcript becomes searchable alongside docs.

Citation strings combine: *"According to your Q2 strategy doc AND last week's planning meeting..."*

### Proactive surfacing (light pipeline)

Unchanged from the teammate's implementation:
- Every 20 transcript lines
- min_score 0.85, k=3
- Dedupe cache (60s) + per-doc cooldown (10m)
- Sensitivity gating (public / internal-pinned / never-confidential)

**No reranking. No query rewriting.** Proactive is fire-and-forget background work and must stay light. Targets ~150ms total.

---

## Workspace Gap Fixes (Critical Prerequisite — Phase 0)

The teammate's schema treats knowledge as user-scoped. For our workspace product this is broken.

### Schema changes

```sql
-- Add workspace_id (nullable: null = personal knowledge)
alter table knowledge_docs add column workspace_id uuid
  references workspaces(id) on delete set null;
create index on knowledge_docs(workspace_id);

-- Add to knowledge_chunks too so retrieval can filter without a join
alter table knowledge_chunks add column workspace_id uuid;
create index on knowledge_chunks(workspace_id);
```

### Retrieval scope

`knowledge_search` RPC and `search_knowledge()` accept an optional `workspace_id`. When set, the WHERE clause becomes:

```sql
where deleted_at is null
  and (
    user_id = caller_user_id   -- caller's own personal docs
    or workspace_id = caller_workspace_id  -- workspace-shared docs
  )
```

When unset (personal mode), only `user_id = caller_user_id AND workspace_id IS NULL` matches.

### Meeting-pin fan-out handling

Pinning a doc to a meeting currently uses `meetings.id` (bigint). With fan-out, multiple rows share the same logical meeting. Two options:

**Option A (recommended):** Pin by `(date[:16], workspace_id)` — the same dedup key we use for workspace meetings in `storage_routes.py`. Add a `meeting_dedup_key` text column to `knowledge_docs`. Update the pin/unpin code to compute it. Cleanest.

**Option B:** Add a `logical_meeting_id` column to `meetings` (a UUID generated at first save, propagated through fan-outs) and reference that. More invasive — touches every meeting row.

Going with **A** in this spec. Lower-risk, no migration of existing meeting rows.

### Sensitivity model simplification

Drop `internal` as the default. New defaults:
- Personal upload (no workspace_id) → `sensitivity = 'private'`
- Workspace upload → `sensitivity = 'workspace'` (any member can use)
- Mark-as-`confidential` is opt-in for either scope.

`internal` was confusing — "what's internal vs confidential?" Rename to `workspace`. Users get a clearer mental model:
- `private` — only me
- `workspace` — my team
- `confidential` — anyone in scope, but ONLY when explicitly pinned to a meeting

---

## Implementation Phases

Each phase leaves the system in a working, shippable state. Stop after any phase and PrismAI still functions.

### Phase 0 — Merge `fixed-changes` + workspace gap fixes (~3 hours)

1. Merge `fixed-changes` into `vids_branch` — resolve conflicts manually
2. Verify all our recent work (sentiment card, brief, dedup fix) survives
3. Add `workspace_id` columns to `knowledge_docs` + `knowledge_chunks`
4. Update `knowledge_search` RPC to accept optional workspace_id and use the OR-scope above
5. Update `knowledge_routes.py` to accept workspace_id on upload + filter on list
6. Add `meeting_dedup_key` column to `knowledge_docs`; compute on pin/unpin
7. Rename sensitivity values: `internal` → `workspace`; migration on existing rows
8. Frontend: KnowledgeBase shows separate sections "My docs" / "[Workspace name] docs"

**Acceptance:** Two users in same workspace each upload a doc with `sensitivity='workspace'`. Both can search and find each other's docs. A `private` doc remains invisible to the other.

### Phase 1 — Cross-source unification: index meeting transcripts (~2 hours)

The single most product-defining upgrade — makes prism feel like it remembers your meetings.

1. After meeting analysis completes (existing `POST /meetings`), trigger background task to:
   - Chunk the transcript via existing `knowledge_ingest/chunker.py`
   - Embed the chunks
   - Insert into `knowledge_chunks` with `source_type='meeting_transcript'`, `workspace_id` set, `meeting_id` set to the meeting row
2. New `knowledge_docs` row per meeting (auto-created): `name='Meeting on May 14, 2026'`, `source_type='meeting_transcript'`, `meeting_id=...`
3. `knowledge_lookup` tool docstring updated: "...searches uploaded documents AND past meeting transcripts."
4. Citations include date for meeting sources.

**Acceptance:** User asks "Prism, what did we decide about pricing?" — bot finds answer from a previous meeting's transcript with citation `"Decision from your May 12 meeting"`.

### Phase 2 — Contextual retrieval (chunk preprocessing) (~2 hours)

The biggest pure-quality jump. Most of the work is one new function.

1. New module: `backend/knowledge_ingest/context_preprocessor.py`
2. `async def add_context(chunks: list[dict], doc_name: str, doc_summary: str) -> list[dict]`
3. For each chunk: one Groq call (Llama 3.3 70B, max_tokens=80) producing a contextual preamble
4. Preamble format: `"From '<doc_name>', section '<heading from chunk metadata or "near top">'. <chunk content>"`
5. Call this in `ingest_doc` BETWEEN chunking and embedding.
6. Store original chunk content separately from the embedded-with-context version — citations show ORIGINAL content to user, not the preamble.

Add to `knowledge_chunks`:
```sql
alter table knowledge_chunks add column embedded_content text;
-- content: original (shown in citations)
-- embedded_content: with preamble (used at embed time, not displayed)
```

**Acceptance:** Search "Q2 budget" — chunk from page 17 of a 50-page strategy doc surfaces because it's now embedded with context "From 'Q2 Strategy', section 'Budget Allocation'." Same chunk without contextual preprocessing scored too low to make top-5.

### Phase 3 — Hybrid retrieval (vector + BM25) (~1.5 hours)

1. Add Postgres FTS (full-text search) on chunk content:
   ```sql
   alter table knowledge_chunks add column content_tsvector tsvector
     generated always as (to_tsvector('english', content)) stored;
   create index knowledge_chunks_fts_idx on knowledge_chunks using gin(content_tsvector);
   ```
2. Modify `search_knowledge()` to run vector + BM25 in parallel via `asyncio.gather`
3. Normalize both score lists (min-max), fuse: `0.7 * vec + 0.3 * bm25`, take top 20
4. Pass top 20 to reranker (Phase 4)

**Acceptance:** Query "PRJ-2547" — exact-match ticket ID surfaces in top 3 even though embedding score is low. Pure-vector search would have missed it.

### Phase 4 — Reranking with BGE-reranker-v2-m3 (~2 hours)

1. Add to `requirements.txt`: `FlagEmbedding>=1.2.0` (~500MB download)
2. New module: `backend/knowledge_reranker.py` — loads BGE-reranker once at startup, exposes `async def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]`
3. Slot into query pipeline between hybrid fusion (top 20) and final return (top 5)
4. Cold-start cost: ~5s model load at first call — preload in `main.py` startup hook
5. Per-query cost: ~100ms on CPU, ~20ms on GPU (we're CPU on Render — accept 100ms)

**Acceptance:** Same query that returned a generic chunk in top-1 before now returns the precisely-relevant chunk in top-1. Measured on a held-out test set of 10 queries against the user's own docs.

### Phase 5 — Query rewriting + streaming response (~1.5 hours)

1. New helper in `knowledge_service.py`: `async def maybe_rewrite_query(query: str, conversation_history: list[str] = None) -> str`
2. Heuristic gate (NO LLM call): skip if `len(query.split()) >= 5` and no pronoun referring to prior turn
3. Otherwise: one Groq call with prompt "Rewrite this terse meeting question into a clear standalone question for document search: ..."
4. Stream the LLM response back to the bot's chat output (existing infrastructure supports this already)

**Acceptance:** Query "Q3?" after a discussion about Q2 budget → rewritten to "What is the Q3 budget?" before embedding. Bot answers correctly.

---

## Testing Strategy

Each phase has a test file in `backend/tests/`:
- `test_contextual_preprocessing.py` — verifies preamble generation + chunk preservation
- `test_hybrid_search.py` — covers vector + BM25 parallel + score fusion
- `test_reranker.py` — verifies BGE-reranker reorders sensibly on synthetic pairs
- `test_query_rewrite.py` — verifies the heuristic gate + LLM rewrite happy/skip paths
- `test_meeting_transcript_ingest.py` — verifies a saved meeting gets indexed as a knowledge source

End-to-end manual test (run after Phase 4):
1. Upload a 30-page company strategy PDF
2. Have a meeting discussing parts of it
3. Ask "Prism, what does our strategy say about X?" — verify answer cites the PDF
4. Ask "Prism, what did we decide about X in the meeting?" — verify answer cites the meeting
5. Ask a follow-up "and Y?" — verify query rewrite, correct answer
6. Ask about a proper noun / ID — verify hybrid search finds it
7. Measure end-to-end latency for 10 queries — expect mean < 1s

---

## Latency Budget Summary

| Path | Operations | Wall-clock |
|---|---|---|
| On-demand query (no rewrite) | embed ∥ BM25 → vec → fuse → rerank → entity → LLM stream first token | **~800ms** to first token |
| On-demand query (with rewrite) | rewrite → embed ∥ BM25 → vec → fuse → rerank → entity → LLM stream first token | **~950ms** to first token |
| Proactive surfacing | embed → vec → sensitivity gate → dedupe → cooldown → optional post | **~150ms** |
| Ingest (per doc) | load → chunk → contextual preprocess → embed → insert | **~5–15s** per ~10-page doc |

The +150ms cost for full smart RAG vs baseline vector RAG is more than worth the quality jump.

---

## Risks & Open Questions

1. **BGE-reranker on Render free tier** — 100ms is the ideal-case CPU. Real measurement might be 200–300ms. If unacceptable, fall back to Cohere Rerank API (~250ms + latency for hop) or skip reranking on proactive.

2. **OpenAI embedding cost at scale** — text-embedding-3-small is $0.02/1M tokens. For a 100-employee workspace with active doc upload, this stays under $50/month. Monitor.

3. **pgvector index size** — HNSW indexing required past ~50k chunks. Add `using hnsw (embedding vector_cosine_ops)` to the migration if not already present.

4. **Contextual preprocessing cost** — one Groq call per chunk at ingest. For a 50-page doc → ~100 chunks → 100 calls → maybe 30s ingest time. Acceptable for one-time cost. Cache by content-hash to avoid recomputation on resync.

5. **Cross-source ranking quality** — meeting transcripts are *much* longer than docs and may dominate retrieval if not bounded. Cap meeting-transcript results to ≤2 in top-5; let docs fill the rest. (Tunable.)

6. **Confidential docs in workspace mode** — when a `confidential` doc is pinned to a meeting, who in the workspace can use it during that meeting? V1 decision: all members (the pin is the access grant). Revisit if needed.

---

## What we are explicitly deferring

- **Self-reflection / answer verification.** Latency cost too high for V1.
- **Multi-query expansion.** Reranking handles most of what this would give.
- **HyDE.** Same — reranking obviates it for our quality bar.
- **Graph RAG layer.** Not needed for fact-lookup workload. Revisit if usage data shows multi-hop demand.
- **Voice ID + Phase 6 work.** Separate spec.
- **AWS migration.** Separate plan in `AWS_MIGRATION_PLAN.md`.

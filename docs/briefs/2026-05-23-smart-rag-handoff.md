# Smart RAG Implementation Brief

**For:** Teammate picking up Phase 5 (Smart RAG upgrades)
**From:** Vidyut (session with Claude, May 23 2026)
**Estimated total effort:** ~9–10 hours across 5 phases
**Spec (source of truth):** [`docs/specs/2026-05-20-smart-rag-additions.md`](../specs/2026-05-20-smart-rag-additions.md)

---

## 1. What's already done (don't redo this)

The baseline vector RAG + workspace scoping is **live in production** and smoke-tested. The spec calls this "Phase 0" and it is **closed**. Specifically:

- ✅ Merged `fixed-changes` into `main` — full knowledge base (loaders, chunker, embeddings client, ingest service, similarity search, two tools `knowledge_lookup` + `web_search`, proactive surfacing) is in the codebase.
- ✅ `workspace_id` columns on `knowledge_docs` + `knowledge_chunks`, RPC widened to `caller_workspace_ids uuid[]` so chunks are visible if `own OR workspace-shared`.
- ✅ `GET /knowledge/docs` scope-aware: `workspace_id` query param (workspace mode) vs. personal mode (`user_id = me AND workspace_id IS NULL`).
- ✅ `KnowledgeBase` page mounted in `DashboardSidebar` (nav entry "Knowledge") — scope-aware header ("Personal documents" vs "<Workspace> documents").
- ✅ Migrations run, Storage bucket `knowledge` created with RLS, `OPENAI_API_KEY` + `TAVILY_API_KEY` set on Render + local `.env`.
- ✅ Smoke test passed live: upload → ingest → ready → query.

**Read these before you start:**
- `docs/specs/2026-05-20-smart-rag-additions.md` — full design (Phases 1–5)
- `CLAUDE.md` → "Knowledge Base / RAG" section — current architecture
- `PRISM_AI_CONTEXT.md` → "Added May 21" + "Added May 22–23" entries — recent context

---

## 2. Branch + working state

- **Branch to work on:** `vids_branch` (working branch). `main` = production.
- **Latest HEAD:** `25c95fd` (as of May 23). Pull latest before starting.
- **Existing tests pattern:** see `backend/tests/test_knowledge_*.py` files from the merge — mirror them for new modules.
- **Local backend deps:** Python 3.12 framework at `/Library/Frameworks/Python.framework/Versions/3.12/`. Run `pip install -r requirements.txt` for any new deps you add — and add them to `requirements.txt` so Render installs them on deploy.

---

## 3. Recommended phase order (matches the spec)

Each phase ships independently. You can stop after any one and the system still works.

### Phase 1 — Cross-source unification: index meeting transcripts (~2 hours) ← START HERE

**Why first:** biggest product-defining lift. Makes Prism feel like it "remembers your meetings" — answers grounded in both docs AND past meeting transcripts.

1. After meeting analysis completes (existing `POST /meetings` in `backend/storage_routes.py`), trigger a background task that:
   - Chunks the transcript via existing `knowledge_ingest/chunker.py`
   - Embeds the chunks (existing `embeddings.embed_batch`)
   - Inserts into `knowledge_chunks` with `source_type='meeting_transcript'`, `workspace_id` set, `meeting_id` set, `user_id` = saver
2. Auto-create a `knowledge_docs` row per meeting: `name='Meeting on <date>'`, `source_type='meeting_transcript'`, `meeting_id=...`. (Add `meeting_transcript` to the `source_type` CHECK constraint in a new migration.)
3. `tools/knowledge_lookup.py` docstring update: "...searches uploaded documents AND past meeting transcripts."
4. Citation strings include date for meeting sources (e.g., `"From your May 12 planning meeting"`).
5. **Cap meeting-transcript results to ≤2 in top-5** — transcripts are much longer than docs and would otherwise dominate retrieval. Apply this in `knowledge_service.search_knowledge` after RPC return.

**Acceptance test:** Ask "what did we decide about pricing?" via the bot — answer cites a previous meeting with date.

**Migration:** new SQL file `supabase/knowledge_meeting_source_migration.sql` — `alter table knowledge_docs drop constraint X; alter table ... add constraint X check (source_type in ('pdf','docx','txt','url','notion','gdrive','meeting_transcript'))`.

### Phase 2 — Contextual retrieval (chunk preprocessing) (~2 hours)

**Why second:** highest pure-quality jump per effort (Anthropic benchmarks: ~35–50% retrieval improvement).

1. New module: `backend/knowledge_ingest/context_preprocessor.py`
2. `async def add_context(chunks, doc_name, doc_summary) -> list[dict]` — for each chunk, one Groq call (Llama 3.3 70B, `max_tokens=80`) producing a ~50–100 token contextual preamble: *"From '<doc_name>', section '<heading or "near top">'. <chunk content>"*
3. Call this in `knowledge_service.ingest_doc` **between** chunking and embedding.
4. **Store original content separately from the embedded-with-context version** — citations must show ORIGINAL content to the user, not the preamble:
   ```sql
   alter table knowledge_chunks add column embedded_content text;
   ```
   `content` = what shows in citations; `embedded_content` = what was embedded.
5. Cache by content-hash to avoid recomputation on doc resync (a small in-memory dict is enough for v1).

**Acceptance:** A query like "Q2 budget" surfaces a chunk from page 17 of a 50-page strategy doc that previously fell below the top-5 cutoff — measured against a held-out test set of ~10 queries.

### Phase 3 — Hybrid retrieval (vector + BM25) (~1.5 hours)

**Why:** catches exact-term matches (proper nouns, IDs, version numbers) that embeddings miss.

1. Add Postgres FTS to `knowledge_chunks`:
   ```sql
   alter table knowledge_chunks add column content_tsvector tsvector
     generated always as (to_tsvector('english', content)) stored;
   create index knowledge_chunks_fts_idx on knowledge_chunks using gin(content_tsvector);
   ```
2. Modify `knowledge_service.search_knowledge` to run **vector + BM25 in parallel** via `asyncio.gather`.
3. Normalize both score lists (min–max), fuse: `0.7 * vec + 0.3 * bm25`. Take top 20 for reranker (Phase 4).

**Acceptance:** Query `"PRJ-2547"` (or any specific ID/proper noun) — exact match surfaces in top 3 even though embedding score is low.

### Phase 4 — Reranking with BGE-reranker-v2-m3 (~2 hours)

**Why:** the difference between "decent" and "wow" RAG. Reorders the top-20 by actual query–document relevance, not just embedding similarity.

1. Add to `requirements.txt`: `FlagEmbedding>=1.2.0` (model is ~500MB; downloads on first use).
2. New module: `backend/knowledge_reranker.py` — loads BGE-reranker once at startup, exposes `async def rerank(query, candidates, top_k=5)`.
3. **Preload the model in `main.py` startup hook** so first request doesn't pay the ~5s cold-start cost.
4. Slot between hybrid fusion (top-20) and final return (top-5) in `search_knowledge`.
5. **Run on CPU** (we're on Render free tier). Expect ~100–200ms per query — acceptable in our latency budget.
6. **Important:** the proactive surfacing path (`knowledge_proactive.py`) must NOT use the reranker. Proactive must stay light (~150ms total) — skip reranking there.

**Acceptance:** Set up a small held-out test set (10 query–correct-chunk pairs). Top-1 accuracy should jump noticeably vs. pre-reranker.

### Phase 5 — Query rewriting + streaming response (~1.5 hours)

**Why:** handles terse queries ("Q3?") and follow-ups ("and engineering?"). Plus streams the LLM answer for perceived speed.

1. New helper in `knowledge_service`: `async def maybe_rewrite_query(query, conversation_history=None) -> str`.
2. **Heuristic gate (no LLM call):** skip rewrite if `len(query.split()) >= 5` AND no pronoun referring to a prior turn. Otherwise: one Groq call with prompt *"Rewrite this terse meeting question into a clear standalone question for document search: ..."*.
3. Stream the LLM response back via the existing chat infrastructure — `ChatPanel.jsx` already supports streamed responses.

**Acceptance:** Ask "Q3?" right after a Q2 conversation — rewritten internally to "What is the Q3 budget?", correct answer returned.

---

## 4. Critical constraints (read before coding)

### Latency budget (do not exceed)

| Path | Target |
|---|---|
| On-demand query (no rewrite) | ~800ms to first token |
| On-demand query (with rewrite) | ~950ms to first token |
| Proactive surfacing | ~150ms (must stay light — runs every 20 transcript lines) |

If a phase blows the budget, fix it before merging. Use `asyncio.gather` aggressively. Preload models. Cache embeddings for repeat queries (small LRU on query → vector).

### What you can NOT break

- **The baseline RAG is live in production.** Don't change the `knowledge_search` RPC signature without a careful migration. Don't change existing endpoints' response shapes — only extend.
- **Workspace scoping must keep working.** All new code paths must respect `caller_workspace_ids`.
- **The proactive surfacing path** (`knowledge_proactive.py`) must remain fast. Don't slot the reranker or query rewrite into it.
- **`bot_store` is in-memory** — don't add features that depend on long-lived bot state across restarts. (That's its own deferred-debt item.)

### Code conventions to follow

- All Supabase access via `_supabase()` in `knowledge_service.py` (uses `SUPABASE_KEY` with `SUPABASE_SERVICE_ROLE_KEY` fallback).
- All chunk inserts MUST include `workspace_id` (denormalized from doc).
- All migrations go in `supabase/` as new files (don't edit existing ones).
- Audit-log every query via `knowledge_queries` insert (wrapped in try/except — never break the request).
- Anti-hallucination: strict-grounding instruction + `NO_GROUNDED_ANSWER` fallback + conflict detection — keep these intact.
- Tests in `backend/tests/test_*.py` following the existing pattern.

---

## 5. Verification pattern (how to know each phase actually works)

Before pushing each phase, run a smoke test like the one we used for Phase 0:

```python
# A small async script that:
# 1. Loads .env
# 2. Inserts a test knowledge_docs row with a real user_id (grab one from `meetings` table)
# 3. Calls ingest_doc with synthetic content
# 4. Verifies status went 'ready', chunks count > 0
# 5. Calls search_knowledge with a relevant query — confirms top-1 score is sensible
# 6. Cleans up (delete chunks + doc)
```

Reference template in PRISM_AI_CONTEXT.md "Added May 21" section. Take a screenshot/log of the result and include in your PR description.

---

## 6. Deployment checklist (per phase)

1. Implement + unit test
2. Run local smoke test against real Supabase
3. Verify build passes: `cd frontend && npm run build`
4. Verify backend imports cleanly: `python3 -c "import main"`
5. Add any new deps to `requirements.txt`
6. Add any new migrations to `supabase/` with clear file names
7. Push to `vids_branch`
8. After all 5 phases done: merge `vids_branch` → `main`, watch Render deploy, set any new env vars first

---

## 7. Open design questions for you to decide

These are NOT in the spec — your call:

1. **Embedded-content vs original-content storage** for Phase 2 — I recommend `embedded_content` column. Alternative: regenerate the preamble at query time (no extra column). Latency cost.
2. **BGE reranker model size** — `bge-reranker-v2-m3` is ~500MB. There's a smaller `bge-reranker-base` (~280MB, slightly lower quality). On Render free tier, smaller is safer.
3. **Query rewriting model** — I assumed Groq Llama 3.3 70B (consistent with our chat). Smaller/faster model (e.g., Llama 3.1 8B) would be fine for this single-turn rewrite.
4. **Cross-source ranking** for Phase 1 — I suggested capping meeting-transcript results to ≤2 in top-5. Tunable. Validate against real queries.

Flag these in your PR description so Vidyut can review.

---

## 8. What to do when you're done

After all 5 phases ship:
1. Update `docs/specs/2026-05-20-smart-rag-additions.md` — mark each phase ✅ done with what was actually built (vs spec).
2. Update `PRISM_AI_CONTEXT.md` and `Orinial_Roadmap.md` — Phase 5 → fully complete.
3. Update `CLAUDE.md` knowledge base paragraph with the new pipeline (contextual ingest, hybrid + rerank query path).
4. Smoke-test in production after deploy.

Ping Vidyut after each phase, not just at the end — easier to course-correct early.

---

## 9. Quick reference — key files

| File | What's in it |
|---|---|
| `backend/knowledge_routes.py` | REST endpoints — upload, list, patch, delete, queries audit |
| `backend/knowledge_service.py` | `search_knowledge`, `ingest_doc`, `_supabase()`, quota check |
| `backend/knowledge_proactive.py` | Background surfacing — keep light |
| `backend/embeddings.py` | OpenAI client + quota circuit-breaker |
| `backend/knowledge_ingest/` | Loaders (pdf/docx/txt/url/notion/gdrive) + chunker |
| `backend/tools/knowledge_lookup.py` | LLM-facing retrieval tool |
| `backend/tools/web_search.py` | Tavily fallback tool |
| `supabase/knowledge_migration.sql` | Base knowledge schema (DON'T re-run) |
| `supabase/knowledge_workspace_migration.sql` | Workspace scoping additions (DON'T re-run) |
| `frontend/src/components/KnowledgeBase.jsx` | Library UI |
| `frontend/src/lib/knowledge.js` | API client |

Good luck. Spec doc is the source of truth — when in doubt, reread it.

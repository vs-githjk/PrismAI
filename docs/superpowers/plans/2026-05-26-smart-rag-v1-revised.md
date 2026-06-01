# Smart-RAG v1 (Revised) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patch the 4 audit gaps in the committed Phase 1+2 smart-RAG work and ship Phase 3 (BM25 hybrid retrieval with Reciprocal Rank Fusion). Defer the BGE reranker and query rewriting to post-AWS migration.

**Architecture:** Phase 1 (transcript indexing) and Phase 2 (contextual preprocessing) already exist on `fixed-changes` — this plan adds targeted fixes to the existing files, then adds a BM25 tsvector column + RPC and an RRF-fusion path to `search_knowledge`. Vector-only retrieval remains available via a `hybrid=False` parameter so the existing call sites and tests don't have to change in lockstep.

**Tech Stack:** Python 3.11, FastAPI, asyncio, Supabase (Postgres + pgvector), Groq (Llama 3.3 70B for preambles), OpenAI text-embedding-3-small, unittest + AsyncMock.

**Spec:** [docs/superpowers/specs/2026-05-26-smart-rag-v1-revised.md](../specs/2026-05-26-smart-rag-v1-revised.md)

**Branch:** `fixed-changes`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/storage_routes.py` | modify | Fix #1 — guard `index_meeting_transcript` so only the primary recorder's POST triggers indexing |
| `backend/knowledge_transcript.py` | modify | Fix #2 — quota check; Fix #4 — lightweight inline preamble |
| `backend/knowledge_ingest/context_preprocessor.py` | modify | Fix #3 — `asyncio.Semaphore(8)` around the Groq call |
| `backend/knowledge_service.py` | modify | Phase 3 — `_rrf_merge` helper + hybrid path in `search_knowledge` |
| `supabase/knowledge_bm25_migration.sql` | create | Phase 3 — tsvector column, GIN index, `knowledge_search_bm25` RPC |
| `backend/tests/test_storage_routes_transcript_guard.py` | create | Test Fix #1 |
| `backend/tests/test_knowledge_transcript.py` | modify | Test Fix #2 + Fix #4 |
| `backend/tests/test_context_preprocessor.py` | modify | Test Fix #3 |
| `backend/tests/test_knowledge_service_hybrid.py` | create | Test Phase 3 (RRF + hybrid path) |

---

## Conventions for this plan

- Commit messages: short imperative title + one-line body when context isn't obvious from the diff. **No `Co-Authored-By` trailer** (per project memory).
- Branch: stay on `fixed-changes`. Do not create a feature branch.
- Tests live in `backend/tests/` and run via `python -m pytest backend/tests/ -q` from the repo root, OR via `python -m pytest C:\Users\abhin\PrismAI\backend\tests -q` on Windows where the relative path is finicky in fresh shells.
- After each task: full backend suite must stay green. Treat any pre-existing failure delta as a regression.

---

## Task 1: Fix #1 — Guard transcript indexing for fan-out recipients

**Files:**
- Modify: `backend/storage_routes.py:236-246`
- Create: `backend/tests/test_storage_routes_transcript_guard.py`

**Background.** When a workspace-dedup'd bot records a meeting, the bot owner's frontend AND every dedup'd teammate's frontend each `POST /meetings`. Today every POST fires `asyncio.create_task(index_meeting_transcript(...))`, producing N duplicate `knowledge_docs` rows for one transcript (each on a different `meeting_id`, so the existing idempotency check misses). The recorder is identifiable: when `entry.recorded_by_user_id` is unset, the caller IS the recorder; when it's set and matches `user_id`, same thing; otherwise the caller is a fan-out teammate and should NOT trigger indexing — they get search access via the workspace_id RLS on `knowledge_chunks`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_storage_routes_transcript_guard.py`:

```python
# backend/tests/test_storage_routes_transcript_guard.py
"""Fix #1 — only the primary recorder's POST triggers transcript indexing."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class _FakeClient:
    """Minimal Supabase client double — every chained call returns self,
    .execute() returns MagicMock(data=[]) so save_meeting's inserts succeed."""
    def table(self, _name): return self
    def insert(self, _payload): return self
    def update(self, _payload): return self
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def single(self): return self
    def execute(self): return MagicMock(data=[])


def _entry(*, recorded_by_user_id):
    """Build a MeetingEntry-like object. Avoids importing the real class so
    this test doesn't trip on supabase init at import time."""
    from storage_routes import MeetingEntry
    return MeetingEntry(
        id=42,
        date="2026-05-26T14:00:00",
        title="Planning Meeting",
        score=80,
        transcript="Alice: hi. Bob: hi back.",
        result={},
        share_token="tok",
        workspace_id="ws-123",
        recorded_by_user_id=recorded_by_user_id,
    )


class TranscriptGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_indexes_when_caller_is_primary_recorder(self):
        from storage_routes import save_meeting

        called = []
        async def fake_index(**kwargs):
            called.append(kwargs)

        with patch("storage_routes._supabase_client", lambda: _FakeClient()), \
             patch("storage_routes.index_meeting_transcript",
                   new=AsyncMock(side_effect=fake_index)), \
             patch("storage_routes.asyncio.create_task", side_effect=lambda c: asyncio.ensure_future(c)):
            entry = _entry(recorded_by_user_id=None)
            await save_meeting(entry, user_id="user-A")

        self.assertEqual(len(called), 1)

    async def test_skips_when_caller_is_fanout_recipient(self):
        from storage_routes import save_meeting

        called = []
        async def fake_index(**kwargs):
            called.append(kwargs)

        with patch("storage_routes._supabase_client", lambda: _FakeClient()), \
             patch("storage_routes.index_meeting_transcript",
                   new=AsyncMock(side_effect=fake_index)), \
             patch("storage_routes.asyncio.create_task", side_effect=lambda c: asyncio.ensure_future(c)):
            entry = _entry(recorded_by_user_id="user-A")
            await save_meeting(entry, user_id="user-B")  # user-B is a teammate, NOT the recorder

        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
```

> **Implementer note:** `storage_routes` may expose its Supabase client via a different symbol (e.g. `_supabase`, `client`, or a module-level `supabase`). Open the file and use whatever the existing tests in `backend/tests/test_storage_routes.py` (or the route's own code at line ~210) actually reference. The patch targets in the test above are illustrative — adjust to match the real symbol so the test isolates correctly. The behavior under test is unchanged either way.

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest backend/tests/test_storage_routes_transcript_guard.py -v
```

Expected: `test_skips_when_caller_is_fanout_recipient` FAILS with `AssertionError: [<kwargs>] != []` because today's code fires indexing unconditionally.

- [ ] **Step 3: Apply the guard in storage_routes**

Edit `backend/storage_routes.py`, replacing the unconditional fire-and-forget at lines 236-246 with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest backend/tests/test_storage_routes_transcript_guard.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Run full backend suite for regression**

```
python -m pytest backend/tests/ -q
```

Expected: pass count = 376 baseline + 2 new tests = 378. No new failures.

- [ ] **Step 6: Commit**

```
git add backend/storage_routes.py backend/tests/test_storage_routes_transcript_guard.py
git commit -m "Guard transcript indexing against workspace fan-out duplicates"
```

---

## Task 2: Fix #2 — Quota check in `index_meeting_transcript`

**Files:**
- Modify: `backend/knowledge_transcript.py`
- Modify: `backend/tests/test_knowledge_transcript.py`

**Background.** `index_meeting_transcript` chunks → embeds → inserts without ever calling `check_user_quota`. A ~3-hour transcript at ~500 chunks can blow past the 50k-chunk quota mid-insert, leaving the doc stuck in `status="processing"` with a partial chunk set and the user out of quota. `ingest_doc` handles this correctly; we mirror its shape.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_knowledge_transcript.py` (before `if __name__ == "__main__":`):

```python
    def test_marks_doc_error_when_quota_exceeded(self):
        import importlib, knowledge_transcript, knowledge_service
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()

        async def raise_quota(*_a, **_k):
            raise knowledge_service.QuotaExceeded("over limit")

        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_transcript, "check_user_quota",
                          new=AsyncMock(side_effect=raise_quota)), \
             patch.object(knowledge_transcript, "embed_batch",
                          new=AsyncMock(return_value=[])):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=99,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-26T14:00:00",
                title="Long meeting",
                transcript="word " * 5000,
            ))

        # We should have inserted the doc row, then UPDATED it to status="error".
        # No knowledge_chunks insert should have happened.
        ops = fake_sb.ops
        self.assertIn("knowledge_docs", [t for t, _ in ops])
        self.assertNotIn("knowledge_chunks", [t for t, _ in ops])
        # Find the error update
        error_updates = [
            payload for table, payload in ops
            if table == "knowledge_docs"
            and payload is not None
            and payload[0] == "update"
            and payload[1].get("status") == "error"
        ]
        self.assertEqual(len(error_updates), 1)
        self.assertIn("over limit", error_updates[0][1].get("error_message", ""))
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest backend/tests/test_knowledge_transcript.py::IndexMeetingTranscriptTests::test_marks_doc_error_when_quota_exceeded -v
```

Expected: FAIL — `check_user_quota` not patched correctly because it's not imported by `knowledge_transcript` yet (likely `AttributeError`), OR test passes-but-for-wrong-reason (no error update written). Either way, code change required.

- [ ] **Step 3: Wire quota check into transcript indexing**

Edit `backend/knowledge_transcript.py`:

1. Update the import at the top:

```python
from knowledge_service import _supabase, INSERT_BATCH_SIZE, _execute, check_user_quota, QuotaExceeded
```

2. Insert the quota check between chunking and embedding (after the empty-chunks early return, before `contents = [c["content"] for c in chunks]`):

```python
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

- [ ] **Step 4: Run the new test and the existing ones**

```
python -m pytest backend/tests/test_knowledge_transcript.py -v
```

Expected: all three tests pass.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest backend/tests/ -q
```

Expected: 378 baseline + 1 new = 379 pass, no new failures.

- [ ] **Step 6: Commit**

```
git add backend/knowledge_transcript.py backend/tests/test_knowledge_transcript.py
git commit -m "Add quota check to transcript indexing"
```

---

## Task 3: Fix #4 — Lightweight inline preamble for transcripts

**Files:**
- Modify: `backend/knowledge_transcript.py`
- Modify: `backend/tests/test_knowledge_transcript.py`

**Background.** Today transcript chunks embed raw content (`embedded_content = chunks[i]["content"]`), so they have no contextual preamble. Routing them through `add_context` (Groq) would burn one LLM call per chunk for an essentially-templated string — every preamble would be *"From '{title}', section 'near top'."* since transcripts have no section headings. Instead, build the preamble in-process from `title + date`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_knowledge_transcript.py`:

```python
    def test_embeds_content_with_inline_preamble(self):
        import importlib, knowledge_transcript
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()
        captured_embed_inputs: list[list[str]] = []

        async def fake_embed(texts):
            captured_embed_inputs.append(list(texts))
            return [[0.0] * 1536 for _ in texts]

        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_transcript, "check_user_quota",
                          new=AsyncMock(return_value=None)), \
             patch.object(knowledge_transcript, "embed_batch",
                          new=AsyncMock(side_effect=fake_embed)):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=7,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-26T14:00:00",
                title="Planning Sync",
                transcript="Alice: hi. Bob: hi back. " * 30,
            ))

        # Every embedded string should start with the lightweight preamble.
        self.assertTrue(captured_embed_inputs, "embed_batch was never called")
        for text in captured_embed_inputs[0]:
            self.assertIn("Planning Sync", text)
            self.assertIn("2026-05-26", text)
            # AND it should NOT be a Groq-style preamble (no "section" wording)
            self.assertNotIn("section", text.split(".")[0].lower())
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest backend/tests/test_knowledge_transcript.py::IndexMeetingTranscriptTests::test_embeds_content_with_inline_preamble -v
```

Expected: FAIL — `"Planning Sync"` is not present in the embedded text because today's code embeds raw `content`.

- [ ] **Step 3: Add the inline preamble**

Edit `backend/knowledge_transcript.py`. After the `chunks = chunk_text(...)` line and the empty-chunks early return, before the quota check (Task 2):

```python
        # Lightweight, deterministic preamble. Transcripts have no section
        # headings, so a Groq-generated preamble would just repeat title+date —
        # build it inline and skip the LLM cost.
        preamble = f"From your meeting '{title}' on {(date or '')[:10]}."
        for c in chunks:
            c["embedded_content"] = f"{preamble} {c['content']}"
```

Then update the row-construction dict to use `embedded_content`:

```python
        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "content": chunks[i]["content"],
                "embedded_content": chunks[i]["embedded_content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
```

And update the embedding source list (the line that today reads `contents = [c["content"] for c in chunks]`):

```python
        contents = [c["embedded_content"] for c in chunks]
```

- [ ] **Step 4: Run the new test plus all prior transcript tests**

```
python -m pytest backend/tests/test_knowledge_transcript.py -v
```

Expected: all four tests PASS.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest backend/tests/ -q
```

Expected: 379 baseline + 1 new = 380 pass, no new failures.

- [ ] **Step 6: Commit**

```
git add backend/knowledge_transcript.py backend/tests/test_knowledge_transcript.py
git commit -m "Add lightweight inline preamble to transcript chunks"
```

---

## Task 4: Fix #3 — Bound concurrent Groq calls in `add_context`

**Files:**
- Modify: `backend/knowledge_ingest/context_preprocessor.py`
- Modify: `backend/tests/test_context_preprocessor.py`

**Background.** `add_context` currently calls `asyncio.gather` across every chunk. A 200-chunk PDF triggers 200 simultaneous Groq calls; the rate limiter starts 429-ing and the per-chunk `try/except` silently falls back to raw content, wiping out the contextual benefit for the chunks that lost. A semaphore at 8 is well under Groq's default RPS and keeps a 200-chunk ingestion at ~5s total.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_context_preprocessor.py`:

```python
    def test_bounds_concurrent_llm_calls(self):
        """Fix #3 — concurrent Groq calls should be capped by a semaphore.
        We verify by counting the maximum number of in-flight _llm_preamble
        calls during a 50-chunk ingest. With the semaphore, max in-flight
        must be <= 8."""
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        in_flight = 0
        peak = 0

        async def slow_llm(system, user, **_):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return "From 'Doc.pdf'."

        chunks = [
            {"content": f"chunk {i}", "chunk_index": i, "metadata": {}}
            for i in range(50)
        ]

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=slow_llm)):
            asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Doc.pdf", doc_summary=""
            ))

        self.assertLessEqual(peak, 8,
            f"Concurrent _llm_preamble calls peaked at {peak}; expected <= 8")
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest backend/tests/test_context_preprocessor.py::ContextPreprocessorTests::test_bounds_concurrent_llm_calls -v
```

Expected: FAIL — peak in-flight ≈ 50 because no semaphore is in place.

- [ ] **Step 3: Add the semaphore**

Edit `backend/knowledge_ingest/context_preprocessor.py`. Add the module-level semaphore near the existing `_cache: dict[str, str] = {}` declaration:

```python
# Cap concurrent Groq calls so a big doc doesn't flood the API and get
# rate-limited (every 429 silently degrades to embedding the raw chunk).
# 8 is comfortably under Groq's default RPS for our workload.
_GROQ_SEM = asyncio.Semaphore(8)
```

And wrap the LLM call inside `_preamble_for_chunk` — change:

```python
    try:
        preamble = (await _llm_preamble(doc_name, doc_summary, heading=heading)).strip()
```

to:

```python
    try:
        async with _GROQ_SEM:
            preamble = (await _llm_preamble(doc_name, doc_summary, heading=heading)).strip()
```

- [ ] **Step 4: Run the new test plus existing ones**

```
python -m pytest backend/tests/test_context_preprocessor.py -v
```

Expected: all three tests pass. The new one passes because the semaphore caps peak at 8.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest backend/tests/ -q
```

Expected: 380 baseline + 1 new = 381 pass, no new failures.

- [ ] **Step 6: Commit**

```
git add backend/knowledge_ingest/context_preprocessor.py backend/tests/test_context_preprocessor.py
git commit -m "Cap concurrent Groq preamble calls at 8"
```

---

## Task 5: Phase 3 — BM25 migration file

**Files:**
- Create: `supabase/knowledge_bm25_migration.sql`

**Background.** Phase 3 introduces lexical search via Postgres tsvector. We add a generated column on `knowledge_chunks` so it stays in sync with `embedded_content` automatically, a GIN index for fast `@@` lookups, and a sibling RPC `knowledge_search_bm25` that mirrors `knowledge_search`'s param shape but uses `ts_rank_cd`. Workspace + caller scoping logic is identical to the vector RPC so we don't have two RLS semantics.

- [ ] **Step 1: Write the migration**

Create `supabase/knowledge_bm25_migration.sql`:

```sql
-- supabase/knowledge_bm25_migration.sql
-- Phase 3 of smart-RAG v1: BM25 lexical index over chunks.
-- Run AFTER knowledge_workspace_migration.sql and knowledge_contextual_migration.sql.
-- Apply in the Supabase SQL editor.

-- 1. Generated tsvector column (auto-updated by Postgres on every write).
alter table knowledge_chunks
  add column if not exists content_tsv tsvector
  generated always as (
    to_tsvector('english', coalesce(embedded_content, content))
  ) stored;

-- 2. GIN index for fast `@@` lookups.
create index if not exists knowledge_chunks_tsv_idx
  on knowledge_chunks using gin(content_tsv);

-- 3. Sibling RPC: same caller/workspace scoping as knowledge_search, but
--    BM25 ranking via ts_rank_cd instead of cosine similarity.
drop function if exists knowledge_search_bm25(text, text, uuid[], bigint, int);

create or replace function knowledge_search_bm25(
    query_text text,
    caller_user_id text,
    caller_workspace_ids uuid[],
    meeting_filter bigint,
    match_limit int
)
returns table (
    id uuid,
    doc_id uuid,
    content text,
    embedded_content text,
    metadata jsonb,
    chunk_index int,
    doc_name text,
    source_type text,
    score float,
    match_type text
)
language sql stable
as $$
    select
        c.id,
        c.doc_id,
        c.content,
        c.embedded_content,
        c.metadata,
        c.chunk_index,
        d.name as doc_name,
        d.source_type,
        ts_rank_cd(c.content_tsv, plainto_tsquery('english', query_text))::float as score,
        'bm25'::text as match_type
    from knowledge_chunks c
    join knowledge_docs d on d.id = c.doc_id
    where d.deleted_at is null
      and (
        c.user_id = caller_user_id
        or d.workspace_id = any(caller_workspace_ids)
      )
      and (meeting_filter is null or d.meeting_id = meeting_filter)
      and c.content_tsv @@ plainto_tsquery('english', query_text)
    order by score desc
    limit match_limit;
$$;
```

- [ ] **Step 2: Verify the file parses (syntax-level only — actual apply is manual)**

```
python -c "open('supabase/knowledge_bm25_migration.sql').read()"
```

Expected: no error. (Full validation happens when Abhinav applies it via the Supabase SQL editor — Task 8.)

- [ ] **Step 3: Commit**

```
git add supabase/knowledge_bm25_migration.sql
git commit -m "Add BM25 tsvector migration for hybrid retrieval"
```

---

## Task 6: Phase 3 — `_rrf_merge` helper

**Files:**
- Modify: `backend/knowledge_service.py`
- Create: `backend/tests/test_knowledge_service_hybrid.py`

**Background.** Reciprocal Rank Fusion combines two ranked lists by summing `1/(k_rrf + rank)` per document. Because it's rank-based, it doesn't care that cosine ∈ [0,1] and BM25 scores are unbounded — eliminating the brittle normalization step from the original plan. Standard `k_rrf = 60`.

- [ ] **Step 1: Write failing unit tests**

Create `backend/tests/test_knowledge_service_hybrid.py`:

```python
# backend/tests/test_knowledge_service_hybrid.py
"""Phase 3 — RRF merge + hybrid search path."""
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class RRFMergeTests(unittest.TestCase):
    def test_combines_two_rankings(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}, {"id": "c", "score": 0.7}]
        bm25 = [{"id": "b", "score": 5.0}, {"id": "d", "score": 4.0}, {"id": "a", "score": 3.0}]
        merged = _rrf_merge(vec, bm25, k_rrf=60)

        ids = [r["id"] for r in merged]
        # `b` appears in both lists at rank 2 (vec) and rank 1 (bm25) → highest fused score
        self.assertEqual(ids[0], "b")
        # `a` appears at rank 1 (vec) and rank 3 (bm25) → second highest
        self.assertEqual(ids[1], "a")
        # `c` and `d` each appear once; `c` at rank 3 (vec) vs `d` at rank 2 (bm25)
        # → d outranks c (1/(60+2) > 1/(60+3))
        self.assertEqual(ids[2], "d")
        self.assertEqual(ids[3], "c")

    def test_handles_empty_branch(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a"}, {"id": "b"}]
        merged_v_only = _rrf_merge(vec, [])
        self.assertEqual([r["id"] for r in merged_v_only], ["a", "b"])

        merged_bm_only = _rrf_merge([], vec)
        self.assertEqual([r["id"] for r in merged_bm_only], ["a", "b"])

        merged_both_empty = _rrf_merge([], [])
        self.assertEqual(merged_both_empty, [])

    def test_overwrites_score_with_fused(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a", "score": 0.9}]
        bm25 = [{"id": "a", "score": 5.0}]
        merged = _rrf_merge(vec, bm25, k_rrf=60)

        self.assertEqual(merged[0]["match_type"], "hybrid")
        # Fused score = 1/(60+1) + 1/(60+1) ≈ 0.0328
        self.assertAlmostEqual(merged[0]["score"], 2 * (1 / 61), places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest backend/tests/test_knowledge_service_hybrid.py::RRFMergeTests -v
```

Expected: all three FAIL with `ImportError: cannot import name '_rrf_merge'`.

- [ ] **Step 3: Add the helper to `knowledge_service.py`**

Edit `backend/knowledge_service.py`. Add this helper above `async def search_knowledge`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest backend/tests/test_knowledge_service_hybrid.py::RRFMergeTests -v
```

Expected: all three PASS.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest backend/tests/ -q
```

Expected: 381 baseline + 3 new = 384 pass.

- [ ] **Step 6: Commit**

```
git add backend/knowledge_service.py backend/tests/test_knowledge_service_hybrid.py
git commit -m "Add Reciprocal Rank Fusion helper for hybrid retrieval"
```

---

## Task 7: Phase 3 — Hybrid path in `search_knowledge`

**Files:**
- Modify: `backend/knowledge_service.py`
- Modify: `backend/tests/test_knowledge_service_hybrid.py`

**Background.** Wire `_rrf_merge` into `search_knowledge` behind a `hybrid: bool = True` parameter. The vector-only path stays available so existing call sites that depend on raw cosine `min_score` semantics keep working unchanged. `min_score` is applied to the vector branch only — BM25 has no analogous threshold.

- [ ] **Step 1: Write failing integration tests**

Append to `backend/tests/test_knowledge_service_hybrid.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class SearchKnowledgeHybridTests(unittest.TestCase):
    def _patched_search(self, vec_rows, bm25_rows, hybrid):
        """Call search_knowledge with both RPCs faked. Returns the merged rows."""
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        # Fake supabase client whose .rpc(name, params).execute() returns the
        # appropriate row list based on RPC name.
        def fake_rpc(name, params):
            class _Q:
                def execute(self_inner):
                    if name == "knowledge_search":
                        return MagicMock(data=list(vec_rows))
                    if name == "knowledge_search_bm25":
                        return MagicMock(data=list(bm25_rows))
                    raise AssertionError(f"Unexpected RPC: {name}")
            return _Q()

        fake_sb = MagicMock()
        fake_sb.rpc = MagicMock(side_effect=fake_rpc)

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.0] * 1536)), \
             patch.object(knowledge_service, "get_user_workspace_ids",
                          new=lambda *_a, **_k: []):
            return asyncio.run(knowledge_service.search_knowledge(
                query="quarterly revenue", user_id="user-1",
                k=5, hybrid=hybrid,
            ))

    def test_hybrid_calls_both_rpcs_and_merges(self):
        vec = [
            {"id": "a", "doc_id": "d1", "score": 0.91, "source_type": "pdf"},
            {"id": "b", "doc_id": "d2", "score": 0.85, "source_type": "pdf"},
        ]
        bm25 = [
            {"id": "b", "doc_id": "d2", "score": 5.2, "source_type": "pdf"},
            {"id": "c", "doc_id": "d3", "score": 4.1, "source_type": "pdf"},
        ]
        rows = self._patched_search(vec, bm25, hybrid=True)
        ids = [r["id"] for r in rows]
        # `b` is the only doc in both lists → ranks first
        self.assertEqual(ids[0], "b")
        # match_type should be "hybrid"
        self.assertEqual(rows[0]["match_type"], "hybrid")

    def test_hybrid_false_preserves_vector_only_behavior(self):
        vec = [
            {"id": "a", "doc_id": "d1", "score": 0.91, "source_type": "pdf"},
            {"id": "b", "doc_id": "d2", "score": 0.85, "source_type": "pdf"},
        ]
        # If hybrid=False, the bm25 list should never be touched.
        rows = self._patched_search(vec, [], hybrid=False)
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, ["a", "b"])
        # Vector-only path leaves score untouched (raw cosine)
        self.assertEqual(rows[0]["score"], 0.91)

    def test_transcript_cap_applies_in_hybrid_path(self):
        vec = [
            {"id": "t1", "doc_id": "d-t1", "score": 0.95, "source_type": "meeting_transcript"},
            {"id": "t2", "doc_id": "d-t2", "score": 0.94, "source_type": "meeting_transcript"},
            {"id": "t3", "doc_id": "d-t3", "score": 0.93, "source_type": "meeting_transcript"},
            {"id": "p1", "doc_id": "d-p1", "score": 0.92, "source_type": "pdf"},
            {"id": "p2", "doc_id": "d-p2", "score": 0.91, "source_type": "pdf"},
        ]
        rows = self._patched_search(vec, [], hybrid=True)
        transcript_count = sum(1 for r in rows if r.get("source_type") == "meeting_transcript")
        # At most 2 transcripts in the top-k (existing cap behavior)
        self.assertLessEqual(transcript_count, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest backend/tests/test_knowledge_service_hybrid.py::SearchKnowledgeHybridTests -v
```

Expected: all three FAIL — `search_knowledge` doesn't accept `hybrid=` yet (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Rewrite `search_knowledge`**

Open `backend/knowledge_service.py`. Locate the existing `async def search_knowledge` and replace its body with the version below. The signature gains a `hybrid: bool = True` parameter; everything else (signature defaults, return shape, transcript cap, conflict marker) stays compatible.

```python
async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
    hybrid: bool = True,
) -> list[dict]:
    """Embed query, run pgvector + (optionally) BM25, fuse with RRF, return matches.

    Args:
        hybrid: When True (default), runs both vector and BM25 searches in
            parallel and fuses with Reciprocal Rank Fusion. When False, keeps
            the original vector-only behavior — `min_score` is applied as a
            raw cosine threshold in the RPC and the returned `score` field is
            the raw cosine similarity.
    """
    sb = _supabase()
    # meetings.id is bigint; coerce string IDs so PostgREST doesn't bounce them.
    meeting_filter: Optional[int]
    try:
        meeting_filter = int(meeting_id) if meeting_id not in (None, "") else None
    except (TypeError, ValueError):
        meeting_filter = None
    workspace_ids = get_user_workspace_ids(sb, user_id)

    if not hybrid:
        # Vector-only path — preserves raw cosine `min_score` semantics.
        query_vec = await embed_text(query)
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
    else:
        # Hybrid path — vector + BM25 in parallel, RRF-fused.
        # Wider top-N (30) per branch so RRF has enough candidates to work with.
        query_vec = await embed_text(query)
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
                    "query_text": query,
                    "caller_user_id": user_id,
                    "caller_workspace_ids": workspace_ids,
                    "meeting_filter": meeting_filter,
                    "match_limit": 30,
                },
            )),
        )
        rows = _rrf_merge(vec_resp.data or [], bm25_resp.data or [])[: k * 3]

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

    if len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True
    # TODO(post-AWS): rerank `rows` here with BGE once we have the RAM headroom.
    return rows
```

- [ ] **Step 4: Run the new hybrid tests**

```
python -m pytest backend/tests/test_knowledge_service_hybrid.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest backend/tests/ -q
```

Expected: 384 baseline + 3 new = 387 pass, no new failures.

> **Implementer note:** The existing `test_knowledge_service.py` may have tests that mock the Supabase `.rpc()` call and expect exactly one RPC invocation. With `hybrid=True` as the default, those mocks will now see two RPC calls. If any such test breaks, the correct fix is to pass `hybrid=False` to those callers (they're testing the vector-only path) — do NOT lower `hybrid`'s default to keep them green.

- [ ] **Step 6: Commit**

```
git add backend/knowledge_service.py backend/tests/test_knowledge_service_hybrid.py
git commit -m "Add hybrid vector+BM25 search with RRF fusion"
```

---

## Task 8: Apply migration in Supabase + end-to-end smoke check

**Files:** none (manual)

**Background.** The BM25 RPC must exist in the live database before the hybrid path produces useful results. Apply the migration manually in the Supabase SQL editor (matches the project's existing migration workflow — `CLAUDE.md` documents the same pattern for the prior migrations).

- [ ] **Step 1: Apply migration**

In the Supabase SQL editor, paste and run the contents of `supabase/knowledge_bm25_migration.sql`. Expect: `ALTER TABLE`, `CREATE INDEX`, `DROP FUNCTION` (likely no-op if not present), `CREATE FUNCTION` — all green. The generated column backfills automatically because it's `STORED` and Postgres computes it from existing rows.

- [ ] **Step 2: Verify the index exists**

In the SQL editor:

```sql
select indexname from pg_indexes where tablename = 'knowledge_chunks';
```

Expected: includes `knowledge_chunks_tsv_idx`.

- [ ] **Step 3: Verify the RPC exists**

```sql
select proname from pg_proc where proname = 'knowledge_search_bm25';
```

Expected: one row.

- [ ] **Step 4: Smoke test the RPC directly**

```sql
select id, doc_name, source_type, score
from knowledge_search_bm25(
    'meeting',                   -- query_text
    '<your user_id>',            -- caller_user_id
    ARRAY[]::uuid[],             -- caller_workspace_ids
    null,                        -- meeting_filter
    5                            -- match_limit
);
```

Replace `<your user_id>` with a real user id from your auth (any row from `meetings`). Expected: a handful of rows OR an empty result if you have no docs whose tsvector matches `'meeting'`. Either is fine — what matters is no error.

- [ ] **Step 5: End-to-end smoke (optional but recommended)**

1. Start the backend: `cd backend && uvicorn main:app --reload --port 8000`
2. From the frontend (or any auth'd client), trigger a knowledge query whose answer is likely to live in a transcript. Watch the backend logs: you should see two RPC requests fire in parallel for each search.
3. Confirm the returned citations cover both `pdf`/`docx` and `meeting_transcript` sources where relevant.

- [ ] **Step 6: Mark plan complete**

If everything above passed, this plan is done. Update any TodoWrite tracking and move on.

---

## Self-review notes (for reference)

- Every spec requirement maps to a task: Fix #1 → Task 1; Fix #2 → Task 2; Fix #4 → Task 3; Fix #3 → Task 4; migration → Task 5; RRF → Task 6; hybrid path → Task 7; deploy + smoke → Task 8.
- Method names are stable across tasks: `_rrf_merge`, `search_knowledge(hybrid=True)`, `knowledge_search_bm25` RPC.
- The deferred reranker has a single insertion point (a TODO comment in `search_knowledge` after the conflict-marker block) so the post-AWS follow-up doesn't require refactoring.
- No placeholder steps. Every code step contains the full code an implementer should write.

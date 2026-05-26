# Smart RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phases 1–5 of the Smart RAG spec — cross-source unification (meeting transcripts as a knowledge source), contextual preprocessing, hybrid vector+BM25 retrieval, BGE reranking, and query rewriting — on top of the already-shipped Phase 0 (workspace-scoped baseline RAG).

**Architecture:** Extend the existing pgvector pipeline in `backend/knowledge_service.py` without breaking its signature. New stages slot into ingest (contextual preamble before embed) and query (BM25 in parallel with vector, fuse, rerank, optional query rewrite). Meeting transcripts get treated as a new `source_type` and flow through the same ingest path. Each phase ships independently — stop after any phase and the system still works.

**Tech Stack:** Python 3.12 + FastAPI, Supabase (Postgres + pgvector + tsvector), OpenAI `text-embedding-3-small`, Groq Llama 3.3 70B, FlagEmbedding `bge-reranker-base` (smaller variant — see Phase 4 rationale).

**Spec source of truth:** `docs/specs/2026-05-20-smart-rag-additions.md`
**Teammate brief (additional context):** `docs/briefs/2026-05-23-smart-rag-handoff.md` (on `origin/vids_branch` only — read via `git show origin/vids_branch:docs/briefs/2026-05-23-smart-rag-handoff.md`)
**Working branch:** `fixed-changes` (per user direction — couples smart-RAG with the recording-playback work already on this branch)

---

## Pre-work: orientation and environment

- [ ] **Step P1: Read these three files end-to-end before touching code**

  1. `docs/specs/2026-05-20-smart-rag-additions.md` (the spec)
  2. `CLAUDE.md` → section "Knowledge Base / RAG"
  3. `backend/knowledge_service.py` (the file every phase touches)

- [ ] **Step P2: Verify backend imports cleanly**

  Run from repo root:
  ```bash
  cd backend && python -c "import main"
  ```
  Expected: no exception. If imports fail, fix before proceeding (Phase 4 will add a heavy dep and you want a clean baseline).

- [ ] **Step P3: Verify required env vars are present**

  Confirm `backend/.env` contains `OPENAI_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (service-role) or `SUPABASE_SERVICE_ROLE_KEY`. If any are missing, the smoke tests at each phase boundary will fail.

- [ ] **Step P4: Run the existing test suite as a baseline**

  ```bash
  cd backend && python -m pytest tests/ -x -q
  ```
  Expected: clean pass (the recent commit `b5557db` fixed 16 stale failures, so this should now be green). Take note of the count — every phase must keep it green.

---

## File Structure (what gets created or modified)

**New files:**
- `supabase/knowledge_meeting_source_migration.sql` — Phase 1 (add `meeting_transcript` to source_type CHECK constraint)
- `supabase/knowledge_contextual_migration.sql` — Phase 2 (add `embedded_content` column)
- `supabase/knowledge_hybrid_migration.sql` — Phase 3 (add `content_tsvector` + GIN index + new `knowledge_search_hybrid` RPC)
- `backend/knowledge_ingest/context_preprocessor.py` — Phase 2 (Groq-backed preamble generation)
- `backend/knowledge_reranker.py` — Phase 4 (BGE-reranker wrapper)
- `backend/knowledge_transcript.py` — Phase 1 (transcript indexing entry-point — keeps storage_routes.py thin)
- `backend/tests/test_knowledge_transcript.py` — Phase 1
- `backend/tests/test_context_preprocessor.py` — Phase 2
- `backend/tests/test_hybrid_search.py` — Phase 3
- `backend/tests/test_knowledge_reranker.py` — Phase 4
- `backend/tests/test_query_rewrite.py` — Phase 5

**Modified files:**
- `backend/knowledge_service.py` — Phases 2, 3, 4, 5 (the orchestration hub)
- `backend/storage_routes.py` — Phase 1 (trigger transcript indexing on `POST /meetings`)
- `backend/main.py` — Phase 4 (preload reranker in `lifespan`)
- `backend/tools/knowledge_lookup.py` — Phase 1 (docstring update for citation formatting)
- `backend/requirements.txt` — Phase 4 (add `FlagEmbedding`)
- `CLAUDE.md` — final cleanup (document the new pipeline)
- `docs/specs/2026-05-20-smart-rag-additions.md` — final cleanup (mark phases done)

**Responsibility split:**
- `knowledge_service.py` stays the single orchestration entry-point — `search_knowledge`, `ingest_doc`, query rewrite, hybrid fusion call out to specialized modules but the public API doesn't change.
- `knowledge_reranker.py`, `context_preprocessor.py`, `knowledge_transcript.py` each have one clear job; they're easy to delete or swap.

---

# Phase 1 — Cross-source unification: index meeting transcripts

**Goal:** After a meeting is saved, its transcript is chunked, embedded, and inserted into `knowledge_chunks` with `source_type='meeting_transcript'`. The bot's `knowledge_lookup` tool now retrieves from docs AND past meetings, with citations that include the meeting date.

**Why this scope is right:** the existing ingest pipeline already chunks+embeds+inserts; we add a thin entry-point that wires a transcript through it and a CHECK constraint update. No changes to retrieval ranking yet — that comes in Phases 3–4.

### Task 1.1: SQL migration — allow `meeting_transcript` as a source type

**Files:**
- Create: `supabase/knowledge_meeting_source_migration.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/knowledge_meeting_source_migration.sql
-- Allow 'meeting_transcript' as a knowledge_docs source_type.
-- Run in Supabase SQL editor AFTER knowledge_workspace_migration.sql.

alter table knowledge_docs
  drop constraint if exists knowledge_docs_source_type_check;

alter table knowledge_docs
  add constraint knowledge_docs_source_type_check
  check (source_type in ('pdf', 'docx', 'txt', 'url', 'notion', 'gdrive', 'meeting_transcript'));
```

- [ ] **Step 2: Run the migration manually in Supabase SQL editor**

  Open Supabase → SQL Editor → paste the file contents → Run. Expected: "Success. No rows returned." A second run is a no-op (the `if exists` guard).

- [ ] **Step 3: Verify the constraint accepted**

  In the same SQL editor:
  ```sql
  select consrc from pg_constraint where conname = 'knowledge_docs_source_type_check';
  ```
  Expected: a row containing `meeting_transcript` in the list. (On newer Postgres versions `consrc` is deprecated; use `pg_get_constraintdef(oid)` instead.)

- [ ] **Step 4: Commit the migration file**

```bash
git add supabase/knowledge_meeting_source_migration.sql
git commit -m "Add meeting_transcript to knowledge_docs source_type CHECK"
```

### Task 1.2: Transcript indexing module — write the failing test first

**Files:**
- Create: `backend/tests/test_knowledge_transcript.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_transcript.py
import asyncio
import sys
import types
import unittest
import uuid
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


class _FakeQuery:
    def __init__(self, sink):
        self.sink = sink
        self._table = None
        self._payload = None
    def table(self, name):
        self._table = name
        return self
    def insert(self, payload):
        self._payload = ("insert", payload)
        return self
    def update(self, payload):
        self._payload = ("update", payload)
        return self
    def select(self, *_a, **_k):
        return self
    def eq(self, *_a, **_k):
        return self
    def single(self):
        return self
    def execute(self):
        self.sink.append((self._table, self._payload))
        return MagicMock(data={"id": "fake-doc-id"})


class _FakeSupabase:
    def __init__(self):
        self.ops = []
    def table(self, name):
        q = _FakeQuery(self.ops)
        q._table = name
        return q


class IndexMeetingTranscriptTests(unittest.TestCase):
    def test_creates_doc_row_and_indexes_chunks(self):
        import importlib, knowledge_transcript
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()

        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_transcript, "embed_batch",
                          new=AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=42,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-25T14:00:00",
                title="Planning Meeting",
                transcript="Alice: hello. Bob: hi back. " * 30,
            ))

        # Should have inserted into knowledge_docs and knowledge_chunks
        tables_touched = [op[0] for op in fake_sb.ops]
        self.assertIn("knowledge_docs", tables_touched)
        self.assertIn("knowledge_chunks", tables_touched)

    def test_skips_empty_transcript(self):
        import importlib, knowledge_transcript
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()
        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=42,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-25T14:00:00",
                title="Empty",
                transcript="",
            ))
        self.assertEqual(fake_sb.ops, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd backend && python -m pytest tests/test_knowledge_transcript.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_transcript'`.

### Task 1.3: Implement the transcript indexing module

**Files:**
- Create: `backend/knowledge_transcript.py`

- [ ] **Step 1: Write the minimal implementation**

```python
# backend/knowledge_transcript.py
"""Index a finished meeting's transcript into knowledge_chunks so it can be
searched alongside uploaded documents. Called from storage_routes.save_meeting
as a fire-and-forget background task."""

import uuid

from embeddings import embed_batch, QuotaExhausted
from knowledge_ingest.chunker import chunk_text
from knowledge_service import _supabase, INSERT_BATCH_SIZE, _execute


def _meeting_doc_name(date: str, title: str) -> str:
    """Stable display name shown in citations."""
    day = (date or "")[:10] or "unknown date"
    base = (title or "").strip() or "Meeting"
    return f"{base} ({day})"


async def index_meeting_transcript(
    meeting_id: int,
    user_id: str,
    workspace_id: str | None,
    date: str,
    title: str,
    transcript: str,
) -> None:
    """Chunk → embed → insert. Idempotent on meeting_id (skips if a doc row
    already exists for this meeting). Errors are swallowed and logged — this
    runs in the background and must not crash the calling request."""
    if not transcript or not transcript.strip():
        return

    sb = _supabase()
    try:
        existing = await _execute(
            sb.table("knowledge_docs")
            .select("id")
            .eq("meeting_id", meeting_id)
            .eq("source_type", "meeting_transcript")
        )
        if existing.data:
            return

        doc_id = str(uuid.uuid4())
        doc_name = _meeting_doc_name(date, title)
        await _execute(
            sb.table("knowledge_docs").insert({
                "id": doc_id,
                "user_id": user_id,
                "meeting_id": meeting_id,
                "workspace_id": workspace_id,
                "name": doc_name,
                "source_type": "meeting_transcript",
                "sensitivity": "internal",
                "status": "processing",
            })
        )

        chunks = chunk_text(transcript, base_metadata={"date": date, "title": title})
        if not chunks:
            await _execute(
                sb.table("knowledge_docs")
                .update({"status": "ready", "chunk_count": 0})
                .eq("id", doc_id)
            )
            return

        contents = [c["content"] for c in chunks]
        try:
            vectors = await embed_batch(contents)
        except QuotaExhausted:
            await _execute(
                sb.table("knowledge_docs")
                .update({"status": "error", "error_message": "OpenAI quota exhausted"})
                .eq("id", doc_id)
            )
            return

        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "content": chunks[i]["content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            await _execute(
                sb.table("knowledge_chunks").insert(rows[i : i + INSERT_BATCH_SIZE])
            )

        await _execute(
            sb.table("knowledge_docs")
            .update({"status": "ready", "chunk_count": len(rows)})
            .eq("id", doc_id)
        )

    except Exception as exc:
        print(f"[transcript-index] meeting {meeting_id} failed: {exc}")
```

- [ ] **Step 2: Run the tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_knowledge_transcript.py -v
```
Expected: both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/knowledge_transcript.py backend/tests/test_knowledge_transcript.py
git commit -m "Add meeting-transcript indexing module (Phase 1)"
```

### Task 1.4: Trigger transcript indexing on POST /meetings

**Files:**
- Modify: `backend/storage_routes.py:212-235` (the `save_meeting` endpoint)

- [ ] **Step 1: Update `save_meeting` to fire the background task**

  Open `backend/storage_routes.py`. At the top of the file, add (alongside the other top-level imports):

```python
from knowledge_transcript import index_meeting_transcript
```

  Then replace the body of `save_meeting` (lines 212–235) with:

```python
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
        "recorded_by_user_id": entry.recorded_by_user_id or None,
    }).execute()

    if entry.workspace_id:
        actual_recorder = entry.recorded_by_user_id or user_id
        asyncio.create_task(_fan_out_to_workspace(client, entry, actual_recorder, entry.workspace_id))

    # Index the transcript for cross-source RAG. Fire-and-forget — failures are
    # logged in index_meeting_transcript itself and must not block the save.
    indexer_user = entry.recorded_by_user_id or user_id
    asyncio.create_task(index_meeting_transcript(
        meeting_id=entry.id,
        user_id=indexer_user,
        workspace_id=entry.workspace_id or None,
        date=entry.date,
        title=entry.title,
        transcript=entry.transcript,
    ))

    return {"ok": True}
```

- [ ] **Step 2: Verify the backend still imports**

```bash
cd backend && python -c "import main"
```
Expected: no exception.

- [ ] **Step 3: Run the full test suite**

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: same green count as the baseline from Step P4 (the new tests add to the count).

- [ ] **Step 4: Commit**

```bash
git add backend/storage_routes.py
git commit -m "Trigger transcript indexing on POST /meetings (Phase 1)"
```

### Task 1.5: Update the `knowledge_lookup` tool docstring + citation hint

**Files:**
- Modify: `backend/tools/knowledge_lookup.py:83-88` (the `register_tool` description)

- [ ] **Step 1: Update the tool description**

  Replace the `description` argument in the `register_tool(...)` call at the bottom of the file with:

```python
    description=(
        "Look up information in the user's knowledge base — uploaded documents "
        "(PDFs, DOCX, web pages, Notion, Google Drive) AND past meeting transcripts. "
        "Use this FIRST when the user asks a factual question that might be in their "
        "documents or something discussed in a previous meeting. Returns matched "
        "content with source citations (including meeting dates when relevant). "
        "If no match, falls back to web_search."
    ),
```

- [ ] **Step 2: Update the strict-grounding instruction so citations include the date for meeting sources**

  Replace the `STRICT_INSTRUCTION` constant at the top of `backend/tools/knowledge_lookup.py`:

```python
STRICT_INSTRUCTION = (
    "Answer ONLY using the content in `matches` above. "
    "When you answer, cite the source by saying \"According to {doc_name}: ...\". "
    "For sources where `source_type` is `meeting_transcript`, phrase the citation "
    "as \"From your meeting on {date from doc_name}: ...\". "
    "If the matches do not contain the answer, respond with exactly the token "
    "NO_GROUNDED_ANSWER so the system can fall back to web_search. "
    "Do not synthesize, infer, or guess beyond the provided content."
)
```

- [ ] **Step 3: Commit**

```bash
git add backend/tools/knowledge_lookup.py
git commit -m "Update knowledge_lookup tool to cite meeting transcripts (Phase 1)"
```

### Task 1.6: Cap meeting-transcript share in the top-k results

**Files:**
- Modify: `backend/knowledge_service.py:74-113` (the `search_knowledge` function)

  Meeting transcripts are much longer than docs and dominate results without this cap. Implementation: post-filter the RPC response.

- [ ] **Step 1: Add the cap**

  In `backend/knowledge_service.py`, replace the body of `search_knowledge` (the part starting after `rows = resp.data or []`) with:

```python
    rows = resp.data or []

    # Cap meeting-transcript results to <= 2 in top-k. Transcripts are much
    # longer than docs and otherwise dominate retrieval. Tunable.
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
    return rows
```

- [ ] **Step 2: Add a unit test for the cap**

  Append to `backend/tests/test_knowledge_service.py` (at the end of the file, inside `KnowledgeServiceTests`):

```python
    def test_search_caps_transcript_results(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        rows = [
            {"chunk_id": "1", "doc_id": "d1", "doc_name": "Mtg A (2026-05-01)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.95},
            {"chunk_id": "2", "doc_id": "d2", "doc_name": "Mtg B (2026-05-02)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.94},
            {"chunk_id": "3", "doc_id": "d3", "doc_name": "Mtg C (2026-05-03)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.93},
            {"chunk_id": "4", "doc_id": "d4", "doc_name": "Budget.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.92},
        ]
        fake_sb = _FakeSupabase({"rpc:knowledge_search": rows})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.1] * 1536)):
            matches = asyncio.run(knowledge_service.search_knowledge(
                "anything", str(uuid.uuid4()), k=5
            ))

        # At most 2 meeting_transcript results, then PDFs fill remaining slots
        transcripts = [m for m in matches if m["source_type"] == "meeting_transcript"]
        self.assertLessEqual(len(transcripts), 2)
        self.assertEqual(matches[-1]["source_type"], "pdf")
```

- [ ] **Step 3: Run the test**

```bash
cd backend && python -m pytest tests/test_knowledge_service.py -v
```
Expected: all tests PASS (the new `test_search_caps_transcript_results` included).

- [ ] **Step 4: Commit**

```bash
git add backend/knowledge_service.py backend/tests/test_knowledge_service.py
git commit -m "Cap meeting-transcript results to 2 per query (Phase 1)"
```

### Task 1.7: Phase 1 smoke test (manual)

**Files:**
- None — manual verification

- [ ] **Step 1: Start the backend locally**

```bash
cd backend && uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Save a meeting with a real transcript via the existing `POST /meetings` flow**

  Easiest path: open the frontend (`cd frontend && npm run dev`), paste any non-trivial transcript into the manual-input UI, and click Analyze. The frontend will hit `/analyze-stream` then `/meetings` to save.

- [ ] **Step 3: Verify a `knowledge_docs` row was created**

  In Supabase SQL editor:
  ```sql
  select id, name, source_type, status, chunk_count, meeting_id, workspace_id, created_at
  from knowledge_docs
  where source_type = 'meeting_transcript'
  order by created_at desc
  limit 5;
  ```
  Expected: 1 row, `status = 'ready'`, `chunk_count > 0`.

- [ ] **Step 4: Query via the bot's path (or directly via Python)**

  Quick Python check (from `backend/`):
  ```python
  import asyncio, os
  from dotenv import load_dotenv; load_dotenv()
  from knowledge_service import search_knowledge
  matches = asyncio.run(search_knowledge(
      "what did we discuss", "<your-user-id-from-meetings-table>", k=5))
  for m in matches: print(m["source_type"], m["doc_name"], m["score"])
  ```
  Expected: at least one row where `source_type == 'meeting_transcript'`.

- [ ] **Step 5: Phase 1 STOP — commit checkpoint**

  At this point the system ships independently. The bot answers "what did we decide…?" with citations including meeting dates.

---

# Phase 2 — Contextual retrieval (chunk preprocessing)

**Goal:** Before embedding, prepend each chunk with a Groq-generated context preamble ("From '<doc_name>', section '<heading>'. <chunk content>") so the embedding captures the chunk's role in its document. The original chunk content is preserved separately for citations.

### Task 2.1: SQL migration — add `embedded_content` column

**Files:**
- Create: `supabase/knowledge_contextual_migration.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/knowledge_contextual_migration.sql
-- Phase 2: store original content separately from the embedded-with-preamble version.
-- Citations show ORIGINAL content; embeddings are generated from the preamble + content.
-- Run AFTER knowledge_meeting_source_migration.sql.

alter table knowledge_chunks
  add column if not exists embedded_content text;

-- Backfill: for existing chunks (which were embedded without a preamble),
-- embedded_content equals content. Future inserts will set it explicitly.
update knowledge_chunks
  set embedded_content = content
  where embedded_content is null;
```

- [ ] **Step 2: Run the migration in Supabase SQL editor**

  Expected: "Success" + a row count for the UPDATE matching the existing chunk count.

- [ ] **Step 3: Commit the migration file**

```bash
git add supabase/knowledge_contextual_migration.sql
git commit -m "Add embedded_content column for contextual preprocessing (Phase 2)"
```

### Task 2.2: Context preprocessor — write the failing test first

**Files:**
- Create: `backend/tests/test_context_preprocessor.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_context_preprocessor.py
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class ContextPreprocessorTests(unittest.TestCase):
    def test_prepends_context_to_each_chunk(self):
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        chunks = [
            {"content": "Q2 budget allocation is $120k.", "chunk_index": 0, "metadata": {"page": 1}},
            {"content": "Q3 will scale up to $200k.", "chunk_index": 1, "metadata": {"page": 2}},
        ]

        async def fake_llm(system, user, **_):
            return "From 'Budget.pdf', section 'Budget Allocation'."

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=fake_llm)):
            result = asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Budget.pdf", doc_summary="Annual budget overview."
            ))

        # Original content preserved
        self.assertEqual(result[0]["content"], "Q2 budget allocation is $120k.")
        # embedded_content has preamble prepended
        self.assertIn("Budget.pdf", result[0]["embedded_content"])
        self.assertIn("Q2 budget allocation is $120k.", result[0]["embedded_content"])
        # Same for second chunk
        self.assertIn("Q3 will scale up to $200k.", result[1]["embedded_content"])

    def test_falls_back_to_content_when_llm_fails(self):
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        chunks = [{"content": "Q2 budget.", "chunk_index": 0, "metadata": {}}]

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=RuntimeError("llm down"))):
            result = asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Budget.pdf", doc_summary=""
            ))

        # On failure, embedded_content falls back to the original content
        self.assertEqual(result[0]["embedded_content"], "Q2 budget.")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd backend && python -m pytest tests/test_context_preprocessor.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_ingest.context_preprocessor'`.

### Task 2.3: Implement the context preprocessor

**Files:**
- Create: `backend/knowledge_ingest/context_preprocessor.py`

- [ ] **Step 1: Write the minimal implementation**

```python
# backend/knowledge_ingest/context_preprocessor.py
"""Per-chunk context preamble generator. One Groq call per chunk.
Result is prepended to chunk content BEFORE embedding (stored as embedded_content);
the original chunk content stays in `content` for citation display."""

import asyncio
import hashlib

from agents.utils import llm_call

PREAMBLE_MODEL_MAX_TOKENS = 80
_PROMPT = (
    "You generate a one-sentence context preamble for a chunk of a longer document. "
    "Given the document name, an optional document summary, and the chunk's section "
    "heading (if any), produce a preamble of the form: "
    "\"From '<doc_name>', section '<heading or \"near top\">'.\" "
    "Output ONLY the preamble sentence — no preface, no quotes around the whole output."
)

# Tiny in-memory cache so resync of an unchanged chunk doesn't pay the Groq cost.
_cache: dict[str, str] = {}


def _cache_key(doc_name: str, chunk_text: str, heading: str) -> str:
    h = hashlib.sha1(f"{doc_name}|{heading}|{chunk_text}".encode("utf-8")).hexdigest()
    return h


async def _llm_preamble(doc_name: str, doc_summary: str, heading: str) -> str:
    user = (
        f"Document name: {doc_name}\n"
        f"Document summary: {doc_summary or '(none)'}\n"
        f"Section heading: {heading or '(none — near top)'}"
    )
    return await llm_call(_PROMPT, user, temperature=0.0)


async def _preamble_for_chunk(chunk: dict, doc_name: str, doc_summary: str) -> str:
    heading = (chunk.get("metadata") or {}).get("heading") or ""
    key = _cache_key(doc_name, chunk["content"], heading)
    if key in _cache:
        return _cache[key]
    try:
        preamble = (await _llm_preamble(doc_name, doc_summary, heading)).strip()
    except Exception:
        preamble = ""
    if preamble:
        _cache[key] = preamble
    return preamble


async def add_context(chunks: list[dict], doc_name: str, doc_summary: str = "") -> list[dict]:
    """Annotate each chunk with `embedded_content` = preamble + content.
    Preserves `content` for citation display. On any per-chunk failure,
    `embedded_content` falls back to `content` so ingest never blocks."""
    if not chunks:
        return chunks

    # Fan out preamble generation in parallel — bounded by Groq's rate limits,
    # but chunks/doc rarely exceeds ~50 so this is safe in practice.
    preambles = await asyncio.gather(*(
        _preamble_for_chunk(c, doc_name, doc_summary) for c in chunks
    ))

    out = []
    for chunk, preamble in zip(chunks, preambles):
        new = dict(chunk)
        if preamble:
            new["embedded_content"] = f"{preamble} {chunk['content']}"
        else:
            new["embedded_content"] = chunk["content"]
        out.append(new)
    return out
```

- [ ] **Step 2: Run the tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_context_preprocessor.py -v
```
Expected: both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/knowledge_ingest/context_preprocessor.py backend/tests/test_context_preprocessor.py
git commit -m "Add context preprocessor module (Phase 2)"
```

### Task 2.4: Wire context preprocessing into `ingest_doc`

**Files:**
- Modify: `backend/knowledge_service.py:132-222` (the `ingest_doc` function)

- [ ] **Step 1: Update `ingest_doc` to call `add_context` and embed `embedded_content`**

  Open `backend/knowledge_service.py`. Add this import alongside the existing ones at the top:

```python
from knowledge_ingest.context_preprocessor import add_context
```

  Then locate the block in `ingest_doc` that currently reads (around line 178–207):

```python
        base_meta = (loaded.page_metadata or [{}])[0]
        chunks = chunk_text(loaded.text, base_metadata=base_meta)

        await check_user_quota(user_id, len(chunks))

        contents = [c["content"] for c in chunks]
        vectors = await embed_batch(contents)
```

  Replace with:

```python
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
```

  Then in the same function, update the chunk-row construction (the list comprehension around line 188–200) so it persists `embedded_content`:

```python
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
```

- [ ] **Step 2: Update transcript indexer to also persist `embedded_content`**

  Open `backend/knowledge_transcript.py`. The transcript path doesn't need contextual preprocessing (a meeting transcript's "name" is `"Title (date)"` — a preamble adds little signal), but the column is now NOT NULL-ish in practice. Update the rows dict literal in `index_meeting_transcript` so `embedded_content` is set:

  Find the `rows = [ ... ]` construction near the bottom and add:

```python
        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "content": chunks[i]["content"],
                "embedded_content": chunks[i]["content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
```

- [ ] **Step 3: Run the full test suite**

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add backend/knowledge_service.py backend/knowledge_transcript.py
git commit -m "Embed chunks with contextual preamble in ingest_doc (Phase 2)"
```

### Task 2.5: Phase 2 smoke test (manual)

- [ ] **Step 1: Upload a new doc through the existing knowledge UI**

  Navigate to the KnowledgeBase page in the dashboard. Upload a short PDF (~5 pages) you can recognize.

- [ ] **Step 2: Verify chunks have `embedded_content` distinct from `content`**

  Supabase SQL editor:
  ```sql
  select id, doc_id, left(content, 60) as content_preview,
         left(embedded_content, 80) as embedded_preview
  from knowledge_chunks
  where doc_id = '<the-uploaded-doc-id>'
  limit 5;
  ```
  Expected: `embedded_preview` starts with `"From '<your doc name>', section '..."` — `content_preview` does not.

- [ ] **Step 3: Phase 2 STOP — commit checkpoint**

  System still ships. Retrieval quality should be visibly better for queries against the newly ingested doc.

---

# Phase 3 — Hybrid retrieval (vector + BM25)

**Goal:** Run vector search and Postgres full-text search (BM25) in parallel, fuse the scores (`0.7 * vec + 0.3 * bm25`), return top 20 to the reranker (Phase 4). Catches exact-term matches embeddings miss (IDs, names, version numbers).

### Task 3.1: SQL migration — add `content_tsvector` + new RPC

**Files:**
- Create: `supabase/knowledge_hybrid_migration.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/knowledge_hybrid_migration.sql
-- Phase 3: Postgres full-text search alongside vector search, fused at the app layer.
-- Adds a tsvector column + GIN index, and a new RPC that returns BM25 candidates
-- so the application can fuse them with vector results.
-- Run AFTER knowledge_contextual_migration.sql.

alter table knowledge_chunks
  add column if not exists content_tsvector tsvector
    generated always as (to_tsvector('english', coalesce(content, ''))) stored;

create index if not exists knowledge_chunks_fts_idx
  on knowledge_chunks
  using gin(content_tsvector);

-- BM25 RPC. Same scoping rules as knowledge_search (own OR workspace-shared,
-- excluding soft-deleted docs). Returns ts_rank_cd as the BM25-flavoured score.
create or replace function knowledge_search_bm25(
  query_text           text,
  caller_user_id       uuid,
  caller_workspace_ids uuid[] default '{}',
  meeting_filter       bigint default null,
  match_limit          int    default 20
)
returns table (
  chunk_id     uuid,
  doc_id       uuid,
  doc_name     text,
  source_type  text,
  sensitivity  text,
  workspace_id uuid,
  meeting_id   bigint,
  content      text,
  metadata     jsonb,
  score        float
)
language sql
stable
as $$
  select
    c.id   as chunk_id,
    c.doc_id,
    d.name as doc_name,
    d.source_type,
    d.sensitivity,
    d.workspace_id,
    d.meeting_id,
    c.content,
    c.metadata,
    ts_rank_cd(c.content_tsvector, plainto_tsquery('english', query_text))::float as score
  from knowledge_chunks c
  join knowledge_docs d on d.id = c.doc_id
  where d.deleted_at is null
    and d.status = 'ready'
    and (
      c.user_id = caller_user_id
      or d.workspace_id = any(caller_workspace_ids)
    )
    and (
      meeting_filter is null
      or d.meeting_id is null
      or d.meeting_id = meeting_filter
    )
    and c.content_tsvector @@ plainto_tsquery('english', query_text)
  order by score desc
  limit match_limit;
$$;
```

- [ ] **Step 2: Run the migration in Supabase SQL editor**

  Expected: "Success." First run may take a few seconds while the GIN index is built. The `generated always as` column triggers an immediate compute over existing rows.

- [ ] **Step 3: Verify the index exists**

  ```sql
  select indexname from pg_indexes
  where tablename = 'knowledge_chunks' and indexname = 'knowledge_chunks_fts_idx';
  ```
  Expected: 1 row.

- [ ] **Step 4: Commit**

```bash
git add supabase/knowledge_hybrid_migration.sql
git commit -m "Add BM25 tsvector index + knowledge_search_bm25 RPC (Phase 3)"
```

### Task 3.2: Write the failing test for hybrid fusion

**Files:**
- Create: `backend/tests/test_hybrid_search.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hybrid_search.py
import asyncio
import sys
import types
import unittest
import uuid
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


class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def execute(self):
        return MagicMock(data=self._data, count=0)


class _FakeSupabase:
    def __init__(self, rpc_payloads: dict):
        self.payloads = rpc_payloads
        self.rpc_calls = []
    def table(self, _): return _FakeQuery([])
    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeQuery(self.payloads.get(name, []))


def _row(chunk_id, doc_id, score, source_type="pdf", doc_name="X.pdf", content="x"):
    return {
        "chunk_id": chunk_id, "doc_id": doc_id, "doc_name": doc_name,
        "source_type": source_type, "sensitivity": "internal",
        "workspace_id": None, "meeting_id": None,
        "content": content, "metadata": {}, "score": score,
    }


class HybridSearchTests(unittest.TestCase):
    def test_fuses_vector_and_bm25(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        vec_rows = [
            _row("a", "d1", 0.9, content="generic content"),
            _row("b", "d2", 0.7, content="other stuff"),
        ]
        bm25_rows = [
            _row("c", "d3", 1.5, content="PRJ-2547 is the ticket"),
            _row("a", "d1", 0.3, content="generic content"),
        ]
        fake_sb = _FakeSupabase({
            "knowledge_search": vec_rows,
            "knowledge_search_bm25": bm25_rows,
        })

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.1] * 1536)):
            matches = asyncio.run(knowledge_service.search_knowledge(
                "PRJ-2547", str(uuid.uuid4()), k=5
            ))

        # Both RPCs called
        call_names = {c[0] for c in fake_sb.rpc_calls}
        self.assertIn("knowledge_search", call_names)
        self.assertIn("knowledge_search_bm25", call_names)

        # Chunk "c" (BM25-only, exact ticket match) must appear in fused results
        chunk_ids = [m["chunk_id"] for m in matches]
        self.assertIn("c", chunk_ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test — expect failure**

```bash
cd backend && python -m pytest tests/test_hybrid_search.py -v
```
Expected: FAIL — `search_knowledge` currently only calls `knowledge_search`, not `knowledge_search_bm25`.

### Task 3.3: Implement hybrid fusion in `search_knowledge`

**Files:**
- Modify: `backend/knowledge_service.py:74-113` (the whole `search_knowledge` body)

- [ ] **Step 1: Replace `search_knowledge` with the hybrid implementation**

  Open `backend/knowledge_service.py`. Add at the top alongside existing constants:

```python
VEC_WEIGHT = 0.7
BM25_WEIGHT = 0.3
HYBRID_TOP_K = 20  # candidate pool passed to reranker (Phase 4) and final cap
```

  Replace the entire `async def search_knowledge(...)` function with:

```python
async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
) -> list[dict]:
    """Hybrid vector + BM25 retrieval. Embeds the query, runs both in parallel,
    fuses scores, returns top-k. Scoped to caller's own docs + workspace-shared docs.
    Reranking (Phase 4) and query rewriting (Phase 5) slot in around this function."""
    sb = _supabase()
    try:
        meeting_filter = int(meeting_id) if meeting_id not in (None, "") else None
    except (TypeError, ValueError):
        meeting_filter = None
    workspace_ids = get_user_workspace_ids(sb, user_id)

    async def _vec_search():
        query_vec = await embed_text(query)
        resp = await _execute(
            sb.rpc("knowledge_search", {
                "query_embedding": query_vec,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": HYBRID_TOP_K,
                "min_score": 0.0,  # we re-filter after fusion
            })
        )
        return resp.data or []

    async def _bm25_search():
        resp = await _execute(
            sb.rpc("knowledge_search_bm25", {
                "query_text": query,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": HYBRID_TOP_K,
            })
        )
        return resp.data or []

    vec_rows, bm25_rows = await asyncio.gather(_vec_search(), _bm25_search())

    fused = _fuse_scores(vec_rows, bm25_rows)

    # Phase 1 cap: meeting transcripts to <= 2 in final k.
    MAX_TRANSCRIPT_HITS = 2
    capped: list[dict] = []
    transcript_count = 0
    for r in fused:
        if r.get("source_type") == "meeting_transcript":
            if transcript_count >= MAX_TRANSCRIPT_HITS:
                continue
            transcript_count += 1
        # Apply min_score on the fused score so callers can still gate weak matches.
        if r.get("score", 0.0) < min_score:
            continue
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
    return rows


def _fuse_scores(vec_rows: list[dict], bm25_rows: list[dict]) -> list[dict]:
    """Min-max normalize each list independently, then combine by chunk_id with
    VEC_WEIGHT * v + BM25_WEIGHT * b. Returns rows sorted by fused score desc."""
    def normalize(rows):
        if not rows:
            return {}
        scores = [r.get("score") or 0.0 for r in rows]
        lo, hi = min(scores), max(scores)
        rng = (hi - lo) or 1.0
        return {r["chunk_id"]: ((r.get("score") or 0.0) - lo) / rng for r in rows}

    vec_norm = normalize(vec_rows)
    bm25_norm = normalize(bm25_rows)

    by_id: dict = {}
    for r in vec_rows + bm25_rows:
        cid = r["chunk_id"]
        if cid not in by_id:
            by_id[cid] = dict(r)
        v = vec_norm.get(cid, 0.0)
        b = bm25_norm.get(cid, 0.0)
        by_id[cid]["score"] = VEC_WEIGHT * v + BM25_WEIGHT * b

    fused = sorted(by_id.values(), key=lambda r: r["score"], reverse=True)
    return fused[:HYBRID_TOP_K]
```

- [ ] **Step 2: Run the hybrid test — expect green**

```bash
cd backend && python -m pytest tests/test_hybrid_search.py -v
```
Expected: PASS.

- [ ] **Step 3: Re-run the full suite**

  Note: the older `test_search_caps_transcript_results` test now hits both RPCs. Update its fake-supabase fixture to provide a BM25 payload (an empty list is fine). Open `backend/tests/test_knowledge_service.py` and find the `test_search_caps_transcript_results` test. Replace the `_FakeSupabase({"rpc:knowledge_search": rows})` line with:

```python
        fake_sb = _FakeSupabase({
            "rpc:knowledge_search": rows,
            "rpc:knowledge_search_bm25": [],
        })
```

  Also update `_FakeSupabase` if it doesn't already key payloads by RPC name — review the test file and align.

  Then:

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add backend/knowledge_service.py backend/tests/test_knowledge_service.py
git commit -m "Hybrid vector + BM25 retrieval with min-max score fusion (Phase 3)"
```

### Task 3.4: Phase 3 smoke test (manual)

- [ ] **Step 1: Insert a test doc with an unusual exact-match token**

  Upload a short text file containing a unique ID like `PRJ-2547` and some generic surrounding text.

- [ ] **Step 2: Query for that exact token via Python**

```python
import asyncio
from dotenv import load_dotenv; load_dotenv()
from knowledge_service import search_knowledge
matches = asyncio.run(search_knowledge("PRJ-2547", "<your-user-id>", k=5))
for m in matches: print(m["score"], m["doc_name"], m["content"][:80])
```
Expected: the chunk containing `PRJ-2547` is in the top 3. Without hybrid (pre-Phase 3), it would have scored too low on pure cosine.

- [ ] **Step 3: Phase 3 STOP — commit checkpoint**

---

# Phase 4 — Reranking with BGE-reranker

**Goal:** Reorder top-20 hybrid candidates by query–document relevance using a cross-encoder, return top-5. The biggest jump from "decent" to "wow" RAG.

**Model choice:** Use `BAAI/bge-reranker-base` (~280MB) for v1. The spec mentions `bge-reranker-v2-m3` (~500MB) — that's stronger but tighter on Render free-tier memory. If the base model proves insufficient on a held-out test set, upgrade to `v2-m3` in a follow-up.

### Task 4.1: Add the FlagEmbedding dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append the dependency**

  Add to the end of `backend/requirements.txt`:

```
# Phase 4 — BGE cross-encoder reranker. ~280MB model downloaded on first use.
FlagEmbedding>=1.2.0,<2.0.0
```

- [ ] **Step 2: Install locally**

```bash
cd backend && pip install -r requirements.txt
```
Expected: FlagEmbedding installs cleanly. If pip complains about torch wheels on Windows, install `torch` from https://pytorch.org/get-started/locally/ first.

- [ ] **Step 3: Verify the model can be loaded (one-time, ~280MB download)**

```bash
python -c "from FlagEmbedding import FlagReranker; r = FlagReranker('BAAI/bge-reranker-base', use_fp16=False); print(r.compute_score([['hello', 'world']]))"
```
Expected: a float score printed. First run downloads the model (~30s on broadband).

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "Add FlagEmbedding dependency for BGE reranker (Phase 4)"
```

### Task 4.2: Write the failing test for the reranker module

**Files:**
- Create: `backend/tests/test_knowledge_reranker.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_reranker.py
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class KnowledgeRerankerTests(unittest.TestCase):
    def test_rerank_returns_top_k_in_score_order(self):
        import importlib, knowledge_reranker
        importlib.reload(knowledge_reranker)

        candidates = [
            {"chunk_id": "a", "content": "irrelevant text"},
            {"chunk_id": "b", "content": "the answer is 42"},
            {"chunk_id": "c", "content": "loosely related"},
        ]

        # Mock the underlying model so the test runs without the 280MB download.
        fake_model = MagicMock()
        fake_model.compute_score.return_value = [0.1, 0.9, 0.3]

        with patch.object(knowledge_reranker, "_get_model", lambda: fake_model):
            out = asyncio.run(knowledge_reranker.rerank(
                "what is the answer?", candidates, top_k=2
            ))

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["chunk_id"], "b")
        self.assertEqual(out[1]["chunk_id"], "c")
        # Original score preserved as `rerank_score`
        self.assertIn("rerank_score", out[0])

    def test_rerank_with_empty_candidates(self):
        import importlib, knowledge_reranker
        importlib.reload(knowledge_reranker)
        out = asyncio.run(knowledge_reranker.rerank("query", [], top_k=5))
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test — expect failure**

```bash
cd backend && python -m pytest tests/test_knowledge_reranker.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'knowledge_reranker'`.

### Task 4.3: Implement the reranker module

**Files:**
- Create: `backend/knowledge_reranker.py`

- [ ] **Step 1: Write the minimal implementation**

```python
# backend/knowledge_reranker.py
"""BGE cross-encoder reranker. Reorders top-20 hybrid candidates by actual
query–document relevance. Loaded once at startup; CPU inference."""

import asyncio
import os
from typing import Optional

_RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
_USE_FP16 = os.getenv("RERANKER_FP16", "0") == "1"  # CPU = fp32; set 1 only on GPU.

_model = None


def _get_model():
    global _model
    if _model is None:
        from FlagEmbedding import FlagReranker
        _model = FlagReranker(_RERANKER_MODEL, use_fp16=_USE_FP16)
    return _model


def preload() -> None:
    """Force model load at app startup so the first request doesn't pay the
    ~5s cold-start cost. Called from main.py's lifespan handler."""
    _get_model()


def _score_pairs(query: str, candidates: list[dict]) -> list[float]:
    model = _get_model()
    pairs = [[query, c.get("content", "")] for c in candidates]
    raw = model.compute_score(pairs)
    if isinstance(raw, float):
        return [raw]
    return list(raw)


async def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Return the top-k candidates ranked by relevance to query.
    Adds `rerank_score` to each returned dict; preserves original `score`."""
    if not candidates:
        return []

    # Cross-encoder inference is CPU-bound and blocking. Run it off the loop.
    scores = await asyncio.to_thread(_score_pairs, query, candidates)
    paired = list(zip(candidates, scores))
    paired.sort(key=lambda p: p[1], reverse=True)

    out = []
    for cand, sc in paired[:top_k]:
        new = dict(cand)
        new["rerank_score"] = float(sc)
        out.append(new)
    return out
```

- [ ] **Step 2: Run the test — expect green**

```bash
cd backend && python -m pytest tests/test_knowledge_reranker.py -v
```
Expected: both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/knowledge_reranker.py backend/tests/test_knowledge_reranker.py
git commit -m "Add BGE reranker module (Phase 4)"
```

### Task 4.4: Preload reranker in app startup

**Files:**
- Modify: `backend/main.py:29-38` (the `lifespan` async context manager)

- [ ] **Step 1: Preload the reranker before yielding**

  Open `backend/main.py`. Add this import alongside the other backend imports:

```python
from knowledge_reranker import preload as preload_reranker
```

  Then update the `lifespan` block:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(run_migrations)
    app.state.http = httpx.AsyncClient(http2=True, timeout=DEFAULT_TIMEOUT)
    app.state.groq = groq_client
    bind_clients(app)
    # Preload the reranker model so the first knowledge query doesn't pay the
    # ~5s cold-start. Heavy CPU/IO so we offload to a thread.
    try:
        await asyncio.to_thread(preload_reranker)
    except Exception as exc:
        print(f"[startup] reranker preload failed (will lazy-load on first use): {exc}")
    try:
        yield
    finally:
        await app.state.http.aclose()
```

- [ ] **Step 2: Verify startup**

```bash
cd backend && uvicorn main:app --port 8000
```
Expected: startup logs show no errors; first request to `/health` returns immediately. Stop the server (`Ctrl+C`) before continuing.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "Preload BGE reranker in app lifespan (Phase 4)"
```

### Task 4.5: Slot the reranker into `search_knowledge`

**Files:**
- Modify: `backend/knowledge_service.py` (the `search_knowledge` function from Phase 3)

  Reranking goes between fusion (top-20) and the meeting-transcript cap. The cap then becomes top-k on the reranker output. **Important:** `knowledge_proactive.py` must NOT pay the reranker cost — add a `rerank` flag.

- [ ] **Step 1: Add the rerank parameter and slot the call**

  Add at the top of `knowledge_service.py` alongside the other imports:

```python
from knowledge_reranker import rerank as rerank_candidates
```

  Update the `search_knowledge` signature and body:

```python
async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
    rerank: bool = True,
) -> list[dict]:
    """Hybrid vector + BM25 retrieval, optional rerank. Scoped to caller's docs
    + workspace-shared. Set rerank=False for latency-sensitive paths
    (proactive surfacing) — that path also skips BM25 + reranking entirely
    and preserves the raw cosine `score` for the existing min_score gate."""
    sb = _supabase()
    try:
        meeting_filter = int(meeting_id) if meeting_id not in (None, "") else None
    except (TypeError, ValueError):
        meeting_filter = None
    workspace_ids = get_user_workspace_ids(sb, user_id)

    async def _vec_search(limit: int, vec_min_score: float):
        query_vec = await embed_text(query)
        resp = await _execute(
            sb.rpc("knowledge_search", {
                "query_embedding": query_vec,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": limit,
                "min_score": vec_min_score,
            })
        )
        return resp.data or []

    async def _bm25_search():
        resp = await _execute(
            sb.rpc("knowledge_search_bm25", {
                "query_text": query,
                "caller_user_id": user_id,
                "caller_workspace_ids": workspace_ids,
                "meeting_filter": meeting_filter,
                "match_limit": HYBRID_TOP_K,
            })
        )
        return resp.data or []

    if not rerank:
        # Latency-sensitive path (proactive surfacing). Vector-only, raw cosine
        # scores so the caller's min_score retains its pre-Phase-3 semantics.
        rows = await _vec_search(limit=k, vec_min_score=min_score)
        rows = _cap_transcripts(rows, k=k)
        _mark_conflict(rows)
        return rows

    vec_rows, bm25_rows = await asyncio.gather(
        _vec_search(limit=HYBRID_TOP_K, vec_min_score=0.0),
        _bm25_search(),
    )
    fused = _fuse_scores(vec_rows, bm25_rows)

    if fused:
        # Rerank against the top-20 candidate pool, take top-k * 2 to leave
        # room for the meeting-transcript cap below.
        fused = await rerank_candidates(query, fused, top_k=max(k * 2, k))

    rows = _cap_transcripts(fused, k=k)
    _mark_conflict(rows)
    return rows


def _cap_transcripts(rows: list[dict], k: int, max_hits: int = 2) -> list[dict]:
    capped: list[dict] = []
    transcript_count = 0
    for r in rows:
        if r.get("source_type") == "meeting_transcript":
            if transcript_count >= max_hits:
                continue
            transcript_count += 1
        capped.append(r)
        if len(capped) >= k:
            break
    return capped


def _mark_conflict(rows: list[dict]) -> None:
    if len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True

    if len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True
    return rows
```

- [ ] **Step 2: Update `knowledge_proactive.py` to pass `rerank=False`**

  Open `backend/knowledge_proactive.py`. Find the `search_knowledge(...)` call in `maybe_proactive_knowledge_check` (around line 87). Change:

```python
        matches = await search_knowledge(query_text, user_id, meeting_id=meeting_id,
                                         k=3, min_score=PROACTIVE_MIN_SCORE)
```

  to:

```python
        matches = await search_knowledge(query_text, user_id, meeting_id=meeting_id,
                                         k=3, min_score=PROACTIVE_MIN_SCORE,
                                         rerank=False)
```

- [ ] **Step 3: Run the test suite**

  The existing hybrid test mocks `embed_text` but not the reranker. Mock it too — open `backend/tests/test_hybrid_search.py` and patch:

```python
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.1] * 1536)), \
             patch.object(knowledge_service, "rerank_candidates",
                          new=AsyncMock(side_effect=lambda q, cands, top_k: cands[:top_k])):
            matches = asyncio.run(knowledge_service.search_knowledge(
                "PRJ-2547", str(uuid.uuid4()), k=5
            ))
```

  Apply the equivalent reranker mock to `test_search_caps_transcript_results` in `backend/tests/test_knowledge_service.py`.

  Then:

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add backend/knowledge_service.py backend/knowledge_proactive.py backend/tests/
git commit -m "Plug BGE reranker into search_knowledge; skip in proactive path (Phase 4)"
```

### Task 4.6: Phase 4 smoke test (manual)

- [ ] **Step 1: Run a query you remember the right answer to**

```python
import asyncio
from dotenv import load_dotenv; load_dotenv()
from knowledge_service import search_knowledge
matches = asyncio.run(search_knowledge("<query>", "<your-user-id>", k=5))
for m in matches:
    print(round(m.get("score") or 0, 3), round(m.get("rerank_score") or 0, 3),
          m["doc_name"], m["content"][:80])
```
Expected: top-1 is the truly relevant chunk. `rerank_score` is set on each row.

- [ ] **Step 2: Time the call once with rerank=True and once with rerank=False**

```python
import asyncio, time
from dotenv import load_dotenv; load_dotenv()
from knowledge_service import search_knowledge
for flag in (False, True):
    t = time.perf_counter()
    await_call = search_knowledge("<query>", "<your-user-id>", k=5, rerank=flag)
    matches = asyncio.run(await_call)
    print(f"rerank={flag}: {(time.perf_counter()-t)*1000:.0f}ms")
```
Expected: `rerank=True` adds ~100–200ms on CPU. If it adds >500ms, profile (the model may be falling back to CPU after a torch issue).

- [ ] **Step 3: Phase 4 STOP — commit checkpoint**

---

# Phase 5 — Query rewriting + (optional) streaming

**Goal:** Detect terse / follow-up queries via heuristics and rewrite them into a standalone form before retrieval. Optional: stream the LLM answer for perceived speed.

We scope this plan to the **rewriting** part. Streaming the bot's chat reply is left as a follow-up since `realtime_routes._send_chat_response` doesn't currently support token streaming and adding that is its own design exercise.

### Task 5.1: Write the failing test for the rewriter

**Files:**
- Create: `backend/tests/test_query_rewrite.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_query_rewrite.py
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class QueryRewriteTests(unittest.TestCase):
    def test_skips_rewrite_for_long_specific_query(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        with patch.object(knowledge_service, "_rewrite_with_llm",
                          new=AsyncMock(return_value="should not be called")):
            out = asyncio.run(knowledge_service.maybe_rewrite_query(
                "what was the Q3 budget allocation discussed last week"
            ))
        self.assertEqual(out, "what was the Q3 budget allocation discussed last week")

    def test_rewrites_short_query(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        with patch.object(knowledge_service, "_rewrite_with_llm",
                          new=AsyncMock(return_value="What is the Q3 budget?")):
            out = asyncio.run(knowledge_service.maybe_rewrite_query(
                "Q3?", conversation_history=["What is the Q2 budget?"]
            ))
        self.assertEqual(out, "What is the Q3 budget?")

    def test_rewrites_followup_signal(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        with patch.object(knowledge_service, "_rewrite_with_llm",
                          new=AsyncMock(return_value="What about engineering hires?")):
            out = asyncio.run(knowledge_service.maybe_rewrite_query(
                "and engineering?",
                conversation_history=["How many sales hires next quarter?"]
            ))
        self.assertEqual(out, "What about engineering hires?")

    def test_falls_back_to_original_on_llm_failure(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        with patch.object(knowledge_service, "_rewrite_with_llm",
                          new=AsyncMock(side_effect=RuntimeError("groq down"))):
            out = asyncio.run(knowledge_service.maybe_rewrite_query("Q3?"))
        self.assertEqual(out, "Q3?")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect failure**

```bash
cd backend && python -m pytest tests/test_query_rewrite.py -v
```
Expected: FAIL — `maybe_rewrite_query` doesn't exist yet.

### Task 5.2: Implement the rewriter

**Files:**
- Modify: `backend/knowledge_service.py` (add the rewriter as a sibling helper)

- [ ] **Step 1: Add the helper near the bottom of `knowledge_service.py` (after `soft_delete_doc`)**

```python
# ── Phase 5: query rewriting ──────────────────────────────────────────────────

import re as _re_rewrite  # local alias to avoid clashing with other imports

_FOLLOWUP_RE = _re_rewrite.compile(
    r"\b(and|what about|how about|also|then|but|or)\b", _re_rewrite.IGNORECASE
)


def _should_rewrite(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    word_count = len(q.split())
    if word_count < 5:
        return True
    if _FOLLOWUP_RE.search(q):
        return True
    return False


_REWRITE_PROMPT = (
    "Rewrite a terse or follow-up meeting question into a single, clear, standalone "
    "question for document search. Use any prior conversation lines as context "
    "but do NOT answer — only rewrite. Respond with ONLY the rewritten question."
)


async def _rewrite_with_llm(query: str, conversation_history: Optional[list[str]] = None) -> str:
    from agents.utils import llm_call
    history = "\n".join(conversation_history or [])
    user = (
        f"Prior conversation:\n{history or '(none)'}\n\n"
        f"Question to rewrite: {query}"
    )
    out = await llm_call(_REWRITE_PROMPT, user, temperature=0.0)
    return (out or "").strip().strip('"').strip("'") or query


async def maybe_rewrite_query(
    query: str,
    conversation_history: Optional[list[str]] = None,
) -> str:
    """Heuristic-gated query rewriter. Returns original query when no rewrite is
    needed. Returns original on LLM failure so retrieval still happens."""
    if not _should_rewrite(query):
        return query
    try:
        return await _rewrite_with_llm(query, conversation_history)
    except Exception as exc:
        print(f"[query-rewrite] failed, using original query: {exc}")
        return query
```

- [ ] **Step 2: Run the tests — expect green**

```bash
cd backend && python -m pytest tests/test_query_rewrite.py -v
```
Expected: all four tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/knowledge_service.py backend/tests/test_query_rewrite.py
git commit -m "Add heuristic-gated query rewriter (Phase 5)"
```

### Task 5.3: Use the rewriter in the `knowledge_lookup` tool

**Files:**
- Modify: `backend/tools/knowledge_lookup.py`

- [ ] **Step 1: Rewrite the user's query before searching**

  At the top of `backend/tools/knowledge_lookup.py`, add to the existing imports:

```python
from knowledge_service import maybe_rewrite_query
```

  Then in `knowledge_lookup` (the handler function), replace:

```python
    matches = await search_knowledge(query, user_id, meeting_id=meeting_id, k=5, min_score=0.75)
```

  with:

```python
    # Conversation history is not currently threaded into the tool call — pass None
    # for now. Future: surface the prior 2-3 chat turns from the bot state.
    rewritten = await maybe_rewrite_query(query, conversation_history=None)
    matches = await search_knowledge(rewritten, user_id, meeting_id=meeting_id, k=5, min_score=0.75)
```

- [ ] **Step 2: Run the suite**

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add backend/tools/knowledge_lookup.py
git commit -m "Rewrite terse queries before retrieval (Phase 5)"
```

### Task 5.4: Phase 5 smoke test (manual)

- [ ] **Step 1: Test the rewriter end-to-end**

```python
import asyncio
from dotenv import load_dotenv; load_dotenv()
from knowledge_service import maybe_rewrite_query
print(asyncio.run(maybe_rewrite_query(
    "Q3?",
    conversation_history=["What is the Q2 budget?"]
)))
```
Expected: a sentence like `"What is the Q3 budget?"` (or a close paraphrase).

- [ ] **Step 2: Phase 5 STOP — commit checkpoint**

---

# Final smoke test + deployment

### Task F.1: End-to-end smoke test

- [ ] **Step 1: Upload one doc and run a meeting**

  In the dashboard:
  1. Upload a recognizable PDF to KnowledgeBase.
  2. Paste a transcript that mentions topics from the doc; run Analyze.
  3. Save the meeting (the existing flow does this on `[DONE]`).

- [ ] **Step 2: Ask 5 queries via the bot (or directly via `search_knowledge`)**

  Each query covers one capability:

  1. *"What does our strategy say about pricing?"* — doc-only, baseline retrieval.
  2. *"What did we decide about pricing last week?"* — meeting-transcript hit (Phase 1).
  3. *"Q3?"* (after a `Q2`-context turn) — query rewrite (Phase 5).
  4. *"PRJ-2547"* — BM25-only exact match (Phase 3).
  5. *"How does the Q2 budget compare to our growth targets?"* — contextual preprocessing helps the right chunk surface (Phase 2); reranker reorders (Phase 4).

  For each, verify:
  - The right chunk appears top-1.
  - Citation includes the doc/meeting name.
  - Total latency from query start to answer ≤ ~1.2s (informal eyeball).

- [ ] **Step 3: Run the full test suite once more**

```bash
cd backend && python -m pytest tests/ -x -q
```
Expected: green.

### Task F.2: Update documentation

**Files:**
- Modify: `docs/specs/2026-05-20-smart-rag-additions.md` — mark each phase ✅ DONE with a one-line summary of what was actually built.
- Modify: `CLAUDE.md` — update the "Knowledge Base / RAG" paragraph to mention contextual ingest, hybrid retrieval, reranking, and query rewriting.

- [ ] **Step 1: Add ✅ DONE markers in the spec**

  For each of Phases 1–5 in `docs/specs/2026-05-20-smart-rag-additions.md`, change the header from `### Phase N — ...` to `### Phase N — ... ✅ DONE (YYYY-MM-DD)` and append a one-line summary of what was implemented (vs. what was specified) directly under the header.

- [ ] **Step 2: Update `CLAUDE.md`**

  In the "Knowledge Base / RAG" section, add a sentence near the end describing the new pipeline:

  > **Smart RAG pipeline (Phases 1–5):** ingest now adds a Groq-generated contextual preamble before embedding (preserved as `embedded_content`); retrieval runs vector + BM25 in parallel, fuses with 0.7/0.3 weighting, reranks the top-20 with BGE-reranker-base, then returns top-5 (meeting transcripts capped to 2). Terse / follow-up queries are heuristically rewritten via Groq before search. Proactive surfacing skips the reranker to stay under its ~150ms budget.

- [ ] **Step 3: Commit documentation updates**

```bash
git add docs/specs/2026-05-20-smart-rag-additions.md CLAUDE.md
git commit -m "Document Smart RAG Phases 1–5 as shipped"
```

### Task F.3: Deploy

- [ ] **Step 1: Push the branch**

```bash
git push origin fixed-changes
```

- [ ] **Step 2: Render env vars**

  No new env vars needed (Phase 0 already added `OPENAI_API_KEY` and `TAVILY_API_KEY`). FlagEmbedding downloads its model on first start — confirm Render's filesystem persists the cache between requests (it does; only between deploys does it re-download). On first deploy, the `/health` endpoint will be slow until the reranker preload completes.

- [ ] **Step 3: Smoke test in production**

  After the Render deploy succeeds, repeat Task F.1 against the production URL. If any query takes >2s, profile (likely the reranker model is re-downloading on cold start).

---

## Spec coverage self-check

Mapping each spec requirement to a task in this plan:

| Spec section | Task(s) |
|---|---|
| Phase 1 — Index transcripts | 1.1, 1.2, 1.3, 1.4 |
| Phase 1 — Cite meeting dates | 1.5 |
| Phase 1 — Cap meeting-transcript hits | 1.6 |
| Phase 2 — Context preprocessor module | 2.2, 2.3 |
| Phase 2 — `embedded_content` column | 2.1 |
| Phase 2 — Cache by content hash | 2.3 (in `_preamble_for_chunk`) |
| Phase 3 — tsvector + GIN index | 3.1 |
| Phase 3 — Parallel vector+BM25 | 3.3 |
| Phase 3 — Min-max normalize + 0.7/0.3 fusion | 3.3 (`_fuse_scores`) |
| Phase 4 — FlagEmbedding dep | 4.1 |
| Phase 4 — `knowledge_reranker.py` module | 4.2, 4.3 |
| Phase 4 — Preload on startup | 4.4 |
| Phase 4 — Skip reranker on proactive | 4.5 |
| Phase 5 — Heuristic gate | 5.2 (`_should_rewrite`) |
| Phase 5 — Groq rewrite + fallback | 5.2 |
| Phase 5 — Wire into `knowledge_lookup` | 5.3 |
| Spec — Latency budget verified | F.1 step 2 |
| Spec — Don't break existing endpoints | (preserved throughout — signatures unchanged, added optional kwarg only) |

**Streaming the bot answer (Phase 5 spec step 4):** intentionally deferred. The current `realtime_routes._send_chat_response` posts a complete message, not tokens. Adding streaming is a separate design exercise (Recall.ai chat API limitations, partial-message UX, etc.) and was not the substantive part of Phase 5. Query rewriting is the load-bearing change here.

**Entity boost (spec step 6):** the spec lists an entity-name boost (multiply score by 1.2 when query contains a name matching the chunk). After Phase 3+4 are live, evaluate on a held-out test set whether this still moves the needle. Adding it later is a 10-line change to `_fuse_scores`. Deferred.

---

## What this plan does NOT do

- Backfill meeting transcripts that existed before Phase 1 went live. To backfill, write a one-off script (`backend/scripts/backfill_transcripts.py`) that pages through `meetings` and calls `index_meeting_transcript` for each. Out of scope here.
- Stream the bot's final answer back to the meeting chat (see note above).
- Implement the entity boost (see note above).
- Touch the frontend. Phases 1–5 are pure backend.

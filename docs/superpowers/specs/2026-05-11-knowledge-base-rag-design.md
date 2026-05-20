# Knowledge Base & Real-Time RAG for Meeting Participation

**Date:** 2026-05-11
**Status:** Design approved, ready for implementation
**Author:** Brainstorming session with Claude

---

## Goal

Let PrismAI ingest user-supplied documents (PDFs, Word docs, text files, URLs, Notion pages, Google Drive files) and use them during live meetings to:

1. Answer questions accurately, grounded only in document content (no hallucination).
2. Proactively surface relevant document content when meeting topics match — but only from safe sources.
3. Cite the source document on every grounded answer.
4. Fall back to web search (Tavily) when documents don't contain the answer.
5. Fall back to asking the user in the meeting chat when web search also fails.

---

## Non-Goals

- Re-implementing or replacing the existing meeting bot. The bot's transcript/memory/proactive infrastructure stays untouched except for **one minimal hook** in `_compress_and_persist`.
- Building a Notion OAuth flow. We reuse the existing "paste integration token" pattern from `/export/notion`.
- Building a hybrid (BM25 + vector) retriever in v1. Defer until retrieval quality data justifies it.
- Implementing a guardian LLM. The strict-grounding prompt + citation requirement is the v1 anti-hallucination strategy.

---

## Architecture

### New files

```
backend/
  knowledge_routes.py            — REST API: upload, list, pin/unpin, delete, re-sync
  knowledge_service.py           — core: chunking, embedding, retrieval, ingestion orchestration
  knowledge_proactive.py         — proactive surfacing check (called from the one hook)
  knowledge_ingest/
    __init__.py
    pdf_loader.py                — PyMuPDF + OCR fallback
    docx_loader.py               — python-docx
    text_loader.py               — txt / md
    url_loader.py                — Tavily Extract + Jina fallback
    notion_loader.py             — Notion API (integration token)
    gdrive_loader.py             — Google Drive API (existing google_access_token)
    chunker.py                   — sliding-window chunking with sentence-boundary preservation
  tools/
    knowledge_lookup.py          — registered tool: vector search + grounded response builder
    web_search.py                — registered tool: Tavily search (general web fallback)
  embeddings.py                  — OpenAI embeddings client + retry/backoff

frontend/src/
  components/
    KnowledgeBase.jsx            — library list view, pin/unpin per meeting, delete
    KnowledgeUploadModal.jsx     — file picker, URL paste, Notion/Drive picker
    KnowledgeDocCard.jsx         — single doc with status, sensitivity, sync timestamp
    KnowledgeQueryLog.jsx        — recent queries audit (debug aid)
  lib/
    knowledge.js                 — API client wrappers

supabase/
  knowledge_migration.sql        — already written
```

### Existing files we touch

| File | Change | Justification |
|---|---|---|
| `backend/main.py` | +1 line | Register `knowledge_routes.router` |
| `backend/tools/__init__.py` | +2 lines | Import `knowledge_lookup` and `web_search` so they register on import |
| `backend/realtime_routes.py` | +2 lines inside `_compress_and_persist` | Call `await maybe_proactive_knowledge_check(...)`. This is the ONLY hook into existing prism logic — additive, behind a try/except that never breaks the existing flow. |
| `frontend/src/App.jsx` | +1 route, +1 nav link | Mount `<KnowledgeBase />` page |
| `backend/.env.example` | +2 keys | `OPENAI_API_KEY`, `TAVILY_API_KEY` |

Nothing else gets modified. No existing function signature changes. No agent file changes. No `meeting_memory.py` changes.

### How retrieval plugs in (zero existing-code changes)

`tools/__init__.py` already imports tool modules at startup. Adding `from . import knowledge_lookup, web_search` registers them with the existing `_TOOLS` dict in `tools/registry.py`. The bot's existing tool-calling loop will then automatically:

1. Include `knowledge_lookup` and `web_search` in every Groq tool-definition list.
2. Call the handlers when the LLM decides to.
3. Pass results back into the LLM context.

The retrieval flow happens entirely inside the tool handler. The bot doesn't need to know it exists.

### How proactive surfacing plugs in (one hook)

Inside `_compress_and_persist` in `realtime_routes.py` — the function that already runs every 20 transcript lines — add:

```python
# Proactive knowledge check (additive, never raises)
try:
    from knowledge_proactive import maybe_proactive_knowledge_check
    await maybe_proactive_knowledge_check(bot_id, state)
except Exception as exc:
    print(f"[proactive-knowledge] {bot_id}: {exc}")
```

This is the only modification. It cannot break existing behavior (wrapped in try/except). If `knowledge_proactive.py` is missing, the import fails and the existing flow continues.

---

## Data Flow

### Ingestion

```
User uploads PDF/URL/Notion/Drive
  → POST /knowledge/upload (or /knowledge/connect-source)
  → knowledge_routes inserts knowledge_docs row (status='processing')
  → BackgroundTasks.add_task(ingest_doc, doc_id)
  → ingestion worker:
      1. loader.load(doc) → text + structured metadata (page numbers, headings, tables)
      2. chunker.split(text) → list[(content, metadata)]
      3. embeddings.embed_batch(chunks) → list[vector]
      4. insert chunks atomically; update chunk_count + status='ready'
  → On error: status='error', error_message=<reason>
```

### On-demand retrieval (in meeting)

```
User says "Prism, what was the Q2 budget?"
  → existing _process_command flow
  → LLM tool-calls knowledge_lookup(query="Q2 budget", meeting_id=<id>)
  → handler:
      1. embeddings.embed(query)
      2. RPC knowledge_search(embedding, user_id, meeting_id, k=5, min_score=0.75)
      3. If results: format as "From [doc_name]: <content>" with citations
      4. If no results above 0.75: return {"no_match": true, "next_step": "web_search"}
  → LLM, seeing no_match, tool-calls web_search(query="...")
  → If web_search returns useful results: LLM answers with web citation
  → If web_search also fails: LLM composes a question to ask in meeting chat
      (existing Recall.ai chat injection handles delivery)
  → knowledge_queries row written with bot_id, fallback path taken
```

### Proactive surfacing

```
Every 20 transcript lines (existing _compress_and_persist trigger):
  → maybe_proactive_knowledge_check(bot_id, state):
      1. Take last 10 transcript lines as proactive "query"
      2. Hash query window → check 60-second dedupe cache; skip if seen
      3. embeddings.embed(query_window)
      4. RPC knowledge_search(embedding, user_id, meeting_id, k=3, min_score=0.85)
         WHERE doc.sensitivity = 'public'
            OR doc.meeting_id = <current_meeting>   ← privacy default
      5. Per-doc cooldown: skip docs surfaced in last 10 minutes
      6. If a chunk passes: post via Recall.ai chat:
         "💡 From [doc_name]: <one-sentence summary> — say 'Prism, more' for details"
      7. Write knowledge_queries audit row
```

---

## Anti-Hallucination Strategy

Three layers, in order of importance:

### Layer 1 — Strict system prompt at retrieval time

The `knowledge_lookup` tool returns content wrapped in this structure:

```json
{
  "matches": [
    {"doc_name": "Q2 Budget.pdf", "content": "...", "score": 0.91, "page": 3}
  ],
  "instruction": "Answer ONLY using the content above. Cite the doc_name. If the content does not contain the answer, respond with exactly: NO_GROUNDED_ANSWER. Do not synthesize or infer beyond the provided content."
}
```

The LLM is instructed in its base system prompt to treat `NO_GROUNDED_ANSWER` as a signal to fall back to `web_search`.

### Layer 2 — Citation requirement

Every doc-grounded response must include the doc name. The system prompt enforces this. If the LLM tries to answer from docs without citing, the meeting chat post is rejected at the handler level and the LLM is asked to retry with citations.

### Layer 3 — Conflict detection

If `knowledge_search` returns top-2 chunks from **different docs** with scores within 0.05 of each other:
1. The handler returns BOTH chunks in `matches`.
2. The instruction string is augmented: "Multiple documents may contain conflicting information. If their content disagrees, present BOTH views with their respective `doc_name` and any date metadata. Do NOT pick one."

This handles the Q1/Q2 strategy doc scenario from the gap analysis.

---

## Privacy & Sensitivity

Three-tier `sensitivity` enum on every doc:

| Tier | Default? | Proactive surfacing | On-demand lookup |
|---|---|---|---|
| `public` | No | ✅ Any meeting | ✅ Any meeting |
| `internal` | ✅ Yes | ⚠️ Only when pinned to the meeting | ✅ Any meeting |
| `confidential` | No | ❌ Never | ⚠️ Only when pinned to the meeting |

The proactive check filters by sensitivity in application code (the SQL RPC returns the column; the Python caller enforces the rule). This keeps the RPC simple and the policy auditable in one place (`knowledge_proactive.py`).

---

## Cost Controls (hard limits)

| Limit | Value | Where enforced |
|---|---|---|
| Max doc size | 50 MB | `knowledge_routes.py` upload handler |
| Max chunks per user | 50,000 | `knowledge_service.py` before insert |
| Embedding batch size | 100 chunks | `embeddings.py` |
| Proactive embedding dedupe | 60-sec sliding window per bot | `knowledge_proactive.py` |
| Tavily calls per user per minute | 10 (matches existing tool registry cap) | `tools/registry.py` rate limit |
| OpenAI embedding retries | 3 with exponential backoff | `embeddings.py` |

---

## Graceful Degradation

| Failure | Fallback |
|---|---|
| OpenAI embeddings API down | Mark doc `status='error'`, retry-queue for 1 hour. For on-demand queries during outage: fall back to PostgreSQL full-text search on `knowledge_chunks.content` |
| Tavily API down | Skip web_search step, go directly to "ask user" prompt |
| pgvector query slow (>1s) | Cap retrieval timeout at 3s; on timeout, return empty match list (LLM treats as no_match) |
| Supabase Storage unavailable | Block upload with clear error; ingestion never starts |
| Notion/Drive token expired | Mark doc `status='error'`, `error_message='reconnect required'`, surface banner in UI |
| OCR fails on scanned PDF | Mark doc `status='error'`, `error_message='unable to extract text'`, suggest manual paste |

---

## Mid-Meeting Upload

Doc cards in the live meeting view accept drag-and-drop and pasted URLs. The upload path:

1. POST to `/knowledge/upload` with `meeting_id` set to the live meeting.
2. Doc card immediately appears with `status='processing'`.
3. Once ingestion completes (typically 5–30 s), card flips to `status='ready'`.
4. The bot's tool registry picks up the new doc automatically on the next `knowledge_lookup` call (no bot restart needed — retrieval queries the live DB).

---

## Frontend UX

```
/dashboard/knowledge          ← new top-level page
  ┌────────────────────────────────────────────────────┐
  │  Knowledge Base                       [+ Upload]   │
  │                                                    │
  │  Filter: [All] [Global] [Pinned to meeting…]      │
  │                                                    │
  │  ┌──────────────────┐ ┌──────────────────┐        │
  │  │ Q2 Budget.pdf    │ │ Strategy Doc     │        │
  │  │ 🔵 Internal      │ │ 🟢 Public        │        │
  │  │ ✓ Ready · 12 chk │ │ ⚠ Stale · 3 d   │        │
  │  │ [Pin] [Sync] [×] │ │ [Pin] [Sync] [×] │        │
  │  └──────────────────┘ └──────────────────┘        │
  └────────────────────────────────────────────────────┘
```

In the existing meeting detail view, add a "Pinned Documents" section showing docs where `meeting_id = this meeting`. Drag-from-library or upload directly.

---

## Implementation Plan for Sonnet 4.6

A 12-task plan, each independently verifiable. Tasks are ordered so each one leaves the system in a working state — you can stop after any task and the existing app still functions.

### Pre-flight (manual, do once)

1. Run `supabase/knowledge_migration.sql` in the Supabase SQL editor.
2. Add to `backend/.env`:
   ```
   OPENAI_API_KEY=sk-...
   TAVILY_API_KEY=tvly-...
   ```
3. Add `drive.readonly` scope on the Google Cloud OAuth consent screen.
4. Create a Supabase Storage bucket named `knowledge` with RLS enabled (`auth.uid()::text = (storage.foldername(name))[1]`).

### Task 1 — Embeddings client

**Files:** `backend/embeddings.py`

Write a small async client that wraps `openai.AsyncOpenAI().embeddings.create(model="text-embedding-3-small", input=...)`. Includes:
- `embed_text(text: str) -> list[float]`
- `embed_batch(texts: list[str]) -> list[list[float]]` — batches of 100, with 3-retry exponential backoff on 429/500/503
- Truncate inputs to 8000 tokens (OpenAI limit is 8192) using `tiktoken`

**Acceptance:** Unit test in `backend/tests/test_embeddings.py` that mocks the OpenAI client and verifies batching + retry behavior.

### Task 2 — Chunker

**Files:** `backend/knowledge_ingest/chunker.py`

Sliding-window chunker:
- 400 tokens per chunk, 80-token overlap
- Snap chunk boundaries to sentence endings using `re.split(r'(?<=[.!?])\s+', text)`
- Preserve metadata (page number, heading) from the loader on each chunk
- Tables: pass through as a single chunk regardless of size (don't split a table)

**Acceptance:** Unit test in `backend/tests/test_chunker.py` with three fixtures: plain prose, prose-with-headings, prose-with-a-table.

### Task 3 — Loaders (5 files)

**Files:** `backend/knowledge_ingest/{pdf_loader,docx_loader,text_loader,url_loader,notion_loader,gdrive_loader}.py`

Each exposes one function:
```python
async def load(source: str | bytes, settings: dict) -> tuple[str, list[dict]]:
    """Returns (full_text, chunks_metadata_hints).
       Raises LoaderError on failure with a user-friendly message."""
```

- `pdf_loader`: PyMuPDF (`fitz`). On empty text, fall back to `pytesseract.image_to_string(page.get_pixmap())` page-by-page.
- `docx_loader`: `python-docx`.
- `text_loader`: read bytes, decode UTF-8 with `errors='replace'`.
- `url_loader`: `httpx.post("https://api.tavily.com/extract", ...)`. On 4xx/5xx, fall back to `https://r.jina.ai/<url>`. On both failing, raise `LoaderError("Page requires login or JavaScript")`.
- `notion_loader`: walk page blocks via Notion API using `user_settings["notion_access_token"]`. Default depth = page only (don't recurse into subpages in v1).
- `gdrive_loader`: list/export files via Drive API using `user_settings["google_access_token"]`. Supports Docs (export as text), Sheets (export as CSV), PDFs (download bytes → pass to pdf_loader).

**Acceptance:** Each loader has a unit test with a recorded fixture (vcr.py or hand-rolled mocks). PDF loader has a scanned-PDF fixture proving OCR fallback fires.

### Task 4 — knowledge_service core

**Files:** `backend/knowledge_service.py`

Functions:
```python
async def ingest_doc(doc_id: UUID) -> None:
    """Background worker. Loads → chunks → embeds → inserts.
       Updates status field at each phase. Never raises — errors written to error_message."""

async def search_knowledge(
    query: str,
    user_id: UUID,
    meeting_id: UUID | None = None,
    k: int = 5,
    min_score: float = 0.75,
) -> list[dict]:
    """Embeds query, calls knowledge_search RPC, returns matches with conflict-detection
       augmentation if top-2 differ by < 0.05."""

async def soft_delete_doc(doc_id: UUID, user_id: UUID) -> None:
    """Sets deleted_at = now()."""

async def check_user_quota(user_id: UUID, new_chunks: int) -> None:
    """Raises QuotaExceeded if user_chunks + new_chunks > 50_000."""
```

**Acceptance:** Integration test in `backend/tests/test_knowledge_service.py` against a test Supabase project (or mocked client). Verifies: ingest → search round-trip, quota guard, soft delete excludes from search, conflict detection.

### Task 5 — knowledge_routes REST API

**Files:** `backend/knowledge_routes.py`

Endpoints (all require auth via existing `require_user_id`):
- `POST /knowledge/upload` — multipart file upload (PDF/DOCX/TXT) or JSON `{source_type: 'url', url: '...'}`. Returns `{doc_id, status: 'processing'}`. Triggers `BackgroundTasks.add_task(ingest_doc, doc_id)`.
- `POST /knowledge/connect-source` — JSON `{source_type: 'notion' | 'gdrive', source_id: '...', meeting_id?: '...'}`. Same return shape.
- `GET /knowledge/docs?meeting_id=&include_global=true` — list docs filtered by scope.
- `PATCH /knowledge/docs/{doc_id}` — update `name`, `sensitivity`, `meeting_id` (pin/unpin).
- `POST /knowledge/docs/{doc_id}/resync` — re-run ingestion atomically (new chunks first, swap, delete old).
- `DELETE /knowledge/docs/{doc_id}` — soft delete.
- `GET /knowledge/queries?bot_id=&limit=50` — audit log.

Register router in `backend/main.py` with `app.include_router(knowledge_routes.router)`.

**Acceptance:** `backend/tests/test_knowledge_routes.py` covering all endpoints with auth, quota, and error paths.

### Task 6 — knowledge_lookup tool

**Files:** `backend/tools/knowledge_lookup.py`

```python
async def knowledge_lookup(args: dict, user_settings: dict | None = None) -> dict:
    """args: { query: str, meeting_id?: str }
       Returns: { matches: [...], instruction: '...' } or { no_match: true }"""
```

Calls `knowledge_service.search_knowledge(...)`. Builds the strict-grounding instruction string. Writes a `knowledge_queries` audit row.

Register via `register_tool(name="knowledge_lookup", ...)`. **No `requires` field** — always available. **No `confirm`** — read-only.

**Acceptance:** Test that mocks `search_knowledge` and verifies the LLM-facing output shape (matches schema in section "Anti-Hallucination — Layer 1").

### Task 7 — web_search tool

**Files:** `backend/tools/web_search.py`

```python
async def web_search(args: dict, user_settings: dict | None = None) -> dict:
    """args: { query: str }
       Calls Tavily search API, returns top 3 results with content snippets and source URLs."""
```

Uses `TAVILY_API_KEY` env var. Always available. No confirm. Audit-logs to `knowledge_queries` with `fallback='web_search'`.

**Acceptance:** Test with mocked Tavily response.

### Task 8 — tools/__init__.py update

**Files:** `backend/tools/__init__.py`

Add:
```python
from . import knowledge_lookup, web_search  # registers on import
```

**Acceptance:** Start the backend; `get_available_tools()` includes both new tools.

### Task 9 — knowledge_proactive module

**Files:** `backend/knowledge_proactive.py`

```python
_dedupe_cache: dict[str, float] = {}  # bot_id → last_query_hash_timestamp
_doc_cooldown: dict[tuple[str, str], float] = {}  # (bot_id, doc_id) → last_surfaced_at

async def maybe_proactive_knowledge_check(bot_id: str, state: dict) -> None:
    """Reads last 10 transcript lines from state, runs sensitivity-aware search,
       posts to Recall.ai chat if a match passes all gates."""
```

Gates:
1. 60-sec dedupe cache (hash of last 10 lines)
2. min_score >= 0.85
3. Sensitivity filter (only `public` OR `meeting_id == current`)
4. Per-doc 10-minute cooldown
5. Skip if a command is currently being processed (check `state["processing"]` flag set by existing `_process_command`)

Posts the proactive message using the existing `_post_chat_message` helper from `realtime_routes.py` (imported, not modified).

**Acceptance:** Unit test that drives the function with synthetic state dicts and verifies each gate.

### Task 10 — Hook into realtime_routes.py

**Files:** `backend/realtime_routes.py`

Locate `_compress_and_persist`. After the existing compression block, insert:

```python
try:
    from knowledge_proactive import maybe_proactive_knowledge_check
    await maybe_proactive_knowledge_check(bot_id, state)
except Exception as exc:
    print(f"[proactive-knowledge] {bot_id}: {exc}")
```

That's the entire change. The try/except guarantees no break to existing behavior.

**Acceptance:** Bring up a bot, watch the existing compression logs continue, verify the new log line `[proactive-knowledge]` appears periodically with no errors.

### Task 11 — Frontend Knowledge Base

**Files:** `frontend/src/components/{KnowledgeBase,KnowledgeUploadModal,KnowledgeDocCard,KnowledgeQueryLog}.jsx`, `frontend/src/lib/knowledge.js`, route in `frontend/src/App.jsx`

Use `apiFetch()` from `lib/api.js` (the existing auth-attaching wrapper). Use existing shadcn/Tailwind patterns (`glassCard`, `cardGlowStyle` from `dashboardStyles`). No glassmorphism as the default surface — sky/cyan accents only.

Components:
- `KnowledgeBase` — list view with filters
- `KnowledgeUploadModal` — file picker, URL paste, Notion ID paste, Google Drive picker (use existing Google OAuth)
- `KnowledgeDocCard` — name, sensitivity pill, status badge, sync time, actions
- `KnowledgeQueryLog` — recent queries with match/fallback info

**Acceptance:** Manual test: upload PDF, see it process, see chunks count update, search via library, pin to a meeting, see it appear in meeting view.

### Task 12 — Mid-meeting upload affordance

**Files:** `frontend/src/components/dashboard/MeetingView.jsx` (existing — add a "Pinned Documents" panel)

Re-uses `KnowledgeUploadModal` with `meeting_id` pre-filled. Live polling: every 5 s, refetch the pinned doc list while any are `status='processing'`.

**Acceptance:** During a live meeting, drop a PDF into the panel, watch it flip to "ready" within ~30 s, then ask "Prism, what does this doc say about X?" and verify the bot answers from the new doc.

---

## Verification Checklist (run before declaring done)

- [ ] All 6 edge-case fixes verified with explicit tests (privacy, mid-meeting upload, concurrent deletion, cost limits, conflict detection, OAuth expiry)
- [ ] Upload a 100-page PDF: chunks created, embeddings generated, retrieval works
- [ ] Upload a scanned PDF: OCR fires, chunks created
- [ ] Paste a Notion public-page URL: ingested via `url_loader` → Tavily Extract
- [ ] Paste a JS-only SPA URL: `LoaderError("requires login")` surfaced cleanly to UI
- [ ] Connect Notion via integration token: page ingested
- [ ] Connect Google Drive (with new scope consented): file ingested
- [ ] Ask "Prism, what was the Q2 budget?" — bot answers with citation
- [ ] Ask a question with no doc match — bot calls `web_search`, answers with web citation
- [ ] Ask a question with neither — bot composes a question and posts it in meeting chat
- [ ] Upload two contradicting strategy docs — bot surfaces BOTH with citations
- [ ] Upload a `confidential` doc, ask about its content WITHOUT pinning it — bot does NOT use it; with pinning — bot uses it
- [ ] Delete a doc mid-search — no broken citations
- [ ] Quota: try to upload doc that would push user over 50,000 chunks — error surfaced
- [ ] Existing meeting flow (transcript, commands, proactive nudges) unaffected — regression check

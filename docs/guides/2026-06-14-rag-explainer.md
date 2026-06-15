# PrismAI RAG — How It Works & How to Use It Best

_Last updated: 2026-06-14. Reflects the smart-RAG build (all phases shipped) and the
Groq→Anthropic/OpenAI model migration of the same day._

This is the plain-language guide to PrismAI's retrieval system: what it does, how a
document becomes answerable, how a question gets answered, and how to get the most out
of it. For the original design spec see
[`docs/specs/2026-05-20-smart-rag-additions.md`](../specs/2026-05-20-smart-rag-additions.md).

---

## 1. What it is, in one paragraph

PrismAI's RAG ("retrieval-augmented generation") lets the assistant answer questions
using **your** material — uploaded documents (PDF, DOCX, TXT, web URLs, Notion, Google
Drive) **and your past meeting transcripts** — instead of guessing from the model's
general knowledge. When you ask something, it finds the most relevant passages from your
knowledge base, hands them to the model as the *only* allowed source, and the model
answers with citations. If nothing relevant is found, it says so and can fall back to a
live web search rather than make something up.

There are **two surfaces** where this runs:

1. **On-demand (chat).** When you ask the chat/assistant a factual question, it calls the
   `knowledge_lookup` tool. This is the full-quality path.
2. **Proactive (live meeting).** While a meeting bot is in a call, every ~10 transcript
   lines it quietly checks whether anything in your knowledge base is relevant to what's
   being said, and surfaces it in chat. This is the fast, lightweight path.

---

## 2. How a document becomes searchable (ingestion)

When you upload a doc (or a meeting ends and its transcript is auto-indexed), it goes
through this pipeline:

1. **Load & extract** — the right loader pulls clean text out of the source
   (`knowledge_ingest/`: `pdf_loader`, `docx_loader`, `text_loader`, `url_loader`,
   `notion_loader`, `gdrive_loader`). PDFs use PyMuPDF with OCR fallback for scans.
2. **Chunk** — text is split into **~400-token chunks with ~80-token overlap**, snapped to
   sentence boundaries so a chunk never cuts mid-sentence (`chunker.py`). Overlap means a
   fact that straddles a boundary still lands whole in at least one chunk.
3. **Contextual preamble** (smart-RAG Phase 2) — each chunk gets a one-sentence,
   model-generated preamble describing where it sits in the document (e.g. "This section
   of the Q3 finance memo covers the revenue forecast."). The preamble is prepended
   *before embedding only* — it's stored separately (`embedded_content`) so what you read
   stays clean, but the embedding is "smarter" about the chunk's context. This noticeably
   improves retrieval on chunks that are ambiguous in isolation.
4. **Embed** — each (preamble + chunk) is turned into a vector with OpenAI
   `text-embedding-3-small` and stored in Supabase pgvector (`knowledge_chunks`).
5. **Index for keyword search** — a Postgres `tsvector` column + GIN index is built so the
   same chunk is also findable by exact keyword/BM25 (smart-RAG Phase 3).

Meeting transcripts run the same pipeline automatically when a meeting is saved
(`knowledge_transcript.py`), so "what did we decide about X last week?" is answerable
without you uploading anything.

---

## 3. How a question gets answered (retrieval)

The heart is `search_knowledge()` in `knowledge_service.py`. For a query it runs:

1. **(Optional) Query rewrite** (Phase 5) — terse or follow-up questions ("and Q3?",
   "what about engineering") are rewritten into standalone queries using your recent
   conversation, so retrieval isn't confused by pronouns/fragments. Heuristic-gated, so
   already-clear questions skip it. _On for the chat path, off for proactive._
2. **Hybrid retrieval** — two searches run in parallel:
   - **Vector** (semantic similarity) via the `knowledge_search` RPC.
   - **BM25** (exact keyword) via the `knowledge_search_bm25` RPC.
   Each returns ~top-30 candidates. (If the BM25 index is missing, it degrades gracefully
   to vector-only.)
3. **Fusion (RRF)** — the two lists are merged with Reciprocal Rank Fusion (`_rrf_merge`),
   which rewards chunks that rank well in *both* semantic and keyword search. This is why
   it handles both "concept" questions and "exact term / acronym / name" questions well.
4. **(Optional) Rerank** (Phase 4) — the fused top-30 are re-scored by an LLM that reads
   each candidate against the question and keeps the truly relevant top-k. _On for chat,
   off for proactive._
5. **Filter & return** — results below a minimum relevance score are dropped, and the
   top-k are returned with their source metadata.

### The two paths, side by side

| | On-demand (`knowledge_lookup`) | Proactive (`knowledge_proactive`) |
|---|---|---|
| Trigger | You ask the chat a question | Every ~10 transcript lines, live bot |
| Query rewrite (Phase 5) | **On** | Off |
| Rerank (Phase 4) | **On** | Off |
| `k` returned | 5 | small |
| Min score | 0.75 | 0.85 (stricter — fewer, surer hits) |
| Latency budget | ~800ms | ~150ms |
| Extra guards | strict grounding, conflict detection, web fallback | dedupe window, per-doc 10-min cooldown, sensitivity gating |

The proactive path is deliberately cheap and conservative — it only interrupts the meeting
when it's quite sure (0.85) and won't repeat itself (dedupe + cooldown).

---

## 4. Scoping: personal vs workspace

Every document and chunk carries an optional `workspace_id` (null = personal).

- In **Personal** mode you see and search **your own** docs.
- In a **workspace** you see and search **that workspace's shared** docs — any member can
  retrieve them.

Retrieval enforces this in the database: a chunk matches only when
`chunk.user_id = you` **OR** `doc.workspace_id` is one of your workspaces (resolved from
`workspace_members`). You can never retrieve another user's personal docs, and moving a
doc between scopes keeps its chunks in sync.

---

## 5. Sensitivity: controlling what the bot surfaces on its own

Each doc has a sensitivity level that **only governs the proactive (in-meeting) path** —
the on-demand path always respects scope but ignores sensitivity (you asked, so you get it):

- **`public`** — can be surfaced proactively in any meeting.
- **`internal`** (default) — surfaced proactively **only when the doc is pinned to that
  specific meeting**.
- **`confidential`** — **never** surfaced proactively. Retrievable on-demand only.

Rule of thumb: anything you'd be unhappy to see auto-posted into a call with an external
guest should be `confidential` (or at least `internal` and unpinned).

---

## 6. The trust layer (why you can believe the citations)

RAG's failure mode is confident hallucination. PrismAI defends against it on several
levels:

- **Strict grounding instruction** — the model is told to answer *only* from the retrieved
  matches and to emit the literal token `NO_GROUNDED_ANSWER` if they don't contain the
  answer. That token triggers a **web_search** fallback rather than a guess.
- **Citations come from data, not prose** — the chat UI's Sources cards and the conflict
  banner are built from a whitelisted, structured `rag_context` (doc name, source type,
  score, snippet, page/timestamp/meeting title), *not* parsed from the model's text. So a
  citation can't be fabricated by the model — it corresponds to a real retrieved chunk.
- **Conflict detection** — if two docs disagree (e.g. an old and a new policy), the system
  flags it, the model is instructed to present **both** views with their sources/dates, and
  the UI shows a conflict banner. It won't silently pick a winner.
- **Audit log** — every lookup is recorded (`knowledge_queries`: query, matched doc,
  score, fallback) so retrieval quality is inspectable.
- **Web-search hardening** — the Tavily fallback has prompt-injection defenses so a
  malicious web page can't hijack the assistant.

---

## 7. Which model does what (current, post-migration)

As of 2026-06-14 Groq is fully removed. The RAG stack now runs on:

- **Embeddings** → OpenAI `text-embedding-3-small` (unchanged — the right tool).
- **Contextual preamble, query rewrite, reranker** → **Claude Haiku 4.5** (they go through
  `agents/utils.llm_call`, so they moved with the migration; some in-code docstrings still
  say "Groq" but the call path is Haiku now, with `gpt-4o-mini` as the cross-provider
  fallback).
- **The chat/assistant that decides to call `knowledge_lookup` and writes the final
  grounded answer** → `gpt-4o-mini` (the tool-calling chat path).

Practical implication: RAG is no longer subject to Groq's 100k-tokens/day cap (the thing
that caused the earlier outage). Your paid Anthropic + OpenAI limits are far higher.

---

## 8. How to use it best (playbook)

- **Put docs in the right scope.** Upload to a **workspace** if teammates should be able to
  ask about it; keep it **Personal** otherwise. Workspace docs are searchable by every
  member.
- **Set sensitivity deliberately.** Default `internal` is safe. Use `confidential` for
  anything that must never auto-surface in a call. Use `public` for reference material you
  *want* the bot to volunteer.
- **Pin a doc to a meeting** when you want the bot to proactively reference it during that
  specific call (this is what lets `internal` docs surface live).
- **Ask specific questions in chat.** The more concrete the question, the better retrieval
  works — and follow-ups like "and for Q3?" are fine, the rewriter resolves them from
  context.
- **Lean on meeting memory.** You don't need to upload transcripts — past meetings are
  auto-indexed. "What did we commit to in the planning meeting?" works out of the box.
- **Trust the Sources cards, not just the prose.** If the answer matters, glance at the
  Sources cards — they're the real retrieved chunks. If you see a **conflict banner**, two
  of your docs disagree: that's a signal to delete/update the stale one.
- **If it says it doesn't know,** that's the grounding working — it would rather fall back
  to web search (or tell you) than invent an answer.

---

## 9. Tuning knobs (env flags)

- `PRISM_RERANKER_ENABLED` (default `1`) — Phase 4 reranking. Set `0` for emergency
  rollback / latency debugging.
- `PRISM_QUERY_REWRITE_ENABLED` (default `1`) — Phase 5 query rewriting. Set `0` to disable.
- Both are **on** for the on-demand path and **off** for proactive regardless, so the live
  bot always stays fast.
- Scores: on-demand `min_score=0.75`, proactive `min_score=0.85`. Raising a threshold =
  fewer but surer results; lowering = more recall, more noise.

---

## 10. Known limitations / gotchas

- **Proactive is conservative by design** — it stays quiet unless quite confident (0.85)
  and respects cooldowns, so it won't surface on every tangentially related line. That's
  intentional, not a bug.
- **Reranker/rewriter add LLM hops** — they cost ~latency + tokens on the on-demand path
  (~800ms budget). The proactive path skips them to stay ~150ms.
- **Quality depends on chunking** — extremely tabular or image-heavy PDFs retrieve worse
  than prose; OCR helps but isn't perfect.
- **Embeddings are OpenAI-hosted** — embedding ingestion needs `OPENAI_API_KEY` and is
  subject to OpenAI quota (there's a circuit-breaker that pauses ingestion on quota
  exhaustion rather than failing hard).
- **Post-AWS TODO** — a local cross-encoder reranker (BGE) is noted for when there's RAM
  headroom, to cut the LLM rerank hop.

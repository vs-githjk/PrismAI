# PrismAI — Meeting Intelligence

One meeting. A graph of specialized AI agents. Instant clarity.

PrismAI turns any meeting — pasted, uploaded, or captured live by an in-meeting bot — into
structured intelligence: summaries, action items, decisions, sentiment, speaker coaching,
follow-up emails, calendar suggestions, and a meeting quality score. It's powered by a
**two-tier parallel agent graph** (LangGraph), with a real-time meeting bot, a vector RAG
knowledge base, and shared team workspaces on top.

Frontend deploys to Vercel; backend runs on Render.

---

## How it works

```
Input (paste / upload / record / live bot)
  → POST /analyze-stream (SSE)
  → LangGraph StateGraph: deterministic router → Tier-1 agents (parallel)
       → barrier (merge + link) → Tier-2 agents (parallel, context-enriched)
  → each agent streams its result as it finishes → UI merges incrementally
```

Routing is **deterministic** (no LLM in the hot path) — every relevant agent runs, gated only
by simple rules (e.g. sentiment needs 2+ speakers). Agents run in two parallel tiers so Tier-2
agents (email, calendar, suggested actions) see Tier-1 results as context.

| Tier | Agent | Output |
|---|---|---|
| 1 | Summarizer | TL;DR + topics |
| 1 | Action Items | Who owns what, with resolved due dates |
| 1 | Decisions | What was agreed, ranked by importance |
| 1 | Sentiment | Tone label + score + tension moments (2+ speakers) |
| 1 | Speaker Coach | Talk-time balance + coaching notes |
| 1 | Meeting Classifier | Detects meeting type (standard / pitch / interview / article) |
| 1.5 | Decision Linker | Maps decisions ↔ action items (bidirectional) |
| 2 | Email Drafter | Ready-to-send follow-up email, from the owner's POV |
| 2 | Calendar Suggester | Follow-up meeting + agenda + attendees |
| 2 | Health Score | 0–100 meeting quality with breakdown + improvement tip |
| 2 | Content Analyst | Deep per-type rubric for pitches / interviews / articles |
| 2 | Action Executor | One-click actions into Jira / Linear / Slack / Gmail / Calendar |

Plus a **Chat** interface (per-meeting, cross-meeting, and tool-calling) to ask questions in
natural language — with image analysis and grounded citations from your knowledge base.

## Input methods

- **Paste** a transcript directly
- **Upload** an audio/text file
- **Record** live audio in the browser
- **Live bot** — PrismAI joins your Google Meet / Zoom / Teams call (via Recall.ai + Deepgram
  `nova-3`), transcribes in real time, answers on request, and analyzes the meeting when it ends

## Beyond analysis

- **Real-time meeting bot** — live transcription, wake-word commands, personas, private "catch me up," and a shareable live view
- **Knowledge base (RAG)** — hybrid vector + BM25 search over your docs *and* past transcripts, with reranking, conflict detection, and citations
- **Team workspaces** — shared meetings, invites, per-workspace briefs, and bot de-duplication
- **Per-workspace integrations** — an owner connects Jira/Slack/etc. once for the workspace; every meeting's tickets and messages route to the team's tools (with a personal fallback), configured with a Personal/Workspace scope switcher
- **Stand-in proxy** — have PrismAI represent you in a meeting you can't attend, then brief you back afterward on what happened for you (decisions, answers to what you asked, tasks now yours)
- **Recording playback** — click any transcript line to seek the recording

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + Tailwind CSS → Vercel |
| Backend | FastAPI (Python) → Render |
| Orchestration | LangGraph (two-tier parallel StateGraph) |
| Inference | Claude Haiku 4.5 (agents + RAG) · GPT-4o-mini (chat, live bot, fallback) |
| Embeddings / RAG | OpenAI `text-embedding-3-small` + pgvector + BM25 |
| Meeting bot | Recall.ai + Deepgram `nova-3` |
| Data / Auth / Storage | Supabase (Postgres + pgvector + Auth + Storage) |
| Web search | Tavily |

## Run locally

```bash
# Backend
cp backend/.env.example backend/.env   # fill in the keys below
cd backend && pip install -r requirements.txt && uvicorn main:app --reload --port 8001

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Key environment variables (see `backend/.env.example` for the full list):

- `ANTHROPIC_API_KEY` — agents, RAG, memory (primary inference)
- `OPENAI_API_KEY` — chat, live bot, embeddings, cross-provider fallback
- `SUPABASE_URL` / `SUPABASE_KEY` — database, auth, storage (service-role key)
- `RECALL_API_KEY` — the live meeting bot (optional; only for the bot flow)
- `TAVILY_API_KEY` — web-search fallback in RAG (optional)

For the live meeting bot, local testing also needs a public HTTPS URL for the Recall webhooks
(`POST /recall-webhook`, `POST /realtime-events`). Set `WEBHOOK_BASE_URL` in `backend/.env` to
that public URL before using the bot flow.

## Deploy

- **Frontend → Vercel:** import the repo, keep the project root at the repo root (uses `vercel.json`), set `VITE_API_URL` to your Render backend (e.g. `https://meeting-copilot-api.onrender.com`), deploy.
- **Backend → Render:** auto-deploys from `render.yaml` on push to `main` (service `meeting-copilot-api`).

Database migrations live in `supabase/` — run `python supabase/migrate.py` (needs `DATABASE_URL`), or paste the SQL files into the Supabase SQL editor in order.

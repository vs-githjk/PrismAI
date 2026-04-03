# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 7 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into 7 colors (agents).

**Live URLs:**
- Frontend: GitHub Pages (`https://vs-githjk.github.io/Agentic-Meeting-Copilot/`)
- Backend: Render.com (`https://meeting-copilot-api.onrender.com`)

> Note: The Render service is named `meeting-copilot-api` — this is the real URL. The display name in the Render dashboard was changed to `agentic-meeting-copilot` but the URL did not change (Render locks URLs to creation-time name).

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS |
| Backend | FastAPI + uvicorn (Python 3.11) |
| AI | Groq API — LLaMA 3.3-70b (agents/chat) + Whisper large-v3 (transcription) |
| Meeting Bot | Recall.ai (joins live calls, records, returns transcript) |
| Database | Supabase (Postgres) — meetings + chats persistent storage |
| Frontend Hosting | GitHub Pages via GitHub Actions |
| Backend Hosting | Render.com free tier |

---

## File Structure

```
/
├── backend/
│   ├── main.py                    # FastAPI app — all endpoints, AGENT_MAP, DEFAULT_RESULT
│   ├── agents/
│   │   ├── orchestrator.py        # Decides which agents to run
│   │   ├── summarizer.py
│   │   ├── action_items.py
│   │   ├── decisions.py
│   │   ├── sentiment.py
│   │   ├── email_drafter.py
│   │   ├── calendar_suggester.py
│   │   └── health_score.py
│   ├── requirements.txt
│   └── .env.example               # Template: GROQ_API_KEY, RECALL_API_KEY, WEBHOOK_BASE_URL, SUPABASE_URL, SUPABASE_KEY
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root: layout, input, result rendering, history, speaker modal, share
│   │   ├── index.css              # Tailwind + custom animations
│   │   └── components/
│   │       ├── ChatPanel.jsx      # Chat interface + agent intent detection + chat history
│   │       ├── AgentTags.jsx      # Badges showing which agents ran
│   │       ├── HealthScoreCard.jsx
│   │       ├── SummaryCard.jsx
│   │       ├── ActionItemsCard.jsx  # Checkboxes persist to Supabase via PATCH /meetings/{id}
│   │       ├── DecisionsCard.jsx
│   │       ├── SentimentCard.jsx
│   │       ├── EmailCard.jsx
│   │       └── CalendarCard.jsx
│   └── vite.config.js             # base: '/Agentic-Meeting-Copilot/'
├── .github/workflows/deploy.yml   # Push to main → build frontend → GitHub Pages
├── render.yaml                    # Render.com backend config (service name: meeting-copilot-api)
├── PRISM_AI_CONTEXT.md            # This file
└── IMPROVEMENT_SPECS_DRAFT_1.md   # Prioritized improvement roadmap — read this alongside this file

> **For incoming LLMs:** Read both docs first for orientation, then read the specific source files relevant to your task before writing any code. The docs give direction; the code gives the patterns to follow.
```

---

## The 7 Agents (ROYGBIV)

| Color | Agent | Runs | Output Key | Shape |
|---|---|---|---|---|
| 🔴 Red | `summarizer` | Always | `summary` | `string` |
| 🟠 Orange | `action_items` | Always | `action_items` | `[{ task, owner, due, completed }]` |
| 🟡 Yellow | `decisions` | Always | `decisions` | `[{ decision, owner, importance: 1-3 }]` |
| 🟢 Green | `sentiment` | Only if tension/conflict | `sentiment` | `{ overall, score, arc, notes, speakers:[{name,tone,score}], tension_moments:[] }` |
| 🔵 Blue | `email_drafter` | Always | `follow_up_email` | `{ subject, body }` |
| 🟣 Indigo | `calendar_suggester` | Only if follow-up discussed | `calendar_suggestion` | `{ recommended, reason, suggested_timeframe }` |
| 💜 Violet | `health_score` | Always | `health_score` | `{ score, verdict, badges:[], breakdown:{clarity,action_orientation,engagement} }` |

Note: `action_items` now includes a `completed` boolean field that persists via PATCH /meetings/{id}.

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe |
| POST | `/analyze` | `{ transcript, speakers? }` → full result object (non-streaming) |
| POST | `/analyze-stream` | `{ transcript, speakers? }` → SSE stream, one event per agent as it completes |
| POST | `/transcribe` | `multipart/form-data: file` → `{ transcript }` via Whisper |
| POST | `/join-meeting` | `{ meeting_url }` → `{ bot_id, status }` |
| GET | `/bot-status/{bot_id}` | Poll bot lifecycle status |
| POST | `/recall-webhook` | Recall.ai sends bot events here |
| POST | `/agent` | `{ agent, transcript, instruction }` → single agent output |
| POST | `/chat` | `{ message, transcript }` → `{ response }` |
| GET | `/meetings` | List meetings (optional `?q=` search by title) |
| POST | `/meetings` | Save/upsert a meeting |
| PATCH | `/meetings/{id}` | Update meeting result (used for action item checkbox state) |
| DELETE | `/meetings/{id}` | Delete meeting (cascades to chats in DB) |
| GET | `/share/{token}` | Public read-only meeting result by share token |
| GET | `/chats` | All chats as `{ meeting_id: messages[] }` map (bulk, avoids N+1) |
| GET | `/chats/{meeting_id}` | Single chat messages |
| POST | `/chats/{meeting_id}` | Save/upsert chat messages |
| DELETE | `/chats/{meeting_id}` | Delete chat for a meeting |

---

## Supabase Schema

```sql
create table meetings (
  id bigint primary key,           -- Date.now() from frontend
  date text not null,
  title text,
  score int,
  transcript text,
  result jsonb,
  share_token text unique,         -- 16-char hex, generated on save
  created_at timestamptz default now()
);

create table chats (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  messages jsonb not null default '[]',
  updated_at timestamptz default now()
);
```

`on delete cascade` means deleting a meeting automatically deletes its chat — no extra frontend call needed.

---

## Speaker Identification

Before analysis runs, `extractSpeakers()` in App.jsx scans the transcript for `Name:` patterns and pre-fills a modal. User assigns roles (e.g. "Engineering Lead"). On Analyze, the backend prepends:

```
Meeting participants:
  - Sarah: Engineering Lead
  - Mike: Product Manager
```

...to the transcript before any agent sees it. All 7 agents benefit automatically. If no names are detected, the modal is skipped entirely.

---

## Streaming Analysis

The frontend calls `POST /analyze-stream` (not `/analyze`). The backend uses SSE + `asyncio.wait(FIRST_COMPLETED)` — each agent streams its result the moment it finishes. Frontend reads the stream chunk by chunk, calling `setResult(prev => ({ ...prev, ...chunk }))` so cards appear one by one. `saveToHistory` is called on `[DONE]`.

SSE event format:
```
data: {"agents_run": ["summarizer", "action_items", ...]}
data: {"agent": "summarizer", "summary": "..."}
data: {"agent": "action_items", "action_items": [...]}
data: [DONE]
```

---

## Shareable Links

When a meeting is saved, a `share_token` (16-char hex via `crypto.randomUUID()`) is generated and stored with the meeting. A **Share** button appears in the results header — clicking it copies:

```
https://vs-githjk.github.io/Agentic-Meeting-Copilot/#share/{token}
```

On page load, App.jsx checks `window.location.hash` for `#share/{token}`. If matched, it fetches `GET /share/{token}` and renders a read-only view with all 7 cards. No router needed — hash-based routing works on GitHub Pages.

---

## Chat System

`ChatPanel.jsx` has two modes:

1. **Regular chat** → `POST /chat` with message + transcript → LLM answers
2. **Agent intent** → detected via regex in `detectAgentIntent()`. If matched, calls `POST /agent` with the instruction appended to the transcript.

**History dropdown:** Shows past meeting chats. Clicking one enters "viewing mode" — a blue banner with "← Back to current chat". While viewing, input is enabled and uses that meeting's transcript. New messages are saved back to that session. Agent re-run intents are disabled in viewing mode (no live cards to update).

**Deleting a chat session** in the dropdown only removes the chat — the meeting is preserved.

**Chat persistence:** Messages saved to `POST /chats/{meetingId}` on every state change.

---

## Persistent State

| What | Where | Notes |
|---|---|---|
| Meeting history | Supabase `meetings` table | No cap, survives browser clears |
| Chat per meeting | Supabase `chats` table | Cascade-deleted with meeting |
| Action item completion | Inside `result` JSON in `meetings` table | Patched via PATCH /meetings/{id} |
| Bot status during call | `bot_store: dict` (in-memory) | Lost on Render restart |
| Share token | `meetings.share_token` column | Generated at save time |

On startup, App.jsx fetches `/meetings` and auto-loads the most recent meeting (transcript + result + chat).

---

## Environment Variables

| Var | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | All LLM calls + Whisper transcription |
| `RECALL_API_KEY` | Yes (bot feature only) | Recall.ai meeting bot |
| `WEBHOOK_BASE_URL` | Yes (bot feature only) | Callback URL for Recall webhooks |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase service_role key (bypasses RLS) |
| `VITE_API_URL` | Frontend build only | Points frontend at backend (GitHub secret) |

---

## Deployment

**Frontend:** Any push to `main` triggers `.github/workflows/deploy.yml`:
- `npm ci` → `npm run build` (with `VITE_API_URL` secret) → upload to GitHub Pages

**Backend:** Render.com auto-deploys from `render.yaml` on push to `main`.
- Free tier spins down after inactivity → cold start can take 30-60s
- `SUPABASE_URL` and `SUPABASE_KEY` must be set manually in Render dashboard (not in render.yaml)

---

## Known Issues / Watch Out For

- **Render free tier sleeps** — first request after inactivity will be slow. Not a bug.
- **Bot store is in-memory** — if Render restarts mid-meeting, `bot_store` is lost. Needs persistent storage to fix properly.
- **Sentiment is conditional** — won't appear for neutral/positive meetings by design.
- **`decisions` importance ranking** — 1 = critical, 2 = significant, 3 = minor. Sorted ascending in `DecisionsCard.jsx`.
- **Share button only appears after analysis** — `shareToken` state is null until a meeting is saved. Loading from history restores the token.
- **SSE and Render free tier** — streaming works but Render free tier may buffer SSE. `X-Accel-Buffering: no` header is set to mitigate.

---

## Product Vision (from improvement spec)

The stated goal is to evolve PrismAI from a **static AI demo** into an **Agentic Meeting Operating System** — a system that understands meetings deeply, maintains memory across sessions, and takes actions on behalf of the user. The key gaps identified:

1. **No agentic behavior** — the app analyzes passively but never acts. It surfaces "Mike owns the roadmap update by Thursday" but doesn't offer to do anything about it.
2. **No cross-meeting memory** — meetings are isolated; no ability to ask "what did I commit to last month?" or see trends.
3. **No proactive suggestions** — after analysis, no nudges like "3 action items detected — generate a Slack summary?" appear.
4. **No external tool integrations** — Slack, Google Docs, Calendar all blocked on auth (see #6).
5. **Highlight-based interaction** — select transcript text → ask AI a contextual question. Not yet built.
6. **Friendly error states** — Groq 429s and failures surface as raw strings.

What is **already built** that the spec asks for (do not re-implement):
- Streaming responses, skeleton cards, step-by-step card appearance ✓
- All 7 analysis cards ✓
- AI chat with agent intent detection ✓
- Persistent storage (Supabase) ✓
- Meeting history + search ✓
- Audio upload + live recording ✓
- Export (Markdown, PDF, copy) ✓

---

## Recent Changes (in order, most recent last)

### Share link flash fix
`INITIAL_SHARE_TOKEN` is computed synchronously at module level (before first render). `shareMode` initializes as `'loading'` when a token is detected, so the full app UI never flashes. The meetings auto-load `useEffect` bails out for share links.

### Landing hero screen
`LandingScreen` component shown to first-time visitors only (gated by `localStorage.getItem('prism_visited')`). Two CTAs:
- **"See it in action"** → fade-out → app mounts → `isDemoMode = true` → `runAnalysis` fires automatically on `SAMPLE_TRANSCRIPT` → blue demo banner appears with "Use my own transcript →" dismiss
- **"Use my own transcript"** → fade-out → normal empty app

Key details:
- `exitLanding(demo)` sets `prism_visited` in localStorage, starts a 370ms CSS fade, then unmounts the landing
- `runAnalysis` takes an optional `transcriptOverride` param so demo can fire before React state updates
- Share links skip the landing entirely

### Bug fixes and code quality pass

A full review of the codebase identified and fixed the following:

**Frontend fixes:**
- `HealthScoreCard` — `!healthScore.score` guard hid the card when score was 0 (valid for a terrible meeting). Fixed to check `score === undefined || score === null`.
- `CalendarCard` — only rendered if `recommended === true`. If the model returns content but omits the boolean, card was silently hidden. Now renders if `recommended` is true OR `reason` is present.
- `DecisionsCard` — filtered out owners named `'Team'` assuming it was a placeholder. Removed — the model's output should be trusted.
- `SentimentCard` — tension moment bullet used `⚡` emoji (won't render on some systems). Replaced with an SVG bolt icon.
- `App.jsx` — "New Meeting" button didn't clear `initialMessages`, so old chat bled into new sessions. Added `setInitialMessages([])`.
- `App.jsx` — history search fired a fetch on every keystroke. Added 300ms debounce via `historySearchDebounceRef`.
- `App.jsx` — SSE stream reader had no timeout; frontend could hang forever if Render stalled. Added `AbortController` with 120s timeout and user-facing "Analysis timed out" error message.
- `App.jsx` — `exportPDF` used deprecated `document.write()`. Replaced with Blob URL approach.
- `App.jsx` — `toggleActionItem` silently diverged on persist failure. Now reverts the optimistic update if the PATCH fails.
- `ChatPanel.jsx` — chat persistence `.catch(() => {})` fully swallowed errors. Now logs `console.warn` so failures are diagnosable.
- `index.css` — `.gradient-text` had no fallback for Firefox (text went invisible). Added `color: #38bdf8` fallback.
- `index.css` — `bg-breathe` animation on `html,body` had no `will-change` hint. Added `will-change: background-image`.

**Backend fixes:**
- All 7 agents + orchestrator had an identical copy of `_strip_fences()`. Extracted to `backend/agents/utils.py` as `strip_fences()`. All agents now `from .utils import strip_fences`.
- `render.yaml` — `WEBHOOK_BASE_URL` pointed to the wrong URL (`agentic-meeting-copilot.onrender.com`). Fixed to `meeting-copilot-api.onrender.com`.
- `requirements.txt` — no version constraints. Added `>=` floor pins to prevent breaking upgrades.

### Landing page always shown + docs update
- `LandingScreen` now shows on every visit (not just first-time). Removed `localStorage.getItem('prism_visited')` gate from `showLanding` init and removed the `localStorage.setItem` call in `exitLanding`. Share links still bypass it via `!INITIAL_SHARE_TOKEN`.
- Added `IMPROVEMENT_SPECS_DRAFT_1.md` — prioritized 10-item roadmap with implementation details and UI bug table.
- Updated `PRISM_AI_CONTEXT.md` file structure to reference the improvement spec, with a note for incoming LLMs to read both docs before touching code.

### Bug fixes (second pass)
- `App.jsx` — SSE while loop didn't exit on `[DONE]`; `break` only escaped the inner `for` loop, leaving the reader spinning. Added `streamDone` flag to break the outer `while` loop.
- All 6 standard agents (`summarizer`, `action_items`, `decisions`, `sentiment`, `email_drafter`, `calendar_suggester`) — removed unreachable `return` fallback after the `for` loop. The `raise HTTPException` path always fires first on double failure, making the fallback dead code.

### UI overhaul
- **2-col grid** for results: Health (full width) → Summary+Sentiment → Actions+Decisions → Email+Calendar
- **Skeleton shimmer cards** shown while agents are streaming (replaces blank waiting)
- **Results header** shows `Xs · ~Ym saved` time stat after `[DONE]`  — `analysisStartRef` tracks start time, elapsed stored in `analysisTime` state
- **Mobile bottom tab bar** — `mobileTab` state (`'input'` | `'results'`), fixed bottom nav, auto-switches to results tab on `[DONE]`
- **Typography** — card titles changed from `uppercase tracking-widest text-xs` to `text-sm font-semibold`; summary body to `text-[15px]`; health verdict bolder
- **Email card** — `<pre>` monospace replaced with styled `<div>` for readable body text
- **SkeletonCard** fully restyled to match dark theme with shimmer accent line

---

## Remaining Roadmap (priority order)

### #1 — Proactive suggestions panel (closes the "agentic behavior" gap)
After analysis completes, show a banner/panel with 2-3 contextual CTAs based on what was found. Examples:
- "3 action items detected — draft a Slack update?" → calls email_drafter with a Slack-format prompt
- "Follow-up meeting recommended for next week — add to calendar?" → deep link to Google Calendar with pre-filled subject/time
- "Unresolved tension detected — want a coaching tip on facilitation?"
Implementation: a `ProactiveSuggestions` component that reads `result` after `[DONE]` and renders relevant prompts. Each prompt fires `POST /agent` with a targeted instruction.

### #2 — Cross-meeting chat / multi-meeting intelligence
Extend the chat interface to answer questions across all stored meetings:
- "What did I commit to last month?"
- "Which meetings had the lowest health scores?"
- "Summarize the last 3 meetings about the mobile app"
Backend: add a `POST /chat/global` endpoint that fetches relevant meetings from Supabase (simple text search on `title` + `result` JSON) and passes them as context to the LLM.
Frontend: detect "cross-meeting" intent in `detectAgentIntent()` (e.g., "last 3 meetings", "across all meetings") and route to the new endpoint.

### #3 — Export options
Copy to Notion, download as PDF, send to Slack. The output is only as good as where it lands. Priority: PDF download + copy-as-markdown (markdown export already exists via `exportMarkdown()`). Slack/Notion need OAuth which blocks on auth (#6).

### #4 — Meeting health trend chart
Graph health scores over time across meetings. Data is already in Supabase (`meetings.score`). Needs a chart library (recommend `recharts` — already React-friendly) and a new view/modal. This creates habit/retention — users start optimizing their score.

### #5 — Better share page
Right now the share page is just a card dump at `/share/{token}`. Needs:
- Branded header with PrismAI logo + "Shared by" context
- CTA: "Analyze your own meeting →" more prominent
- OG meta tags for link previews (requires SSR or a meta-tag injection hack for GitHub Pages)

### #6 — Auth (Google SSO)
Use Supabase Auth (already in the stack — just needs `supabase.auth.signInWithOAuth`). This is the unlock for team features. Until this lands, all data is browser-anonymous. Add to both backend (JWT validation middleware) and frontend (auth context + protected routes).

### #7 — Team workspace
After auth: meetings scoped to `user_id`, shared workspaces, team history. Requires schema migration: add `user_id` column to `meetings` and `chats` tables.

### #8 — Model fallback
Each agent's `run()` catches Groq errors and retries with OpenAI (`gpt-4o-mini`) or Anthropic (`claude-haiku-4-5`). Add `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` to env vars. The agent pattern is identical — just swap the client and model name.

### #9 — Bot store persistence
`bot_store` dict in `main.py` is in-memory — lost on Render restart. Move to a `bots` table in Supabase: `id`, `status`, `result`, `error`, `transcript`, `created_at`.

### #10 — Mobile polish
Tab bar is in place. Still needed: transcript textarea height on mobile, chat panel sizing, share page mobile layout.

### #11 — Friendly error states
Groq 429s, empty transcripts, network failures — currently surface as raw error strings. Need designed error cards with retry CTAs.

### #12 — "Time saved" social sharing
After analysis: show a shareable image/card with the time saved stat. People screenshot and share this — it's a growth loop.

---

## Agent Code Pattern (for reference)

`_strip_fences` is now a shared utility in `backend/agents/utils.py`. Import it instead of defining it locally:

```python
import json, os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a ___. ..."
    'Return ONLY valid JSON: { "key": ... }. '
    "If the transcript contains a [User instruction: ...] line, follow it exactly."  # only if re-runnable via chat
)

async def run(transcript: str) -> dict:
    for attempt in range(2):
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
        )
        raw = response.choices[0].message.content
        try:
            return json.loads(strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise HTTPException(status_code=500, detail="agentname: failed to parse JSON after retry")
    return {"key": default_value}
```

### Adding a New Agent — Checklist

1. Create `backend/agents/yourname.py` — follow the pattern above
2. Import it in `backend/main.py`
3. Add to `AGENT_MAP` and `AGENT_RESULT_KEY` in `main.py`
4. Add default value to `DEFAULT_RESULT` in `main.py` (and mirror in `frontend/src/App.jsx`)
5. Add to both result-builder loops in `main.py` (~lines 88 and ~294)
6. Add to `ALL_AGENTS` list in `orchestrator.py`
7. Add guardrail in `orchestrator.py` if it should always run
8. Add to `AGENTS_META` in `App.jsx` with icon + gradient
9. Add to `AGENT_CONFIG` in `AgentTags.jsx` with ROYGBIV color
10. Create `YournameCard.jsx` in `frontend/src/components/`
11. Import and place card in `App.jsx` (both desktop and mobile layouts)

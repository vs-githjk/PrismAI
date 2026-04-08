# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 7 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into 7 colors (agents).

**Live URLs:**
- Frontend: Vercel (`https://agentic-meeting-copilot.vercel.app/`)
- Backend: Render.com (`https://meeting-copilot-api.onrender.com`)
- GitHub: `https://github.com/vs-githjk/PrismAI` (repo was renamed — update your remote: `git remote set-url origin https://github.com/vs-githjk/PrismAI.git`)

> Note: The Render service is named `meeting-copilot-api` — this is the real URL. The display name in the Render dashboard was changed but the URL did not (Render locks URLs to creation-time name).

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS |
| Backend | FastAPI + uvicorn (Python 3.11) |
| AI | Groq API — LLaMA 3.3-70b (agents/chat) + Whisper large-v3 (transcription) |
| Auth | Supabase Auth — Google SSO via `supabase.auth.signInWithOAuth` |
| Meeting Bot | Recall.ai (joins live calls, records, returns transcript) |
| Database | Supabase (Postgres) — meetings + chats + user scoping |
| Frontend Hosting | Vercel |
| Backend Hosting | Render.com free tier |

---

## File Structure

```
/
├── backend/
│   ├── main.py                    # FastAPI app shell — middleware + router wiring only
│   ├── auth.py                    # require_user_id() dependency + shared Supabase client
│   ├── analysis_service.py        # AGENT_MAP, AGENT_RESULT_KEY, DEFAULT_RESULT, run_full_analysis, merge_agent_results
│   ├── analysis_routes.py         # /analyze, /analyze-stream, /transcribe
│   ├── storage_routes.py          # /meetings, /chats, /share, /insights — all auth-gated
│   ├── recall_routes.py           # /join-meeting, /bot-status/{id}, /recall-webhook — intentionally unauthenticated
│   ├── chat_routes.py             # /chat, /chat/global (auth-gated), /agent (unauthenticated)
│   ├── export_routes.py           # /export/slack, /export/notion
│   ├── cross_meeting_service.py   # Pure Python: derives insights from meeting history (no LLM)
│   ├── calendar_resolution.py     # Resolves relative date phrases ("next Thursday") to ISO dates
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── summarizer.py
│   │   ├── action_items.py
│   │   ├── decisions.py
│   │   ├── sentiment.py
│   │   ├── email_drafter.py
│   │   ├── calendar_suggester.py
│   │   ├── health_score.py
│   │   └── utils.py               # strip_fences() — shared by all agents
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root: all state, input modes, results, landing, share
│   │   ├── index.css              # Tailwind + custom animations + height-aware landing breakpoints
│   │   ├── main.jsx
│   │   ├── lib/
│   │   │   ├── supabase.js        # Supabase client (from VITE_SUPABASE_* env vars, null if unconfigured)
│   │   │   └── api.js             # apiFetch() — wraps fetch, auto-attaches Bearer token from session
│   │   └── components/
│   │       ├── ChatPanel.jsx      # Chat + agent intent + global intent + history dropdown
│   │       ├── AgentTags.jsx
│   │       ├── HealthScoreCard.jsx
│   │       ├── SummaryCard.jsx
│   │       ├── ActionItemsCard.jsx
│   │       ├── DecisionsCard.jsx
│   │       ├── SentimentCard.jsx
│   │       ├── EmailCard.jsx
│   │       ├── CalendarCard.jsx
│   │       ├── CrossMeetingInsights.jsx  # Insights panel — shown when signed in with 2+ meetings
│   │       ├── ScoreTrendChart.jsx       # Health score over time (recharts)
│   │       ├── ProactiveSuggestions.jsx
│   │       ├── IntegrationsModal.jsx     # Slack + Notion config
│   │       ├── ErrorCard.jsx
│   │       └── SkeletonCard.jsx
│   ├── .env.example
│   └── vite.config.js
├── render.yaml
├── PRISM_AI_CONTEXT.md            # This file
└── IMPROVEMENT_SPECS_DRAFT_1.md   # Prioritized roadmap
```

> **For incoming LLMs:** Read both docs first, then read the specific source files for your task. Never assume the docs match the code exactly — the code is authoritative.

---

## The 7 Agents (ROYGBIV)

| Color | Agent | Runs | Output Key | Shape |
|---|---|---|---|---|
| 🔴 Red | `summarizer` | Always | `summary` | `string` |
| 🟠 Orange | `action_items` | Always | `action_items` | `[{ task, owner, due, completed }]` |
| 🟡 Yellow | `decisions` | Always | `decisions` | `[{ decision, owner, importance: 1-3 }]` |
| 🟢 Green | `sentiment` | Only if tension/conflict | `sentiment` | `{ overall, score, arc, notes, speakers:[{name,tone,score}], tension_moments:[] }` |
| 🔵 Blue | `email_drafter` | Always | `follow_up_email` | `{ subject, body }` |
| 🟣 Indigo | `calendar_suggester` | Only if follow-up discussed | `calendar_suggestion` | `{ recommended, reason, suggested_timeframe, resolved_date, resolved_day }` |
| 💜 Violet | `health_score` | Always | `health_score` | `{ score, verdict, badges:[], breakdown:{clarity,action_orientation,engagement} }` |

`calendar_suggestion` now includes `resolved_date` and `resolved_day` — resolved by `calendar_resolution.py` from the agent's natural language timeframe before returning to the frontend.

---

## API Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | No | Liveness probe |
| POST | `/analyze` | No | Full analysis (non-streaming) |
| POST | `/analyze-stream` | No | SSE stream, one event per agent |
| POST | `/transcribe` | No | Whisper audio transcription |
| POST | `/agent` | No | Single agent re-run (used by chat intent) |
| POST | `/chat` | No | Chat with transcript context |
| POST | `/chat/global` | **Yes** | Chat across all user's saved meetings |
| GET | `/meetings` | **Yes** | List user's meetings |
| POST | `/meetings` | **Yes** | Save/upsert a meeting |
| PATCH | `/meetings/{id}` | **Yes** | Update result (action item checkboxes) |
| DELETE | `/meetings/{id}` | **Yes** | Delete meeting (cascades to chats) |
| GET | `/insights` | **Yes** | Cross-meeting intelligence (pure Python, no LLM) |
| GET | `/share/{token}` | No | Public read-only meeting by share token |
| GET | `/chats` | **Yes** | All chats as `{ meeting_id: messages[] }` map |
| GET | `/chats/{meeting_id}` | **Yes** | Single meeting's chat |
| POST | `/chats/{meeting_id}` | **Yes** | Save/upsert chat messages |
| DELETE | `/chats/{meeting_id}` | **Yes** | Delete chat |
| POST | `/join-meeting` | No | Start Recall.ai bot |
| GET | `/bot-status/{bot_id}` | No | Poll bot lifecycle + result |
| POST | `/recall-webhook` | No | Recall.ai event callbacks |
| POST | `/export/slack` | No | Send recap to Slack webhook |
| POST | `/export/notion` | No | Export full meeting to Notion |

**Auth pattern:** `require_user_id` in `auth.py` reads `Authorization: Bearer <token>`, validates against Supabase, returns `user_id`. All auth-gated endpoints scope their DB queries to that `user_id`. `/analyze`, `/chat`, `/agent` are intentionally unauthenticated so the demo flow works before sign-in.

---

## Supabase Schema

```sql
create table meetings (
  id bigint primary key,           -- Date.now()-based ID from frontend
  user_id uuid references auth.users(id),
  date text not null,
  title text,
  score int,
  transcript text,
  result jsonb,
  share_token text unique,
  created_at timestamptz default now()
);

create table chats (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  user_id uuid references auth.users(id),
  messages jsonb not null default '[]',
  updated_at timestamptz default now()
);

create index on meetings(user_id);
```

Both tables have `user_id`. All queries filter by it. `on delete cascade` means deleting a meeting automatically deletes its chat.

---

## Auth

- Frontend: `frontend/src/lib/supabase.js` initializes the Supabase client from `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`. If either is missing, `supabase` exports as `null` and auth is disabled gracefully.
- Frontend: `frontend/src/lib/api.js` exports `apiFetch()` — always use this instead of raw `fetch()`. It auto-attaches `Authorization: Bearer <token>` from the active session.
- Frontend: `App.jsx` — `signInWithGoogle()` calls `supabase.auth.signInWithOAuth({ provider: 'google' })`. `authSession` / `authReady` states gate data loading. On sign-out, history and insights clear.
- **Local workspace on sign-in:** If a user has an unsaved analyzed meeting when they sign in, it is automatically saved to their account.
- Backend: `auth.py` — `require_user_id(request)` validates the Bearer token against Supabase's `/auth/v1/user` endpoint and returns `user_id`. Used as a FastAPI `Depends`.

---

## Streaming Analysis

Frontend calls `POST /analyze-stream`. Backend uses SSE + `asyncio.wait(FIRST_COMPLETED)` — each agent streams its result the moment it finishes. Frontend reads chunk by chunk, calling `setResult(prev => ({ ...prev, ...chunk }))`.

SSE event format:
```
data: {"agents_run": ["summarizer", "action_items", ...]}
data: {"agent": "summarizer", "summary": "..."}
data: {"agent": "action_items", "action_items": [...]}
data: [DONE]
```

`saveToHistory` is called on `[DONE]`. The stream has a 120s `AbortController` timeout.

---

## Cross-Meeting Intelligence

`GET /insights` (auth-gated) fetches the user's last 50 meetings and passes them to `cross_meeting_service.py`, which derives entirely in Python (no LLM call):

- **Top owners** — who has the most action items
- **Ownership drift** — owners carrying load across multiple meetings
- **Recurring themes** — significant terms appearing across meetings
- **Recurring blockers** — action items/summaries flagged with blocker language
- **Resurfacing decisions** — same decision topic appearing in multiple meetings
- **Hygiene issues** — meetings with missing owners or due dates
- **Recommended actions** — up to 4 concrete next steps based on the above

Shown in `CrossMeetingInsights.jsx` when signed in with 2+ meetings.

---

## Chat System

`ChatPanel.jsx` has three modes:

1. **Agent intent** — regex in `detectAgentIntent()`. Calls `POST /agent` with instruction. Updates the relevant result card. Single-level undo stores the previous value of that one key.
2. **Global intent** — regex in `detectGlobalIntent()`. Requires sign-in. Calls `POST /chat/global` which queries user's meeting history and answers across all meetings. Tagged with "⊕ searched all meetings".
3. **Regular chat** — `POST /chat` with message + transcript context.

**History dropdown:** Shows past meeting chats. "Viewing mode" shows a blue banner. Agent re-run intents are disabled in viewing mode.

---

## Recall.ai Bot Flow

1. `POST /join-meeting` → Recall.ai creates a bot, returns `bot_id`. Bot joins the call.
2. Frontend polls `GET /bot-status/{bot_id}` every 4 seconds.
3. When call ends, Recall.ai sends webhook to `POST /recall-webhook` → backend sets status to `processing`, fires `_process_bot_transcript` as a background task.
4. `_process_bot_transcript` fetches transcript from Recall (5 retries), runs `run_full_analysis`, stores result in `bot_store[bot_id]`.
5. Frontend poll sees `done` with transcript + result → saves to history, switches to results view.

**Critical:** `bot_store` is in-memory. Lost on Render restart. If Render restarts mid-meeting, the bot result is gone. This is a known limitation — fix requires moving to a `bots` Supabase table.

**Race condition fix (already applied):** Recall marks their bot `done` before our analysis finishes. The `/bot-status` endpoint guards against this by not letting Recall's `done` override our internal `processing` status until `_process_bot_transcript` actually completes.

---

## Auto-Deliver Recap

`deliverMeetingRecap()` in `App.jsx` fires automatically after a meeting is analyzed if Slack/Notion auto-send is enabled in integrations. Deduped by a `deliveryKey` to prevent double-sends. Configured via `IntegrationsModal.jsx` (settings saved to `localStorage`).

---

## Shareable Links

`share_token` (16-char hex) is generated at save time. Share button copies:
```
https://agentic-meeting-copilot.vercel.app/#share/{token}
```
On load, `App.jsx` checks `window.location.hash` for `#share/{token}`. Share links skip the landing and auth entirely. OG + Twitter meta tags injected dynamically for link previews.

---

## Landing Page

`LandingScreen` shown to first-time visitors only (gated by `sessionStorage`). Two CTAs:
- **"See it in action"** → fade-out → demo mode → auto-runs analysis on a random sample transcript
- **"Use my own transcript"** → fade-out → normal empty workspace

Share links bypass the landing. Logo in the header navigates back to the landing.

**Height-aware CSS breakpoints** in `index.css`: at `max-height: 1000px` the hero scales to 0.78, agent grid hides, headline shrinks. At `max-height: 800px` more aggressive compression. This covers standard laptop viewports.

---

## Environment Variables

| Var | Where | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Render | All LLM calls + Whisper |
| `RECALL_API_KEY` | Render | Recall.ai bot |
| `WEBHOOK_BASE_URL` | Render | `https://meeting-copilot-api.onrender.com` |
| `SUPABASE_URL` | Render | Supabase project URL |
| `SUPABASE_KEY` | Render | **service_role** key — never expose to frontend |
| `VITE_API_URL` | Vercel | Points frontend at backend |
| `VITE_SUPABASE_URL` | Vercel | Same Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Vercel | **anon** key — safe for browser |

---

## Deployment

**Frontend:** Vercel auto-deploys from `main`. Root directory: `frontend`. Build: `npm run build`. Output: `dist`.

**Backend:** Render.com auto-deploys from `render.yaml` on push to `main`.
- Free tier spins down after inactivity → cold start 30-60s
- `SUPABASE_URL`, `SUPABASE_KEY`, `RECALL_API_KEY`, `WEBHOOK_BASE_URL` must be set manually in Render dashboard

---

## Known Issues / Watch Out For

- **Render free tier sleeps** — first request after inactivity is slow. Not a bug.
- **`bot_store` is in-memory** — lost on Render restart. Needs a `bots` Supabase table to fix properly.
- **Bot endpoints are unauthenticated** — `/join-meeting`, `/bot-status`, `/recall-webhook` have no auth. Bot results aren't scoped to a user. Known limitation of the current bot architecture.
- **Sentiment is conditional** — won't appear for neutral/positive meetings by design.
- **`decisions` importance** — 1 = critical, 2 = significant, 3 = minor. Sorted ascending in `DecisionsCard.jsx`.
- **SSE buffering** — `X-Accel-Buffering: no` header is set to mitigate Render free tier SSE buffering.

---

## Remaining Roadmap (priority order)

1. **Bot store persistence** — move `bot_store` to a `bots` Supabase table so restarts don't lose in-flight meetings
2. **Model fallback** — each agent catches Groq 429/errors, retries with `gpt-4o-mini` or `claude-haiku-4-5`. Add `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` to Render.
3. **Aria-label pass** — all icon-only buttons (export, share, history, delete) need `aria-label`
4. **Team workspace** — add `workspace_id` to schema, invite flow, shared history. Blocked on the existing single-user auth being stable first.

---

## Agent Code Pattern

`strip_fences` is in `backend/agents/utils.py`. Import it, don't redefine it:

```python
import json, os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a ___. ..."
    'Return ONLY valid JSON: { "key": ... }. '
    "If the transcript contains a [User instruction: ...] line, follow it exactly."
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
```

### Adding a New Agent — Checklist

1. Create `backend/agents/yourname.py` — follow the pattern above
2. Import it in `backend/analysis_service.py`
3. Add to `AGENT_MAP` and `AGENT_RESULT_KEY` in `analysis_service.py`
4. Add default value to `DEFAULT_RESULT` in `analysis_service.py` (and mirror in `frontend/src/App.jsx`)
5. Add to both result-builder loops in `analysis_routes.py`
6. Add to `ALL_AGENTS` list in `orchestrator.py`
7. Add guardrail in `orchestrator.py` if it should always run
8. Add to `AGENTS_META` in `App.jsx` with icon + gradient
9. Add to `AGENT_CONFIG` in `AgentTags.jsx` with ROYGBIV color
10. Create `YournameCard.jsx` in `frontend/src/components/`
11. Import and place card in `App.jsx` (both desktop and mobile layouts)

---

## Google Calendar Integration (built, partially working)

### What was built
- `backend/calendar_routes.py` — `POST /calendar/connect`, `GET /calendar/events`, `GET /calendar/status`, `DELETE /calendar/disconnect`
- `supabase/calendar_migration.sql` — `user_settings` table (run this in Supabase SQL editor before using calendar features — **already run**)
- `frontend/src/components/UpcomingMeetings.jsx` — panel in Join tab showing upcoming events with meeting links; star/mark events for auto-join
- `IntegrationsModal.jsx` — Calendar tab with connect/disconnect UI and auto-join mode selector
- `App.jsx` — `calendarConnected` state, `connectGoogleCalendar()`, `disconnectCalendar()`, auto-join polling effect, auto-join prompt toast

### Auto-join modes (stored in `localStorage` as `prism_autojoin`)
- `off` (default) — nothing automatic
- `ask` — toast prompt when meeting starts within 5 min
- `auto` — bot joins automatically at ≤2 min
- `marked` — auto-join only starred events (stars stored in `localStorage` as `prism_marked_events`)

### Workspace declutter (done)
- Removed hero blurb card (eyebrow, H1, 4 status pills)
- Removed "Input Quality" nested box (duplicate stats + patronizing copy)
- Replaced with a single slim `Meeting workspace` header

### Calendar connect — BROKEN, needs debugging

**Symptom:** After OAuth flow completes, Calendar tab still shows "Connect Google Calendar" — `calendarConnected` stays false.

**Root cause (best guess):** Supabase does not reliably return `provider_token` in the session when the user is already signed in and re-auths for a new scope. `provider_token` is null → `trySaveProviderToken()` exits early → `/calendar/connect` is never called → backend never stores the token.

**What was tried:**
1. Check `provider_token` in `onAuthStateChange` only → didn't work
2. Check in both `getSession()` and `onAuthStateChange` → didn't work
3. Combined calendar scope into the main `signInWithGoogle` flow with `prompt: consent` → still shows "Connect" button

**Required env vars on Render (must be set):**
- `GOOGLE_CLIENT_ID` — from Google Cloud Console OAuth credentials
- `GOOGLE_CLIENT_SECRET` — same

**Required Supabase config:**
- Google OAuth scopes must include `https://www.googleapis.com/auth/calendar.readonly`
- Test user (the developer's email) must be added in Google Cloud → APIs & Services → OAuth consent screen → Audience → Test users

**Recommended next debugging step:**
Add a temporary `console.log` in `trySaveProviderToken` to log `session?.provider_token` and see if it's null or present. Specifically:

```javascript
const trySaveProviderToken = (session) => {
  console.log('[calendar] provider_token:', session?.provider_token, 'refresh:', session?.provider_refresh_token)
  if (!session?.provider_token) return
  ...
}
```

If `provider_token` is always null, the fix is to NOT go through Supabase for calendar OAuth. Instead:
- Use a direct Google OAuth PKCE flow for calendar (separate from Supabase sign-in)
- Store the returned tokens directly
- This avoids Supabase's session management entirely for the calendar token

**Files involved:**
- `frontend/src/App.jsx` — `trySaveProviderToken`, `signInWithGoogle`, `connectGoogleCalendar`, `calendarConnected` state
- `frontend/src/components/IntegrationsModal.jsx` — Calendar tab UI
- `frontend/src/components/UpcomingMeetings.jsx` — events panel
- `backend/calendar_routes.py` — all calendar API routes
- `supabase/calendar_migration.sql` — already applied

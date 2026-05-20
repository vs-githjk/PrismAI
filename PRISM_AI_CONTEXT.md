# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 8 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into colors (agents).

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
| Landing WebGL | `ogl` (Prism component) + `three.js` (LightPillar component) |
| Fonts | Inter/Nunito/Sora in the Vite app; Geist/Inter packages are also available |

---

## Current Design Direction

PrismAI should read as a shadcn-style product UI with the existing cyan/sky accent, not as a glassmorphism website.

**Core direction:**
- Use shadcn/radix patterns first: solid dark surfaces, crisp borders, clear focus rings, consistent radius, restrained shadow, and predictable controls.
- Keep the current cyan/sky accent family as the brand accent: `#22d3ee`, `#67e8f9`, Tailwind `cyan-*` / `sky-*`, and existing `rgba(14,165,233,...)` states.
- Use the accent for primary CTAs, active navigation, selected states, focus rings, badges, and key data highlights.
- Avoid frosted blur/glass as a default surface treatment for dashboard cards, modals, page sections, nav bars, or result cards.
- Glass-like treatment is still allowed as an accent when it adds emphasis: primary CTA treatment, focused callouts, one-off highlights, or promotional moments.
- The design should feel premium through clarity, spacing, alignment, typography, and specificity rather than heavy glow, blur, or ambient effects.

---

## File Structure

```
/
├── backend/
│   ├── main.py                    # FastAPI app shell — middleware + router wiring only
│   ├── auth.py                    # require_user_id() dependency + shared Supabase client
│   ├── analysis_service.py        # LangGraph two-tier StateGraph + AGENT_MAP, TIER1_AGENTS, TIER2_AGENTS, _GRAPH, run_full_analysis
│   ├── analysis_routes.py         # /analyze, /analyze-stream, /transcribe
│   ├── storage_routes.py          # /meetings, /chats, /share, /insights — all auth-gated; fan-out on workspace save
│   ├── workspace_routes.py        # /workspaces, /invites — workspace CRUD + invite system
│   ├── recall_routes.py           # /join-meeting (workspace dedup), /bot-status/{id}, /recall-webhook
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
│   │   ├── speaker_coach.py       # 8th agent — talk-time % + coaching notes per speaker
│   │   └── utils.py               # strip_fences(), llm_call() — shared by all agents
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Root: all state, input modes, results, landing, live share, dashboard routing
│   │   ├── index.css              # Tailwind + custom animations + height-aware landing breakpoints
│   │   ├── main.jsx
│   │   ├── lib/
│   │   │   ├── supabase.js        # Supabase client (from VITE_SUPABASE_* env vars, null if unconfigured)
│   │   │   ├── api.js             # apiFetch() — wraps fetch, auto-attaches Bearer token from session
│   │   │   └── insights.js        # Cross-meeting insights utility (dashboard)
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
│   │       ├── SpeakerCoachCard.jsx      # 8th agent card — talk-time bars, coaching notes (rose/pink)
│   │       ├── CrossMeetingInsights.jsx  # Insights panel — shown when signed in with 2+ meetings
│   │       ├── ScoreTrendChart.jsx       # Health score over time (recharts)
│   │       ├── ProactiveSuggestions.jsx
│   │       ├── IntegrationsModal.jsx     # Slack + Notion config
│   │       ├── DashboardMcpPage.jsx      # Full dashboard at /dashboard-mcp — MeetingView + IntelligenceView
│   │       ├── MagicBento.jsx            # Bento grid visual component (landing/dashboard)
│   │       ├── DotField.jsx              # Animated dot field background
│   │       ├── Prism.jsx                 # WebGL ray-marched prism background (ogl) — landing page bg
│   │       ├── Prism.css
│   │       ├── LightPillar.jsx           # WebGL light pillar effect (three.js) — landing page corners
│   │       ├── LightPillar.css
│   │       ├── ErrorCard.jsx
│   │       ├── SkeletonCard.jsx
│   │       ├── dashboard/                # Sub-components for DashboardMcpPage
│   │       │   ├── MeetingView.jsx       # Single-meeting view tab
│   │       │   ├── IntelligenceView.jsx  # Cross-meeting intelligence tab
│   │       │   ├── ActionBoard.jsx, DecisionMemory.jsx, HealthTrend.jsx
│   │       │   ├── MeetingsRail.jsx, MetricTile.jsx, OwnerLoad.jsx
│   │       │   ├── StatsCanvas.jsx, StatsHero.jsx, ThemeChips.jsx, Vitals.jsx
│   │       │   └── useCountUp.js, dashboardStyles.js
│   │       └── ui/                       # shadcn primitives
│   │           ├── tabs.jsx, dropdown-menu.jsx, button.tsx, dialog.tsx, text-rotate.tsx
│   ├── vercel.json                # SPA catch-all rewrite — prevents /dashboard-mcp 404 on refresh
│   ├── .env.example
│   └── vite.config.js
├── supabase/
│   ├── action_refs_migration.sql  # action_refs table — closed-loop action item tracking
│   ├── bot_commands_migration.sql
│   ├── chats_unique_migration.sql
│   ├── calendar_migration.sql
│   ├── auth_migration.sql
│   └── tools_migration.sql
├── render.yaml
├── PRISM_AI_CONTEXT.md            # This file
├── IMPROVEMENT_SPEC_2.md          # Feature spec — Features 1-5 status and test instructions
└── IMPROVEMENT_SPECS_DRAFT_1.md   # Original prioritized roadmap
```

> **For incoming LLMs:** Read both docs first, then read the specific source files for your task. Never assume the docs match the code exactly — the code is authoritative.

---

## The 8 Agents

| Color | Agent | Runs | Output Key | Shape |
|---|---|---|---|---|
| 🔴 Red | `summarizer` | Always | `summary` | `string` |
| 🟠 Orange | `action_items` | Always | `action_items` | `[{ task, owner, due, completed }]` |
| 🟡 Yellow | `decisions` | Always | `decisions` | `[{ decision, owner, importance: 1-3 }]` |
| 🟢 Green | `sentiment` | Only if tension/conflict | `sentiment` | `{ overall, score, arc, notes, speakers:[{name,tone,score}], tension_moments:[] }` — `overall` vocab: `collaborative \| aligned \| decision-making \| exploratory \| frictional \| divergent \| rushed \| draining \| neutral`. Per-speaker word counts are pre-computed in Python before the LLM call so the prompt has hard evidence to anchor labels. |
| 🔵 Blue | `email_drafter` | Always | `follow_up_email` | `{ subject, body }` |
| 🟣 Indigo | `calendar_suggester` | Only if follow-up discussed | `calendar_suggestion` | `{ recommended, reason, suggested_timeframe, resolved_date, resolved_day }` |
| 💜 Violet | `health_score` | Always | `health_score` | `{ score, verdict, badges:[], breakdown:{clarity,action_orientation,engagement} }` |
| 🩷 Pink | `speaker_coach` | Always | `speaker_coach` | `{ speakers:[{name,talk_pct,decisions_owned,actions_owned,coaching_note}] }` |

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
| GET | `/meetings` | **Yes** | List meetings — pass `?workspace_id=` to scope to workspace |
| GET | `/meetings/{id}` | **Yes** | Fetch single meeting; workspace-member auth (any member can read) |
| POST | `/meetings` | **Yes** | Save/upsert meeting; accepts `recorded_by_user_id` for dedup'd bots; fans out to workspace members if `workspace_id` set |
| PATCH | `/meetings/{id}` | **Yes** | Update result, title, share_token, workspace_id |
| DELETE | `/meetings/{id}` | **Yes** | Delete meeting (own copy only) |
| POST | `/meetings/{id}/claim-email` | **Yes** | Claim follow-up email send for workspace |
| GET | `/insights` | **Yes** | Cross-meeting intelligence — pass `?workspace_id=` to scope |
| GET | `/share/{token}` | No | Public read-only meeting by share token |
| GET | `/chats` | **Yes** | All chats as `{ meeting_id: messages[] }` map |
| GET | `/chats/{meeting_id}` | **Yes** | Single meeting's chat |
| POST | `/chats/{meeting_id}` | **Yes** | Save/upsert chat messages |
| DELETE | `/chats/{meeting_id}` | **Yes** | Delete chat |
| POST | `/workspaces` | **Yes** | Create workspace (auto-adds creator as owner) |
| GET | `/workspaces` | **Yes** | List workspaces the user belongs to |
| GET | `/workspaces/{id}` | **Yes** | Workspace detail + members list |
| PATCH | `/workspaces/{id}` | **Yes** | Rename (owner only) |
| DELETE | `/workspaces/{id}` | **Yes** | Delete workspace; meetings fall to Personal |
| DELETE | `/workspaces/{id}/members/{uid}` | **Yes** | Remove member (owner) or self-leave |
| POST | `/workspaces/{id}/regenerate-invite` | **Yes** | Regenerate invite token (owner only) |
| GET | `/workspaces/{id}/brief` | **Yes** | Open (unchecked) action items from this workspace's last-30-day meetings; max 10, each links back to source meeting |
| GET | `/invites/{token}` | No | Validate invite token, return workspace info |
| POST | `/invites/{token}/accept` | **Yes** | Join workspace via invite token |
| POST | `/join-meeting` | No | Start Recall.ai bot — checks workspace dedup first |
| GET | `/bot-status/{bot_id}` | No | Poll bot lifecycle + result |
| POST | `/recall-webhook` | No | Recall.ai event callbacks |
| POST | `/export/slack` | No | Send recap to Slack webhook |
| POST | `/export/notion` | No | Export full meeting to Notion |

**Auth pattern:** `require_user_id` in `auth.py` reads `Authorization: Bearer <token>`, validates against Supabase, returns `user_id`. All auth-gated endpoints scope their DB queries to that `user_id`. `/analyze`, `/chat`, `/agent` are intentionally unauthenticated so the demo flow works before sign-in.

---

## Supabase Schema

```sql
-- Core meeting storage
create table meetings (
  id bigint primary key,           -- Date.now()-based ID from frontend
  user_id uuid references auth.users(id),
  date text not null,
  title text,
  score int,
  transcript text,
  result jsonb,
  share_token text unique,
  workspace_id uuid references workspaces(id) on delete set null,  -- null = Personal
  recorded_by_user_id text,        -- set on fan-out copies; null = recorded by self
  email_claimed_by text,           -- user_id who claimed the follow-up email send
  created_at timestamptz default now()
);

create table chats (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  user_id uuid references auth.users(id),
  messages jsonb not null default '[]',
  updated_at timestamptz default now()
);

-- Workspace system
create table workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by text not null,
  invite_token text unique not null default gen_random_uuid()::text,
  created_at timestamptz default now()
);

create table workspace_members (
  workspace_id uuid references workspaces(id) on delete cascade,
  user_id text not null,
  user_email text,                 -- stored at join time for display
  role text not null default 'member',  -- 'owner' | 'member'
  joined_at timestamptz default now(),
  primary key (workspace_id, user_id)
);

-- Active bot registry — powers workspace dedup
create table meeting_bots (
  id uuid primary key default gen_random_uuid(),
  meeting_url text not null,       -- normalized (lowercase, no query params)
  bot_id text not null,
  owner_user_id text not null,
  workspace_id uuid references workspaces(id) on delete set null,
  status text not null default 'joining',  -- joining | recording | processing | done | error
  created_at timestamptz default now()
);

create index on meetings(user_id);
create index on meetings(workspace_id);
```

**Meeting ownership rules:**
- `workspace_id = null` → Personal meeting, visible only to owner
- `workspace_id` set, `recorded_by_user_id = null` → recorder's copy in workspace
- `workspace_id` set, `recorded_by_user_id` set → fan-out copy for a workspace member

**Workspace invite:** One invite token per workspace stored on the `workspaces` row. Anyone with the link can join. Owner can regenerate the token to revoke access.

---

## Auth

- Frontend: `frontend/src/lib/supabase.js` initializes the Supabase client from `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`. If either is missing, `supabase` exports as `null` and auth is disabled gracefully.
- Frontend: `frontend/src/lib/api.js` exports `apiFetch()` — always use this instead of raw `fetch()`. It auto-attaches `Authorization: Bearer <token>` from the active session.
- Frontend: `App.jsx` — `signInWithGoogle()` calls `supabase.auth.signInWithOAuth({ provider: 'google' })`. `authSession` / `authReady` states gate data loading. On sign-out, history and insights clear.
- **Local workspace on sign-in:** If a user has an unsaved analyzed meeting when they sign in, it is automatically saved to their account.
- Backend: `auth.py` — `require_user_id(request)` validates the Bearer token against Supabase's `/auth/v1/user` endpoint and returns `user_id`. Used as a FastAPI `Depends`.

---

## Streaming Analysis

Frontend calls `POST /analyze-stream`. Backend uses a LangGraph `StateGraph` with `graph.astream(stream_mode="updates")` — each agent node streams its result the moment it finishes. Frontend reads chunk by chunk, calling `setResult(prev => ({ ...prev, ...chunk }))`.

**Two-tier execution:**
- Tier 1 (parallel): `summarizer`, `decisions`, `action_items`, `sentiment`, `speaker_coach`
- `tier1_barrier`: synchronizes all Tier 1 results → builds `context` dict `{summary, decisions, action_items, sentiment}`
- Tier 2 (parallel, enriched): `email_drafter`, `health_score`, `calendar_suggester` — each receives `context` to produce richer output

SSE event format (unchanged from before LangGraph):
```
data: {"agents_run": ["summarizer", "action_items", ...]}   ← from orchestrator node
data: {"agent": "summarizer", "summary": "..."}             ← from t1_summarizer node
data: {"agent": "action_items", "action_items": [...]}      ← from t1_action_items node
data: {"agent": "email_drafter", "follow_up_email": {...}}  ← from t2_email_drafter node
data: {"agents_run": ["summarizer", ...]}                   ← final succeeded list
data: [DONE]
```

`tier1_barrier` updates are silently skipped in SSE (pass-through node). `saveToHistory` is called on `[DONE]`. The stream has a 120s `AbortController` timeout.

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

### Landing Visual Layer (as of Apr 2026)

The landing page may keep the prism metaphor and WebGL effects, but the surrounding UI should follow the current shadcn + cyan/sky direction. Use solid/near-solid surfaces and crisp borders for normal UI. Do not treat glass panels as the default landing or dashboard language.

Three layered WebGL effects sit behind landing content, stacked in DOM order where used (all `position:absolute, inset:0, pointer-events:none`):

1. **`<Prism />`** (`ogl`, `components/Prism.jsx`) — full-page ray-marched WebGL prism. `animationType="rotate"`, `scale=3.6`, `glow=1.4`, `bloom=1.2`, `colorFrequency=1.1`, `baseWidth=5.5`, `height=3.5`, `noise=0.04`. Transparent canvas — dark page bg shows through outside the prism shape.

2. **Top vignette** (`<div>`) — `linear-gradient(to bottom, rgba(7,4,15,0.6) 0% → transparent 15%)` — keeps logo + badge readable.

3. **Bottom fade** (`<div>`) — `linear-gradient(to bottom, transparent 60% → #07040f 100%)` — gives the prism a clean floor.

4. **`<LightPillar />`** × 2 (`three.js`, `components/LightPillar.jsx`) — one on each side edge (width 22%, full height). Both use `topColor="#38bdf8"`, `intensity=0.7`, `glowAmount=0.004`, `mixBlendMode="screen"`. Left: `bottomColor="#0d9488"`, `pillarRotation=30`. Right: `bottomColor="#6366f1"`, `pillarRotation=-30`. Both have inner-edge `mask-image` gradient so they dissolve toward the center.

**Tuning reference:**
- Prism too dim → raise `glow` / `bloom` (never go above ~2.0/1.6 or it washes out)
- Prism too wide/blurry → reduce `baseWidth`, raise `colorFrequency`
- Pillars too visible → lower `intensity` or tighten the mask gradient stop from 15% toward 5%
- Text unreadable → strengthen `text-shadow` on `.landing-screen h1/p` in `index.css` and/or deepen top vignette

**Fonts:** The Vite app currently loads Inter, Nunito, and Sora via Google Fonts, with `@fontsource-variable/geist` and `@fontsource-variable/inter` also installed. Use the existing font variables/classes in `index.css`; do not introduce a new type system without updating this handoff.

**`gradient-text`** (used on "Clarity that lasts."): uses `background-clip: text` with a white→sky-blue gradient. Text-shadow doesn't work on clipped text — use `filter: drop-shadow()` instead.

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

## Workspace System (In Progress — May 2026)

### What's been built
- **DB schema:** `workspaces`, `workspace_members`, `meeting_bots` tables; `meetings` extended with `workspace_id`, `recorded_by_user_id`, `email_claimed_by`
- **Backend:** `workspace_routes.py` — full workspace CRUD + invite system (multi-use revocable links)
- **Bot dedup:** `recall_routes.py` — before joining, checks if any workspace member's bot is already in the meeting (via `_find_shared_workspace_bot`). Returns `{skip: true, existing_bot_id}` instead of joining.
- **Fan-out:** `storage_routes.py` — `POST /meetings` with `workspace_id` triggers async `_fan_out_to_workspace`, writing copies to all other workspace members
- **Email claim:** `POST /meetings/{id}/claim-email` — first-claim model, locks send button for others
- **Scoped queries:** `/meetings` and `/insights` both accept `?workspace_id=` — workspace mode returns all members' meetings
- **Frontend switcher:** Chip row in DashboardPage below header — Personal + workspace chips + `+ New` inline creator
- **Workspace state in App.jsx:** `activeWorkspaceId` state, passed to DashboardPage + used in meeting save + history/insights fetches

- **Frontend invite flow (Step 6 — done):**
  - `INITIAL_INVITE_TOKEN` detected synchronously at module load from `window.location.hash` matching `#invite/{token}`
  - When present, App.jsx renders an invite acceptance screen instead of the normal app
  - Unauthenticated: saves token to `sessionStorage` (`prism_pending_invite`), triggers Google OAuth; `SIGNED_IN` handler restores by navigating to `/dashboard#invite/{token}`
  - Authenticated: "Join [workspace]" button → `POST /invites/{token}/accept` → writes `prism_active_workspace` to sessionStorage → "Go to dashboard" button
  - Workspace ⚙ settings panel in DashboardPage: appears below chip row when active workspace gear is clicked. Shows invite link (copy/regenerate for owners), member list with remove buttons, delete/leave workspace.

- **Bot dedup UI (Step 7 — done):**
  - `dedupBotInfo` state in App.jsx (`{ botId, ownerUserId, ownerUserEmail }`) — separate from `botStatus` to avoid breaking existing bot state logic
  - When join returns `{skip: true}`, sets `dedupBotInfo`, points `activeBotId` at the existing bot, and starts polling it — results flow in normally
  - `rejoinMeeting()` in App.jsx clears `dedupBotInfo` + resets bot state then calls `joinMeeting()` — used by the inline Rejoin button in the error banner
  - Auto-clears `dedupBotInfo` via `useEffect` when `botStatus` goes to `done` or `error`
  - DashboardPage: dedup strip ("Prism is already in this meeting via [email]") shown above the normal status banner; error banner now has inline "Rejoin" button
  - Backend: `_find_shared_workspace_bot` now returns `owner_user_email` (from `workspace_members.user_email`)

- **Meeting attribution UI (Step 8 — done):**
  - `workspaceMemberMap` state in DashboardPage (`{ userId: email }`) — built by fetching `GET /workspaces/{id}` when `activeWorkspaceId` changes
  - `recordedByEmail` computed in DashboardPage from `currentMeeting.recorded_by_user_id` — only non-null for fan-out copies (teammate recorded, not the current user)
  - MeetingsRail: shows `via [email]` in muted text at the bottom of each card where the recorder is a teammate
  - MeetingView: shows `Recorded by [email]` in muted text below the meeting date
  - Props threaded: DashboardPage → StatsCanvas → MultiMeetingHome → MeetingsRail

- **First-run workspace nudge (gap fix — done):**
  - Shows a dismissible callout below the chip row when: user is signed in + workspace fetch has resolved (`workspacesLoaded = true`) + no workspaces exist + not previously dismissed
  - `workspacesLoaded` flag (default `false`, set `true` after fetch) prevents a flash of the nudge on load for users who already have workspaces
  - "Create workspace" button opens the inline name input directly
  - "×" button permanently dismisses via `localStorage` key `prismai:workspace-nudge-dismissed`
  - Disappears automatically once the first workspace is created (condition falls false)

- **Phase 2 — Meeting Pattern Intelligence (done):**
  - `cross_meeting_service.py`: 4 new metrics — `completion_rate {total,completed,rate}`, `decision_velocity {avg,total}`, `open_owner_load [{owner,open,total}]`, `unresolved_themes [{theme,count}]`
  - `unresolved_themes`: words from summaries/action items filtered to exclude any word appearing in decision text (word-subtraction approach, no ML dependency)
  - `open_owner_load`: counts open vs total action items per owner across all workspace meetings; completion IS persisted via `PATCH /meetings/{id}`
  - `insights.js`: `normalizeInsights` extended with `completionRate`, `decisionVelocity`, `openOwnerLoad`, `unresolvedThemes`
  - `StatsHero.jsx`: expanded from 4 to 6 `MetricTile` entries (`grid-cols-2 lg:grid-cols-3`); shows completion rate + avg decisions. Accepts `workspaceName` prop — header shows "Team · [name] / Team intelligence" when set
  - `IntelligenceView.jsx`: accepts `workspaceName` prop; when set, renders `MembersLeaderboard` card (open owner load, amber progress bars) + "Unresolved topics" card (themes without a decision, amber chips) in a new 2-col row
  - `DashboardPage.jsx`: computes `workspaceName` inline from `workspaces.find()` — passed to `IntelligenceView`

### Fixed May 15 2026 — Post-deploy bugs + workspace auto-classification

**Bug fixes (all committed to main):**
- **Workspace history not re-fetching on switch** — `activeWorkspaceId` missing from history effect deps in `App.jsx`. Added.
- **Workspace settings panel too transparent** — `rgba(255,255,255,0.03)` bg → `#0f0f12` solid + `boxShadow` in `DashboardPage.jsx`.
- **Settings panel staying open when switching workspaces** — `switchWorkspace()` now calls `setWsSettingsId(null); setWsDetails(null)`.
- **Stale meeting result after workspace switch** — `onWorkspaceChange` now also calls `setResult(null); setMeetingId(null)`.
- **No title or back arrow on fresh analyses** — `MeetingView` header guard changed from `{meeting && ...}` to `{(onBack || meeting) && ...}`; `meeting.date` → `meeting?.date`.
- **Old transcript in new meeting panel** — `resetTranscriptWorkspaces` now called in `onOpenChange` when the + panel opens.
- **Single-meeting dashboard looked bare** — `SingleMeetingState` redesigned to centered "Good start." layout matching multi-meeting welcome style.
- **Duplicate meetings in workspace view** — backend workspace query was returning ALL rows with matching `workspace_id` (both recorder's original AND fan-out copies). Fixed with Python dedup: group by `(date[:16], recorded_by_user_id or user_id)`, keep one per logical meeting (prefer current user's copy). Originals have `recorded_by_user_id = null` (falls back to `user_id`), fan-outs have it set — both resolve to same key. `user_id` added to select, stripped from response.
- **Content overlapping workspace chip row** — `<main>` had `-mt-3`. Changed to `mt-2`.
- **`NewMeetingPanel` ReferenceError on Join tab** — `workspaces` referenced as free variable but is local state of `DashboardPage`. Fixed by passing `workspaces={workspaces}` explicitly at render site and using `props.workspaces` inside `NewMeetingPanel`.

**Features added:**
- **Upcoming meetings workspace auto-classification** — `GET /calendar/events` returns `attendee_emails` (excluding self). `GET /workspaces` returns `member_emails` (bulk query, not N+1). `UpcomingMeetings.jsx` `matchWorkspace()` finds best-overlap workspace. Matched events show cyan workspace chip; unmatched show gray "Personal" chip. Join button passes matched `wsId` to `onJoinWithWorkspace` (silently sets workspace without clearing current result view).

### Fixed May 17–18 2026 — Dedup edge case, sentiment rework, pre-meeting brief

**Duplicate workspace meeting cards when bot was dedup'd (commit `45dc2a9`):**
- *Symptom:* Two users in the same workspace both join a meeting; one bot is dedup'd to the other. After the meeting, dashboard shows two cards for the same meeting (one tagged `via teammate@…`).
- *Root cause:* Both frontends still independently called `POST /meetings`, producing 4 rows (2 originals + 2 fan-outs) with 2 distinct dedup keys under the old `(date[:16], recorded_by_user_id or user_id)` formula.
- *Fix:* `MeetingEntry` now accepts `recorded_by_user_id`; frontend passes the dedup'd bot's owner id through `startPolling` → `saveToHistory` → POST payload. `_fan_out_to_workspace` uses `entry.recorded_by_user_id or user_id` so all fan-out copies share one recorder. The GET `/meetings` + `/insights` workspace dedup key was also relaxed from `(date[:16], recorder)` → `date[:16]` only (within one workspace, two rows at the same minute are the same meeting). This relaxation also retroactively collapses pre-fix duplicate rows.

**Sentiment agent reworked — actionable vocabulary, no lazy neutral, rich UI (commit `7e627bd`):**
- *Symptom:* Sentiment almost always rendered as the single word "neutral" — most of the agent's output was being thrown away by the UI.
- *Root cause:* `MeetingView` rendered only `sentiment.overall` and `notes`; the existing `score`, `arc`, `speakers[]`, `tension_moments[]` fields were never displayed. The prompt also defaulted to neutral too aggressively.
- *Fix (backend `sentiment.py`):* Replaced `positive/neutral/tense/unresolved` with `collaborative / aligned / decision-making / exploratory / frictional / divergent / rushed / draining / neutral`. "Neutral" is still valid but reserved for genuinely flat meetings. Added `_compute_talk_distribution()` — pure Python parsing of `Speaker: text` lines that feeds per-speaker word share into the prompt as hard evidence (no extra LLM call, no tier change). Expanded per-speaker tone vocab to include `enthusiastic` and `reserved`. Prompt explicitly names signals (hedging, interruptions, repeated questions, enthusiasm markers, commit-vs-defer).
- *Fix (frontend `SentimentCard.jsx`):* New dedicated card renders overall pill (color-coded by label via `LABEL_META`), animated score bar, trend arc indicator, notes, per-speaker tone rows, and tension moments. Removed prior `!readOnly` guard so it also renders on the shared meeting view.

**Workspace pre-meeting brief on upcoming meeting cards (commit `0874f78`):**
- New `GET /workspaces/{id}/brief` returns `{open_items: [{task, owner, due, meeting_id, meeting_title, meeting_date}]}` — up to 10 unchecked action items from this workspace's meetings in the last 30 days. Membership-gated. Dedups fan-out copies by `date[:16]`, preferring the caller's own row so the linked `meeting_id` opens in their dashboard.
- New `GET /meetings/{id}` with workspace-member auth — lets the Brief panel open any source meeting even when it isn't in the caller's currently-loaded workspace history.
- `UpcomingMeetings.jsx`: workspace-matched events get a **Brief** button next to the cyan workspace chip. Click → lazy-fetches the brief → expands an inline `<BriefPanel>` listing items with owner / due / source meeting / age. Each item is clickable → calls `onOpenMeeting(meetingId)`.
- `DashboardPage.jsx`: `handleOpenMeetingById(meetingId)` — closes the new-meeting popover, uses in-memory history if available, otherwise fetches `GET /meetings/{id}` and routes through the existing `handleSelectMeeting` (which calls `loadFromHistory` + switches view).
- Personal upcoming meetings intentionally do NOT show a brief — V1 is workspace-only (workspace meetings have cohesive context, scattered personal history rarely does).

### Status: Workspace + Phase 2 + Phase 3 (LangGraph) complete — Phases 5–8 pending

### Key design decisions (locked)
- Invite links: multi-use, revocable by owner regenerating the token
- Any member can share the link; only owner can remove members
- Meeting attribution: auto-detect from calendar attendees (not yet built) → active workspace fallback → user prompt on tie
- Personal meetings always separate; meetings fall to Personal when workspace deleted
- Fan-out: full data (transcript + analysis) to all workspace members
- Follow-up email: first-claim model (anyone can claim, locks for others once claimed)
- Action items: synced across workspace (one completion state — not yet implemented, planned)
- Bot failure: manual recovery alert now; auto-takeover planned for later

### Remaining roadmap (original 8-phase plan — Phases 1 and 4 complete)

**Phase 2 — Meeting Pattern Intelligence**
Cross-workspace analytics: decision velocity, recurring unresolved topics, action item completion rate, meeting health trend, top contributors. New endpoint `GET /workspace-insights/{workspace_id}`. Frontend: team health trend chart, recurring themes card, members leaderboard.

**Phase 3 — LangGraph Orchestration ✅ Complete**
Two-tier `StateGraph` in `analysis_service.py`. Tier 1 (summarizer, decisions, action_items, sentiment, speaker_coach) runs in parallel; `tier1_barrier` merges results and builds context; Tier 2 (email_drafter, health_score, calendar_suggester) runs enriched with that context. Streaming via `graph.astream(stream_mode="updates")`. SSE format unchanged — zero frontend changes. Foundation for Phases 5–7 agent dependencies.

**Phase 5 — Graph RAG Knowledge Base**
`workspace_docs` + `workspace_graph` tables. Upload docs → entity extraction → graph. New LangGraph retrieval node injected before agents when workspace has knowledge loaded. Chat shows "Answered from team knowledge" badge.

**Phase 6 — Voice Identification**
Speaker enrollment (10s sample → embedding via ElevenLabs or Resemblyzer). Store `{user_id, voice_embedding}` in `user_settings`. During live meeting: match audio segments to enrolled users. Access control: unrecognized voice → public context only.

**Phase 7 — Context-Aware Conversation**
Chat agent tracks named entities + ambiguous references across the conversation. On ambiguity, generates clarifying question + choice UI instead of hallucinating. Multi-turn context window: last 10 exchanges + relevant meeting excerpts in prompt.

**Phase 8 — Personas**
4-5 system prompt variants (Default, Concise, Formal/Executive, Cheeky/Sarcastic, Socratic). Workspace-level default + personal override. Persona chip indicator in chat.

**Deferred debt (not original phases, but real issues):**
- `bot_store` in-memory → lost on Render restart. Fix: move to a `bots` Supabase table.
- Auto-takeover on bot failure (Option B) — currently manual alert only.

### Fixed Apr 20 2026 (commit 73e5097) — Two bugs from codebase audit

- **`get_valid_token()` `.single()` crash** — `calendar_routes.py:98` used `.single()` (throws PostgREST error on 0 rows) instead of `.maybe_single()`. Any chat tool call for a user without a connected calendar would return 500 instead of a clean 404 "not connected" error. Fixed: `.maybe_single()` + try-except.
- **`save_chat` TOCTOU race** — `storage_routes.py` used select+insert/update pattern (same race already fixed in `save_user_settings`). Two concurrent chat saves could both see an empty row and both insert, creating duplicate chat rows. Fixed: `upsert(on_conflict="meeting_id,user_id")`. Migration: `supabase/chats_unique_migration.sql` — run in Supabase SQL Editor before deploying.

### Fixed Apr 20 2026 (commit 33c5737) — Four follow-up bugs

- **`autoDeliveryRef` key collision** — `deliverMeetingRecap()` now takes `meetingId` as third arg; dedup key is the ID (not title+score), so two meetings with the same title/score both deliver correctly.
- **`savedMeetingRef` not reset on save failure** — `saveToHistory` `.catch()` now resets `savedMeetingRef.current = null` and `setMeetingId(null)`. If Render cold-starts and the POST fails, the user can retry.
- **Notion export silent truncation** — export now chunks all blocks into sequential `PATCH /blocks/{page_id}/children` calls (100 per request) after the initial page create. Large meetings no longer silently lose content past block 100.
- **`calendar_create_event` hardcoded `America/New_York`** — default timezone changed to `UTC`. LLM can still pass an explicit timezone if known; users outside ET no longer get wrong event times.

### Fixed Apr 20 2026 (commit 4c8877b) — Security hardening + reliability

**Security:**
- **CORS wildcard removed** — `main.py` now reads `ALLOWED_ORIGINS` env var (comma-separated). Default: Vercel URL + localhost. `ALLOWED_ORIGINS` is set on Render.
- **`/transcribe` rate limited** — IP-based 5 req/min cap. Demo flow still works (no auth required), budget abuse blocked.
- **Recall webhook HMAC** — `recall_routes.py` verifies `x-recall-signature` if `RECALL_WEBHOOK_SECRET` is set. Currently inactive (no static webhook registered in Recall dashboard — webhooks are per-bot). Safe to enable later.
- **Realtime tools bypass fixed** — `_process_command` now uses `get_available_tools(user_settings, exclude_confirm=True)`. Tools that require human confirmation (Gmail send, Slack post, Calendar create, Linear) are no longer offered to the live-meeting LLM. Defense-in-depth: even if LLM names one, `execute_tool` returns `requires_confirmation` instead of firing.
- **`/chat/confirm-tool` arg injection fixed** — server now stashes `{tool, arguments}` under a random `pending_id` (5-min TTL, `_pending_tools` dict in `chat_routes.py`). Client sends only `pending_id` at confirm time. Client can no longer swap args between preview and execution.

**Reliability:**
- **All 6 agents catch `Exception` not `JSONDecodeError`** — `summarizer`, `action_items`, `decisions`, `sentiment`, `email_drafter`, `calendar_suggester` now return safe defaults on any failure, not just parse errors. Matches `health_score.py`'s existing pattern.
- **`llm_call` fallback detection** — replaced `"429" in str(exc)` string matching with typed `exc.status_code` check + specific keyword list. More reliable; won't miss 500/502/504.
- **`strip_fences` edge case** — regex rewrite handles `` ```json{...}``` `` on a single line (old line-split code returned empty string → retry).

**Bugs:**
- **`ProactiveSuggestions` auth drop** — was using raw `fetch()`, dropping the auth token. Now uses `apiFetch`.
- **`save_user_settings` TOCTOU** — replaced select+insert/update with `upsert(on_conflict="user_id")`. Two tabs saving simultaneously no longer races.
- **`get_meetings` filter after limit** — now fetches 200 rows before filtering for meaningful results, then caps at 50. Partial saves no longer crowd out real meetings.
- **`_db_append_command` race** — replaced read-modify-write with atomic Postgres RPC (`append_bot_command`). SQL migration: `supabase/bot_commands_migration.sql` (already run ✓).
- **`RECALL_API_BASE` hardcoded** — both `recall_routes.py` and `realtime_routes.py` now read from `RECALL_API_BASE` env var (default: `us-west-2`).

**Performance:**
- **ChatPanel persistence debounced** — 800ms debounce on chat writes. Was firing a POST on every single message state change.

### Fixed later same session (Apr 19 2026)

**Realtime / live meeting:**
- **Double message bug** — `_send_voice_response` was falling back to `_send_chat_response` when voice failed, causing every response to appear twice. Removed the fallback — chat is always sent first (line 232), voice is additive only.
- **Voice 415 error** — `output_audio/` endpoint was receiving raw bytes with `Content-Type: audio/mpeg`. Recall.ai expects multipart form-data. Fixed: `files={"file": ("audio.mp3", audio_bytes, "audio/mpeg")}`.
- **Tool over-triggering** — LLM was calling `gmail_read` to answer "what's the day?". Two fixes: (1) injected current datetime into system prompt so factual questions need no tools, (2) tightened system prompt: only call a tool when the command explicitly requires external data.
- **Tool call format error (400)** — Llama 3.3 70b occasionally generates malformed tool calls. Added try/except in the Groq tool loop: on 400, strips `tools` from call_kwargs and retries plain.
- **`gmail_send` hallucinating `example.com`** — LLM was guessing recipient addresses. System prompt now: for `gmail_send`, only send if the user states a full email address in their command — otherwise ask for it.
- **Meeting chat commands silently ignored** — `participant_events.chat_message` handler was reading message text from the wrong nesting level (`payload["data"]` root instead of `payload["data"]["data"]`). Commands typed in Google Meet/Zoom chat were never processed. Fixed to mirror transcript event pattern. Added logging.

**History / auth:**
- **Workspace blank after demo exit** — `exitDemoMode` called `clearWorkspaceState` leaving an empty workspace. Now calls `loadFromHistory(history[0])` if signed in with history, restoring the last real meeting.
- **`savedMeetingRef` not set on auth auto-load** — when sign-in auto-loaded the latest meeting, `savedMeetingRef.current` stayed null, breaking the duplicate-save guard for subsequent actions. Now set on auto-load.
- **Share button missing for older meetings** — `shareToken` was null for meetings saved before the share_token field existed. Both auth auto-load and `loadFromHistory` now generate a token on demand and silently PATCH it to Supabase.
- **`PATCH /meetings/:id`** — extended to accept `share_token` in addition to `result`.

**UI:**
- **Transcript box truncated at 180 chars** — now `max-h-36 overflow-y-auto` with full transcript scrollable inside. `whitespace-pre-wrap` added so speaker line breaks render correctly.

**Agents:**
- **Summarizer length** — was hardcoded to 2-3 sentences regardless of transcript size. Now scales: <500 words → 2-3 sentences, 500-2000 words → short paragraph, 2000+ words → 3-5 sentences covering all major topics.

**Infrastructure / resilience:**
- **Model fallback** — all 7 agents now use `llm_call()` in `agents/utils.py` instead of calling Groq directly. On 429/503/overload, falls back to `claude-haiku-4-5-20251001` if `ANTHROPIC_API_KEY` is set on Render. `anthropic>=0.40.0` added to `requirements.txt`.
- **Calendar status endpoint** — was making two Supabase queries and had dead/contradictory logic. Replaced with single query: `connected = calendar_connected AND google_access_token is set`.

### Shipped Apr–May 2026 — Features 1–5

**Feature 5 — Shareable Live View** (commits `2763adf`, `7d1bc9c`)
- `/join-meeting` generates a `live_token` (16-char hex) stored in `bot_store` + `_live_token_index`
- Public endpoint `GET /live/{live_token}` returns status, commands, transcript_lines, result, brief, transcript
- `LiveMeetingView` component in `App.jsx` — polls every 3s, renders full result cards when done
- Bot intro message posts the live link in Meet chat 20s after joining (`FRONTEND_URL` env var)
- `vercel.json` SPA catch-all rewrite prevents 404 on direct navigation to `/dashboard-mcp`

**Feature 2 — Proactive Interventions** (commit `6d4b55b`)
- `_run_proactive_checker(bot_id)` asyncio task started per bot on join, checks every 60s
- 4 triggers: no decisions after 30 min, approaching 60 min, action items with no owners, recurring blocker keywords match past meetings
- Throttled: max 1 proactive message per 10 minutes per bot

**Feature 4 — Speaker Coaching** (commit `6d4b55b`)
- `backend/agents/speaker_coach.py` — 8th agent, always runs, returns `[]` if <2 named speakers
- `SpeakerCoachCard.jsx` — rose/pink, animated talk-time bars, per-speaker coaching note
- Shown in all 4 layouts: desktop, mobile, share view, live share view

**Feature 1 — Pre-Meeting Brief** (commit `6d4b55b`)
- `_build_pre_meeting_brief(user_id)` in `recall_routes.py` — pure Python, no LLM, fetches last 10 meetings
- Returns `{open_items, recent_decisions, blockers}` — included in `GET /live/{live_token}` response
- Also pulls unresolved `action_refs` rows into open_items
- `PreMeetingBrief` collapsible card in `LiveMeetingView` — sky-blue, hides when status=done
- "Save to my history" button in live viewer — POSTs full result+transcript to `/meetings` when logged in

**Feature 3 — Closed-Loop Action Items** (commit `6d4b55b`)
- `supabase/action_refs_migration.sql` — `action_refs` table with RLS enabled
- `execute_tool()` in `tools/registry.py` injects `external_ref: {tool, external_id}` when Linear or Calendar tools succeed
- `_process_command` in `realtime_routes.py` saves a row to `action_refs` after each successful tool call
- `derive_cross_meeting_insights()` in `cross_meeting_service.py` accepts `user_id`, returns `unresolved_action_refs`
- `ActionItemsCard.jsx` shows Linear (⬡) or Calendar (📅) ID pill when `item.external_ref` present

**Dashboard Redesign** (commits `e21a994`, `180f71a`)
- New `DashboardMcpPage` at `/dashboard-mcp` — two views: MeetingView and IntelligenceView
- `MagicBento`, `DotField`, `dashboard/` sub-components (ActionBoard, HealthTrend, OwnerLoad, etc.)
- shadcn UI primitives: `tabs`, `dropdown-menu`, `button`, `dialog`, `text-rotate`
- "View dashboard" button added to landing CTA row
- `frontend/vercel.json` added to prevent SPA 404 on Vercel

### Previously fixed
- **Landing page visual overhaul (Apr 2026)** — replaced CSS-only prism center element with full-page WebGL Prism background (`ogl`). Added LightPillar corner effects (`three.js`). Loaded Space Grotesk + Manrope fonts. Tuned gradient overlays, glass panel opacity, gradient-text contrast, and `filter: drop-shadow` for clipped text.
- **Design direction clarified (Apr 2026)** — current target is shadcn-style dark surfaces with the existing cyan/sky accent. Avoid full-site glassmorphism; reserve glass-like treatment for accents such as CTAs or focused highlights.
- **CrossMeetingInsights 3-col header overflow** — OWNERSHIP DRIFT / ACTION HYGIENE / UNRESOLVED DECISIONS labels clipped by `overflow-hidden` container on narrow viewports. Headers now stack vertically.
- **Decision theme noise** — Month/day names (`april`, `monday`, `jan`, etc.) were surfacing as recurring decision themes. Full set of month/day names + abbreviations added to `STOP_WORDS` in `CrossMeetingInsights.jsx`.
- **Aria-labels** — send message (ChatPanel), delete chat session (ChatPanel), remove speaker (App.jsx).

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

1. Create `backend/agents/yourname.py` — follow the pattern above. If Tier 2, add `context: dict = {}` param to `run()` and use available keys (`summary`, `decisions`, `action_items`, `sentiment`).
2. Import it in `backend/analysis_service.py`
3. Add to `AGENT_MAP` in `analysis_service.py`
4. Add to `TIER1_AGENTS` or `TIER2_AGENTS` frozenset in `analysis_service.py` — Tier 2 if it benefits from reading Tier 1 results
5. Add to `AGENT_RESULT_KEY` in `analysis_service.py`
6. Add default value to `DEFAULT_RESULT` in `analysis_service.py` (and mirror in `frontend/src/App.jsx`)
7. Add a result extraction block in `_state_to_result()` in `analysis_service.py`
8. If Tier 2: add its output key to `_tier1_barrier`'s context dict if other Tier 2 agents should read it
9. Add to `ALL_AGENTS` list in `orchestrator.py`
10. Add guardrail in `orchestrator.py` if it should always run
11. Add to `AGENTS_META` in `App.jsx` with icon + gradient
12. Add to `AGENT_CONFIG` in `AgentTags.jsx` with ROYGBIV color
13. Create `YournameCard.jsx` in `frontend/src/components/`
14. Import and place card in `App.jsx` (both desktop and mobile layouts)

---

## Google Calendar Integration (fully working ✓)

### What was built
- `backend/calendar_routes.py` — `POST /calendar/connect`, `POST /calendar/exchange-code`, `GET /calendar/events`, `GET /calendar/status`, `DELETE /calendar/disconnect`
- `supabase/calendar_migration.sql` — `user_settings` table (**already run**)
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

### Calendar connect — WORKING

**Root cause (resolved):** Supabase v2 does not persist `provider_token` in stored sessions. Three Supabase-based approaches were tried; all failed.

**Fix:** Direct Google OAuth PKCE flow, completely bypassing Supabase for the calendar token.

**How it works:**
1. `connectGoogleCalendar()` generates a PKCE verifier/challenge, stores verifier in `sessionStorage`, redirects to Google OAuth with `state=calendar_connect`
2. Google redirects back to `window.location.origin` with `?code=...&state=calendar_connect`
3. A `useEffect` in `App.jsx` detects `state === 'calendar_connect'`, retrieves the verifier, cleans the URL, POSTs to `/calendar/exchange-code`
4. Backend exchanges the code+verifier with Google, stores tokens in `user_settings`, returns `{ok: true}`
5. Frontend sets `calendarConnected = true`

**Env vars in place:**
- Vercel: `VITE_GOOGLE_CLIENT_ID`
- Render: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Google Cloud Console: redirect URIs `https://agentic-meeting-copilot.vercel.app` and `http://localhost:5173` added

**Files involved:**
- `frontend/src/App.jsx` — `generateCodeVerifier`, `generateCodeChallenge`, `connectGoogleCalendar` (PKCE flow), calendar callback `useEffect`
- `frontend/src/components/IntegrationsModal.jsx` — Calendar tab UI
- `frontend/src/components/UpcomingMeetings.jsx` — events panel
- `backend/calendar_routes.py` — `POST /calendar/exchange-code` (PKCE token exchange), all other calendar routes
- `supabase/calendar_migration.sql` — already applied

---

## Live Meeting Tools + Voice — Setup Checklist

The agentic tool-calling system and live voice responses require several env vars and external service configs. Here's everything needed:

### Render Dashboard — Environment Variables

Add these in Render → `meeting-copilot-api` → Environment:

| Variable | Required? | Where to get it | What it enables |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | [console.groq.com](https://console.groq.com) | All LLM calls + Whisper transcription |
| `RECALL_API_KEY` | **Yes** | [recall.ai dashboard](https://recall.ai) | Bot joining meetings |
| `SUPABASE_URL` | **Yes** | Supabase → Settings → API | Database + auth |
| `SUPABASE_KEY` | **Yes** | Supabase → Settings → API → `service_role` key | Backend DB access (never expose to frontend) |
| `WEBHOOK_BASE_URL` | **Yes** | Already set: `https://meeting-copilot-api.onrender.com` | Recall.ai webhooks |
| `GOOGLE_CLIENT_ID` | **Yes** | Google Cloud Console → Credentials | Calendar/Gmail OAuth |
| `GOOGLE_CLIENT_SECRET` | **Yes** | Google Cloud Console → Credentials | Calendar/Gmail token exchange |
| `ELEVENLABS_API_KEY` | For voice | [elevenlabs.io](https://elevenlabs.io) → Profile → API Keys | TTS voice responses in meetings |
| `ELEVENLABS_VOICE_ID` | Optional | ElevenLabs → Voices → copy ID | Custom voice (default: `21m00Tcm4TlvDq8ikWAM` / Rachel) |
| `SLACK_BOT_TOKEN` | For Slack | Slack App → OAuth & Permissions → Bot Token (`xoxb-...`) | Slack read/post/search tools |
| `LINEAR_API_KEY` | For Linear | [linear.app/settings/api](https://linear.app/settings/api) | Linear issue creation tool |

### Vercel Dashboard — Environment Variables

Add these in Vercel → Project Settings → Environment Variables:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://meeting-copilot-api.onrender.com` |
| `VITE_SUPABASE_URL` | Your Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase `anon` key (safe for browser) |
| `VITE_GOOGLE_CLIENT_ID` | Same Google Client ID as Render |

### Google Cloud Console — Required Setup

1. **OAuth Consent Screen** → Edit → Scopes → Add:
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.readonly`
2. **Credentials** → Your OAuth 2.0 Client → Authorized redirect URIs:
   - `https://agentic-meeting-copilot.vercel.app`
   - `http://localhost:5173` (for local dev)
3. If the app is in "Testing" mode, add your Google account as a test user

### Supabase — Migrations

Run in **Supabase SQL Editor** (in order, skip if already applied):

1. `supabase/auth_migration.sql` — creates `meetings` + `chats` tables
2. `supabase/calendar_migration.sql` — creates `user_settings` table with Google token columns
3. `supabase/tools_migration.sql` — adds `linear_api_key`, `slack_bot_token` columns + creates `bot_sessions` table

### What works without optional env vars

| Missing var | Impact |
|---|---|
| `ELEVENLABS_API_KEY` | Bot still works — responds via **meeting chat text** instead of voice. TTS silently falls back to chat. |
| `SLACK_BOT_TOKEN` | Slack tools unavailable in chat. Users can still set per-user tokens via Integrations modal. |
| `LINEAR_API_KEY` | Linear tool unavailable. Users can still set per-user keys via Integrations modal. |
| `GOOGLE_CLIENT_ID/SECRET` | Calendar connect + Gmail tools disabled entirely. |

### How live meeting commands work (end to end)

1. User clicks "Join Meeting" → `POST /join-meeting` creates Recall.ai bot with `realtime_endpoints` webhook
2. Recall.ai streams transcript chunks + chat messages to `POST /realtime-events` in real time
3. `realtime_routes.py` watches for trigger phrase: **"Prism, ..."** or **"PrismAI, ..."**
4. Detected command → LLM (Groq) picks tools from the user's available set → executes
5. Response sent back via:
   - Meeting chat: `POST /bot/{id}/send_chat_message/` (always works)
   - Voice (if ElevenLabs configured): ElevenLabs TTS → `POST /bot/{id}/output_audio/`
6. Command logged to `bot_sessions` table + shown in frontend command log
7. After meeting ends → full transcript analysis runs as before (7 agents)

---

## Recent Work — Utterance Accumulator + Realtime Security Hardening

Branch `fixed-changes`. All work is feature-flagged; flag-off behavior is byte-identical to pre-change state. Full design log is in `UTTERANCE_ACCUMULATOR_NOTES.md` at the repo root — that file is the authoritative record. This section is the summary for handoff.

### What changed (high level)

Two intertwined projects landed together:

1. **Utterance Accumulator** — turns Recall's wire-level transcript chunks into semantic utterances before they hit the buffer, command dispatcher, or downstream agents. Fixes the "mid-sentence pause fires a half-command" and "ping-pong duplicated lines" issues in live meetings.
2. **Realtime security hardening (Phase 0)** — closes attack paths in the realtime webhook surface that were exploitable independent of the accumulator (unsigned webhook, name-only owner gate, no ingress rate limit, raw display names).

### New files

| File | Purpose |
|---|---|
| `backend/utterance_accumulator.py` | Pure-logic accumulator. `Accumulator`, `PendingUtterance`, `FlushedUtterance`. No asyncio, no globals. 5 flush triggers (speaker change, max-cap, pause, punctuation grace, flush_all). Detects Deepgram cumulative re-emissions (e.g. "prism" → "prism can" → "prism can you") via prefix overlap. |
| `backend/perception_state.py` | Per-bot perception state + security counters. Hosts the owner participant-ID lock (`maybe_lock_owner_id`, `is_owner_with_lock`), the `bot_self_speaker_id` field (wired but filter pending empirical test), and `_SECURITY_KEYS` surface for owner-only debug. |
| `backend/tests/test_utterance_accumulator.py` | 40 tests across 9 groups — basics, single-speaker flow, speaker change, re-emission dedup, discard/flush_all, DoS guards, callback exception containment, utterance_id stability, helper units, integration ping-pong replay. |
| `backend/tests/test_accumulator_integration.py` | 14 tests — state init under both flag states, `_emit_utterance` buffer format parity, full flow with flag on/off, cleanup, compare mode, realistic transcript simulation. |
| `backend/tests/test_security_hardening.py` | 29 tests — speaker-name sanitization, ingress rate limit, owner lock, `is_owner_with_lock`, realtime token index, payload-handler refactor. |
| `backend/tests/test_barge_in.py`, `test_injection_guard.py`, `test_pre_perception.py`, `test_prompt_structure.py` | Supporting suites for prompt-injection guard, pre-perception state, barge-in detection, prompt assembly. |
| `UTTERANCE_ACCUMULATOR_NOTES.md` | Full design + change log. Read this before extending the accumulator. |

### Modified files

- **`backend/realtime_routes.py`** (+1100 lines) — speaker-name sanitization helper, per-bot ingress rate limit (50/s sliding window, pre-lock), token-in-URL webhook route `POST /realtime-events/{token}` alongside the legacy unauthenticated route, refactored payload handling into `_handle_realtime_payload(payload, verified_bot_id=None)`, accumulator import + lazy state init + tick task, `_emit_utterance` / `_dispatch_slow_path_command` helpers, branching chunk handler (accumulator path vs. legacy path), Phase B stop-command `discard_speaker` wiring, `cleanup_bot_state` flushes and unregisters tokens, optional compare-mode legacy-buffer simulation.
- **`backend/recall_routes.py`** (+90 lines) — bot creation generates `secrets.token_urlsafe(32)` realtime_token, embeds it in the webhook URL, registers in `_realtime_token_index`, stores in `bot_store[bot_id]`.
- **`backend/calendar_routes.py`** — minor edits to token validity helpers used by chat-tools refresh path.
- **`backend/chat_routes.py`** — minor adjustments to `_get_user_settings` (Google token refresh via `get_valid_token`).
- **`backend/tools/{calendar,gmail,slack,tts}.py`** — prompt-injection / argument-handling hardening to align with the security work.

### Feature flags (all opt-in; defaults off)

| Env var | Default | Effect |
|---|---|---|
| `PRISM_ACCUMULATOR` | unset | Routes chunks through `utterance_accumulator`. Flag-off path is byte-identical to pre-change behavior. |
| `PRISM_ACC_PAUSE_MS` | `1200` | Pause threshold that ends an utterance. |
| `PRISM_ACC_PUNCT_GRACE_MS` | `200` | Grace window after terminal punctuation before flushing. |
| `PRISM_ACC_MAX_CHARS` | `500` | Utterance char cap. |
| `PRISM_ACC_MAX_WORDS` | `80` | Utterance word cap. |
| `PRISM_ACC_COMPARE` | unset | Run legacy fuzzy-dedup buffer in parallel for offline diffing. Writes to `state["transcript_buffer_legacy"]`. Logs `[ACC-COMPARE-SUMMARY]` at meeting end. |
| `PRISM_OWNER_ID_LOCK` | unset | After a 5s grace post bot-join, lock `state["owner_speaker_id"]` to the participant_id of the first name-matching chunk. After lock, owner gate requires ID match; name-only mismatches increment `owner_impersonation_attempts`. |

### Security counters added to `perception_state._SECURITY_KEYS`

`owner_impersonation_attempts`, `ingress_rate_limited`, `accumulator_evictions`. All surface via the owner-only debug path; non-zero values warrant investigation.

### Test status at hand-off

**144 tests passing, 0 failing** across `test_utterance_accumulator`, `test_accumulator_integration`, `test_security_hardening`, `test_injection_guard`, `test_pre_perception`, `test_barge_in`. Pre-existing failing suites (`test_streamed_voice`, `test_voice_pipeline`, `test_chat_export_routes`, `test_recall_routes`, `test_storage_routes`) are unrelated to these changes — verified.

### Known limitations + open work

- **Bot-self TTS filter** — `state["bot_self_speaker_id"]` exists but the filter at slow-path dispatch isn't wired pending one live meeting to confirm whether Recall echoes the bot's TTS as a transcript event.
- **Recall participant_id consistency** — accumulator merging and owner ID-lock both assume `participant.id` is stable across chunks for the same human. One live meeting will confirm. If unstable, owner lock would never claim and accumulator merging fails per-speaker.
- **Wake-word-only follow-up** — legacy path had an 8s pending-trigger window so "Ok, Prism" + later "schedule a meeting" dispatched the second utterance. Accumulator path drops this; `_dispatch_slow_path_command` only fires when `_detect_command` matches the current utterance. Acceptable for v1, flagged in notes.
- **In-memory `_realtime_token_index`** — server restart mid-meeting causes the tokenized route to 401 for that bot until it ends. Consistent with the existing `bot_store` in-memory limitation; would need a `bot_sessions.realtime_token` column to persist.

### Phase status

- Phase 0 (security hardening) — **complete**.
- Phase 1 (accumulator module) — **complete**.
- Phase 2 (integration behind flag) — **complete**.
- Phase 3 (validation tooling: compare mode + realistic simulation) — **complete**.
- Phase 4 (default-on + remove legacy fuzzy-dedup + drop flags) — **pending** soak.
- Phase 5 (diarization heuristic, per-speaker pause tuning, out-of-order chunk sorting, wake-word-only follow-up, bot-self filter wiring) — **deferred**.

### Operational rollout

1. Deploy with all flags off — zero behavior change.
2. Enable `PRISM_ACCUMULATOR=1 PRISM_ACC_COMPARE=1` on a test bot; run a meeting; grep `[ACC-COMPARE-SUMMARY]` and diff `transcript_buffer` vs `transcript_buffer_legacy`.
3. Enable `PRISM_OWNER_ID_LOCK=1` independently; monitor `owner_impersonation_attempts`.
4. After a clean soak, drop the legacy path in `realtime_routes.py` (Phase 4).

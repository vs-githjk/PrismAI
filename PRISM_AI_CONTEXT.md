# PrismAI — LLM Handoff Document

> Written for an LLM picking up development. Read this before touching any code.

---

## What Is PrismAI

A meeting intelligence web app. User pastes a transcript, uploads audio, records live, or connects a bot to a live Zoom/Meet/Teams call. The transcript is routed to 7 parallel AI agents (LLaMA 3.3-70b via Groq) each producing a different output card. The name "Prism" is intentional — white light (raw transcript) enters the prism (orchestrator) and splits into 7 colors (agents).

**Live URLs:**
- Frontend: Vercel (`https://agentic-meeting-copilot.vercel.app/`)
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
| Frontend Hosting | Vercel |
| Backend Hosting | Render.com free tier |

---

## File Structure

```
/
├── backend/
│   ├── main.py                    # FastAPI app shell: middleware + router wiring
│   ├── auth.py                    # Supabase token validation + shared Supabase client
│   ├── analysis_service.py        # Shared analysis pipeline helpers
│   ├── analysis_routes.py         # /analyze, /analyze-stream, /transcribe
│   ├── storage_routes.py          # meetings, chats, share routes
│   ├── recall_routes.py           # Recall bot join/status/webhook routes
│   ├── chat_routes.py             # /chat, /chat/global, /agent
│   ├── export_routes.py           # Notion + Slack export endpoints
│   ├── tests/
│   │   ├── test_auth.py
│   │   ├── test_storage_routes.py
│   │   ├── test_recall_routes.py
│   │   ├── test_main_routes.py
│   │   └── test_chat_export_routes.py
│   ├── agents/
│   │   ├── orchestrator.py        # Decides which agents to run
│   │   ├── utils.py               # shared strip_fences helper
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
│   │   ├── App.jsx                # Root: layout, auth state, input, results, history, speaker modal, share
│   │   ├── index.css              # Tailwind + custom animations
│   │   ├── lib/
│   │   │   ├── supabase.js        # Supabase browser client
│   │   │   └── api.js             # auth-aware fetch helper
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
│   │       ├── ProactiveSuggestions.jsx # Post-analysis contextual action panel
│   │       └── ErrorCard.jsx        # Designed error states with retry CTA
│   └── vite.config.js             # Vite config + manual chunking for vendor splits
├── .github/workflows/deploy.yml   # Legacy GitHub Pages deploy workflow (no longer primary frontend host)
├── render.yaml                    # Render.com backend config (service name: meeting-copilot-api)
├── supabase/
│   └── auth_migration.sql         # Adds user_id columns + indexes for auth-scoped data
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
| POST | `/chat/global` | `{ message, limit? }` → `{ response }` — answers across all stored meetings |
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
  user_id uuid references auth.users(id) on delete cascade,
  created_at timestamptz default now()
);

create table chats (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  messages jsonb not null default '[]',
  updated_at timestamptz default now()
);
```

`on delete cascade` means deleting a meeting automatically deletes its chat — no extra frontend call needed.

Additional indexes created by `supabase/auth_migration.sql`:
- `meetings_user_id_idx`
- `chats_user_id_idx`
- `chats_user_id_meeting_id_idx` (unique per user + meeting)

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
https://agentic-meeting-copilot.vercel.app/#share/{token}
```

On page load, App.jsx checks `window.location.hash` for `#share/{token}`. If matched, it fetches `GET /share/{token}` and renders a read-only view with all 7 cards. No router needed — hash-based routing still works cleanly on Vercel.

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

On startup, App.jsx fetches `/meetings` and auto-loads the most recent meeting (transcript + result + chat). The app now also persists whether the user is on the landing screen or inside the main workspace, so refreshing keeps them on the same screen.

---

## Environment Variables

| Var | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | All LLM calls + Whisper transcription |
| `RECALL_API_KEY` | Yes (bot feature only) | Recall.ai meeting bot |
| `WEBHOOK_BASE_URL` | Yes (bot feature only) | Callback URL for Recall webhooks |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase service_role key (bypasses RLS) |
| `VITE_API_URL` | Frontend build only | Points frontend at backend (set in Vercel) |
| `VITE_SUPABASE_URL` | Frontend build only | Supabase project URL for browser auth |
| `VITE_SUPABASE_ANON_KEY` | Frontend build only | Supabase anon key for browser auth |

**Important split:**
- Render/backend uses `SUPABASE_KEY` = service role key
- Vercel/frontend uses `VITE_SUPABASE_ANON_KEY` = anon key
- No separate JWT secret is required in the current implementation because backend auth validates Supabase access tokens through `GET /auth/v1/user`

---

## Deployment

**Frontend:** Vercel deploys the `frontend/` app.
- Root directory: `frontend`
- Install command: `npm install`
- Build command: `npm run build`
- Output directory: `dist`
- Required env vars:
  - `VITE_API_URL=https://meeting-copilot-api.onrender.com`
  - `VITE_SUPABASE_URL=https://qttzotttqqjkpuaepxoj.supabase.co`
  - `VITE_SUPABASE_ANON_KEY=<anon key>`

**Backend:** Render.com auto-deploys from `render.yaml` on push to `main`.
- Free tier spins down after inactivity → cold start can take 30-60s
- `SUPABASE_URL` and `SUPABASE_KEY` must be set manually in Render dashboard (not in render.yaml)
- Recall.ai features also require `RECALL_API_KEY` and `WEBHOOK_BASE_URL` to be set in Render
- Current auth setup uses Supabase Google sign-in via Supabase Auth; Google OAuth redirect goes through `https://qttzotttqqjkpuaepxoj.supabase.co/auth/v1/callback`

---

## Known Issues / Watch Out For

- **Render free tier sleeps** — first request after inactivity will be slow. Not a bug.
- **Bot store is in-memory** — if Render restarts mid-meeting, `bot_store` is lost. Needs persistent storage to fix properly.
- **Sentiment is conditional** — won't appear for neutral/positive meetings by design.
- **`decisions` importance ranking** — 1 = critical, 2 = significant, 3 = minor. Sorted ascending in `DecisionsCard.jsx`.
- **Share button only appears after analysis** — `shareToken` state is null until a meeting is saved. Loading from history restores the token.
- **SSE and Render free tier** — streaming works but Render free tier may buffer SSE. `X-Accel-Buffering: no` header is set to mitigate.
- **Frontend is now functionally stable** — recent demo/workspace race conditions were fixed and auth is in, but there are still no frontend automated tests.
- **Bot completion UX was improved** — when a meeting bot finishes, the frontend now keeps the returned transcript in the paste input and gives a clearer next step (`view results` if results exist, `analyze now` if only the transcript is available).
- **Frontend build is much healthier now** — lazy loading + manual chunking reduced the initial app shell significantly, but `recharts` still lives in a large deferred `charts` chunk.
- **Auth verification currently calls Supabase on each protected request** — reliable and simple, but not the lowest-latency design. Local JWT verification via JWKS could be a future optimization.
- **Share links remain intentionally public** — only explicitly shared meetings are public; all normal meetings/chats/history are user-scoped.
- **Backend test suite exists now** — 22 tests currently pass across auth, storage, Recall, analysis shell, chat, and export flows.

---

## Major UX / Product Work Recently Shipped

- **Frontend hosting migrated to Vercel** — GitHub Pages is no longer the primary frontend host.
- **Landing page redesigned** — more cinematic prism metaphor, animated transformation from raw transcript to structured intelligence, stronger headline and CTA treatment.
- **Workspace visual system upgraded** — glass surfaces, stronger gradients, more motion, richer result headers, and a signature `PrismStoryPanel` / `PrismSignatureScene`.
- **Result cards upgraded** — clearer hierarchy, quick-glance metadata, trust framing, and more polished card internals.
- **Input quality guidance added** — transcript stats and named-speaker cues now appear in the input panel.
- **Analyze action visibility improved** — transcript areas are shorter and the paste flow keeps the primary analyze action visible more reliably.
- **Bot completion flow improved** — live meeting completion now leads to a clearer next action instead of a dead-end status message.
- **Per-input drafts added** — paste, record, and upload now preserve separate transcript drafts, while `Clear` wipes only the current mode.
- **In-app workspace polished** — demo mode, empty states, and transcript workspace UI now feel more intentional and less hacky.
- **Left-panel usability improved** — workspace header and pre-analysis chat were compressed so the transcript and `Analyze Meeting` action stay visible more reliably.
- **Stale analysis races fixed** — exiting demo mode or resetting the workspace now cancels in-flight analysis so old results cannot repaint the app after the user has moved on.
- **Recall error handling hardened** — backend now surfaces Recall status-check failures accurately instead of masking them as `404 Bot not found`.
- **Render config improved** — `render.yaml` now includes `SUPABASE_URL` and `SUPABASE_KEY` placeholders so fresh Render provisioning is less error-prone.

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

### Auth + backend architecture + performance phase (latest)
- **Supabase Auth foundation shipped** — browser sign-in/sign-out state now uses Supabase Auth with Google provider. Frontend sends the Supabase access token to the backend; backend validates it via Supabase and derives `user_id`.
- **Per-user data isolation shipped** — `meetings` and `chats` are now scoped by `user_id`; signed-in users only see their own history and chats. Share links remain public by token only.
- **Supabase migration added** — `supabase/auth_migration.sql` adds `user_id` columns and indexes for `meetings` + `chats`.
- **Signed-in / signed-out UX tightened** — the app now distinguishes synced workspaces from local-only ones more clearly, offers direct sign-in prompts in local-only states, and clears persisted state more explicitly when auth drops.
- **Backend modularization completed** — the giant backend file was split into `auth.py`, `analysis_service.py`, `analysis_routes.py`, `storage_routes.py`, `recall_routes.py`, `chat_routes.py`, and `export_routes.py`. `backend/main.py` is now a thin app shell.
- **Backend reliability tests added** — there are now 22 passing backend tests covering auth failures, storage scoping, Recall bot flows, analysis shell routes, chat/global chat, and export edge cases.
- **Auth hardening completed** — backend auth now handles Supabase outages gracefully and returns clean 503 / 401 responses instead of brittle failures.
- **Export hardening completed** — Notion export now handles non-JSON failure bodies safely instead of crashing while parsing errors.
- **Frontend lazy-loading shipped** — `ChatPanel`, `ProactiveSuggestions`, `ScoreTrendChart`, and `IntegrationsModal` now load on demand.
- **Frontend chunk splitting shipped** — Vite manual chunking now separates `react`, `supabase`, and `recharts` vendor chunks so the initial app shell loads much faster.
- **Current frontend bundle shape** — main app shell is now ~149 kB, React vendor ~146 kB, Supabase ~194 kB, charts ~333 kB (deferred), instead of one giant initial bundle.

### Frontend stabilization + final polish before backend phase
- **Landing page fit fixes** — headline sizing and height-based compression were rebalanced so standard laptop viewports no longer look overly squashed.
- **Workspace polish** — demo banner, empty state, workspace header, and results briefing were refined to feel more product-like and less like placeholders.
- **Per-mode transcript drafts** — switching between Paste / Record / Upload now starts clean per mode, while preserving what was previously entered in each mode.
- **Clear button added** — users can clear the current transcript mode without manual deletion.
- **Pre-analysis layout tightened** — transcript workspace is more dominant, pre-analysis chat is reduced, and `Analyze Meeting` stays visible more reliably.
- **Demo exit race fixed** — if the user clicks demo, then exits to "Use my own transcript" while analysis is still loading, stale demo results are now canceled and ignored.
- **Workspace reset race fixed** — the same stale-analysis guard now applies to `New Meeting`, `Clear all`, deleting the active meeting, and other workspace reset flows.
- **Codebase sanity pass completed** — frontend production build and backend Python compilation both pass after the above fixes.

### Integrations + UI polish sprint (current)
- **Landing grid mobile fix** — `grid-cols-7` → `grid-cols-2 sm:grid-cols-4 lg:grid-cols-7` ✓
- **Health score trend chart** — `ScoreTrendChart.jsx` using recharts; collapsed by default above transcript card; click data points to load meeting; shows avg + trend delta ✓
- **Slack integration** — `IntegrationsModal.jsx` (Slack tab: webhook URL + test button); `POST /export/slack` backend endpoint; "Send to Slack" in both export menus ✓
- **Notion integration** — Notion tab in IntegrationsModal (token + parent page ID); `POST /export/notion` backend endpoint builds full structured page (health, summary, to-do action items, decisions, email); "Export to Notion" in both export menus ✓
- **Integrations button** — link icon in header opens IntegrationsModal; toast feedback after export success/failure ✓
- **Card hover states, staggered entrance, mobile empty state** — already shipped in prior sprint ✓

> **TODO: Landing page needs a visual makeover** — currently static and boring. Needs animation, more visual interest, better hierarchy. Do not just tweak copy — redesign the `LandingScreen` component in App.jsx.

> **Notion + Slack are configured and working.** User has set up both integrations. Export to Slack and Export to Notion both confirmed working in production.

### Calendar suggestion done-state
- Clicking "Open Calendar" in `ProactiveSuggestions` no longer dismisses the suggestion. Instead sets `done: true` on the item.
- Done items remain visible at 50% opacity with a green checkmark replacing the accent dot and a strikethrough label — confirms the action was taken.
- Action button is hidden on done items; dismiss X remains.

### Mobile polish + share page overhaul + time saved banner
**Mobile polish:**
- `ChatPanel.jsx` — fixed `height: 360px` replaced with `minHeight: 300px / maxHeight: 40vh` — adapts to viewport, no cutoff on short screens.
- Mobile tab bar — added `env(safe-area-inset-bottom, 0px)` padding — no longer overlaps content on notched iPhones.
- Dead `getElementById('mobile-results')` call removed — "Analysis complete — tap to see results" button now calls `setMobileTab('results')` directly.

**Share page overhaul (`shareMode` render in App.jsx):**
- Sticky branded header bar with logo, "shared" badge, and "Analyze your own →" CTA in top-right.
- Meeting title, full date, and `AgentTags` shown above cards.
- Bottom CTA block: "Try PrismAI free →" gradient button.
- OG meta tags (`og:title`, `og:description`, `og:type`, `twitter:card`, `twitter:title`, `twitter:description`) injected dynamically via DOM in the share `useEffect` — link previews now work on Slack/iMessage/Twitter.
- `document.title` updated to meeting title on share load.

**Time saved banner:**
- `showTimeSaved` state, set true on `[DONE]`, cleared on new analysis start.
- Renders above `ProactiveSuggestions` in both desktop and mobile results blocks.
- Shows "~X minutes saved · analyzed in Ys" with emerald styling.
- Share button copies pre-written tweet to clipboard: `"Just analyzed my meeting in Xs with PrismAI — saved ~Y minutes. Try it: [url]"`.
- Dismiss X closes the banner.

### Cross-meeting chat (`POST /chat/global`)
**Backend (`main.py`):**
- New `GlobalChatRequest` model: `{ message: str, limit: int = 10 }`.
- `POST /chat/global` — fetches last N meetings from Supabase (`id, title, date, score, result`), builds compact context per meeting (~200 chars: summary + action items + decisions), hard cap at 12k chars total, drops oldest meetings first if exceeded.
- System prompt positions LLM as a cross-meeting intelligence assistant that cites meeting titles/dates.
- Returns `{ response: string }`.

**Frontend (`ChatPanel.jsx`):**
- New `detectGlobalIntent(msg)` function — matches patterns: "last N meetings", "across all meetings", "what did I commit", "which meetings", "past/previous meetings", "recurring", "trend", "over time", "last month/week/quarter", "all time", "history of", "meeting history".
- `globalIntent` flag computed after `agentIntent` check — only fires if no agent intent matched.
- Routes to `POST /chat/global` instead of `POST /chat` when flag is true.
- `loadingGlobal` state: shows "Searching all meetings…" animated text in the loading bubble instead of the 3-dot bounce.
- Global replies tagged with "⊕ searched all meetings" below the message content.
- `setLoadingGlobal(false)` called in `finally` block — prevents stuck loading state on network errors.

### ErrorCard + health score count-up animation
**`frontend/src/components/ErrorCard.jsx` (new file):**
- Props: `message`, `onRetry`.
- Detects error type from message string: timeout → "Server is waking up"; 429/rate-limit → "Too many requests"; network failure → "Cannot reach the server"; generic fallback.
- Each variant has a tailored title + detail sentence.
- Retry button re-fires `runAnalysis([])`.
- Replaces the raw red text div that was in App.jsx.

**`HealthScoreCard.jsx` — count-up animation:**
- New `useCountUp(target, duration)` hook using `requestAnimationFrame` with ease-out cubic easing.
- `CircleGauge` uses `useCountUp` — both the displayed number and the arc offset animate from 0 → actual score over 1 second.
- `BreakdownBar` uses `useCountUp` — both the label number and the bar width animate in sync.
- CSS transition removed from arc (was `transition: stroke-dashoffset 1s ease-out`) — now driven by rAF directly.

### Proactive Suggestions Panel (`ProactiveSuggestions.jsx`)
New component placed above `HealthScoreCard` in both desktop and mobile results blocks. Renders after `health_score` is present (signals stream complete). Shows up to 3 contextual action cards based on `result`:

| Trigger | Suggestion | Action |
|---|---|---|
| `calendar_suggestion.recommended` | "Follow-up meeting recommended" | Opens Google Calendar deep link |
| `action_items.length >= 3` | "X action items — draft Slack update?" | `POST /chat` inline response |
| Tension in sentiment | "Tension detected — facilitation tip?" | `POST /chat` inline response |
| `health_score.score < 60` | "Low score — tips to improve?" | `POST /chat` inline response |

- Per-suggestion state: `{ loading, response, error, dismissed, done }`.
- Link-type suggestions use `done` state (crossed-out) instead of `dismissed` so completion is visible on return.
- Chat-type suggestions expand inline; action button hides after response received.
- Dismiss X per suggestion; panel hides when all dismissed/done.

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

### Landing page navigation + session state fixes
- Uses `sessionStorage` (not `localStorage`) for the visited gate — new tab/window shows landing, hard refresh stays in the app
- PrismAI logo in the header clicks back to landing (`onClick={() => setShowLanding(true); setLandingExiting(false)}`)
- Share links still bypass landing via `!INITIAL_SHARE_TOKEN`
- Slack test button routes through backend (`POST /export/slack`) to avoid CORS — was previously calling Slack directly from the browser
- Notion page ID extraction fixed — regex finds the 32-char hex ID regardless of title prefix in the URL (e.g. `PrismAI-Meetings-338ede0d...`)
- **New Meeting** sets `sessionStorage.prism_new_meeting` flag — refresh after clicking New Meeting stays blank instead of reloading the last meeting. Flag is cleared when a meeting is saved or loaded from history.
- **Delete active meeting** — now clears the current view immediately if the deleted meeting is the one being displayed. Previously only removed it from the history list.
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

### #1 — Final product polish sweep
This is now the best leverage area because the foundations are finally strong.
- continue smoothing cramped or repetitive states in the workspace
- improve small-screen/mobile transitions and edge cases
- tighten copy consistency and visual hierarchy across demo vs real-workspace states
- add frontend tests if possible for the highest-risk state flows

### #2 — Backend reliability expansion
- add more tests for share-link edge cases, export variants, and auth failure states
- keep tightening signed-in vs signed-out persistence rules
- continue improving Recall bot lifecycle handling and recoverability
- move `bot_store` persistence out of memory eventually

### #3 — Frontend performance follow-through
- keep trimming non-critical initial work
- consider more targeted chart optimization or alternative lighter charting if needed
- profile expensive rerenders inside `App.jsx` and the results workspace

### #4 — Health score trend chart
Graph `meetings.score` over time. Data already in Supabase. Deferred until users have enough meeting history for it to be meaningful (aim for after first week of public use).
- `recharts` library: `npm install recharts`
- `ScoreTrendChart.jsx` with `AreaChart`, color-coded by score range
- Placement: above meeting history list, collapsed by default with "Show trend" toggle
- Minimum 2 meetings required to render

### #5 — Team workspace / collaboration
Single-user auth and per-user scoping now exist. The next collaboration layer would require:
- a `workspaces` table
- workspace membership / roles
- meetings and chats associated with both `workspace_id` and `user_id`
- share permissions beyond simple public token links

### #6 — Model fallback
Each agent catches Groq errors and retries with OpenAI (`gpt-4o-mini`) or Anthropic (`claude-haiku-4-5`). Agent pattern is identical — swap client + model name. Add `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars.

### #7 — Bot store persistence
`bot_store` dict in `main.py` is in-memory — lost on Render restart. Move to a `bots` Supabase table: `id`, `status`, `result`, `error`, `transcript`, `created_at`.

### #8 — Slack / Google Docs integration *(blocked on #1)*
Full OAuth flows. The proactive suggestions calendar deep link covers the calendar case without auth for now.

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

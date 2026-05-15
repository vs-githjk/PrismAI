# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Frontend (React + Vite — `frontend/`)
```bash
cd frontend && npm install
npm run dev        # localhost:5173
npm run build
npm run preview
```

### Backend (FastAPI — `backend/`)
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Copy `backend/.env.example` → `backend/.env` and fill in keys before running locally.

### Next.js App (new landing — `next-app/`)
```bash
cd next-app && npm install
npm run dev        # localhost:3000 (Turbopack)
npm run typecheck
npm run lint
npm run format
```
This app is a fresh scaffold (shadcn/ui + Tailwind v4 + Next 16 + React 19). It is not yet wired to the backend and is being built as a replacement landing experience.

---

## Architecture

PrismAI is a meeting intelligence app with three layers: a React+Vite frontend, a FastAPI backend, and a new Next.js app in progress.

### Request → Analysis Flow

```
User input (paste / upload / record / bot)
  → POST /analyze-stream (SSE)
  → backend runs a LangGraph StateGraph (two-tier parallel execution)
      Tier 1 (parallel): summarizer, decisions, action_items, sentiment, speaker_coach
      tier1_barrier: merges Tier 1 results → builds context dict
      Tier 2 (parallel, enriched): email_drafter, health_score, calendar_suggester
  → each agent node streams its result as it finishes (graph.astream stream_mode="updates")
  → frontend merges results incrementally: setResult(prev => ({ ...prev, ...chunk }))
  → [DONE] event triggers save to Supabase
```

8 agents total — all use `llama-3.3-70b-versatile` via Groq. Conditional agents (sentiment, calendar_suggester) only run when the orchestrator selects them. Tier 2 agents receive a `context` dict built from Tier 1 results: `{summary, decisions, action_items, sentiment}`. This produces richer emails, more accurate health scores, and better calendar reasoning.

### Backend Structure

`main.py` is purely wiring — middleware and router registration only. Logic lives in `*_routes.py` and `*_service.py` files. `auth.py` exports a single FastAPI `Depends`: `require_user_id(request)` — it validates the Bearer token against Supabase and returns `user_id`. All auth-gated endpoints use it; `/analyze`, `/chat`, `/agent` are intentionally unauthenticated for the pre-login demo flow.

`analysis_service.py` is the agent registry and LangGraph orchestrator. Key exports: `AGENT_MAP`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `TIER1_AGENTS`, `TIER2_AGENTS`, `_GRAPH` (compiled StateGraph singleton), `run_full_analysis`. The two-tier graph: orchestrator node → Tier 1 fan-out (Send) → tier1_barrier (builds context) → Tier 2 fan-out (Send, enriched with context) → END. Adding an agent requires updating `AGENT_MAP`, `TIER1_AGENTS` or `TIER2_AGENTS`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `_state_to_result`, the graph construction in `_build_graph`, and the agent file itself. If it's a Tier 2 agent, also add `context: dict = {}` to its `run()` signature.

`workspace_routes.py` handles all workspace and invite logic: create/rename/delete workspaces, add/remove members, generate/validate/accept invite tokens (multi-use, revocable by owner).

`recall_routes.py` now checks for workspace dedup before joining: `_find_shared_workspace_bot()` queries `meeting_bots` to detect if a teammate's bot is already in the meeting. If found, returns `{skip: true, existing_bot_id, owner_user_email}` (email sourced from `workspace_members`) without calling Recall.ai. Registers new bots in `meeting_bots` after a successful join. `_mb_update_status()` keeps `meeting_bots.status` in sync with webhook events.

`storage_routes.py` `POST /meetings` now fans out to workspace members via async `_fan_out_to_workspace()` when `workspace_id` is set. `/meetings` and `/insights` both accept `?workspace_id=` to scope queries to a workspace (all members' meetings).

All agents import `strip_fences` from `backend/agents/utils.py`. Never redefine it.

### Frontend Structure

`App.jsx` holds all application state, all input modes, all result state, and the landing/share routing. It is intentionally a large file — don't split it without a strong reason. Always use `apiFetch()` from `lib/api.js` instead of raw `fetch()` — it auto-attaches the auth token.

`App.jsx` also owns `activeWorkspaceId` state (persisted to `sessionStorage` as `prism_active_workspace`). This is passed to `DashboardPage` and used in: meeting saves (`workspace_id` in `POST /meetings` payload), history fetches (`/meetings?workspace_id=`), and insights fetches (`/insights?workspace_id=`). `onWorkspaceChange` callback in DashboardPage updates this state.

`App.jsx` detects `#invite/{token}` hash synchronously via `INITIAL_INVITE_TOKEN` at module load. When present, the normal app render is replaced by an invite acceptance screen. Unauthenticated users see a "Sign in with Google" button — the token is saved to `sessionStorage` (`prism_pending_invite`) before the OAuth redirect, and the `SIGNED_IN` auth handler restores it by navigating to `/dashboard#invite/{token}`. Accepted invites write `prism_active_workspace` to sessionStorage so the dashboard opens in the right workspace.

`DashboardPage.jsx` renders the workspace chip row (Personal + workspace chips + `+ New` creator) just below the header. Switching a workspace calls `props.onWorkspaceChange(wsId)` which updates App.jsx state and triggers a re-fetch. Workspace list is fetched in DashboardPage via `GET /workspaces`. Each active workspace chip has a ⚙ button that opens an inline settings panel below the chip row — shows the invite link (copy/regenerate), member list with remove buttons, and delete/leave workspace. A first-run nudge callout appears below the chip row for signed-in users who have no workspaces yet; it is permanently dismissed via `localStorage` key `prismai:workspace-nudge-dismissed`. The nudge only renders after the workspace fetch resolves (`workspacesLoaded` flag) to prevent a flash on load for users who already have workspaces.

The landing page has a three-layer WebGL stack (all `position:absolute, inset:0, pointer-events:none`): `<Prism />` (ogl, full-page ray-marched prism), a top vignette div, a bottom fade div, and two `<LightPillar />` instances (three.js, one per side edge). Current tuning values are documented in `PRISM_AI_CONTEXT.md` → "Landing Visual Layer".

Current design direction: use shadcn/radix-style product surfaces with the app's existing cyan/sky accent (`#22d3ee`, `#67e8f9`, `sky-*` / `cyan-*`). Do not make glassmorphism the default visual language for the site or dashboard. Glass-like treatment is only an accent for CTAs, focused highlights, or special moments.

`ChatPanel.jsx` runs three chat modes in priority order: agent intent (regex → `POST /agent`), global intent (regex → `POST /chat/global`, requires auth), regular chat (`POST /chat`).

### Auth

Frontend Supabase client (`lib/supabase.js`) returns `null` if env vars are missing — auth degrades gracefully. Google Calendar uses a direct PKCE flow (not Supabase OAuth) because Supabase v2 doesn't persist `provider_token` in stored sessions. The PKCE verifier is stored in `sessionStorage` during the redirect.

### Known Limitations

- `bot_store` in `recall_routes.py` is in-memory — lost on Render restart. Fix requires a `bots` Supabase table.
- Bot endpoints (`/join-meeting`, `/bot-status`, `/recall-webhook`, `/realtime-events`) are unauthenticated by design — bot results are not user-scoped.
- Render free tier cold starts take 30–60s.
- All workspace frontend steps (6–8) are complete. First-run workspace nudge added. Phase 2 (Meeting Pattern Intelligence) complete. Phase 3 (LangGraph two-tier orchestration) complete. Phases 5–8 pending.

---

## Deployment

- **Frontend:** Vercel auto-deploys `frontend/` on push to `main`. Build: `npm run build`, output: `dist`.
- **Backend:** Render auto-deploys from `render.yaml` on push to `main`. Service name is `meeting-copilot-api` (URL is locked to creation-time name regardless of dashboard display name).
- **Next.js app:** Not yet deployed.

Supabase migrations must be run manually in the SQL editor (in order):
1. `auth_migration.sql` — meetings + chats tables
2. `calendar_migration.sql` — user_settings table
3. `tools_migration.sql` — linear_api_key, slack_bot_token columns + bot_sessions table
4. Workspace migrations (run May 2026 — no file yet, run directly in SQL editor):
   - `workspaces` table
   - `workspace_members` table (with `user_email` column)
   - `meeting_bots` table
   - `alter table meetings add column workspace_id, recorded_by_user_id, email_claimed_by`

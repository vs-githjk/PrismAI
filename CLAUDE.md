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
  → backend spawns 7 async Groq agents concurrently (asyncio.gather)
  → each agent streams its result as it finishes (FIRST_COMPLETED)
  → frontend merges results incrementally: setResult(prev => ({ ...prev, ...chunk }))
  → [DONE] event triggers save to Supabase
```

The 7 agents map directly to ROYGBIV: summarizer, action_items, decisions, sentiment (conditional), email_drafter, calendar_suggester (conditional), health_score. All use `llama-3.3-70b-versatile` via Groq. Conditional agents (sentiment, calendar_suggester) only run when the orchestrator detects relevant content.

### Backend Structure

`main.py` is purely wiring — middleware and router registration only. Logic lives in `*_routes.py` and `*_service.py` files. `auth.py` exports a single FastAPI `Depends`: `require_user_id(request)` — it validates the Bearer token against Supabase and returns `user_id`. All auth-gated endpoints use it; `/analyze`, `/chat`, `/agent` are intentionally unauthenticated for the pre-login demo flow.

`analysis_service.py` is the agent registry — `AGENT_MAP`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `run_full_analysis`. Adding an agent requires updating both this file and 10 other locations (see `PRISM_AI_CONTEXT.md` → "Adding a New Agent — Checklist").

All agents import `strip_fences` from `backend/agents/utils.py`. Never redefine it.

### Frontend Structure

`App.jsx` holds all application state, all input modes, all result state, and the landing/share routing. It is intentionally a large file — don't split it without a strong reason. Always use `apiFetch()` from `lib/api.js` instead of raw `fetch()` — it auto-attaches the auth token.

The landing page has a three-layer WebGL stack (all `position:absolute, inset:0, pointer-events:none`): `<Prism />` (ogl, full-page ray-marched prism), a top vignette div, a bottom fade div, and two `<LightPillar />` instances (three.js, one per side edge). Current tuning values are documented in `PRISM_AI_CONTEXT.md` → "Landing Visual Layer".

Current design direction: use shadcn/radix-style product surfaces with the app's existing cyan/sky accent (`#22d3ee`, `#67e8f9`, `sky-*` / `cyan-*`). Do not make glassmorphism the default visual language for the site or dashboard. Glass-like treatment is only an accent for CTAs, focused highlights, or special moments.

`ChatPanel.jsx` runs three chat modes in priority order: agent intent (regex → `POST /agent`), global intent (regex → `POST /chat/global`, requires auth), regular chat (`POST /chat`).

### Auth

Frontend Supabase client (`lib/supabase.js`) returns `null` if env vars are missing — auth degrades gracefully. Google Calendar uses a direct PKCE flow (not Supabase OAuth) because Supabase v2 doesn't persist `provider_token` in stored sessions. The PKCE verifier is stored in `sessionStorage` during the redirect.

### Known Limitations

- `bot_store` in `recall_routes.py` is in-memory — lost on Render restart. Fix requires a `bots` Supabase table.
- Bot endpoints (`/join-meeting`, `/bot-status`, `/recall-webhook`, `/realtime-events`) are unauthenticated by design — bot results are not user-scoped.
- Render free tier cold starts take 30–60s.

---

## Deployment

- **Frontend:** Vercel auto-deploys `frontend/` on push to `main`. Build: `npm run build`, output: `dist`.
- **Backend:** Render auto-deploys from `render.yaml` on push to `main`. Service name is `meeting-copilot-api` (URL is locked to creation-time name regardless of dashboard display name).
- **Next.js app:** Not yet deployed.

Supabase migrations must be run manually in the SQL editor (in order): `auth_migration.sql` → `calendar_migration.sql` → `tools_migration.sql`.

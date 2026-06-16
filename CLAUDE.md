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

---

## Architecture

PrismAI is a meeting intelligence app with two layers: a React+Vite frontend and a FastAPI backend.

### Request → Analysis Flow

```
User input (paste / upload / record / bot)
  → POST /analyze-stream (SSE)
  → backend runs a LangGraph StateGraph (two-tier parallel execution)
      orchestrator: DETERMINISTIC routing (no LLM) — runs all agents; sentiment only if 2+ speakers
      Tier 1 (parallel): summarizer, decisions, action_items, sentiment, speaker_coach
      tier1_barrier: merges Tier 1 results → runs decision_linker (Tier 1.5) → builds context dict
      Tier 2 (parallel, enriched): email_drafter, health_score, calendar_suggester
  → each agent node streams its result as it finishes (graph.astream stream_mode="updates")
  → frontend merges results incrementally: setResult(prev => ({ ...prev, ...chunk }))
  → [DONE] event triggers save to Supabase
```

9 agents total (8 graph nodes + decision_linker in the barrier) — all go through `llm_call()` in `backend/agents/utils.py`, which calls Groq's `llama-3.3-70b-versatile` and falls back to `claude-haiku-4-5-20251001` on Groq rate-limit / 5xx (retries once if Groq says wait ≤5s before falling back). Never bypass `llm_call`. **Routing is deterministic (Jun 2026): the orchestrator is no longer an LLM call** — `agents/orchestrator.run_orchestrator()` is pure logic that runs every agent, gating only `sentiment` to 2+-speaker meetings; `calendar_suggester` always runs and self-decides `recommended` (so `CalendarCard` only renders when `recommended`). Tier 2 agents receive a `context` dict built from Tier 1 results: `{summary, decisions, action_items, sentiment, unactioned_decisions}`. Current agent output shapes (post Jun 2026 review): summarizer adds `tldr` + `topics`; decisions add `rationale` (importance surfaced + sorted in UI); action_items add a resolved `due_date` (overdue/due-soon badges); sentiment `tension_moments` are `{moment, status: resolved|carried_over}`; health_score adds `improvement_tip`; calendar_suggestion adds `suggested_time` + `agenda` + `attendees` + `resolved_time` (with an Add-to-Calendar action); `decision_links` maps decisions↔action items.

### Backend Structure

`main.py` is purely wiring — middleware and router registration only. Logic lives in `*_routes.py` and `*_service.py` files. `auth.py` exports a single FastAPI `Depends`: `require_user_id(request)` — it validates the Bearer token against Supabase and returns `user_id`. All auth-gated endpoints use it; `/analyze`, `/chat`, `/agent` are intentionally unauthenticated for the pre-login demo flow.

`analysis_service.py` is the agent registry and LangGraph orchestrator. Key exports: `AGENT_MAP`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `TIER1_AGENTS`, `TIER2_AGENTS`, `_GRAPH` (compiled StateGraph singleton), `run_full_analysis`. The two-tier graph: orchestrator node → Tier 1 fan-out (Send) → tier1_barrier (builds context) → Tier 2 fan-out (Send, enriched with context) → END. Adding an agent requires updating `AGENT_MAP`, `TIER1_AGENTS` or `TIER2_AGENTS`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `_state_to_result`, the graph construction in `_build_graph`, and the agent file itself. If it's a Tier 2 agent, also add `context: dict = {}` to its `run()` signature.

`decision_linker` is a special "Tier 1.5" agent: it runs INSIDE `_tier1_barrier` (not as a graph node, so it's not in `TIER2_AGENTS`/`_build_graph`) because it needs both Tier 1 outputs (decisions + action_items) AND must feed Tier 2 (it adds `unactioned_decisions` to the context that `calendar_suggester` reads). It maps decisions→action items by their original-array index, returns `decision_links` (wired in `AGENT_RESULT_KEY` + `DEFAULT_RESULT` + `_state_to_result`), and `analysis_routes` has a dedicated `tier1_barrier` branch in the SSE loop to stream its output (barrier updates are otherwise skipped). Frontend renders bidirectional links in `MeetingView` (decisions show ↳ linked actions or a "No action item" flag; actions show "From decision: …").

`workspace_routes.py` handles all workspace and invite logic: create/rename/delete workspaces, add/remove members, generate/validate/accept invite tokens (multi-use, revocable by owner). Also exposes `GET /workspaces/{id}/brief` — returns up to 10 open (unchecked) action items from the workspace's meetings in the last 30 days, each carrying `meeting_id` for click-through. Membership-gated. Dedups fan-out copies by `date[:16]` preferring the caller's own row so the linked `meeting_id` opens in their dashboard.

`recall_routes.py` now checks for workspace dedup before joining: `_find_shared_workspace_bot()` queries `meeting_bots` to detect if a teammate's bot is already in the meeting. If found, returns `{skip: true, existing_bot_id, owner_user_email}` (email sourced from `workspace_members`) without calling Recall.ai. Registers new bots in `meeting_bots` after a successful join. `_mb_update_status()` keeps `meeting_bots.status` in sync with webhook events. **Idempotency (Jun 2026):** `_process_bot_transcript` is guarded by an in-memory `_processing_bots` set so only ONE analysis runs per bot — `/bot-status` polls used to re-spawn a full analysis on every poll while `status=="processing"` (it couldn't tell a running task from a dead one), piling up dozens of concurrent runs and exhausting Groq's daily token limit. The `/bot-status` call-ended branch is now one rule: run once unless already done/error or in flight (the empty in-memory guard after a restart still allows the legitimate recovery re-trigger).

`storage_routes.py` `POST /meetings` accepts an optional `recorded_by_user_id` on the entry — set by the frontend when the user's bot was workspace-dedup'd to a teammate's, so the actual recorder is attributed correctly. `_fan_out_to_workspace()` uses `entry.recorded_by_user_id or user_id` so all fan-out copies share the same recorder regardless of which workspace member's frontend triggered the POST. `/meetings` and `/insights` both accept `?workspace_id=` — workspace mode fetches ALL members' rows (no user_id filter) then deduplicates in Python by `date[:16]` only (within one workspace, two rows at the same minute are the same logical meeting). Prefer the current user's own copy. `user_id` is included in the select for dedup, then stripped before the response. `GET /meetings/{id}` returns a single meeting with workspace-membership auth — used by the upcoming-meeting Brief panel to open source meetings outside the currently-loaded workspace history.

All agents import `strip_fences` from `backend/agents/utils.py`. Never redefine it.

`realtime_routes.py` is the live-meeting surface: receives Recall.ai transcript + chat webhooks, runs the utterance accumulator → command detection → tool execution → optional TTS response loop. Also exposes the live-share index (token gated by `bot_sessions.live_token`) and the realtime SSE for the dashboard's live view. This file is large by design — much of the live-meeting product surface lives here.

**Bot turns in the transcript (Jun 2026):** the bot's own replies are recorded into the saved transcript so a meeting reads as a real dialogue (critical for solo meetings — otherwise it looks like the user talking to themselves) and there's a lasting record of what the bot said. `realtime_routes._record_bot_line(bot_id, state, text, bot_name)` appends `"{persona_name}: {reply}"` to BOTH the live-memory `transcript_buffer` AND the durable append-only `realtime_transcript_lines` (via `_append_realtime_line` + throttled persist), in chronological order interleaved with the human utterances. Called at the two reply-finalization points in `_process_command` (main path + Haiku fallback), replacing the old hardcoded `"Prism: {reply}"` buffer append. In `recall_routes._process_bot_transcript`, when the bot actually spoke (`_BOT_NAME_PREFIXES` — every persona name + Prism/PrismAI — detected in `realtime_transcript_lines`), that bot-inclusive live transcript is used as the final transcript for analysis + display (Recall's audio transcript wouldn't contain the bot's chat replies). Recall `segments` are still used for the recording player. When the bot was silent, behavior is unchanged (Recall transcript primary, realtime fallback when empty).

**Solo free-flow (Jun 2026):** when exactly one human is in the meeting, the bot drops the wake-word requirement and treats every substantive utterance as a command (natural 1-on-1 conversation). Driven by Recall `participant_events.join`/`.leave` webhooks (now subscribed in `recall_routes._join` alongside `transcript.data` + `chat_message`) → `state["participants"]` roster → `_human_participant_count` (the bot self-excludes via `_looks_like_bot_participant`, matching `is_current_user`/`is_bot` flags or any name in `PERSONA_NAMES`/`Prism*`). `_solo_mode_active` returns True when humans == 1. Fallback when participant events are unavailable (e.g. mid-meeting restart): distinct human speaker count (`human_speaker_ids`), guarded by `max_humans_seen` so a group meeting never drops into free-flow. Wired in `_dispatch_slow_path_command` (adds the no-wake-word command path, filtered by `_solo_freeflow_eligible`: ≥3 words, not a mute phrase) and `_ambient_on_utterance` (returns early in solo mode so ambient doesn't double-process). Flag: `PRISM_SOLO_FREEFLOW` (default ON). Mute kill-switch + gap-before-speaking still apply.

`chat_routes.py` exposes three chat surfaces in priority order matched by `ChatPanel.jsx`: `POST /chat` (per-meeting chat against transcript), `POST /chat/global` (auth-gated cross-meeting chat), `POST /agent` (intent → tool call). All three call Groq directly (not via `llm_call`) because they handle their own streaming + history shaping. **RAG trust layer (Jun 2026):** when the tool-calling loop (`/chat` + `/chat/global`) runs `knowledge_lookup`, `build_rag_context()` normalizes the result into a whitelisted `rag_context` (top 5 sources: doc_name, source_type, score, 500-char snippet, page/timestamp/meeting_title + a `has_conflict` flag) returned alongside `reply`. `ChatPanel` renders a conflict banner + Sources cards from this structured data — citations come from `rag_context`, never from the model's prose. (`knowledge_lookup` now also returns `doc_id`/`chunk_id`/`possible_conflict`/`has_conflict` so this works.) `POST /agent` re-runs a single agent; for Tier-2 agents it rebuilds the pipeline `context` from the `result` shipped by `ChatPanel` so re-runs aren't context-blind (e.g. `health_score` sees sentiment's tension resolution). **Continuous per-meeting chat (Jun 2026):** `POST /chat-sessions/{id}` upserts in place when given `session_id` (else inserts + prunes to 3). `ChatPanel` restores the meeting's latest session on mount, auto-saves each turn (debounced, chained so no duplicate inserts), flushes on unmount, and has a "New chat" button that clears the thread + starts a fresh session; `DashboardPage` clears stale sessions on meeting switch (ChatPanel is keyed by meetingId).

`calendar_routes.py` owns the Google Calendar OAuth callback exchange, `GET /calendar/events` (lists next-N upcoming events with `attendee_emails` for workspace matching), `POST /calendar/create-event` (the follow-up "Add to Calendar" action — reuses `get_valid_token` for a fresh token + `tools/calendar.calendar_create_event` to insert; adds a Meet link when attendees are present), and the per-meeting bot auto-join settings. `calendar_resolution.py` is pure logic for parsing natural-language date/time references ("next Tuesday at 3pm") — now also extracts time-of-day + more phrasings (end of week/month, numeric M/D) with a `dateparser` fallback; used by both calendar_suggester and action_items (to resolve `due_date`). The frontend mirrors it in `lib/resolveDate.js` (client fallback for seed/old meetings) and `lib/dueStatus.js` (overdue/due-soon). `CalendarCard` uses custom `DatePopover`/`TimePopover` (Radix popover) instead of native inputs, with teammate-email suggestion chips.

`cross_meeting_service.py` powers `/insights` and cross-meeting chat: rolls per-meeting agent outputs into themes (most-common decisions, top action owners, sentiment trend, health-score trend) over a workspace or user's last N meetings. `meeting_memory.py` is the three-layer memory used during a live bot session (raw recent window + rolling compressed summary + entity slots). `utterance_accumulator.py` turns wire-level Recall chunks into bounded semantic utterances (speaker change / pause / punctuation / max-length). `perception_state.py` is the pre-perception observability layer (event-id dedup, partial-drop ratio) gated by `PRISM_PRE_PERCEPTION=1`. `voice_pipeline.py` is the streaming sentence segmenter + TTS dispatch policy (pysbd-based; tests-only until wired in).

`clients.py` is the shared Groq / Anthropic / Recall HTTP client provider (use these via `Depends`, do not instantiate clients per-request). `analysis_routes.py` is the SSE-streamed `/analyze` and `/analyze-stream` surface that drives the dashboard analysis flow; logic lives in `analysis_service.py`. `export_routes.py` is a small one-file router for transcript/summary export.

### Knowledge Base / RAG (merged from `fixed-changes`, May 2026)

Vector RAG over user-uploaded docs + (planned) meeting transcripts. `knowledge_routes.py` (REST: upload/upload-url/connect-source, docs CRUD, resync, queries audit), `knowledge_service.py` (ingest orchestration + `search_knowledge`), `embeddings.py` (OpenAI `text-embedding-3-small`, batching + retry + quota circuit-breaker), `knowledge_ingest/` (pdf/docx/txt/url/notion/gdrive loaders + sentence-aware chunker), `knowledge_proactive.py` (surfaces relevant chunks every 20 transcript lines via one hook in `realtime_routes._compress_and_persist`). Two registered tools: `tools/knowledge_lookup.py` (grounded retrieval with strict-grounding + `NO_GROUNDED_ANSWER` fallback signal + conflict detection) and `tools/web_search.py` (Tavily fallback with prompt-injection defenses). Anti-hallucination: strict instruction string + citation requirement + conflict flag.

**Workspace scoping:** `knowledge_docs` + `knowledge_chunks` carry a nullable `workspace_id` (null = personal). `search_knowledge` resolves the caller's workspace_ids from `workspace_members` and passes them to the `knowledge_search` RPC, which matches a chunk when `c.user_id = caller OR d.workspace_id = any(caller_workspace_ids)`. `ingest_doc` propagates the doc's `workspace_id` onto every chunk; PATCH keeps chunks in sync when a doc moves scope. `knowledge_service._supabase()` reads `SUPABASE_SERVICE_ROLE_KEY` then falls back to `SUPABASE_KEY` (this project's name for the service-role key).

**Env vars:** `OPENAI_API_KEY` (embeddings only — chat stays on Groq) and `TAVILY_API_KEY` (web_search + url_loader). Both must be set on Render for production RAG. New Python deps: `openai`, `tiktoken`, `pymupdf`, `pytesseract`, `python-docx`, `notion-client`, `pysbd`, `langgraph`.

**Status:** Smart-RAG **all phases shipped** on `vids_branch` (pending production deploy). Phase 1 (meeting transcripts indexed alongside docs via `knowledge_transcript.py`, lightweight inline preamble), Phase 2 (`knowledge_ingest/context_preprocessor.py` adds a Groq-generated one-sentence preamble per chunk before embedding; LRU-capped at 5000 entries), Phase 3 (hybrid vector+BM25 with Reciprocal Rank Fusion in `_rrf_merge`, graceful fallback if BM25 RPC missing), Phase 4 (`knowledge_reranker.py` — Groq Llama 3.3 70B reranks top-30 to top-k, flag-gated by `PRISM_RERANKER_ENABLED`, 4s timeout), Phase 5 (`knowledge_query_rewriter.py` — heuristic gate + Groq rewrite for terse/follow-up queries, 3s timeout, `PRISM_QUERY_REWRITE_ENABLED` flag). The on-demand `knowledge_lookup` tool turns rerank + rewrite ON; the proactive surfacing path keeps both OFF to stay ~150ms. Spec: `docs/specs/2026-05-20-smart-rag-additions.md`. Handoff brief: `docs/briefs/2026-05-23-smart-rag-handoff.md`.

**Frontend UX:** `KnowledgeBase` is mounted as a top-level dashboard view via a "Knowledge" item in `DashboardSidebar` (`activeView === 'knowledge'`), rendered with the active workspace's id+name. The page shows scope-aware content: in Personal it lists your own *unshared* docs; in a workspace it lists that workspace's *shared* docs (membership-gated by the `workspace_id` query param to `GET /knowledge/docs`). `KnowledgeDocCard` follows the dashboard glass-card aesthetic with a status dot + sensitivity pill. The shared Radix Dialog primitive (`ui/dialog.tsx`) uses `bg-black/70 + backdrop-blur-sm` for its overlay — older `bg-black/10` was invisible on the dark dashboard.

### Frontend Structure

`App.jsx` holds all application state, all input modes, all result state, and the landing/share routing. It is intentionally a large file — don't split it without a strong reason. Always use `apiFetch()` from `lib/api.js` instead of raw `fetch()` — it auto-attaches the auth token.

`App.jsx` also owns `activeWorkspaceId` state (persisted to `sessionStorage` as `prism_active_workspace`). This is passed to `DashboardPage` and used in: meeting saves (`workspace_id` in `POST /meetings` payload), history fetches (`/meetings?workspace_id=`), and insights fetches (`/insights?workspace_id=`). Two callbacks handle workspace changes: `onWorkspaceChange(wsId)` — full switch, clears `result` and `meetingId` so no stale meeting shows; `onJoinWithWorkspace(wsId)` — silently sets the active workspace without clearing the current view (used when joining a bot from a pre-matched calendar event). History re-fetches on workspace switch because `activeWorkspaceId` is in the history effect's dependency array.

`App.jsx` detects `#invite/{token}` hash synchronously via `INITIAL_INVITE_TOKEN` at module load. When present, the normal app render is replaced by an invite acceptance screen. Unauthenticated users see a "Sign in with Google" button — the token is saved to `sessionStorage` (`prism_pending_invite`) before the OAuth redirect, and the `SIGNED_IN` auth handler restores it by navigating to `/dashboard#invite/{token}`. Accepted invites write `prism_active_workspace` to sessionStorage so the dashboard opens in the right workspace.

`DashboardPage.jsx` renders the workspace chip row (Personal + workspace chips + `+ New` creator) just below the header. Switching a workspace calls `props.onWorkspaceChange(wsId)` which updates App.jsx state and triggers a re-fetch. `switchWorkspace()` in DashboardPage also closes the settings panel (`setWsSettingsId(null); setWsDetails(null)`) so it doesn't persist across workspace switches. Workspace list is fetched in DashboardPage via `GET /workspaces` and includes `member_emails` (one bulk query, not N+1). Each active workspace chip has a ⚙ button that opens an inline settings panel below the chip row — shows the invite link (copy/regenerate), member list with remove buttons, and delete/leave workspace. A first-run nudge callout appears below the chip row for signed-in users who have no workspaces yet; it is permanently dismissed via `localStorage` key `prismai:workspace-nudge-dismissed`. The nudge only renders after the workspace fetch resolves (`workspacesLoaded` flag) to prevent a flash on load for users who already have workspaces.

`NewMeetingPanel` is defined at module scope (above `DashboardPage`). It receives `workspaces` as an explicit prop (`workspaces={workspaces}` passed at render site) — do NOT reference the `workspaces` free variable inside it, as that is local state of `DashboardPage` and is out of scope.

`UpcomingMeetings.jsx` matches calendar `attendee_emails` (returned by `GET /calendar/events`) against workspace `member_emails` (returned by `GET /workspaces`) to auto-classify upcoming meetings. Matched meetings show a cyan workspace chip plus a **Brief** button; unmatched meetings show a gray "Personal" chip. Clicking Brief lazy-fetches `GET /workspaces/{id}/brief` and expands an inline `<BriefPanel>` listing open action items from recent workspace meetings. Each item is clickable → calls `onOpenMeeting(meetingId)`, which closes the new-meeting popover and routes through `handleOpenMeetingById` in `DashboardPage.jsx` (uses in-memory history if loaded, else fetches `GET /meetings/{id}`). Clicking Join passes the matched workspace id to `onJoinWithWorkspace`.

`SentimentCard.jsx` is a dedicated card in `frontend/src/components/dashboard/` that renders the sentiment agent's full output: color-coded overall label pill, trend arc indicator, animated score bar, notes, per-speaker tone rows, and tension moments. Replaces the prior 2-line inline block in `MeetingView`. Renders on both dashboard and shared meeting view (no `readOnly` guard). The agent vocabulary is `collaborative | aligned | decision-making | exploratory | frictional | divergent | rushed | draining | neutral` — color mapping is in `LABEL_META`. Keep that map in sync if the prompt vocabulary in `backend/agents/sentiment.py` ever changes.

The landing page has a three-layer WebGL stack (all `position:absolute, inset:0, pointer-events:none`): `<Prism />` (ogl, full-page ray-marched prism), a top vignette div, a bottom fade div, and two `<LightPillar />` instances (three.js, one per side edge). Current tuning values are documented in `PRISM_AI_CONTEXT.md` → "Landing Visual Layer". As of Jun 2026, the landing also has a pre-rendered video loop alternative — `PrismCapture.jsx` + `scripts/capture-prism.mjs` produce `public/prism-loop.mp4`, which the redesigned `HowItWorks.jsx` can swap in for GPU-cheap playback on lower-end devices. `LandingNav` is returner-aware (shows "Go to dashboard" for known users instead of signup CTAs). The earlier `ProofSection` is retired — its role is absorbed into the new HowItWorks layout.

Personas: 7 presets defined in `backend/personas.py PRESETS` — `default`, `concise`, `formal`, `cheeky`, `socratic`, `warm`, `analytical` — plus `custom` (per-user only, 500-char cap). Workspace default is preset-only (no `custom`) so an admin can't inject arbitrary prompt text into all members' meetings. `PersonaChip.jsx` exposes the picker in ChatPanel header, workspace modal, and account dropdown.

**Live-bot identity per persona (Jun 2026):** every non-default preset renames the in-meeting bot to a Prism-family name (`concise→Flash`, `formal→Crystal`, `cheeky→Glint`, `socratic→Echo`, `warm→Glow`, `analytical→Spectrum`). Defined in `backend/personas.py PERSONA_NAMES` / `PERSONA_GREETINGS`. The bot's intro chat message (`recall_routes._send_bot_intro`) picks a hardcoded greeting per preset; the live-link + consent lines are appended verbatim regardless. The persona name is also injected into the cached static system prefix (`_build_static_prefix` in `realtime_routes.py` — `"Your name in this meeting is X..."`) so the bot self-identifies as that name in every LLM reply. **Wake words are per-bot:** the bot responds to its persona name (e.g. "Flash, summarize…") in addition to the always-on `Prism / PrismAI` aliases — `_BOT_WAKE_ALIAS[bot_id]` is populated by `_get_settings_for_bot` and compiled patterns cached in `_WAKE_PATTERN_CACHE`. Cleared on bot teardown. Custom personas keep the "Prism" name + default greeting (custom is tone-only). The Recall participant display name in the meeting sidebar stays `PrismAI` regardless of preset.

Bot reply formatting: chat replies are sent verbatim (no `✓` prefix — removed Jun 2026). Proactive nudges and the knowledge-proactive surfacing message both use the active persona name when telling the user how to invoke the bot (`Say 'Flash, summarize…'` rather than `Say 'Prism, summarize…'`).

**Persona picker UI (Jun 3 2026):** `PersonaChip.jsx` shows the bot's display name alongside the preset label everywhere it mounts. Each preset has a matching lucide icon with a subtle per-persona accent color — `default→Triangle (cyan)`, `concise→Zap (amber)`, `formal→Gem (slate)`, `cheeky→Sparkles (fuchsia)`, `socratic→Radio (indigo)`, `warm→Sun (orange)`, `analytical→BarChart3 (violet)`. The chip in the chat header reads e.g. `⚡ Concise · Flash ▾`; the account dropdown row shows `⚡ Persona  ‹Concise · Flash›`; picker dialog rows show icon + label + name. The `PRESETS` array (icon + name + iconClass) is the single source of frontend truth — keep it in sync with `backend/personas.py PERSONA_NAMES`. Custom personas keep the "Prism" name in the chip (custom is tone-only on the backend).

Current design direction: use shadcn/radix-style product surfaces with the app's existing cyan/sky accent (`#22d3ee`, `#67e8f9`, `sky-*` / `cyan-*`). Do not make glassmorphism the default visual language for the site or dashboard. Glass-like treatment is only an accent for CTAs, focused highlights, or special moments.

`ChatPanel.jsx` runs three chat modes in priority order: agent intent (regex → `POST /agent`), global intent (regex → `POST /chat/global`, requires auth), regular chat (`POST /chat`).

### Auth

Frontend Supabase client (`lib/supabase.js`) returns `null` if env vars are missing — auth degrades gracefully. Google Calendar uses a direct PKCE flow (not Supabase OAuth) because Supabase v2 doesn't persist `provider_token` in stored sessions. The PKCE verifier is stored in `sessionStorage` during the redirect.

### Known Limitations

- `bot_store` in `recall_routes.py` is in-memory — lost on Render restart. Fix requires a `bots` Supabase table.
- Bot endpoints (`/join-meeting`, `/bot-status`, `/recall-webhook`, `/realtime-events`) are unauthenticated by design — bot results are not user-scoped.
- Render free tier cold starts take 30–60s.
- Roadmap state (per `PRISM_AI_CONTEXT.md`): Phases 1–4 complete and deployed (workspaces, meeting pattern intelligence, LangGraph two-tier orchestration, bot dedup). Phase 5 (RAG) — baseline live in production; smart-RAG upgrades (Phases 1–5 of the smart-RAG sub-plan) pending. Phases 6–8 (voice ID, context-aware conversation, personas) pending.
- `MeetingView.jsx` header renders when `onBack || meeting` is truthy — not just when `meeting` is set. This ensures fresh analyses (which have `onBack` but no `meeting` object) still show the title and back arrow. Use `meeting?.date` not `meeting.date`.
- `StatsCanvas.jsx` `SingleMeetingState`: centered layout matching the multi-meeting welcome style. Shown when history has exactly 1 entry.

---

## Deployment

- **Frontend:** Vercel auto-deploys `frontend/` on push to `main`. Build: `npm run build`, output: `dist`.
- **Backend:** Render auto-deploys from `render.yaml` on push to `main`. Service name is `meeting-copilot-api` (URL is locked to creation-time name regardless of dashboard display name).

All Supabase migrations live in `supabase/`. Two ways to apply them:

- **Runner (preferred):** `python supabase/migrate.py` applies every migration in dependency order. Requires `DATABASE_URL` in `backend/.env` (Supabase connection pooler URL). All migrations are idempotent (`IF NOT EXISTS` guards), safe to re-run.
- **SQL editor (fallback):** paste files into the Supabase SQL Editor in the order listed below. `full_schema_fix.sql` is a consolidated idempotent script that covers calendar + tools + bot_commands in one shot if you'd rather not run them individually.

Migration order (dependency-correct):

1. `auth_migration.sql` — meetings + chats tables.
2. `calendar_migration.sql` — `user_settings` table.
3. `tools_migration.sql` — `linear_api_key` / `slack_bot_token` columns + `bot_sessions` table.
4. `bot_sessions_live_token_migration.sql` — `bot_sessions.live_token` (unique) so the live-share index survives Render restarts.
5. `bot_commands_migration.sql` — `append_bot_command()` RPC for atomic command appends (avoids read-modify-write race on `bot_sessions.commands`).
6. `memory_migration.sql` — `bot_sessions.memory_summary` (TEXT) + `bot_sessions.live_state` (JSONB) for the three-layer live-meeting memory system.
7. `chat_sessions_migration.sql` — per-meeting ephemeral `chat_sessions` table (replaces single-row `chats` model; backend prunes to 3 most recent per meeting).
8. `chats_unique_migration.sql` — unique constraint on `chats(meeting_id, user_id)` so legacy upsert paths stop racing. Deduplicates existing rows first.
9. `action_refs_migration.sql` — `action_refs` table tracking action items resolved into external tools (Linear/Slack/Gmail).
10. `workspace_migration.sql` — `workspaces` + `workspace_members` (note: `user_id` / `workspace_id` stored as `text`, not uuid) + `meeting_bots` + adds `workspace_id` / `recorded_by_user_id` / `email_claimed_by` columns to `meetings`.
11. `knowledge_migration.sql` — `knowledge_docs` + `knowledge_chunks` (pgvector) + `knowledge_queries` + `knowledge_search` RPC. Also create a private Supabase Storage bucket named `knowledge` (50MB) with the RLS policy in the file's header.
12. `knowledge_workspace_migration.sql` — adds `workspace_id` to `knowledge_docs` / `knowledge_chunks`, RLS for workspace members (casts to text since `workspace_members` columns are text), and redefines `knowledge_search` with a `caller_workspace_ids uuid[]` param (drops the old 5-arg signature first). Run AFTER `knowledge_migration.sql`.
13. `knowledge_meeting_source_migration.sql` — extends `source_type` CHECK to allow `'meeting_transcript'`. Smart-RAG Phase 1 (cross-source unification).
14. `knowledge_contextual_migration.sql` — adds `embedded_content` column to `knowledge_chunks` + backfills existing rows so future writes can store the preamble-augmented text separately from the displayed `content`. Smart-RAG Phase 2 (contextual retrieval).
15. `knowledge_bm25_migration.sql` — adds `content_tsv` generated tsvector column + GIN index + `knowledge_search_bm25` RPC (same caller/workspace scoping as `knowledge_search`). Smart-RAG Phase 3 (hybrid retrieval via Reciprocal Rank Fusion). Run AFTER #14. Includes a session-scoped `SET maintenance_work_mem='128MB'` so the GIN build doesn't OOM on Supabase's default 32MB.
16. `knowledge_transcript_unique_migration.sql` — partial unique index on `knowledge_docs (meeting_id)` filtered to `source_type='meeting_transcript' AND deleted_at IS NULL`. Closes a race window where two concurrent `save_meeting` calls could double-index the same transcript. Run AFTER #13.
17. `personas_migration.sql` — `user_settings.persona_preset` + `persona_custom_prompt` (500-char check), `workspaces.default_persona` (preset-only, no custom), `meetings.persona_used` (nullable audit field). All with CHECK constraints; idempotent.
18. `personas_warm_analytical_migration.sql` — adds `'warm'` and `'analytical'` to the persona CHECK constraints on `user_settings.persona_preset` + `workspaces.default_persona`. Run AFTER #17.
19. `recording_migration.sql` — `meetings.recall_bot_id` + `recording_provider` + `transcript_segments` (jsonb); `bot_sessions.transcript_segments` staging area + partial index on `recall_bot_id`. Powers the Recording Playback feature.

Here's the full roadmap, sequenced by dependency. Each phase is a coherent shippable unit — you can demo and get feedback before moving to the next.

Phase 1 — Workspace Layer (foundation for everything)
Why first: Every other feature scopes to a workspace. Nothing else makes sense without this.

DB (Supabase)

workspaces — id, name, created_by, created_at
workspace_members — workspace_id, user_id, role (owner/member), joined_at
meetings — add workspace_id nullable (null = personal)
Backend

CRUD routes: create workspace, invite member by email, list your workspaces, leave/delete workspace
All /meetings, /insights, /chats queries gain a workspace_id param — if provided, scope to workspace; otherwise fall back to user-owned
Frontend

Workspace switcher chip row at top of dashboard (Personal + team names)
On first open: prompt to create a workspace or stay Personal
Meeting save flow: "Save to: Personal / Engineering / Marketing" picker
History + Intelligence views re-query when active workspace changes
Milestone: You can create a team, invite a colleague, and both see the same meetings.

Phase 2 — Meeting Pattern Intelligence (the data payoff)
Why second: Once workspaces exist you have the cross-user dataset to make intelligence meaningful.

Backend

Extend cross_meeting_service.py to accept workspace_id
New analytics: decision velocity (decisions per meeting over time), recurring unresolved topics (NLP cluster on summaries), action item completion rate, meeting health trend, top contributors by action items assigned
New endpoint: GET /workspace-insights/{workspace_id} — returns all of the above
Frontend

Intelligence view gets a workspace-scoped mode — same layout, but charts show team data, not just yours
New chart: "Team Health Over Time" (health score trend line per workspace)
Recurring themes card: top 5 topics that appear across meetings without a decision
Members leaderboard: who owns the most open action items
Milestone: Dashboard shows your team's meeting health trend and who's blocking decisions.

Phase 3 — LangGraph Orchestration (infra unlock)
Why third: Before you add more agents (knowledge base, voice, context-awareness), the pipeline needs to be composable. Current asyncio.gather doesn't handle conditionals, retries, or shared state cleanly.

Backend

Replace analysis_service.py with a StateGraph — each of the 7 agents is a node
Orchestrator node runs first, returns {agents_to_run: [...]} — conditional edges replace the current run_sentiment_if hacks
Shared state object = DEFAULT_RESULT dict — nodes read from and write to it
SSE emission happens in a streaming callback, same format as today — frontend changes: zero
Add per-node retry (3x) and error boundary (one agent failing doesn't abort others)
Milestone: Analysis pipeline is a visual graph. Adding a new agent = add one node + one edge, no other file changes.

Phase 4 — Multi-User Bot Deduplication (network effect)
Why fourth: Depends on workspace membership to know who to fan out results to.

DB

meeting_bots — id, meeting_url_hash, bot_id, owner_user_id, workspace_id, status, created_at
Backend

Before joining: check meeting_bots for active bot on same URL hash. If found, return {existing_bot_id, owner} instead of joining
After analysis completes: query workspace_members + Google Calendar to find other users who had this meeting in their calendar → fan out result by writing to their meetings table with recorded_by_user_id attribution
Existing share token system re-used for the fan-out
Frontend

If a bot already in meeting is detected: show "Prism is already in this meeting (via [name]). You'll get the summary when it's done." banner
History shows meetings recorded by others with a "via [name]'s Prism" tag
Milestone: Two users with Prism in the same meeting → one bot joins, both get the summary.

Phase 5 — Knowledge Base / Graph RAG (enterprise moat)
Why fifth: Needs workspace (for scoping), LangGraph (to add a retrieval node cleanly), and enough real usage to know what to index.

DB

workspace_docs — id, workspace_id, filename, content, uploaded_by, created_at
workspace_graph — entity nodes + edges (people, projects, decisions, terminology) stored as JSON or in a dedicated graph structure (start simple: JSON in Postgres, migrate to Neo4j if needed)
Backend

/workspace/{id}/knowledge — upload docs (PDF, txt, md), parse into entity graph
Graph builder: NLP pass to extract entities and relationships, write to workspace_graph
New LangGraph node: retrieval — runs before agents when a workspace has knowledge loaded; injects relevant context into agent prompts
Chat agent updated: answers grounded to graph context, refuses to speculate beyond it
Frontend

Settings panel: "Team Knowledge Base" — upload files, see indexed entities, delete docs
Chat shows "Answered from team knowledge" badge when retrieval was used
Milestone: Upload your company org chart + project brief → Prism answers "who owns X project" correctly without hallucinating.

Phase 6 — Voice Identification (security/trust layer)
Why sixth: Most impactful when multi-user bots are live and knowledge bases have sensitive data.

Backend

Speaker enrollment: record 10-second voice sample → generate embedding (use ElevenLabs or a dedicated model like Resemblyzer)
Store {user_id, voice_embedding} in user_settings
During live meeting: Recall.ai webhook delivers audio segments → identify speaker → match to enrolled users
Access control middleware: if query comes from an unrecognized voice, respond with only public workspace context (no personal calendar, email, action items)
Frontend

Onboarding step: "Enroll your voice" — record sample, confirm
In-meeting UI: shows identified speakers in real time
"Private data protected" indicator when Prism is active in a meeting
Milestone: You ask Prism about your calendar in a meeting, a colleague asks the same question, Prism only answers you.

Phase 7 — Context-Aware Conversation (quality layer)
Why seventh: Needs knowledge base for grounding, benefits from workspace history for disambiguation.

Backend

Chat agent tracks conversation state: named entities mentioned, ambiguous references, unresolved questions
When a question references something ambiguous ("what did she say about the budget"), generate a clarifying question instead of guessing
Multi-turn context window: last 10 exchanges + relevant meeting excerpts kept in prompt
Frontend

Chat input shows "Prism is asking..." state when disambiguation is needed
Clarifying question rendered as a choice UI (two options + free text)
Milestone: "What did Sarah decide?" → Prism: "I found two things Sarah mentioned — the Q3 budget cut and the vendor switch. Which did you mean?"

Phase 8 — Personas (delight layer)
Why last: Standalone feature, low complexity, good marketing story after everything else is solid.

4-5 system prompt variants: Default (current), Concise, Formal/Executive, Cheeky/Sarcastic, Socratic/Intellectual
Workspace-level setting (team picks a default persona) + personal override
Tiny UI: persona selector in settings, chip indicator in chat
Summary
Phase	What it is	Unlocks
1	Workspace layer	Everything
2	Team intelligence	B2B story
3	LangGraph	Agent scalability
4	Multi-user bot dedup	Network effect
5	Graph RAG knowledge base	Enterprise sales
6	Voice identification	Security story
7	Context-aware chat	Quality/trust
8	Personas	Delight/marketing
-------------------------------------------------------------
## CURRENT STATUS — updated Jul 6 2026

**All 8 original phases shipped & live** (main → Render + Vercel auto-deploy). The original
roadmap is essentially complete; the product has since grown well past it. Summary:

| Phase | Status |
|---|---|
| Phase 1 — Workspace Layer | ✅ Done (CRUD, invites, switcher, attribution, per-workspace knowledge + personas) |
| Phase 2 — Meeting Pattern Intelligence | ✅ Done (completion rate, decision velocity, owner load, unresolved themes) + **Calendar view** of history (Month/Week/Day, filters, insights rail) |
| Phase 3 — LangGraph Orchestration | ✅ Done (two-tier StateGraph, deterministic router, 10 agents incl. `decision_linker` + `action_executor`) |
| Phase 4 — Multi-User Bot Dedup | ✅ Done (workspace dedup + fan-out + liveness check + durable `meeting_bots`) |
| Phase 5 — Knowledge Base / RAG | ✅ Done (workspace-scoped + smart-RAG Phases 1–5: cross-source transcripts, contextual preamble, hybrid vector+BM25 RRF, LLM reranker, query rewriter) |
| Phase 6 — Voice Identification | 🔄 **Being built by another teammate** (off our plate). Voice/latency/wake/interrupt redo is the highest-impact item and is owned elsewhere. |
| Phase 7 — Context-Aware Conversation | ◑ Partially covered (continuous per-meeting chat, RAG trust layer, live catch-up). Full disambiguation UI still pending. |
| Phase 8 — Personas | ✅ Done (7 presets + custom, workspace default, per-bot identity/names/wake-words) |

**Major features shipped SINCE the original 8 phases** (all on `main`):
- **Custom domain** — app live at `meetprismai.com` (Vercel + Route 53), Supabase auth at `auth.meetprismai.com`.
- **SSO-only sign-in** — Google + Microsoft (Azure); email/password dropped.
- **Recording Playback** — Recall video/audio + synced click-to-seek transcript (gap: no click-to-seek on bot-active meetings — see backlog).
- **Stand-in async proxy** (Feature A) + **Live catch-up "Ask Prism, just you"** (Feature B).
- **Outbound integrations** — Jira (rich [Prism] tickets), Microsoft Teams recap, Outlook calendar, Slack, Notion, Linear, Gmail, Google Calendar. (Currently per-user; per-workspace routing is a backlog item.)
- **Suggested Actions** — Tier-2 `action_executor` prepares owner's action items → approve-first execute.
- **LLM migration** — Groq removed; agents/RAG on Claude Haiku 4.5, chat/bot on gpt-4o-mini, stand-in composer on gpt-4o.
- **Live-bot polish** — branded "PrismAI Notetaker" join (name + logo tile), `/leave` command, solo free-flow, mute kill-switch, speak-short/chat-full, owner-POV email, bot-exit traceability (dismissable banner).
- **Transcription grounding** — Deepgram nova-3 keyterms (KB + teammate names) + async batch re-transcription for bot-silent meetings.
- **Move / delete meetings** (Jul 6) — owner-cascade across workspace fan-out copies; RAG transcript follows; delete tombstones the bot so recovery can't resurrect it.
- **Image analysis in chat** (Jul 6, IN PROGRESS) — paste/drop images into per-meeting + global chat; gpt-4o-mini vision; private `chat-images` bucket + signed URLs.

**▶ CURRENT PRIORITY ORDER (Jul 6 2026):**
1. **Image analysis — CLUBBED (IN PROGRESS):** (a) images in app chat (per-meeting + global `/chat`, `/chat/global`) — paste/drop/attach, gpt-4o-mini vision, private `chat-images` bucket + signed URLs; **(b) images posted in the live meeting chat** (Meet/Teams) — the bot "sees" them and can answer. Confident part = image **URLs** pasted in chat (Recall relays chat text → detect URL → feed to vision model). Attachment **files** in Teams chat depend on whether Recall's `chat_message` webhook includes the attachment URL — verify during build; fall back to URLs if not. Reuses the same vision message-shaping as (a).
2. **★ LIVE-BOT SCREEN-SHARE VISION (DEFERRED — future feature):** the bot watches the shared *screen* (video feed) in real time — demos, slides, whiteboards. Deferred by user Jul 6. **Feasibility-gated when picked up:** verify Recall's real-time video-frame / screenshot API + design a frame-sampling strategy (cost/latency). Builds on the image-analysis vision pipeline.
3. **Notifications system** — Supabase `notifications` table + event triggers + bell/unread UI (build on Devaj's StatusIsland). Plan at `docs/specs/2026-06-03-notifications-system-plan.md`.
4. **Per-workspace integrations** — move Jira project / Slack channel / Teams webhook from per-user → per-workspace (unlocks per-workspace Jira routing + notes routing). Architectural, multi-day.
5. **Timestamped-transcript click-to-seek** for bot-active meetings (emit segments from the realtime buffer's word timestamps).
6. Smaller registered asks: summarizer "when the bot left" mention; grounding from doc *content* not just titles; Teams recap → workspace tasks.

**Deferred / parked:**
- **AWS migration** — parked until paying/regular users (restart-bug class mitigated via durable owner lookup + startup poller recovery). Plan at `AWS_MIGRATION_PLAN.md`.
- **Browser extension** (impromptu capture) — scoped, Phase-1 ready, parked.
- **Onboarding / guided tour** — parked.
- **CRM (HubSpot)** — only if committing to a vertical; multi-day.
- **Move/delete permission polish** — request-to-owner flow + true per-user "hide from my view" (non-owner delete is cosmetic-only today).
- Bot auto-takeover on failure (Option B) — manual alert only for now.

**Deferred debt:**
- `bot_store` in-memory → lost on Render restart (mitigated by durable `meeting_bots` + startup recovery; full fix = the parked AWS/DB work).
- Action item completion state is per-member; should be one shared state per workspace meeting.

-------------------------------------------------------------
Key files to know
File	Role
backend/workspace_routes.py	All workspace + invite logic
backend/recall_routes.py	Bot join, dedup, webhook handling
backend/storage_routes.py	Meeting save, fan-out, scoped queries
frontend/src/App.jsx	All state, invite screen, bot logic
frontend/src/components/DashboardPage.jsx	Chip row, settings panel, attribution map
frontend/src/components/dashboard/MeetingsRail.jsx	History cards with attribution
frontend/src/components/dashboard/MeetingView.jsx	Meeting detail with attribution
PRISM_AI_CONTEXT.md	Full system reference — read this first
CLAUDE.md	Claude-specific instructions — always read before touching code

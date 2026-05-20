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
Phase 1 is the only thing blocking everything else. Want to start there — schema first, then backend routes, then the workspace switcher?


-------------------------------------------------------------
What's NOT done yet (next session picks up here)
The app is not yet deployed — everything is on main branch locally, untested against the live backend. First thing next session:

Push to main → Render auto-deploys backend, Vercel auto-deploys frontend
Smoke test: create workspace → copy invite link → open in incognito → accept → switch workspace chip → verify history scopes correctly
Remaining phases (6 left)
What was built here was Phase 1 (Workspaces + Invites) and Phase 4 (Bot Dedup + Fan-out). The remaining six:

Bot store persistence — bot_store in recall_routes.py is in-memory, lost on Render restart. Needs a bots Supabase table. Without this, in-flight meetings are lost on cold start.
Meeting Pattern Intelligence — cross-workspace analytics UI: decision velocity, recurring themes, action item completion rates. Backend cross_meeting_service.py has the foundation.
Action item sync across workspace — right now each member has their own completion state. Should be one shared state per workspace meeting.
LangGraph orchestration — replace asyncio.gather in analysis_service.py with a StateGraph. Cleaner conditional routing, per-agent retry, better observability.
Graph RAG knowledge base — workspace-scoped document ingestion, entity graph, grounded chat answers instead of transcript-only context.
Auto-takeover on bot failure — when the active workspace bot errors, notify suppressed members and trigger a new join from one of them automatically. (Option B — we deliberately deferred this, currently using Option C which is just a manual alert.)
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

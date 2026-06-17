# Proxy Representation + Private Catch-up — Design Spec

**Date:** 2026-06-17
**Status:** Planning (pre-implementation; awaiting sign-off)
**Origin:** Roadmap item #4 ("send info through piggyback bots to the shared live bot"), expanded in design.

This spec covers **two related but distinct features** that share an auth model and
access to live bot state, but nothing else:

- **Feature A — Async Proxy ("Stand-in"):** a workspace member who can't attend a
  meeting has the bot represent them. They converse with the bot beforehand to build
  an accurate, *approved* update synthesized from their action items + notes; the bot
  delivers it into the meeting when it runs.
- **Feature B — Private Catch-up ("Side-chat"):** a member who joins late or has a
  question they don't want to ask aloud gets a private assistant grounded in the live
  meeting (rolling summary + decisions + action items + transcript). Answers go back
  only to the asker — never into the meeting.

They are planned and built separately. Feature A is the hero (higher impact, more
build); Feature B is the lighter sibling (mostly assembly over existing infra).

---

## 0. Why this is worth building (and the risks)

- **Strategic fit:** Prism already owns the expensive infra this needs — a live bot in
  the room with TTS + meeting-chat + workspace dedup + rolling memory. For competitors
  (Otter/Fireflies/Read.ai) this is a major build; for us it's a thin layer. No
  mainstream meeting assistant ships "bot represents an absent member live."
- **ICP:** teams that still hold *live recurring meetings* (standups/syncs) **and** have
  occasional absentees. Fully-async teams use Geekbot/StandupBot instead.
- **Risk 1 — adoption friction (the whole ballgame):** the note must be left *before*
  the meeting. If buried, nobody uses it. Entry point must be contextual (UpcomingMeetings)
  and, later, nudged.
- **Risk 2 — misrepresentation:** a proxy that says something wrong/unapproved is *worse*
  than no update. Mitigated by the mandatory approval gate (§A.4).
- **Caveat — owner attribution is fuzzy:** action-item `owner` is a free-text name from
  the transcript, not a linked user_id. "My items" is a name-match, not a hard join. The
  pre-meeting conversation + approval compensate.

---

# FEATURE A — Async Proxy ("Stand-in")

## A.1 End-to-end flow

1. **Trigger.** In `UpcomingMeetings`, a workspace-matched meeting shows a
   **"Can't make it? → Have Prism represent me"** action. Clicking opens the
   **Stand-in composer** for that meeting (carries `meeting_url`, `workspace_id`,
   `calendar_event_id`, `scheduled_for`, `meeting_label`).
2. **Draft.** On open, the bot generates a first-pass draft from the author's
   relevant action items (open + recently completed) across the workspace's last
   30 days, plus any standing notes. Shown as the bot's opening message.
3. **Converse.** Author and bot chat to refine (the bot asks clarifying questions;
   author edits freely). This is a normal chat surface, private to the author.
4. **Approve.** Author clicks **Approve**. The current draft text is **frozen** as
   `approved_body`; row moves `draft → pending`. Author can re-open to edit
   (→ back to `draft`) or cancel (→ `canceled`) any time before delivery.
5. **Bind.** The row is keyed by `(workspace_id, normalized meeting_url)` — the same
   key `meeting_bots` uses for dedup. No calendar-id plumbing into the bot required.
6. **Deliver.** When *any* bot for that workspace reaches `in_call_recording` on that
   URL, it looks up `pending` representations for the key and delivers them:
   - posts a single consolidated message to the **meeting chat**,
   - adds them to the **live-share brief**,
   - flips each row `pending → delivered` (idempotent; survives restart/dedup),
   - **spoken aloud only on request** ("Prism, any updates from people who couldn't
     make it?") — never auto-spoken (delivery model A).
7. **Expire.** If no bot ever joins, rows expire (`scheduled_for + 6h`, or
   `created_at + 24h` when no schedule). Author optionally notified it wasn't delivered.

## A.2 Data model — `proxy_representations` (new table)

```
id                uuid pk default gen_random_uuid()
workspace_id      text not null              -- text, matches workspace_members
meeting_url       text not null              -- NORMALIZED (the bind key)
calendar_event_id text                       -- optional, for richer dedup/expiry
meeting_label     text                       -- display only ("Mon Standup")
scheduled_for     timestamptz                -- meeting start (for expiry/ordering)
author_user_id    text not null
author_name       text not null              -- display name used in delivery
author_email      text
draft_body        text                       -- working text (conversation output)
approved_body     text                       -- frozen on approve; what gets delivered
structured        jsonb default '{}'         -- optional {done:[], doing:[], blockers:[]}
status            text not null default 'draft'
                  -- draft | pending | delivered | expired | canceled
created_at        timestamptz default now()
approved_at       timestamptz
delivered_at      timestamptz
delivered_bot_id  text                       -- which bot delivered (audit)
```

Indexes: `(workspace_id, meeting_url, status)` for the bot lookup;
`(author_user_id, status)` for the management list.
Idempotency: delivery is a conditional update `... where status='pending'` so two
concurrent bots / a restart re-trigger deliver exactly once (mirrors the
`_processing_bots` guard pattern).
Migration: `supabase/proxy_representations_migration.sql`, idempotent (`IF NOT EXISTS`),
`workspace_id`/`author_user_id` as **text** (project convention). RLS for workspace
members (cast to text). Add to the migration order list in CLAUDE.md.

## A.3 Synthesis sources (the "meaningful update")

The draft is generated by an LLM (gpt-4o-mini, the chat model) from:
- **Action items owned by the author** across the workspace's last 30 days
  (name-match on `owner`), with `completed`, `task`, `due`. → "what you finished /
  what's still open."
- **Decisions the author was party to** (optional, lower priority).
- **Author's standing notes** (if any — v2 standing profile) + **structured fields**
  (Done/Doing/Blockers) they fill in the composer.
Prompt frames it as a concise stand-up-style update in the author's voice, first
person ("I finished X; Y is in progress; blocked on Z"). Never invents completion —
only states what the data/notes support; unknowns become questions the bot asks.

## A.4 Approval gate (non-negotiable)

- Nothing is deliverable until `status='pending'` with a non-empty `approved_body`.
- `approved_body` is what gets delivered, verbatim (post-synthesis, post-approval).
- Re-editing after approval reverts to `draft` and clears `approved_at` (must re-approve).
- The bot's delivered message is clearly attributed as a stand-in (§A.6) so the team
  knows it's a represented update, not the bot's own claim.

## A.5 Endpoints (all `require_user_id`, workspace-membership gated)

```
POST   /proxy/representations                 create (draft) for a meeting
GET    /proxy/representations?status=&upcoming=1   list mine
GET    /proxy/representations/{id}            fetch one (author or workspace member?)  -> author only for draft
PATCH  /proxy/representations/{id}            update draft_body/structured/meeting fields
POST   /proxy/representations/{id}/message    conversational turn -> returns bot reply + updated draft
POST   /proxy/representations/{id}/approve    freeze approved_body, status->pending
POST   /proxy/representations/{id}/cancel     status->canceled
```
- Membership check: author must be a member of `workspace_id`; the meeting_url is taken
  on trust from the author's own UpcomingMeetings selection (already membership-derived).
- The conversation endpoint reuses chat infra (gpt-4o-mini, streaming optional) with a
  system prompt seeded by the synthesis context (§A.3).

## A.6 Bot-side delivery (realtime_routes / recall_routes)

- **Trigger point:** `recall_routes` bot-status / webhook branch where status becomes
  `in_call_recording` (meeting actually started). Guarded by an in-memory
  `_delivered_proxy_for_bot` set + the DB conditional update for true idempotency.
- **Lookup:** `pending` rows where `workspace_id` = bot's workspace AND `meeting_url` =
  bot's normalized join URL.
- **Chat message (always):** one consolidated post —
  ```
  📋 Stand-in updates (members who couldn't attend):
  • Alice — "Finished the API integration; auth flow still open, blocked on the staging keys."
  • Bob — "Shipped the dashboard cards; reviewing Priya's PR next."
  ```
- **Brief (always):** add a `proxy_updates` array to the `/live/{token}` payload and the
  pre-meeting brief so the live-share panel renders them.
- **Spoken (on request only):** a new intent on the wake-word path — "any updates from
  people who couldn't make it / who's out" → bot reads the consolidated list aloud
  (uses `_spoken_version` to keep it clean). Folds into existing command handling.
- **Attribution / trust:** delivered text is wrapped/labelled as a stand-in update; it is
  NOT attributed as a human participant utterance and does not enter owner-gating.
- **Recording in transcript:** the delivered stand-in block is recorded via
  `_record_bot_line` (so the saved transcript shows "Prism: 📋 Stand-in updates …") —
  consistent with the bot-turns-in-transcript work (Jun 2026).

## A.7 Lifecycle / state machine

```
draft ──approve──> pending ──bot delivers──> delivered
  │                   │
  │                   ├── author cancels ──> canceled
  └── author cancels ─┘
pending ──no bot by expiry──> expired
```
- Edit always pulls back to `draft`. Only `pending` is eligible for delivery.
- Expiry: a lightweight sweep (on next list fetch, or a periodic check) marks
  overdue `pending`/`draft` rows `expired`. No cron required for v1 (lazy on read).

## A.8 Edge cases

- **Meeting URL mismatch** (calendar link ≠ join URL): rely on `_normalize_meeting_url`;
  if it still misses, the row simply never binds → expires. Author picks from
  UpcomingMeetings (real URL), so this is rare.
- **Manual join (no calendar URL):** representation won't bind. Acceptable v1 — surface
  only on calendar-matched meetings.
- **Bot restarts mid-meeting:** in-memory delivery guard is empty after restart, but the
  DB `status='delivered'` prevents re-posting (conditional update no-ops).
- **Author shows up anyway:** v1 delivers regardless (they approved it; harmless). v2:
  detect the author among participants (we now track the roster for solo free-flow) and
  *hold* their stand-in, optionally asking the bot to skip it.
- **Multiple absentees:** consolidated into one chat post + brief block (no spam).
- **Author in multiple overlapping meetings:** rows are per `(workspace, url)`, so no
  collision.
- **Privacy:** the pre-meeting conversation + draft are private to the author until
  approved; `approved_body` is intentionally public to attendees on delivery.

---

# FEATURE B — Private Catch-up ("Side-chat")

## B.1 Purpose & scope

A workspace member watching/￼attending a live meeting (especially a late joiner or a
dedup'd piggybacker) opens a **private** chat with the bot:
- **"Catch me up"** (one tap) → concise summary of what's happened so far.
- **Free Q&A** ("what did they decide about the launch date?") grounded in live state.
Answers return **only to the asker**. Nothing is spoken aloud or posted to meeting chat.

## B.2 Data sources (all already exist)

- `meeting_memory.get_memory_snapshot(rt)` → `memory_summary`, `live_decisions`,
  `live_action_items`, `top_entities` (already exposed on `/live/{token}`).
- `state["transcript_buffer"]` (recent lines).
- Optional: `search_knowledge` for workspace docs (reuse existing RAG).

## B.3 Endpoint (FINAL — token-gated, streaming, member RAG)

```
POST /live/{live_token}/ask    token-gated (NO login required); rate-limited per token
  Authorization: Bearer <jwt>  OPTIONAL — if present + valid + member of the bot's
                               workspace, unlocks RAG fallback (else meeting-only)
  body: { question?: str, mode: "catchup" | "qa" }
  -> text/event-stream: data:{"token":"…"}  …  data:{"done":true,"sources":[…]}
```
- **Token-gated, not login-gated** (decision 2026-06-17): the live page already exposes
  the transcript+memory by possession of `live_token`; catch-up only summarizes the same
  data, so it inherits that model. Resolves `live_token → bot_id` exactly like
  `GET /live/{token}` (in-memory index, DB fallback). Endpoint lives in `recall_routes`
  next to `/live/{token}`; the streaming generator lives in `realtime_routes`.
- **Streaming (decision):** SSE, mirrors `/analyze-stream` (`StreamingResponse`,
  `media_type="text/event-stream"`, `data: {json}\n\n`; frontend reads via `getReader`).
- **RAG fallback — MEMBERS ONLY (decision):** for `qa` mode, if the request carries a
  valid JWT whose user is a member of the **bot's workspace**, run `search_knowledge`
  (scoped to that member) and inject top snippets as "background knowledge — use only if
  the meeting doesn't answer"; the final `done` event carries `sources` (doc names).
  Anonymous link-holders get **meeting-only** (no KB exposure to external guests).
  `catchup` mode never uses RAG.
- **Never** calls `_send_chat_response` / TTS. Streams to the caller's browser only.
- **Rate-limited per token:** ~1.5s min interval, ~12/min cap → `429`.

## B.4 Surface (FINAL)

- **Primary — the live-share page** (`/#live/{token}`, `LiveMeetingView` in App.jsx):
  a new **"Ask Prism (just you)"** card near the top, visible while `status==='recording'`.
  "Catch me up" button + question box; answers stream in and stack as a local thread.
  Sends `Authorization` when a Supabase session exists (unlocks member RAG).
- **Secondary — dashboard live area** (`NewMeetingPanel` in DashboardPage): same card,
  for the bot owner + dedup'd teammates. Built as one shared component `LiveCatchup.jsx`
  used by both surfaces; takes `liveToken` + optional `accessToken`.
- **Dedup token (decision):** add the owner's `live_token` to the `/join-meeting` dedup
  skip responses so a dedup'd teammate can reach the live view + catch-up straight from
  their dashboard. Frontend stores it (`setActiveLiveToken`) in the skip branch.

## B.5 Edge cases

- **Bot not live / no transcript yet:** "Nothing's happened yet" graceful reply.
- **Meeting ended:** fall back to the saved meeting chat (existing per-meeting chat).
- **Non-member calls:** 403.

---

## Build order (proposed)

1. **A. Async Proxy** (hero):
   1a. Migration + table + CRUD/conversation/approve endpoints.
   1b. UpcomingMeetings trigger + Stand-in composer (chat + approve).
   1c. Bot-side delivery (chat + brief + record-in-transcript) + idempotency.
   1d. Spoken-on-request intent.
   1e. Management nav section (list/cancel/history).
2. **B. Private Catch-up** (sibling):
   2a. `/bot/{bot_id}/ask` endpoint (catchup + qa) + membership auth + rate limit.
   2b. Live-view "Ask privately" panel; expose token/bot_id to dedup'd users.

## Open decisions to confirm before coding

- **D1.** v1 surface = UpcomingMeetings trigger only (management section right after)? (rec: yes)
- **D2.** Delivery = consolidated single chat post + brief, spoken-on-request? (rec: yes)
- **D3.** Synthesis pulls action items (name-match) + notes + structured fields; decisions optional? (rec: yes)
- **D4.** Expiry handled lazily on read (no cron) for v1? (rec: yes)
- **D5.** Author-present-anyway handling deferred to v2 (v1 delivers regardless)? (rec: yes)
- **D6.** Feature B ships after Feature A, not interleaved? (rec: yes)
```

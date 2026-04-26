# PrismAI — Improvement Spec 2

> Roadmap for the five differentiating features added after the Apr 22 2026 session.
> Update this doc each time a feature ships or is verified in a live test.

---

## Bug Fixes Shipped Apr 22 2026 (pre-feature work)

These fixes were a prerequisite for reliable live meeting testing.

| Fix | Commit | What changed |
|---|---|---|
| Command trigger word count | `bc8029f` | `_detect_command` now counts words (≥3), not characters. Stops "Prism, what is" (2 words) from firing. |
| Dedup normalization | `bc8029f` | Rolling transcript dedup now normalizes (lowercase, strip punctuation) before comparing, so "What is today's date?" and "what is today's date." are treated as the same command. |
| Google Meet chat parser | `eee46c6` | Chat messages from Google Meet are nested at `data.data.data.text`. Previous parser stopped one level too shallow and always read empty string. |
| Calendar hallucination guard | `b275772` | System prompt now instructs LLM: for `calendar_create_event`, ask for title AND date/time if either is missing — never invent details. |

---

## Feature 5 — Shareable Live View ✅ Shipped

**Status:** `2763adf` + `7d1bc9c` — deployed to Render + Vercel

### What it does

Anyone with the live link can watch a meeting unfold in real time — Prism commands, transcript, and full analysis cards when the meeting ends. No sign-in required. The link is posted automatically in the meeting chat when the bot joins.

### How it works

**Backend (`recall_routes.py`):**
- `/join-meeting` now generates a `live_token` (16-char hex, via `secrets.token_hex`) and stores it in `bot_store[bot_id]` and `_live_token_index`.
- New public endpoint `GET /live/{live_token}` returns: `status`, `commands[]`, `transcript_lines[]` (last 100), `result` (when done), `error`.
- Falls back to Supabase `bot_sessions` table if server restarted and in-memory index was lost.
- `/join-meeting` response now includes `live_token` alongside `bot_id`.

**Frontend (`App.jsx`):**
- `INITIAL_LIVE_TOKEN` constant reads `#live/{token}` from `window.location.hash` on page load (same pattern as `INITIAL_SHARE_TOKEN`).
- If a live token is detected, renders `<LiveMeetingView token={...} />` instead of the main app.
- `LiveMeetingView` polls `GET /live/{live_token}` every 3 seconds.
- Shows: live transcript feed (last 30 lines), Prism commands + replies as they happen, full analysis cards when status becomes `done`, processing/error states.
- When bot status is `recording`, a **"⬡ Copy live link"** button appears in the Join tab so the host can also manually share the link.
- `activeLiveToken` stored in `sessionStorage` alongside `activeBotId` so it survives page refresh.

**Bot intro message (`recall_routes.py` → `_send_bot_intro`):**
- When the bot posts its intro message 20s after joining, it now appends the live link:
  > "Anyone can follow along live: https://agentic-meeting-copilot.vercel.app/#live/abc123"
- Uses `FRONTEND_URL` env var (default: `https://agentic-meeting-copilot.vercel.app`).

### Environment variable needed
| Var | Where | Value |
|---|---|---|
| `FRONTEND_URL` | Render | `https://agentic-meeting-copilot.vercel.app` |

Add this to Render → `meeting-copilot-api` → Environment if not set. The intro message falls back to the hardcoded default if missing — it won't break, but the URL will be wrong if the frontend ever moves.

### How to test

1. Start a meeting → Prism bot joins
2. Wait ~20 seconds → check the Google Meet chat for Prism's intro message — it should contain a live link
3. Open the live link in a separate browser window (or send to a friend)
4. Speak in the meeting: the viewer's window should update within 3 seconds showing the transcript line
5. Say `"Prism, what is today's date?"` — the command + reply should appear in the viewer within ~5 seconds
6. End the meeting — viewer should transition to "Analyzing…" spinner, then full result cards

---

## Feature 2 — Proactive Interventions ✅ Shipped

**Status:** Implemented Apr 25 2026 — deployed on next push to main

### What it does

Prism speaks up without being asked. During a live meeting it monitors for patterns and posts alerts to the meeting chat automatically — for example, if 30 minutes pass with no decision logged, or a topic has come up in previous meetings without resolution.

### Implementation

**Backend (`realtime_routes.py` + `recall_routes.py`):**
- `_run_proactive_checker(bot_id)` — `asyncio.Task` per bot, checks every 60s after a 2-minute grace period. Started via `asyncio.create_task` in `recall_routes.py` → `join_meeting`. Exits when `status` leaves `joining`/`recording`.
- `_fetch_historical_blockers(user_id)` — fetches user's last 10 meetings, extracts incomplete action items + summaries that match `looks_like_blocker()` (reused from `cross_meeting_service.py`), returns `[{keywords, date}]`.
- Transcript handler now sets `meeting_start_ts` on first transcript line and increments `decisions_detected`, `action_items_detected`, `owners_detected` per line.

**Triggers (checked in this priority order):**
| # | Trigger | Condition | Message | Once? |
|---|---|---|---|---|
| 3 | Long meeting | 55+ min elapsed | ⏱️ Approaching 1 hour, wrap up | ✅ |
| 1 | No decisions | 30+ min, `decisions_detected == 0` | 📋 No decisions logged | ✅ |
| 4 | No owners | 3+ action items, `owners_detected == 0`, 15+ min | 👤 Action items lack clear owners | ✅ |
| 2 | Recurring blocker | 2+ keywords from a past blocked item appear in current transcript | ⚠️ Topic came up unresolved in [date] meeting | once per blocker |

**Throttle:** max 1 proactive message per 10 minutes per bot.

**State fields added to `_bot_state`:** `meeting_start_ts`, `intervention_last_ts`, `decisions_detected`, `action_items_detected`, `owners_detected`, `sent_30min_nudge`, `sent_55min_nudge`, `sent_no_owners_nudge`, `recurring_blocker_checked`, `historical_blockers`.

### How to test

1. Start a meeting, temporarily lower the 30-min threshold to 2 min in `_run_proactive_checker` (`elapsed_min >= 2`), stay silent → verify nudge appears in Google Meet chat
2. For recurring blocker: ensure the user has a past meeting with a blocker-flagged action item, start a new meeting mentioning 2+ of the same keywords → verify alert fires
3. Restore threshold to 30 min before shipping

---

## Feature 4 — Speaker Coaching Report ✅ Shipped

**Status:** Implemented Apr 25 2026 — deployed on next push to main

### What it does

A new post-meeting card showing speaker-level stats: talk time percentage, decision ownership, action item ownership, and a one-line coaching note per speaker. Shown in all four layouts: desktop, mobile, share view, and live share view.

### Implementation

**Backend:**
- `backend/agents/speaker_coach.py` — always-run agent (guardrailed in orchestrator). Returns `speakers: []` if fewer than 2 named speakers found (card hides itself).
- Added to `AGENT_MAP`, `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `merge_agent_results` in `analysis_service.py`.
- Added to `ALL_AGENTS` + always-include guardrail in `orchestrator.py`.

**Frontend:**
- `frontend/src/components/SpeakerCoachCard.jsx` — rose/pink color scheme. Shows: conversation balance bar (animated, color-coded green/amber/red), per-speaker rows with avatar initials, animated talk-time bar, decision/action-item ownership pills, coaching note.
- Placed after Email + Calendar row in desktop; after CalendarCard in mobile, share, and live share views.
- Added to `AGENTS_META` in `App.jsx` and `AGENT_CONFIG` in `AgentTags.jsx`.

### How to test

1. Run a multi-speaker transcript through `/analyze` — verify `speaker_coach` key is present in the JSON response
2. Verify the `SpeakerCoachCard` renders with speaker rows and talk-time bars
3. Verify talk percents sum to ~100% across all speakers
4. Run a single-speaker transcript — verify the card is hidden (`speakers: []`)

---

## Feature 1 — Pre-Meeting Brief ✅ Shipped

**Status:** Implemented Apr 25 2026 — deployed on next push to main

### What it does

When you open a live meeting link, Prism surfaces a collapsible brief at the top of the viewer: open action items from your last 5 meetings, recent decisions, and recurring blockers — before conversation starts.

### Implementation

**Backend (`recall_routes.py`):**
- `_build_pre_meeting_brief(user_id)` — pure Python, no LLM. Fetches last 10 meetings, returns `{open_items, recent_decisions, blockers}` or `None` when nothing noteworthy.
- `GET /live/{live_token}` response now includes `brief` (lazily computed + cached in `bot_store`) and `transcript` (when `status == done`).
- Also pulls unresolved `action_refs` rows into `open_items` (Feature 3 integration).

**Frontend (`App.jsx`):**
- `PreMeetingBrief` component — sky-blue collapsible card. Sections: Open Action Items (○ orange), Recent Decisions (⚖ yellow), Recurring Blockers (⚠ red). Shows item count in header.
- Rendered at top of `LiveMeetingView` content area when `status !== 'done'`. Hidden when brief is empty.
- **Save to my history** button: appears in the live viewer when `status === 'done'` and user is logged in. POSTs full result + transcript to `/meetings` via `apiFetch`.

### How to test

1. Ensure you have at least one past saved meeting with action items or decisions
2. Start a new meeting — open the `#live/{token}` URL
3. Verify the Pre-Meeting Brief card appears at the top (collapsed by default)
4. Expand it — verify open items, decisions, and/or blockers from past meetings appear
5. End the meeting — verify the "Save to my history" button appears when logged in
6. Click Save — verify the meeting appears in your history tab

---

## Feature 3 — Closed-Loop Action Items ✅ Shipped

**Status:** Implemented Apr 25 2026 — deployed on next push to main

### What it does

When Prism creates a Linear ticket or Google Calendar event via a live command, it stores the external reference (ticket ID, event ID) in Supabase. Unresolved refs surface in the pre-meeting brief and cross-meeting insights on subsequent meetings.

### Implementation

**Supabase (`supabase/action_refs_migration.sql`):**
- New `action_refs` table: `(user_id, meeting_id, action_item, tool, external_id, resolved, created_at)`. RLS enabled with per-user policy.

**Backend (`tools/registry.py`):**
- `execute_tool()` now injects `external_ref: {tool, external_id}` into the result whenever `linear_create_issue` (returns `issue_id`) or `calendar_create_event` (returns `event_id`) succeeds.

**Backend (`realtime_routes.py`):**
- `_process_command`: after each `execute_tool` call, if result has `external_ref`, inserts a row into `action_refs` with the command text as `action_item`.

**Backend (`cross_meeting_service.py`):**
- `derive_cross_meeting_insights(history, user_id=None)` now accepts `user_id`, fetches unresolved `action_refs`, and returns them in a new `unresolved_action_refs` key.

**Backend (`storage_routes.py`):**
- `/insights` now passes `user_id` to `derive_cross_meeting_insights`.

**Backend (`recall_routes.py`):**
- `_build_pre_meeting_brief` pulls unresolved `action_refs` into `open_items` so they appear in the live viewer brief.

**Frontend (`ActionItemsCard.jsx`):**
- If an action item has `external_ref`, shows a small pill with the Linear ID (⬡) or Calendar event ID (📅).

### How to test

1. In a live meeting say `"Prism, create a Linear ticket for the API refactor"`
2. Check Supabase `action_refs` table — should have a row with the Linear ticket ID
3. Start a new meeting — verify the unresolved ref appears in the Pre-Meeting Brief
4. Check `/insights` response — should include `unresolved_action_refs` array
5. Mark `resolved = true` in Supabase — verify it no longer appears in the brief

---

## Testing Checklist (run after each deployment)

| Check | How |
|---|---|
| Live link in bot intro | Join a meeting, wait 20s, check Google Meet chat |
| Live viewer updates | Open `#live/{token}` in separate window, speak, verify within 3s |
| Live viewer → results transition | End the meeting, verify viewer shows full cards |
| Command trigger (3-word guard) | Say "Prism, what is" — should NOT fire |
| Command trigger (valid) | Say "Prism, what is today's date?" — should fire once |
| Chat command | Type "Prism, what is today's date?" in Google Meet chat — should respond |
| Calendar guard | Say "Prism, add a calendar event" — should ask for details, not create |
| Gmail read | Say "Prism, what was my last email?" — should call `gmail_read` and return real data |

---

## Commit Log

| Commit | Date | Description |
|---|---|---|
| `bc8029f` | Apr 22 2026 | Fix live command trigger: count words not chars, normalize dedup comparison |
| `eee46c6` | Apr 22 2026 | Fix chat message parser: text is at data.data.data.text for Google Meet |
| `b275772` | Apr 22 2026 | Guard calendar_create_event: ask for title/date/time if not stated |
| `2763adf` | Apr 22 2026 | Add live share: #live/{token} viewer with real-time transcript and commands |
| `7d1bc9c` | Apr 22 2026 | Include live share link in bot intro message |
| TBD | Apr 25 2026 | Feature 2: proactive interventions (_run_proactive_checker, 4 triggers) |
| TBD | Apr 25 2026 | Feature 4: speaker coaching (SpeakerCoachCard, speaker_coach agent) |
| TBD | Apr 25 2026 | Feature 1: pre-meeting brief in live viewer + save to history button |
| TBD | Apr 25 2026 | Feature 3: closed-loop action refs (action_refs table, external_ref injection) |

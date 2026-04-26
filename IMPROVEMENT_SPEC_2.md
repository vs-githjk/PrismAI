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

## Feature 2 — Proactive Interventions 🔲 Not started

**Status:** Planned

### What it does

Prism speaks up without being asked. During a live meeting it monitors for patterns and posts alerts to the meeting chat automatically — for example, if 30 minutes pass with no decision logged, or a topic has come up in previous meetings without resolution.

### Planned implementation

**Backend (`realtime_routes.py`):**
- Add a background periodic checker per bot (runs every 5 minutes while `status === 'recording'`).
- Tracks: elapsed time since last command, number of decisions/action items detected in real-time transcript, whether any recurring topics from cross-meeting history are present.
- Fires `_send_chat_response` with a proactive nudge if thresholds are crossed.

**Triggers to implement (in priority order):**
| Trigger | Condition | Message |
|---|---|---|
| No decisions in 30 min | 30+ min elapsed, no decision keywords seen | "📋 30 minutes in — no decisions logged yet. Say 'Prism, summarize what's been decided' to capture them." |
| Recurring blocker | Topic matches a blocker from cross-meeting history | "⚠️ This topic came up unresolved in your [date] meeting. Say 'Prism, what happened last time?' to check." |
| Long meeting approaching | 55 min elapsed | "⏱️ Meeting approaching 1 hour. Consider wrapping up with action items." |
| No owners assigned | Action items detected but no speaker explicitly took ownership | "👤 Some action items may not have clear owners. Say 'Prism, who owns what?' to clarify." |

**State tracking needed:**
- `state["intervention_last_ts"]` — timestamp of last proactive message (throttle: max 1 per 10 min)
- `state["meeting_start_ts"]` — set when bot status transitions to `recording`
- `state["decisions_detected"]` — count of lines containing decision keywords

### How to test

1. Start a meeting, stay silent for 31 minutes (or temporarily lower threshold to 2 minutes for testing)
2. Verify Prism posts the no-decisions nudge in the chat without being asked
3. Start a second meeting on the same topic as a previous one — verify recurring topic alert fires

---

## Feature 4 — Speaker Coaching Report 🔲 Not started

**Status:** Planned

### What it does

A new post-meeting card showing speaker-level stats: talk time percentage, word count, decision ownership, and a one-line coaching note per speaker. Managers would pay for this alone for 1:1s and standups.

### Planned implementation

**Backend:**
- New agent: `backend/agents/speaker_coach.py`
- Input: full transcript (with speaker labels and word timestamps from Recall)
- Output:
```json
{
  "speakers": [
    {
      "name": "Vidyut Sriram",
      "word_count": 312,
      "talk_percent": 68,
      "decisions_owned": 2,
      "action_items_owned": 3,
      "coaching_note": "Dominated the conversation — consider inviting more responses."
    }
  ],
  "balance_score": 42
}
```
- Follows the standard agent checklist (add to `AGENT_MAP`, `analysis_service.py`, etc.)

**Frontend:**
- New `SpeakerCoachCard.jsx`
- Shows each speaker as a row: avatar initials, name, horizontal talk-time bar, owned items count, coaching note
- `balance_score` shown as a gauge (0 = one person talked entirely, 100 = perfectly balanced)

### How to test

1. Run a multi-speaker transcript through `/analyze`
2. Verify `speaker_coach` result appears in the response
3. Check the card renders with correct percentages adding to ~100%

---

## Feature 1 — Pre-Meeting Brief 🔲 Not started

**Status:** Planned

### What it does

Before a meeting starts, Prism surfaces a brief: open action items from previous meetings with the same attendees, decisions previously made on the same topic, and recurring blockers. You walk in prepared instead of scrambling.

### Planned implementation

**Backend:**
- New endpoint `GET /pre-meeting-brief?meeting_url={url}` (auth-gated)
- Extracts the meeting title/attendees hint from the calendar event matched to the URL
- Queries user's last 50 meetings from Supabase
- Runs `cross_meeting_service.py`-style analysis: open action items, recent decisions, recurring themes
- Returns structured brief (no LLM — pure Python, same as `/insights`)

**Frontend:**
- Shown in the Join tab when the user has a calendar event matched to the meeting URL
- Appears as a compact panel above the Join button: "3 open items from your last meeting with this group"
- Expandable to show full brief
- Dismissed automatically when the bot joins

### How to test

1. Connect Google Calendar
2. Paste a meeting URL that matches a calendar event
3. Verify the brief panel appears with relevant context from previous meetings
4. Join the meeting — verify the brief dismisses

---

## Feature 3 — Closed-Loop Action Items 🔲 Not started

**Status:** Planned (most complex — depends on Feature 4 being stable)

### What it does

When Prism creates a Linear ticket or Google Calendar event via a live command, it stores the external reference (ticket ID, event ID) against the action item. Subsequent meetings check whether those references are resolved and surface stale ones in the pre-meeting brief and cross-meeting insights.

### Planned implementation

**Backend:**
- Extend `execute_tool()` return values to include an `external_ref` field when a resource is created (Linear ticket ID, Google Calendar event ID)
- Store refs in a new `action_refs` Supabase table: `(meeting_id, action_item_text, tool, external_id, resolved)`
- New background job: periodically poll Linear/Calendar to check resolution status, update `resolved` flag
- Surface unresolved refs in `/insights` and `/pre-meeting-brief`

**Supabase migration needed:**
```sql
create table action_refs (
  id bigserial primary key,
  meeting_id bigint references meetings(id) on delete cascade,
  action_item text,
  tool text,
  external_id text,
  resolved boolean default false,
  created_at timestamptz default now()
);
```

### How to test

1. In a live meeting say `"Prism, create a Linear ticket for the API refactor"`
2. Check Supabase `action_refs` table — should have a row with the Linear ticket ID
3. Resolve the ticket in Linear
4. Start a new meeting — verify the action item is marked resolved in the pre-meeting brief

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

# PrismAI — Improvement Specs Draft 1

> Prioritized implementation roadmap. Work through these in order — each builds on the last.

---

## Build Now (High Impact, No Auth Dependency)

### #1 — Proactive Suggestions Panel

**What:** After analysis completes, show a panel with 2-3 contextual action prompts based on what the agents found.

**Why:** The single biggest gap between "static demo" and "agentic system." This is what makes it feel like an agent rather than a report generator.

**Example prompts:**
- "3 action items detected — draft a Slack update?" → calls `POST /agent` with email_drafter + Slack-format instruction
- "Follow-up meeting recommended for next week — add to Google Calendar?" → deep link to Google Calendar with pre-filled subject/time
- "This meeting scored 34 — want facilitation tips?" → calls `POST /agent` with a coaching prompt

**Implementation:**
- New `ProactiveSuggestions.jsx` component
- Renders after `[DONE]` by reading the `result` object
- Conditions:
  - Show Slack prompt if `action_items.length >= 2`
  - Show Calendar prompt if `calendar_suggestion.recommended === true`
  - Show coaching prompt if `health_score.score < 50`
- Each CTA fires `POST /agent` with a targeted instruction and displays the response inline
- Dismiss button per suggestion; dismissed state does not persist (resets on new analysis)

**No backend changes needed.** Reuses existing `/agent` endpoint.

---

### #2 — Friendly Error States

**What:** Replace raw error strings with designed error cards that include retry CTAs.

**Why:** Currently Groq 429s, cold start timeouts, and empty transcript errors all surface as ugly raw strings. The stream timeout message added previously is a start but has no recovery path.

**Error cases to handle:**

| Error | Current behavior | Target behavior |
|---|---|---|
| Groq 429 (rate limit) | Raw string | Card: "Too many requests — wait a moment and retry" + Retry button |
| Stream timeout (120s) | Plain text message | Card: "Analysis timed out — the server may be waking up" + Retry button |
| Empty transcript submitted | Raw 422 | Inline validation before submit: "Paste a transcript to analyze" |
| Network failure | Unhandled / crashes | Card: "Could not reach the server — check your connection" + Retry button |
| Agent JSON parse failure | Raw 500 string | Card: "One agent failed to parse its response" + partial results still shown |
| Join Meeting error | Error text, no recovery | Card with Retry button that re-fires the join request |
| Chat API error | "Sorry, something went wrong" | Distinguish: network vs. server vs. timeout with appropriate message |

**Implementation:**
- `ErrorCard.jsx` component: accepts `title`, `message`, `onRetry` (optional)
- Replace all `setError(...)` + raw string renders in `App.jsx` with `ErrorCard`
- Add inline transcript validation in the Analyze button handler (before fetch)
- Retry button in analysis errors re-calls `runAnalysis()` with the existing transcript
- Partial results: if stream emits some agents before failing, keep showing what arrived — don't wipe the result

---

### #3 — Cross-Meeting Chat / Multi-Meeting Intelligence

**What:** Extend the chat interface to answer questions across all stored meetings. Add `POST /chat/global` backend endpoint.

**Why:** Data is already in Supabase. This is the most powerful feature buildable without auth — unlocks "what did I commit to last month?", "show me my 3 lowest-scoring meetings", "any recurring action items that aren't getting done?"

**Frontend:**
- Extend `detectAgentIntent()` in `ChatPanel.jsx` to detect cross-meeting queries:
  - Triggers: "last N meetings", "across all meetings", "last month", "recurring", "all time", "history of"
  - When detected: route to `POST /chat/global` instead of `POST /chat`
- Show a subtle indicator in the chat UI when global mode is active (e.g., "Searching across all meetings…")
- Response renders exactly like a normal chat message — no special card needed

**Backend (`POST /chat/global`):**
- Accepts `{ message, limit? }` — no transcript needed
- Fetches recent meetings from Supabase (`meetings` table, ordered by `created_at desc`)
- **Context window management (critical):** Do NOT dump all transcripts. Strategy:
  - Default: fetch last 10 meetings, include only `title`, `date`, `score`, and `result` JSON (not raw transcripts) — results are already summarized
  - If query mentions transcripts explicitly, include truncated transcript (first 500 chars per meeting)
  - Hard cap: if total context exceeds ~12k tokens, drop oldest meetings first
- Pass assembled context + user message to Groq LLaMA 3.3-70b
- Return `{ response: string }`

**Example queries it should handle:**
- "What did I commit to last month?" → scans `action_items` across meetings
- "Show me my 3 lowest-scoring meetings" → reads `score` field
- "Any recurring action items that keep showing up?" → pattern matches across `action_items` arrays
- "Summarize everything discussed about the mobile app" → full-text scan of results

---

### #4 — Health Score Trend Chart

**What:** Graph `meetings.score` over time. Render as a sparkline in the history panel or a dedicated trend view.

**Why:** Data is already in Supabase. Creates retention — once users can see their score over time, they start optimizing it. Closes the loop with cross-meeting chat (#3).

**Implementation:**
- Add `recharts` to frontend dependencies (`npm install recharts`)
- New `ScoreTrendChart.jsx` component using `<LineChart>` or `<AreaChart>`
  - X axis: meeting date
  - Y axis: health score (0–100)
  - Tooltip: meeting title + score on hover
  - Color: green above 70, yellow 50-70, red below 50 (use `<defs>` gradient or segment coloring)
- Placement: above the meeting history list in the left panel, collapsed by default with a "Show trend" toggle
- Data source: already returned by `GET /meetings` — no backend changes needed
- Minimum viable: requires at least 2 meetings to render (hide chart otherwise)

---

## Build After (Medium Impact)

### #5 — Mobile Polish

**What:** Fix broken layouts on small screens. Tab bar exists but several components are broken.

**Specific issues:**
- Transcript textarea height doesn't adapt on mobile (too tall, pushes content off screen)
- `ChatPanel.jsx` has fixed height `360px` — gets cut off on short screens (iPhone SE, etc.)
- Tab bar has no safe-area inset — overlaps content on notched devices (add `pb-safe` or `env(safe-area-inset-bottom)`)
- iPad landscape gets excessive whitespace from `pb-16` padding
- `getElementById('mobile-results')` is dead code — element never defined, scroll-to-results silently does nothing. Fix or remove.

---

### #6 — Better Share Page

**What:** The share page (`/share/{token}`) is currently a raw card dump. Needs polish.

**Needed:**
- Branded header with PrismAI logo + "Meeting shared via PrismAI"
- Prominent "Analyze your own meeting →" CTA button below the results
- Meeting title and date shown at top
- OG meta tags for link previews (requires injecting `<meta>` tags dynamically on share load — works for most platforms, not full SSR)

---

### #7 — "Time Saved" Card / Social Sharing

**What:** After analysis, show an estimated time saved vs. manual summarizing. People screenshot this — organic growth loop.

**Implementation:**
- Formula already partially in codebase (`Math.round(analysisTime * 1.8 + 20)` — document and validate this)
- Render as a dismissible banner after `[DONE]`: "PrismAI saved you ~23 minutes of manual work"
- Add a **Share** button that copies a pre-written tweet/text: "Just analyzed my meeting in 12s with @PrismAI — saved ~23 minutes. Try it: [url]"
- No backend needed

---

## Blocked on Auth (Do Last)

### #8 — Auth (Google SSO via Supabase)

**What:** Add `supabase.auth.signInWithOAuth({ provider: 'google' })` to both frontend and backend.

**Why first:** Every feature below is blocked until this lands. Until auth exists, all data is browser-anonymous and team features are impossible.

**Implementation:**
- Frontend: auth context + protected routes, redirect to sign-in on first visit (replaces/integrates with existing `LandingScreen`)
- Backend: JWT validation middleware — validate `Authorization: Bearer <token>` on protected endpoints
- Supabase: enable Google OAuth in dashboard, configure redirect URL

---

### #9 — Slack / Google Docs / Calendar Integration

**Blocked on:** Auth (#8)

Full OAuth flows for Slack and Google. Until auth lands, users have no identity to attach tokens to. The proactive suggestions panel (#1) handles the calendar case with a deep link in the interim.

---

### #10 — Team Workspace

**Blocked on:** Auth (#8) + schema migration

Add `user_id` column to `meetings` and `chats` tables. Scope all queries by `user_id`. Shared workspaces require a separate `workspaces` table and membership model.

---

## Lower Priority / Maintenance

- **Model fallback** — Groq is reliable enough. When needed: catch Groq errors in each agent, retry with `openai` client + `gpt-4o-mini`. Add `OPENAI_API_KEY` to env.
- **Bot store persistence** — Only matters if Recall.ai bot feature is actively used. Fix: move `bot_store` dict to a `bots` Supabase table.
- **Export to Notion** — Blocked on OAuth. Not worth the complexity until auth is in.

---

## UI Bugs to Fix (Found in Code Review)

These are small but worth fixing alongside the features above:

| Bug | File | Fix |
|---|---|---|
| `getElementById('mobile-results')` targets non-existent element — scroll does nothing | `App.jsx` | Remove dead code or add the ID to the correct element |
| Join Meeting error has no retry — user must reload | `App.jsx` | Add Retry button that re-fires the join request |
| ChatPanel fixed height `360px` cut off on short screens | `ChatPanel.jsx` | Replace with `max-h-[40vh]` or similar viewport-relative height |
| Tab bar overlaps content on notched devices | `App.jsx` | Add `env(safe-area-inset-bottom)` padding |
| All icon-only buttons missing `aria-label` | Multiple | Add `aria-label` to export, share, history, delete buttons |
| No error boundary — one card crash brings down the whole app | `App.jsx` | Wrap results section in a React `ErrorBoundary` component |
| Potential duplicate event listeners in ChatPanel `useEffect` | `ChatPanel.jsx` | Audit and clean up the mousedown listener registration |

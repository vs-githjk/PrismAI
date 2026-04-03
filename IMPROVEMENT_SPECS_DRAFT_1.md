# PrismAI — Improvement Specs Draft 2

> Updated after first public release sprint. Completed items marked ✓. Work through remaining items in order.

---

## Completed ✓

| Item | What shipped |
|---|---|
| Proactive Suggestions Panel | `ProactiveSuggestions.jsx` — up to 3 contextual CTAs after analysis. Calendar link, Slack draft, facilitation tip, health tips. Done-state (crossed-out) for link actions. |
| Friendly Error States | `ErrorCard.jsx` — timeout / rate-limit / network / generic variants with tailored copy and Retry CTA. Replaces raw error strings. |
| Cross-Meeting Chat | `POST /chat/global` backend endpoint. `detectGlobalIntent()` in ChatPanel. "Searching all meetings…" loading indicator. Global reply badge. `loadingGlobal` always reset in `finally`. |
| Mobile Polish | ChatPanel height viewport-relative (`minHeight: 300px / maxHeight: 40vh`). Tab bar safe-area inset. Dead `getElementById` scroll removed. |
| Share Page Overhaul | Sticky branded header, meeting title/date/AgentTags, bottom CTA block. OG + Twitter meta tags injected on share load. `document.title` updated. |
| Time Saved Banner | Dismissible emerald banner after `[DONE]`. Shows "~X min saved · analyzed in Ys". Share button copies pre-written tweet. |
| Health Score Count-Up | `useCountUp` hook with rAF + ease-out cubic. Drives circle arc, number display, and all 3 breakdown bars simultaneously. |

---

## Build Now

### #1 — UI Polish Pass

**What:** Make the results section feel alive and premium instead of static.

**Specific changes (in order of impact):**

**1a. Card hover states**
All 7 result cards currently have zero hover feedback — they're completely inert on desktop. Add to each card's outer div:
```jsx
className="... transition-all duration-200 hover:-translate-y-0.5"
style={{ ..., cursor: 'default' }}
// On hover, also intensify the border slightly:
// border: '1px solid rgba(255,255,255,0.13)' on hover vs 0.07 at rest
```
The subtlest possible lift — not a card flip, just enough to feel interactive. Do NOT add `hover:scale` — at card size it looks jumpy.

**1b. Staggered card entrance**
Cards currently all have `animate-fade-in-up` but fire within the same ~100ms window since they stream in. The visual effect is lost. Apply explicit delays so each card in the 2-col grid arrives 60ms after the previous:
```jsx
// Health: delay-0
// Summary: delay-[60ms], Sentiment: delay-[120ms]
// ActionItems: delay-[180ms], Decisions: delay-[240ms]
// Email: delay-[300ms], Calendar: delay-[360ms]
// ProactiveSuggestions: delay-[420ms]
```
These are after the card first renders, not from page load — Tailwind's `animation-delay` inline style works here.

**1c. Mobile empty state**
The mobile results tab empty state is:
```jsx
<div className="flex items-center justify-center h-64 text-gray-600 text-sm">
  Analyze a meeting to see results
</div>
```
Replace with the same `<EmptyState onDemo={() => startDemo()} />` component used on desktop. It already exists — just needs to be rendered in the mobile empty branch.

**1d. Landing agent grid — 2-col on mobile**
The decorative agent grid on `LandingScreen` uses `grid-cols-4` at all breakpoints. Change to `grid-cols-2 sm:grid-cols-4` so it's readable on phones.

**No backend changes needed for any of 1a–1d.**

---

### #2 — Health Score Trend Chart

**What:** Graph health scores over time. Deferred until users have 5+ meetings stored.

**When to build:** After first week of public use — wait until there's enough data for the chart to be meaningful.

**Implementation:**
- `npm install recharts`
- New `ScoreTrendChart.jsx`: `AreaChart` with `X=date`, `Y=score (0-100)`
  - Color: green above 70, amber 50-70, red below 50 via `<linearGradient>` in `<defs>`
  - Tooltip: meeting title + score on hover
  - Dot on each data point, click → load that meeting
- Placement: above meeting history list in left panel, collapsed by default
- Toggle: "Show trend ↗" / "Hide trend" button
- Minimum 2 meetings to render (hide entirely otherwise)
- Data source: `history` state already has `score` and `date` — no backend changes

---

## Build After (Medium Impact)

### #3 — Auth (Google SSO via Supabase)

**What:** `supabase.auth.signInWithOAuth({ provider: 'google' })`. Unlock for all team features.

**Why now:** Data is currently browser-anonymous. Every user shares the same Supabase namespace — any user can see all meetings. This is a security issue for public launch beyond friends/testing.

**Implementation:**
- Supabase dashboard: enable Google OAuth, set redirect URL to `https://vs-githjk.github.io/Agentic-Meeting-Copilot/`
- Frontend: `AuthContext` wrapping App — `supabase.auth.getSession()` on load, `signInWithOAuth` / `signOut` actions
- `LandingScreen`: add "Sign in with Google" as a third CTA or replace "Use my own transcript" — TBD
- Backend: `Authorization: Bearer <token>` middleware, validate JWT via Supabase's public key
- All `/meetings` and `/chats` endpoints filter by `user_id` extracted from JWT

**Schema migration required:**
```sql
alter table meetings add column user_id uuid references auth.users(id);
alter table chats add column user_id uuid references auth.users(id);
create index on meetings(user_id);
```

---

### #4 — Team Workspace *(blocked on #3)*

Add `workspace_id` to schema. Invite flow. Shared meeting history. Out of scope until auth is stable.

---

## Lower Priority / Maintenance

- **Model fallback** — Each agent catches Groq errors, retries with `gpt-4o-mini` (OpenAI) or `claude-haiku-4-5` (Anthropic). Identical pattern — swap client + model. Add `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars to Render.
- **Bot store persistence** — Move `bot_store` dict in `main.py` to a `bots` Supabase table. Only matters if Recall.ai bot feature is actively used.
- **Slack / Notion integration** — Blocked on auth (#3). Calendar is covered by deep link in ProactiveSuggestions.
- **Export to Notion** — Blocked on OAuth.

---

## UI Bugs Still Outstanding

| Bug | File | Fix |
|---|---|---|
| Join Meeting error shown as raw text, no retry | `App.jsx` | Replace with `ErrorCard` + re-fire join request |
| All icon-only buttons missing `aria-label` | Multiple | Add `aria-label` to export, share, history, delete buttons |
| No error boundary — one card crash brings down the whole app | `App.jsx` | Wrap results section in React `ErrorBoundary` |
| Transcript textarea height doesn't adapt on mobile | `App.jsx` | Set `max-h-[30vh]` on the textarea on mobile breakpoint |

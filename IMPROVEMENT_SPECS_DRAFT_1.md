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
| Workspace Visual Pass | Premium glass surfaces, ambient backgrounds, richer result presentation, `PrismStoryPanel`, `PrismSignatureScene`, stronger motion language, and trust framing across cards. |
| Landing Page Redesign | More cinematic prism metaphor, stronger hero composition, animated transcript-to-intelligence transformation, livelier CTA treatment, and laptop-height fit improvements. |
| Landing Refresh Persistence | User now stays on landing when refreshing from landing, and stays in-app when refreshing after entering the workspace. |
| Join Meeting Completion UX | Bot flow now preserves the transcript on completion and gives a clearer next action (`view results` or `analyze now`). |
| Vercel Frontend Migration | Frontend is now configured for Vercel deployment with `frontend/` as root and `VITE_API_URL` as the key frontend env var. |
| CrossMeetingInsights 3-col overflow fix | OWNERSHIP DRIFT / ACTION HYGIENE / UNRESOLVED DECISIONS headers were overflowing narrow columns and getting clipped. Fixed by stacking label + "tap to inspect" vertically. |
| Decision theme stop-words | Month/day names (`april`, `monday`, `jan`, etc.) were surfacing as recurring decision themes. Added full set of month/day names + abbreviations to `STOP_WORDS`. |
| Aria-labels on icon-only buttons | Added `aria-label` to: send message (ChatPanel), delete chat session (ChatPanel), remove speaker (App.jsx). |

---

## Build Now

### #1 — Final Frontend Fit & UX Sweep

**What:** Finish the remaining rough edges in the frontend so the product feels consistent and fully intentional across real laptop/mobile usage.

**Specific changes (in order of impact):**

**1a. Landing page must truly fit above the fold**
- On shorter laptop heights, the redesigned landing page can still push low-priority decorative elements below the fold.
- Keep the hero’s core story visible first: logo, headline, supporting copy, prism scene, and primary CTAs.
- Decorative agent grid should stay hidden or collapse into a compact strip on short desktop heights if needed.

**1b. Left input panel adaptive height**
- The analyze action is more visible than before, but the panel still needs a proper height strategy across common laptop sizes.
- Keep the primary action visible without relying on lucky viewport dimensions.

**1c. Join meeting flow needs one final polish**
- After Recall.ai meetings end, the path from “meeting finished” to “results are here” should be frictionless and obvious.
- Ideal behavior: auto-show results when available, or present a single dominant CTA when only the transcript is ready.

**1d. Accessibility and interaction pass**
- Finish `aria-label` coverage.
- Ensure icon-only buttons and secondary actions are consistently accessible.
- Check keyboard flow, focus visibility, and mobile tap targets.

**No backend changes needed for most of 1a–1d.**

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
- Supabase dashboard: enable Google OAuth, set redirect URL to the Vercel frontend URL
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
- **Bundle splitting / performance** — Frontend JS bundle is still large; add code splitting and trim non-critical upfront payload.

---

## UI Bugs Still Outstanding

| Bug | File | Fix |
|---|---|---|
| Landing page still overflows on some laptop heights | `App.jsx`, `index.css` | Continue height-aware compression and hide decorative content sooner |
| Left panel still feels cramped on some desktop sizes | `App.jsx` | Refine transcript/chat vertical allocation and sticky action placement |
| Vercel URL / docs branding still inconsistent in places | Docs + marketing copy | Replace legacy GitHub Pages references and unify public URL messaging |

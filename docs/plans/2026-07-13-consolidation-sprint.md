# Consolidation Sprint — Plan of Action

**Created:** 2026-07-13 · **Status:** PLANNED (do not begin until user says "begin")
**Driver:** Real user feedback (5 points) → shift from feature-building to hardening.
**Decision:** Consolidation sprint FIRST. Per-workspace integrations DEFERRED (speculative, no team blocked on it today).

---

## Why this sprint exists

Feedback, condensed: *the product is powerful but rough, and roughness is now capping adoption.*
The 5 points map to **one goal** — make what we already have trustworthy, obvious, and cohesive:

| # | User's words | What it really is |
|---|---|---|
| 1 | Stable foundations | Reliability — no stale-state/dup/edge-case bugs |
| 2 | Make users' lives easier | Reduce friction on every existing surface |
| 3 | Transparency | User always knows what the app + bot are doing |
| 4 | Layman-readable summary | **Already good — PARKED** |
| 5 | UI/UX consistency | One look, feel, and behavior everywhere |

**Guiding principle: trust-per-pixel, not features-per-sprint.** This is a trust product (a bot in
private meetings). Confused-but-powerful loses to simple-and-reliable. During this sprint:
- **No net-new features.** Every change makes an existing thing clearer, simpler, or more reliable.
- Success test for any change: *would a first-time user trust this more after it?*

---

## The 4 audit lenses

Every surface gets rated 1–5 on each:
1. **Reliability** — works every time; handles empty/error/stale/race/edge cases.
2. **Clarity / Transparency** — user understands what it does and what's happening now.
3. **Ease** — steps-to-value, friction, discoverability.
4. **Consistency** — visual + behavioral; matches the rest of the app.

Each finding: `surface · lens · issue · severity(1-3) · effort(S/M/L) · priority`.
Priority = severity × reach ÷ effort. Output = one ranked backlog.

---

## Surface inventory (what we audit)

**A. Entry & onboarding** — Landing (Prism/HowItWorks/Pricing/Team), SSO auth, first-run nudge, empty states.
**B. Core meeting loop** — input modes (paste/upload/record/bot), analysis streaming + loading/skeleton, MeetingView + all result cards (Summary, ActionItems, Decisions, Sentiment, SpeakerCoach, Health/Content score, Email, Calendar, SuggestedActions, DecisionLinks, RecordingPlayer, transcript).
**C. Live meeting / bot** — join flow, LiveMeetingView, LiveCatchup, live-share page, bot behaviors (wake words, personas, solo free-flow, commands, TTS, what it says/records).
**D. Home & intelligence** — StatsCanvas/Hero, ActionBoard, IntelligenceView, Vitals, HealthTrend, OwnerLoad, Trend, CalendarView, Insights.
**E. Workspaces & collaboration** — chips, settings, invites, members, Brief panel, UpcomingMeetings, fan-out, move/delete.
**F. Knowledge / RAG** — KnowledgeBase, upload modals, doc cards/viewer, pinned docs, sources/citations.
**G. Chat** — ChatPanel (3 modes), image analysis, history sessions, agent re-runs.
**H. Stand-in / proxy** — ProxyProfile, StandInComposer.
**I. Integrations & settings** — IntegrationsModal, calendar OAuth, account dropdown, PersonaChip.
**J. Cross-cutting primitives** — modals (dialog.tsx), buttons (button.tsx), chips, toasts/StatusIsland, empty/loading/error states (SkeletonCard, ErrorCard), spacing/radius/color tokens.

---

## Phases

### Phase 0 — Audit (produces the backlog) — **BREADTH-FIRST (locked)**
- I walk EVERY surface in the inventory (A–J), rate on the 4 lenses, log findings — full map before any fixing. Consistency can only be judged across the whole app, and priorities only make sense across the whole map.
- **Deliverable:** ranked backlog appended to this doc (living list). User reviews + reprioritizes.
- No code changes.

### Fixing cadence (locked)
- Findings are **clustered by area/type** ("like ones together") and shipped in **larger grouped PRs**, not many tiny ones. Breadth to see → priority-clustered depth to fix.

### Phase 1 — Quick wins (grouped by type, S-effort, high trust-per-effort)
- Typos, missing/ambiguous labels, missing empty/loading/error states, obvious visual inconsistencies, "where does this go?" gaps (like the Jira/Linear destination fix already shipped).
- Batched into a few grouped PRs (e.g. "all label/copy fixes", "all missing-state fixes").

### Phase 2 — Consistency pass (design-system + visual refresh) — **extend ui/* AND broader refresh on the table (locked)**
- **2a — Define the target visual direction FIRST** (short reference: the ONE aesthetic — tokens, one modal/card/chip/button/toast pattern, empty/loading/error patterns). A broader refresh is welcome, but it must *converge* on one direction, not add a third style. Anchor on CLAUDE.md: cyan/sky accent (#22d3ee/#67e8f9), shadcn/radix surfaces, glass as accent only (not default).
- **2b — Extend `components/ui/*`** into the full shared layer, then migrate surfaces onto it area-by-area (grouped PRs).
- Note: a broader refresh sharpens a LOT once the niche/target-user is known — worth deciding direction with that in mind.

### Phase 3 — Transparency pass
- "What the bot does / where things go": action destinations (done for tickets), live-bot activity cues, what's recorded/consent, agent explainers ("why this card exists"), RAG provenance (already strong — verify).
- A short, in-product "how Prism works" surface for new users.

### Continuous — Foundations (underneath all phases)
- Fix reliability bugs as the audit surfaces them (stale-state class, idempotency, error handling, races). Tonight's stale-view + dup-file fixes are the template.

---

## Deliverables & tracking
- **This doc** = the living plan + backlog.
- Per-phase = small reviewable PRs to `main`.
- Backlog items checked off here as they ship.

## Definition of done (sprint)
- Every **core** surface (B, C, D) rates ≥4/5 on all four lenses.
- One consistent component system in use across the app.
- A first-time user can articulate what the bot does and where their data/actions go.

## Explicitly deferred
- **Per-workspace integrations** (#2 backlog) — revisit after the sprint, or sooner if a real team gets blocked.
- **Niche/vertical decision** — the biggest lever, but parked. Un-park soon: consistency/ease/transparency all sharpen once we know the ONE target user.
- **Voice redo, CRM, screen-share vision, images→KB, extension** — parked.

---

## Decisions (locked Jul 14)
1. **Audit style** — BREADTH-FIRST (cover all surfaces), then priority-clustered depth for fixing.
2. **Ship cadence** — group like findings, ship in larger grouped PRs.
3. **Design-system scope** — extend `components/ui/*` AND a broader visual refresh is on the table (must converge on one direction; define it first in Phase 2a).

---

## BACKLOG (populated in Phase 0 — empty until the audit runs)

_(ranked findings land here)_

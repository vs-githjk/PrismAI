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

## BACKLOG — Phase 0 audit findings (breadth pass, Jul 14)

**Method:** cross-cutting code scans (grep-verified across all 56 frontend components) + line reads of the core surfaces (App.jsx input flow, DashboardPage, MeetingView, ChatPanel, SuggestedActions). Each finding: lens · evidence · effort(S/M/L) · reach. Priority = trust-impact × reach ÷ effort.
**Coverage honesty:** systemic findings below are hard-verified. Surface-specific items tagged `[deep-dive]` get a line-by-line read during their grouped fix PR (listed at the bottom).

### TIER P0 — highest trust-per-effort (systemic, do first)

**Group A — Component consistency (theme #5)**
- **A1. Shared `ui/button` has ZERO adoption.** 34 files, **186 raw `<button>`, 0 import `ui/button`.** Every button is bespoke → inconsistent size/state/focus/disabled. *Consistency · verified · M · huge reach.* → finalize a Button variant set, migrate area-by-area.
- **A2. Modal fragmentation.** 7 hand-rolled `fixed inset-0` overlays (ChatPanel, StandInComposer, SuggestedActions, …) vs 4 on shared `ui/dialog` → inconsistent overlay/blur/escape/focus-trap/scroll-lock. *Consistency + a11y · verified · M.* → one Dialog, migrate all.
- **A3. Fragmented feedback/toasts.** ≥5 mechanisms: `notifyStatus`, `setWorkspaceToast`, `StatusIsland`, `setIntegrationToast`, `setInviteStatus`. *Consistency · verified · M.* → one toast/status system.

**Group B — Reliability (theme #1)**
- **B1. Raw `fetch()` bypasses `apiFetch`** in LiveCatchup, IntegrationsModal (×2), LiveMeetingView → they SKIP the new `cache:'no-store'` fix (+ auth on authed ones). Reopens the stale-data class we just closed. *Reliability · verified · S.* → route through apiFetch (or a shared no-store fetch for token-gated public calls).
- **B2. 54 swallowed `catch {}`.** Some legit best-effort; several hide real failures (no toast/retry). *Reliability/error-recovery · verified · M — audit each.*
- **B3. Leftover `console.*`** in App.jsx, ChatPanel, IntegrationsModal. *Polish · S.*

**Group C — Accessibility (theme #1/#5)**
- **C1. Icon-only buttons missing `aria-label`.** 186 buttons / 47 aria-labels → many unlabeled icon buttons (screen-reader + missing tooltips). *A11y · verified · M.*
- **C2. Native `confirm()` for destructive delete** (KnowledgeDocCard) — inconsistent, blocking, ugly. *Consistency/UX · verified · S.* → shared confirm dialog.

### TIER P1 — transparency + ease (themes #2, #3)

**Group D — Transparency (theme #3)**
- **D1. No consistent "bot is recording / what's captured" cue.** Consent/recording copy in only 3 files. A trust product needs a clear, uniform in-meeting + on-join notice. *Transparency · high trust · M · [deep-dive: live view + join].*
- **D2. No in-product "what Prism/the bot does" for new users** (only marketing landing). *Transparency/ease · M.*
- **D3. Inconsistent "why this card / how it's computed" explainers** — some cards have help (Sentiment, HealthScore), others none. *Transparency · S-M · normalize.*
- **D4. Extend the destination pattern** (shipped for tickets) to ALL outbound actions + clearer "connect X first" states. *Transparency/ease · S.*

**Group E — Ease & friction (theme #2)**
- **E1. Empty states — verify core surfaces** (Home 0-meetings, Knowledge, Workspace, Insights) are actionable, not blank. *Ease · M · [deep-dive].*
- **E2. Loading states — verify every async surface** shows skeleton/spinner (no blank/jump). *Ease/perf · M · [deep-dive].*
- **E3. Disabled controls (19 files) — verify each explains WHY** ("connect Slack first," not a dead grey button). *Ease · S-M.*
- **E4. Generic error copy** ("Agent call failed", "Chat failed", "Slack export failed", "Something went wrong") — no cause/recovery path. *Ease/transparency · M.*
- **E5. Input-flow clarity** (paste/record/upload/join) — verify each mode self-explains + handles bad input. *Ease · [deep-dive].*

### TIER P2 — design-system foundation (theme #5, feeds Phase 2)
- **F1. No color-token layer** — raw hex scattered (App 21, ProxyProfile 20, SentimentCard 19, CalendarView 17, DashboardPage 14…). *Consistency · L · Phase 2a.*
- **F2. Inconsistent date formatting** — `toLocaleDateString`/`toLocaleString`/`formatSessionDate`/`Intl` mixed. *Consistency · S-M · one date util.*
- **F3. Spacing/radius not tokenized** — verify against CLAUDE.md scale during the visual pass. *Consistency · Phase 2.*

### Still to deep-read (during grouped fix PRs)
Landing (HowItWorks/Pricing/Signup/Nav), KnowledgeBase + upload/viewer modals, LiveMeetingView + LiveCatchup, ProxyProfile + StandInComposer, WorkspaceIsland + workspace settings, CalendarView, and each result card (Summary/ActionItems/Decisions/Sentiment/SpeakerCoach/Health/Content/Email/Calendar/RecordingPlayer).

### Progress log
- **✅ B1** (raw fetch → apiFetch): LiveMeetingView poll + IntegrationsModal webhooks done; LiveCatchup intentionally left (streaming POST, per-viewer token).
- **✅ B3** reviewed → no-op (all `console.*` are legit error logging).
- **🟡 E4** started: chat error copy now offline-aware + recovery. Remaining generic messages (analysis fail, export fail, ErrorBoundary) pending.

### ⚠️ Sequencing correction (Jul 14)
The big structural unifications — **A1 buttons, A2 modals, A3 toasts, C1 app-wide a11y, F1 tokens** — are **Phase 2 (design-system)**, NOT quick wins. They must follow **Phase 2a: define the ONE visual direction** (a user decision — depends on target aesthetic). Phase 1 = only the safe, direction-independent quick wins (B1 ✅, E3, E4, D3, D4, C2-if-a-shared-confirm-exists).

_Next decision (user): start Phase 2a (pick the visual direction) to unblock the button/modal/token unification, or keep grinding Phase-1 quick wins first._

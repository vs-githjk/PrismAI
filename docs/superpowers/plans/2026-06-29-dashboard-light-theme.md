# Dashboard Light Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-toggleable light theme to the PrismAI dashboard (dark stays the default; light is opt-in, per-browser).

**Architecture:** A ~16-token CSS-variable layer in `index.css` — dark values in `:root`, light overrides in a bare `.theme-light` class. The chokepoints (`dashboardStyles.js` + the `.dashboard-island`/`.dashboard-popup` CSS) consume the tokens; the remaining hardcoded `text-white`/`bg-white/…` utilities across ~25 dashboard components are swept to token-driven Tailwind arbitrary values. A `localStorage`-backed toggle in the account dropdown flips `.theme-light` on both the dashboard root (first-paint correctness) and `document.documentElement` (so Radix popovers that portal to `body` get the tokens).

**Tech Stack:** React 18 + Vite, Tailwind CSS 3.4 (`darkMode: ['class']`, currently unused), lucide-react icons, Radix dropdown. No test framework installed — verification is a dependency-free `node` script + `git grep` assertions + `npm run build` + manual contrast pass.

**Spec:** `docs/superpowers/specs/2026-06-29-dashboard-light-theme-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `frontend/src/index.css` | `:root` token defaults + `.theme-light` overrides; `.dashboard-page`/`.dashboard-island`/`.dashboard-popup` consume tokens | Modify |
| `frontend/scripts/check-theme-tokens.mjs` | Dependency-free assertion that every token is defined in both blocks and `--db-text` flips | Create |
| `frontend/src/components/dashboard/dashboardStyles.js` | Shared card/text/border tokens (16 importers) → `var(--db-*)` | Modify |
| `frontend/src/components/DashboardPage.jsx` | `theme` state + effect (localStorage + `<html>` class + unmount cleanup); root `className`; pass props to sidebar | Modify |
| `frontend/src/components/dashboard/DashboardSidebar.jsx` | Sun/Moon toggle row in the account dropdown | Modify |
| ~25 dashboard component files | Sweep hardcoded white utilities → tokens | Modify (Tasks 4–6) |

---

## Task 1: Token layer + `.theme-light` override in `index.css`

**Files:**
- Create: `frontend/scripts/check-theme-tokens.mjs`
- Modify: `frontend/src/index.css` (the `@layer base { :root { … } }` block near line 982; the `.dashboard-page` rule near line 1077; `.dashboard-island` near 1092; `.dashboard-popup` near 1112)

- [ ] **Step 1: Write the failing check script**

Create `frontend/scripts/check-theme-tokens.mjs`:

```js
// Dependency-free guard: every --db-* token must be defined in BOTH the :root
// default block and the .theme-light override block, and --db-text must differ
// (proves the cascade flips). Run: node scripts/check-theme-tokens.mjs
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

const TOKENS = [
  '--db-chrome-bg', '--db-page-bg', '--db-glass-top', '--db-glass-bottom',
  '--db-shadow', '--db-text', '--db-text-soft', '--db-text-muted',
  '--db-text-faint', '--db-fill', '--db-fill-strong', '--db-border',
  '--db-border-strong', '--db-accent', '--db-accent-text', '--db-accent-fill',
]

// Grab the contents of the first `<selector> { ... }` whose body contains --db-text.
function block(selector) {
  const re = new RegExp(selector.replace(/[.*]/g, '\\$&') + '\\s*\\{([^}]*--db-text:[^}]*)\\}', 's')
  const m = css.match(re)
  return m ? m[1] : null
}
function valueOf(body, token) {
  const m = body && body.match(new RegExp(token + '\\s*:\\s*([^;]+);'))
  return m ? m[1].trim() : null
}

const root = block(':root')
const light = block('\\.theme-light')
const errors = []

if (!root) errors.push(':root block defining --db-text not found')
if (!light) errors.push('.theme-light block defining --db-text not found')

for (const t of TOKENS) {
  if (root && !valueOf(root, t)) errors.push(`:root missing ${t}`)
  if (light && !valueOf(light, t)) errors.push(`.theme-light missing ${t}`)
}
if (root && light && valueOf(root, '--db-text') === valueOf(light, '--db-text')) {
  errors.push('--db-text is identical in :root and .theme-light (theme does not flip)')
}

if (errors.length) {
  console.error('FAIL:\n' + errors.map((e) => '  - ' + e).join('\n'))
  process.exit(1)
}
console.log(`PASS: all ${TOKENS.length} tokens defined in both blocks and --db-text flips`)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && node scripts/check-theme-tokens.mjs`
Expected: `FAIL` listing `:root block defining --db-text not found` and `.theme-light block defining --db-text not found` (tokens don't exist yet).

- [ ] **Step 3: Add token defaults to `:root`**

In `frontend/src/index.css`, inside the existing `@layer base { :root { … } }` block (the one starting near line 982 with `--background: oklch(1 0 0);`), append the dark token defaults before the closing `}` of `:root`:

```css
    /* ── Dashboard theme tokens (dark = default; .theme-light overrides) ── */
    --db-chrome-bg: #19191a;
    --db-page-bg: #202021;
    --db-glass-top: rgba(255, 255, 255, 0.07);
    --db-glass-bottom: rgba(255, 255, 255, 0.035);
    --db-shadow: 0 10px 30px rgba(0,0,0,0.32), 0 1px 0 rgba(255,255,255,0.10) inset, 0 -1px 0 rgba(0,0,0,0.20) inset;
    --db-text: rgba(255, 255, 255, 0.95);
    --db-text-soft: rgba(255, 255, 255, 0.85);
    --db-text-muted: rgba(255, 255, 255, 0.70);
    --db-text-faint: rgba(255, 255, 255, 0.45);
    --db-fill: rgba(255, 255, 255, 0.05);
    --db-fill-strong: rgba(255, 255, 255, 0.08);
    --db-border: rgba(255, 255, 255, 0.09);
    --db-border-strong: rgba(255, 255, 255, 0.14);
    --db-accent: #22d3ee;
    --db-accent-text: #67e8f9;
    --db-accent-fill: rgba(34, 211, 238, 0.10);
```

- [ ] **Step 4: Add the `.theme-light` override block**

In `frontend/src/index.css`, immediately AFTER the closing `}` of the `:root` block from Step 3 (still inside `@layer base`), add:

```css
  .theme-light {
    --db-chrome-bg: #e6eaef;
    --db-page-bg: #eef1f5;
    --db-glass-top: #ffffff;
    --db-glass-bottom: #fcfdff;
    --db-shadow: 0 6px 20px rgba(15,23,42,0.08), 0 1px 0 rgba(255,255,255,0.9) inset;
    --db-text: #0f172a;
    --db-text-soft: #334155;
    --db-text-muted: #475569;
    --db-text-faint: #94a3b8;
    --db-fill: rgba(15, 23, 42, 0.04);
    --db-fill-strong: rgba(15, 23, 42, 0.06);
    --db-border: rgba(15, 23, 42, 0.08);
    --db-border-strong: rgba(15, 23, 42, 0.12);
    --db-accent: #06b6d4;
    --db-accent-text: #0e7490;
    --db-accent-fill: rgba(34, 211, 238, 0.14);
  }
```

- [ ] **Step 5: Point the dashboard structural CSS at the tokens**

In `frontend/src/index.css`, edit these existing rules:

`.dashboard-page` (near line 1077) — replace the two hardcoded bgs:
```css
.dashboard-page {
  --dashboard-chrome-bg: var(--db-chrome-bg);
  --dashboard-bg: var(--db-page-bg);
  --dashboard-topbar-h: 76px;
  --dashboard-sidebar-w: 300px;
  --dashboard-gutter: 16px;
  --dashboard-edge: 26px;
  background: var(--dashboard-chrome-bg);
  background-image: none;
  font-family: "Inter Variable", Inter, "Segoe UI", sans-serif;
}
```

`.dashboard-island` (near line 1092) — replace `background`, `border`, `box-shadow`:
```css
.dashboard-island {
  background: linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%);
  backdrop-filter: blur(26px) saturate(115%);
  -webkit-backdrop-filter: blur(26px) saturate(115%);
  border: 1px solid var(--db-border);
  border-radius: 16px;
  box-shadow: var(--db-shadow);
}
```

`.dashboard-popup` (near line 1112) — same treatment, heavier blur preserved:
```css
.dashboard-popup {
  background: linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%);
  backdrop-filter: blur(40px) saturate(120%);
  -webkit-backdrop-filter: blur(40px) saturate(120%);
  border: 1px solid var(--db-border);
  box-shadow: var(--db-shadow);
}
```

- [ ] **Step 6: Run the check + build to verify they pass**

Run: `cd frontend && node scripts/check-theme-tokens.mjs`
Expected: `PASS: all 16 tokens defined in both blocks and --db-text flips`

Run: `cd frontend && npm run build`
Expected: build completes with no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/index.css frontend/scripts/check-theme-tokens.mjs
git commit -m "Add dashboard theme token layer + theme-light overrides"
```

---

## Task 2: Migrate `dashboardStyles.js` to tokens

This is the highest-leverage edit — 16 components import these exports.

**Files:**
- Modify: `frontend/src/components/dashboard/dashboardStyles.js`

- [ ] **Step 1: Write the failing guard**

Run: `git grep -n "rgba(255,255,255\|text-white" -- frontend/src/components/dashboard/dashboardStyles.js`
Expected (current state): matches on the `cardGlowStyle`, `eyebrow`, `cardTitle`, `bodyText`, `subtleText`, `divider`, `tableRow` lines. This is the "red" — those hardcoded colors must be gone after this task.

- [ ] **Step 2: Replace the file contents with token-driven versions**

Overwrite `frontend/src/components/dashboard/dashboardStyles.js` with:

```js
// Matches the floating chrome islands (.dashboard-island in index.css): theme
// tokens drive both light + dark. See index.css :root / .theme-light.
export const glassCard = 'rounded-2xl border border-[color:var(--db-border)]'
export const cardGlowStyle = {
  background: 'linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%)',
  backdropFilter: 'blur(26px) saturate(115%)',
  WebkitBackdropFilter: 'blur(26px) saturate(115%)',
  boxShadow: 'var(--db-shadow)',
}
export const eyebrow = 'text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--db-text)]'
export const cardTitle = 'text-base font-semibold tracking-[-0.01em] text-[color:var(--db-text)]'
export const bodyText = 'text-sm leading-6 text-[color:var(--db-text-soft)]'
export const subtleText = 'text-xs leading-5 text-[color:var(--db-text-soft)]'
export const divider = 'border-[color:var(--db-border)]'
export const tableRow = 'border-t border-[color:var(--db-border)] px-3 py-2'
```

- [ ] **Step 3: Run the guard to verify it now passes**

Run: `git grep -n "rgba(255,255,255\|text-white" -- frontend/src/components/dashboard/dashboardStyles.js`
Expected: no matches.

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/dashboardStyles.js
git commit -m "Migrate dashboardStyles shared tokens to theme variables"
```

---

## Task 3: Theme state, toggle wiring, and account-dropdown control

After this task the toggle works end-to-end even though most components aren't swept yet (the chokepoints from Tasks 1–2 already respond).

**Files:**
- Modify: `frontend/src/components/DashboardPage.jsx` (root `className` near line 946; `<DashboardSidebar … />` render near line 1002; add state/effect near the other top-of-component `useState` hooks)
- Modify: `frontend/src/components/dashboard/DashboardSidebar.jsx` (imports line 2–14; props destructure line 48+; account dropdown near line 339–356)

- [ ] **Step 1: Add theme state + effect in `DashboardPage`**

In `frontend/src/components/DashboardPage.jsx`, add near the other `useState` hooks at the top of the component body:

```jsx
const [theme, setTheme] = useState(() => localStorage.getItem('prism_dashboard_theme') || 'dark')
const toggleTheme = () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))

useEffect(() => {
  localStorage.setItem('prism_dashboard_theme', theme)
  const root = document.documentElement
  root.classList.toggle('theme-light', theme === 'light')
  return () => root.classList.remove('theme-light')
}, [theme])
```

(`useState`/`useEffect` are React imports — confirm they're already imported at the top of the file; add them to the existing `react` import if missing.)

- [ ] **Step 2: Apply theme to the root element + flip inherited text token**

First confirm the swap is safe — `--landing-text` must not be read anywhere in the dashboard except this one root element:

Run: `git grep -n "landing-text" -- frontend/src/components frontend/src/App.jsx`
Expected: the only dashboard-side match is `DashboardPage.jsx:946` (the line being changed). All other `--landing-text` usage lives in landing-only CSS classes in `index.css`, which we are not touching. If any dashboard component reads `var(--landing-text)` directly, convert it to `var(--db-text)` in the relevant sweep task instead.

Then change the root `<div>` className (near line 946) from:

```jsx
className="landing-page dashboard-page min-h-dvh overflow-x-hidden text-[color:var(--landing-text)]"
```

to:

```jsx
className={`landing-page dashboard-page min-h-dvh overflow-x-hidden text-[color:var(--db-text)]${theme === 'light' ? ' theme-light' : ''}`}
```

- [ ] **Step 3: Pass theme props to the sidebar**

In `frontend/src/components/DashboardPage.jsx`, in the `<DashboardSidebar` render (near line 1002), add two props alongside the existing ones:

```jsx
        theme={theme}
        onToggleTheme={toggleTheme}
```

- [ ] **Step 4: Accept the props + import icons in `DashboardSidebar`**

In `frontend/src/components/dashboard/DashboardSidebar.jsx`, add `Sun` and `Moon` to the lucide-react import (lines 2–14):

```jsx
  Sun,
  Moon,
```

And add to the props destructure (after `signOut,` near line 70):

```jsx
    theme,
    onToggleTheme,
```

- [ ] **Step 5: Add the toggle row to the account dropdown**

In `frontend/src/components/dashboard/DashboardSidebar.jsx`, inside the `<DropdownMenuGroup>` of the account dropdown (after the PersonaChip `<div>` that closes near line 355, still before `</DropdownMenuGroup>`), add:

```jsx
              <DropdownMenuItem
                onSelect={() => onToggleTheme?.()}
                className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-[color:var(--db-text-soft)] focus:bg-cyan-300/[0.08]"
              >
                {theme === 'light'
                  ? <Moon className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />
                  : <Sun className="h-4 w-4 shrink-0 text-[color:var(--db-text-muted)]" />}
                {theme === 'light' ? 'Dark theme' : 'Light theme'}
              </DropdownMenuItem>
```

(Let the menu close on select — the default Radix `onSelect` behavior — which is the expected affordance after picking a theme.)

- [ ] **Step 6: Build + manual verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

Run: `cd frontend && npm run dev`, open the dashboard, then verify:
- Account dropdown shows a "Light theme" row with a sun icon.
- Clicking it flips the page/chrome/islands to light; the row now reads "Dark theme" with a moon icon; the dropdown (a `.dashboard-popup`) is itself light.
- Reload the page → the chosen theme persists.
- Navigate to the landing page (sign out or go to `/`) → it is still dark (no leak).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DashboardPage.jsx frontend/src/components/dashboard/DashboardSidebar.jsx
git commit -m "Wire dashboard light/dark toggle with localStorage persistence"
```

---

## Sweep mapping rules (used by Tasks 4–6)

Replace each hardcoded white-based utility with its token equivalent. White opacities map to the nearest text tier:

| From | To |
|---|---|
| `text-white`, `text-white/88`, `text-white/9x` (≥90) | `text-[color:var(--db-text)]` |
| `text-white/{80,84,85,92}` (80–89) | `text-[color:var(--db-text-soft)]` |
| `text-white/{62,70}` (~60–75) | `text-[color:var(--db-text-muted)]` |
| `text-white/{30,35,42,45,50}` (≤50) | `text-[color:var(--db-text-faint)]` |
| `bg-white/[0.0x]` with x ≤ 5 | `bg-[var(--db-fill)]` |
| `bg-white/[0.0x]` with x ≥ 7 | `bg-[var(--db-fill-strong)]` |
| `border-white/[0.0x]` with x ≤ 10 | `border-[color:var(--db-border)]` |
| `border-white/[0.0x]` with x ≥ 12 | `border-[color:var(--db-border-strong)]` |

**Do NOT touch** (deliberately deferred per spec — `ponytail:` known ceiling): status colors (`text-red-*`, `text-amber-*`, `text-emerald-*`, `text-cyan-*`, `bg-cyan-400/*`, etc.) and the `.card-glow-*` classes. These read acceptably on light and are spot-fixed in Task 7 only if they fail contrast. The accent links/labels that currently use `text-cyan-200`/`text-cyan-300` may optionally be moved to `text-[color:var(--db-accent-text)]` when encountered, but that is not required for completion.

---

## Task 4: Sweep `components/dashboard/*`

**Files (modify each):** every `.jsx` under `frontend/src/components/dashboard/` that contains a white-based utility — confirm the list with `git grep -l "white" -- frontend/src/components/dashboard`. Known: `DashboardTopbar.jsx`, `WorkspaceIsland.jsx`, `DashboardSidebar.jsx`, `MeetingView.jsx`, `ActionBoard.jsx`, `CalendarCard.jsx`, `DecisionMemory.jsx`, `DatePopover.jsx`, `EmailCard.jsx`, `HealthTrend.jsx`, `IntelligenceView.jsx`, `MeetingHealthTriangle.jsx`, `MetricTile.jsx`, `OwnerLoad.jsx`, `StatsHero.jsx`, `SentimentCard.jsx`, `SpeakerCoachCard.jsx`, `ThemeChips.jsx`, `Vitals.jsx`.

- [ ] **Step 1: Inventory the work**

Run: `git grep -nE "(text|bg|border)-white(/\[?[0-9.]+\]?)?" -- frontend/src/components/dashboard`
Expected: a list of every occurrence to convert. Note the count.

- [ ] **Step 2: Apply the mapping rules**

For each match, apply the "Sweep mapping rules" table above. Work one file at a time. (`DashboardSidebar.jsx` still has the account-block `text-white/88`, `text-white/42`, `text-white/35`, `border-white/[0.06]`, `bg-white/[0.05]` from Task 3 — convert those too.)

- [ ] **Step 3: Verify no white-based structural utilities remain**

Run: `git grep -nE "(text|bg|border)-white(/\[?[0-9.]+\]?)?" -- frontend/src/components/dashboard`
Expected: no matches.

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard
git commit -m "Sweep dashboard core components to theme tokens"
```

---

## Task 5: Sweep top-level dashboard components

**Files (modify each that contains white utilities):** `frontend/src/components/` — `ChatPanel.jsx`, `KnowledgeBase.jsx`, `KnowledgeDocCard.jsx`, `KnowledgeDocViewer.jsx`, `KnowledgeUploadModal.jsx`, `IntegrationsModal.jsx`, `PersonaChip.jsx`, `StandInComposer.jsx`, `ProxyProfile.jsx`, `LiveCatchup.jsx`, `UpcomingMeetings.jsx`, `SentimentCard.jsx`, `ActionItemsCard.jsx`, `DecisionsCard.jsx`, `HealthScoreCard.jsx`, `AgentTags.jsx`, `CalendarView.jsx`, `SkeletonCard.jsx`.

- [ ] **Step 1: Inventory**

Run: `git grep -nE "(text|bg|border)-white(/\[?[0-9.]+\]?)?" -- frontend/src/components/ChatPanel.jsx frontend/src/components/Knowledge*.jsx frontend/src/components/IntegrationsModal.jsx frontend/src/components/PersonaChip.jsx frontend/src/components/StandInComposer.jsx frontend/src/components/ProxyProfile.jsx frontend/src/components/LiveCatchup.jsx frontend/src/components/UpcomingMeetings.jsx frontend/src/components/SentimentCard.jsx frontend/src/components/ActionItemsCard.jsx frontend/src/components/DecisionsCard.jsx frontend/src/components/HealthScoreCard.jsx frontend/src/components/AgentTags.jsx frontend/src/components/CalendarView.jsx frontend/src/components/SkeletonCard.jsx`
Expected: list of occurrences.

- [ ] **Step 2: Apply the mapping rules**

Apply the "Sweep mapping rules" table to every match, one file at a time.

> **Scope note:** These files render only inside the dashboard, so they are in scope. If you discover one is ALSO used by the landing/share/auth surface (check with `git grep -n "<ComponentName" -- frontend/src/App.jsx`), leave its colors hardcoded for that shared usage and flag it in the Task 7 notes instead of converting — do not risk lightening a dark-only surface.

- [ ] **Step 3: Verify**

Run the same `git grep` from Step 1.
Expected: no matches (except any intentionally-skipped shared-surface file noted in Step 2).

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components
git commit -m "Sweep top-level dashboard components to theme tokens"
```

---

## Task 6: Sweep the dashboard branches of `App.jsx`

`App.jsx` holds both landing and dashboard rendering. Only convert white utilities inside the dashboard/result/meeting view branches — NOT the landing branch.

**Files:**
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Inventory + classify**

Run: `git grep -nE "(text|bg|border)-white(/\[?[0-9.]+\]?)?" -- frontend/src/App.jsx`
Expected: ~37 occurrences. For each, determine whether it is inside a dashboard-only render path (e.g. the authenticated dashboard, the analysis result/meeting view) or the landing/marketing path. Use surrounding JSX (`landing-…` classes, hero/signup markup = landing; `dashboard-…`, `MeetingView`, result cards = dashboard).

- [ ] **Step 2: Convert dashboard-path matches only**

Apply the "Sweep mapping rules" table to dashboard-path occurrences. Leave landing-path occurrences untouched.

- [ ] **Step 3: Verify remaining matches are landing-only**

Run the `git grep` from Step 1 again and confirm every remaining match is in a landing/marketing render path.
Expected: no dashboard-path white utilities remain.

- [ ] **Step 4: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "Sweep App.jsx dashboard branches to theme tokens"
```

---

## Task 7: Manual contrast pass + spot-fixes

**Files:**
- Modify: any component/`index.css` rule found to fail contrast in light (status colors, `.card-glow-*`, accent links).

**Done when:** every surface in the Step 1 walkthrough is legible in light mode (no white-on-white text, no invisible borders, status badges readable), the cascade check + build pass (Step 3), and dark mode is visually unchanged from before (Step 4). "Legible" = body/label text reads without strain at normal zoom; it is not a pixel-perfect redesign pass.

- [ ] **Step 1: Run the full app in light mode**

Run: `cd frontend && npm run dev`. Switch to Light theme. Walk every dashboard surface:
- Home: greeting card, action-items card, meetings card.
- Meeting view: every agent card — summary, decisions, action items, sentiment (`SentimentCard`), health score, speaker coach, email draft, calendar suggestion, decision links.
- Chat panel (including Sources/conflict banner).
- Knowledge base + doc card + doc viewer + upload modal.
- Stand-in composer + proxy profile.
- Live catch-up panel; upcoming meetings + brief panel.
- Integrations modal; persona picker dialog; date/time popovers (Radix portals).
- Workspace settings panel; sign-in button.

- [ ] **Step 2: Record + fix contrast failures**

For each element that is unreadable on light (e.g. a `text-*-400` status color too pale on white, an invisible `.card-glow-*`, a white-on-white accent), apply a minimal fix:
- Status text too light → bump to the `-600`/`-700` shade only under light, or move to a `--db-*`-paired value.
- Accent link/label unreadable → `text-[color:var(--db-accent-text)]`.
- `.card-glow-*` invisible and the card looks flat → add a light-mode shadow via `.theme-light .card-glow-*` overrides in `index.css`.

Keep fixes surgical — do not re-theme anything that already reads fine.

- [ ] **Step 3: Re-run guards**

Run: `cd frontend && node scripts/check-theme-tokens.mjs` → Expected: `PASS`.
Run: `cd frontend && npm run build` → Expected: succeeds.

- [ ] **Step 4: Verify dark is unchanged**

Toggle back to Dark and confirm the dashboard looks identical to before this work (the token defaults reproduce the original dark values exactly).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Light-theme contrast spot-fixes"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- §1 Token set → Task 1 (Steps 3–4). All 16 tokens, both blocks. ✓
- §2 Chokepoint migration → Task 1 Step 5 (CSS rules), Task 2 (`dashboardStyles.js`), Task 3 Step 2 (root `--landing-text`→`--db-text`). ✓
- §3 Component sweep + mapping rules → Tasks 4–6 with the shared mapping table; deferred status/glow noted. ✓
- §4 Toggle mechanism (state, effect, unmount cleanup, root + `<html>` class, bare `.theme-light`, dropdown UI) → Task 3. ✓
- §5 Scope guardrails (landing stays dark, unmount cleanup, opaque bg) → Task 3 Step 1 cleanup + Step 6 verify; Tasks 5–6 landing-exclusion notes. ✓
- §6 Testing (automated cascade check + manual pass) → Task 1 script + Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code/CSS/command step shows actual content. ✓

**Type/name consistency:** `theme`/`setTheme`/`toggleTheme`, `onToggleTheme`, `prism_dashboard_theme`, `.theme-light`, and all `--db-*` token names are identical across Tasks 1–7. ✓

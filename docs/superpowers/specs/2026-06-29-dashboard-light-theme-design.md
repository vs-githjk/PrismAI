# Dashboard Light Theme — Design

**Date:** 2026-06-29
**Scope:** Dashboard only (signed-in product surface). Landing / auth / share screens stay dark.
**Mode:** User toggle (light + dark coexist). Dark stays the default; light is opt-in, per-browser.
**Palette:** "Cool & clean" — near-white cool-gray page, solid white cards, slate text, cyan accent (darkened to `#0e7490` for text/links on light).

---

## Problem

PrismAI has no theme system. Tailwind is configured `darkMode: ['class']`, but nothing ever toggles a `.dark` class. The dark look is hardcoded across ~40 components in 600+ places (`text-white`, `bg-white/5`, `rgba(255,255,255,…)`) plus three CSS-variable sets (`--landing-*`, `--dashboard-*`, and an unused shadcn `:root`/`.dark` pair). "Add a light mode" therefore means "introduce a theming layer where none exists," scoped to the dashboard.

The hardcoded color utilities are **direction-dependent**: `text-white/70` and `bg-white/[0.05]` only make sense on a dark base (light text / faint light film). On a light page they invert wrong. The fix is a semantic token layer whose values flip between themes.

## Approach (chosen)

**Semantic CSS-variable tokens + class flip.** ~16 scoped tokens, dark values as the `:root` default and a `.theme-light` override block. A toggle flips the class and persists to `localStorage`. No new dependencies, no new files. Both themes coexist; a third theme later is one more value block.

Rejected alternatives:
- **Tailwind `dark:` variant** — doubles 600+ color utilities into the diff, and the inline glass gradients/shadows in `dashboardStyles.js` can't use `dark:` anyway (they need CSS vars), so it runs two mechanisms for the same result.
- **Structural-only invert (~6 vars, patch reactively)** — the white-text sweep is unavoidable for a real light mode, so the savings mostly evaporate while leaving rough edges.

---

## 1. Token set

Defined as a **bare `.theme-light` class** (not `.dashboard-page.theme-light`) so portaled content also picks it up (see §4). Defaults (dark) live in `:root`.

| Token | Dark (default, `:root`) | Light (`.theme-light`) | Used for |
|---|---|---|---|
| `--db-chrome-bg` | `#19191a` | `#e6eaef` | page field behind chrome |
| `--db-page-bg` | `#202021` | `#eef1f5` | content field |
| `--db-glass-top` | `rgba(255,255,255,.07)` | `#ffffff` | island/card gradient top |
| `--db-glass-bottom` | `rgba(255,255,255,.035)` | `#fcfdff` | island/card gradient bottom |
| `--db-shadow` | `0 10px 30px rgba(0,0,0,.32), 0 1px 0 rgba(255,255,255,.10) inset, 0 -1px 0 rgba(0,0,0,.20) inset` | `0 6px 20px rgba(15,23,42,.08), 0 1px 0 rgba(255,255,255,.9) inset` | island/popup shadow |
| `--db-text` | `rgba(255,255,255,.95)` | `#0f172a` | headings / primary |
| `--db-text-soft` | `rgba(255,255,255,.85)` | `#334155` | body |
| `--db-text-muted` | `rgba(255,255,255,.70)` | `#475569` | secondary |
| `--db-text-faint` | `rgba(255,255,255,.45)` | `#94a3b8` | placeholders / disabled |
| `--db-fill` | `rgba(255,255,255,.05)` | `rgba(15,23,42,.04)` | hover / chip / input fills |
| `--db-fill-strong` | `rgba(255,255,255,.08)` | `rgba(15,23,42,.06)` | stronger fills |
| `--db-border` | `rgba(255,255,255,.09)` | `rgba(15,23,42,.08)` | card / divider borders |
| `--db-border-strong` | `rgba(255,255,255,.14)` | `rgba(15,23,42,.12)` | emphasised borders |
| `--db-accent` | `#22d3ee` | `#06b6d4` | bright fills, dots, bars |
| `--db-accent-text` | `#67e8f9` | `#0e7490` | links, active labels |
| `--db-accent-fill` | `rgba(34,211,238,.10)` | `rgba(34,211,238,.14)` | active-nav background |

## 2. Chokepoint migration (does most of the work)

Three edits cover the bulk of surfaces:

- **`frontend/src/index.css`** — add the `:root` token defaults + the `.theme-light` override block. Rewrite the existing `.dashboard-page` `--dashboard-chrome-bg` / `--dashboard-bg`, `.dashboard-island`, and `.dashboard-popup` rules to consume `--db-*` (page bgs, glass gradient stops, borders, shadows).
- **`frontend/src/components/dashboard/dashboardStyles.js`** — swap hardcoded `text-white`, `rgba(255,255,255,…)`, and dark shadows for `var(--db-*)`, using Tailwind arbitrary values (e.g. `text-[color:var(--db-text)]` — the same pattern the dashboard root already uses with `--landing-text`). The 16 components that import this file update for free.
- **`frontend/src/components/DashboardPage.jsx`** (root element, line ~946) — change `text-[color:var(--landing-text)]` → `text-[color:var(--db-text)]` so inherited text color flips with the theme.

## 3. Component sweep (~25 files)

Mechanical find-replace of the remaining hardcoded utilities to token equivalents. Map each white opacity to the nearest text tier:

- `text-white` and `text-white/≥90` (e.g. `/92`) → `text-[color:var(--db-text)]`
- `text-white/{80,84,85}` → `…var(--db-text-soft)`
- `text-white/70` → `…var(--db-text-muted)`
- `text-white/≤50` (e.g. `/35`, `/45`) → `…var(--db-text-faint)`
- `bg-white/[0.0x]` → `bg-[var(--db-fill)]` (≤0.05) or `bg-[var(--db-fill-strong)]` (≥0.07)
- `border-white/[0.0x]` → `border-[color:var(--db-border)]` (≤0.10) or `border-[color:var(--db-border-strong)]` (≥0.12)

**Deliberately left as-is in v1** (`ponytail:` known ceilings):
- **Status colors** — overdue red, due-soon amber, emerald/health greens, typically `text-*-400`. They read acceptably on light; spot-fix any that fail contrast. Upgrade path: give the failing ones light/dark token pairs.
- **`.card-glow-*` rings** (`index.css`) — subtle colored box-shadows. Mostly invisible-but-harmless on light. Spot-fix if a card looks flat.

In-scope files (dashboard surface): everything under `frontend/src/components/dashboard/`, plus `DashboardPage.jsx`, `ChatPanel.jsx`, `KnowledgeBase.jsx`, `KnowledgeDocCard.jsx`, `KnowledgeDocViewer.jsx`, `KnowledgeUploadModal.jsx`, `IntegrationsModal.jsx`, `PersonaChip.jsx`, `StandInComposer.jsx`, `ProxyProfile.jsx`, `LiveCatchup.jsx`, `UpcomingMeetings.jsx`, `SentimentCard.jsx`, `ActionItemsCard.jsx`, `DecisionsCard.jsx`, `HealthScoreCard.jsx`, `AgentTags.jsx`, `CalendarView.jsx`, `SkeletonCard.jsx`, and the dashboard branches of `App.jsx`.

## 4. Toggle mechanism (no new deps, no new files)

- **State** in `DashboardPage`: `const [theme, setTheme] = useState(() => localStorage.getItem('prism_dashboard_theme') || 'dark')`.
- **Effect**: persist to `localStorage`, and `document.documentElement.classList.toggle('theme-light', theme === 'light')`. **Cleanup removes the class on unmount** so it never leaks to the landing page.
- **First paint**: the `.dashboard-page` root element also includes `theme-light` in its `className` when `theme === 'light'`, so the visible dashboard is correct on first render (no flash). The `<html>`-level class (from the effect) exists so **Radix popovers / dialogs that portal to `document.body`** — outside the dashboard subtree — still receive the tokens. Both selectors are the same bare `.theme-light` class, so values are consistent.
- **Toggle UI**: a sun/moon row in the account dropdown (`DashboardSidebar` footer, next to the Persona picker). `theme` + `onToggleTheme` are passed from `DashboardPage` like the existing sidebar props.

## 5. Scope guardrails

- Landing, auth, and share screens read `--landing-*` and their own hardcoded colors, never `--db-*` — so defining `--db-*` globally is inert for them. They stay dark.
- The `.theme-light` class is added only inside the dashboard and removed on unmount, so it cannot affect the landing page even after a user has chosen light.
- The dashboard root's opaque `--db-chrome-bg` covers the dark body gradient (`html, body` background in `index.css`), so the body never shows through under light.

## 6. Testing

- **One automated check** (assert-style, no framework): a small script confirming the cascade flips — `:root` resolves `--db-text` to a light/near-white value, and an element with `.theme-light` resolves it to a dark value (`#0f172a`). The smallest thing that fails if the override block is wrong.
- **Manual contrast pass** in light mode over each dashboard view: home (greeting / action items / meetings), meeting view (all agent cards), chat panel, knowledge base + doc viewer, stand-in composer + profile, live catch-up, and at least one Radix popover/dialog (persona picker, date popover) to confirm portaled tokens work.

## Out of scope / explicitly skipped

- Full status-color light palette (§3) — until contrast bugs show up.
- Pre-paint `<head>` script — the root `className` handles first-paint; add only if a flash appears.
- Theming the landing / auth / share surfaces.
- "Follow system setting" (`prefers-color-scheme`) — manual toggle only for v1; trivial to add later (seed the `localStorage` default from the media query).

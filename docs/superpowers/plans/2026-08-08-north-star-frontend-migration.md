# North-Star Frontend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the approved north-star visual and structural direction (matte graphite shell, split Home with a real global assistant, standalone Actions page, source-grounded Meeting record) into the real Prism frontend without changing any backend, data contract, or production behavior.

**Architecture:** The dashboard is already token-driven: 17 `--db-*` CSS variables (dark `:root` + `.theme-light` overrides in `frontend/src/index.css`) feed `dashboardStyles.js`, which ~27 components import. The migration re-values those tokens to matte, recomposes the three fixed chrome islands, then ships four vertical UI slices (Home split, Actions page, Trend separation, Meeting record) that reuse the existing `activeView` state machine, `lib/actionItems.js` utilities, and `App.jsx` callbacks unchanged.

**Tech Stack:** React 18 + Vite, Tailwind utilities + hand-rolled CSS in `frontend/src/index.css`, Radix primitives, lucide-react icons, Node built-in test runner (`npm test` = `node --test tests/`).

**Design source of truth:** `docs/superpowers/specs/2026-08-08-prism-north-star-frontend-migration-design.md` (Status: Approved for implementation).

## Global Constraints

- **No backend, schema, or API change.** Frontend-only; every endpoint call shape stays byte-identical.
- **Existing callbacks and data contracts stay stable:** do not rewrite analysis streaming, meeting persistence, workspace scoping, calendar connections, integrations, auth, Live, Stand-in, or Knowledge behavior (`App.jsx` and `DashboardPage.jsx` orchestration stays).
- **Explicit preservation list (spec §Explicit preservation):** authentication, sample/test mode, light theme, workspace switching/settings/invites, personal + workspace integrations, all capture modes, analysis streaming, meeting history/search/delete/move/share/export, calendar providers, notifications, Knowledge workflows, Stand-in workflows + follow-up briefs, Live and public/shared views, all meeting summary/intelligence cards, recording/transcript/document/presentation features, personas, source-linked action completion, meeting-scoped chat persistence/tools/corrections.
- **Light theme remains functional.** Every re-valued dark token gets a matte-equivalent `.theme-light` value in the same commit. Theme mechanism (localStorage `prism_dashboard_theme`, `.theme-light` class on the dashboard root and `document.documentElement`) is untouched.
- **No demo artifacts:** no fixtures, scenario controls, `Prototype` banners, story parameters, or simulated receipts enter production.
- **Navigation stays `activeView` + sessionStorage (`prism_active_view`).** No React Router. All view changes go through `persistView()` in `DashboardPage.jsx`.
- **Responsive boundaries are the existing ones:** 1023/1024px shell breakpoint (fixed islands ↔ drawer), `max-height: 800px` short-viewport relief. Do NOT import the demo's 1080/1180/700px boundaries.
- **Cyan (`--db-accent`) is reserved for selection, primary action, focus, and provenance** — never for score bands or status stripes (existing CLAUDE.md invariant). Missing scores render a dash, never zero.
- **Each task leaves a usable product.** Per-task verification: `npm run build` (in `frontend/`), a focused browser smoke check via the dev server, and `npm test` whenever anything in `frontend/src/lib/` changes.
- **Commits:** short imperative summaries matching repo style (e.g. `Matte shell tokens: charcoal canvas, solid islands, both themes`). **No `Co-Authored-By` trailer** (user preference).
- **Branch:** create `north-star-migration` off `fixed-changes` (the active dev line) in an isolated worktree at execution time.

## Slice map (spec §Rollout)

| Slice | Tasks |
|---|---|
| 1. Foundation and shell | Task 1 (matte tokens), Task 2 (shell recomposition) |
| 2. Complete Home | Task 3 (split + WorkspaceChatPanel), Task 4 (operational column + mobile sheet) |
| 3. Actions / Trend separation | Task 5 (ActionsView + nav), Task 6 (Trend compact summary + ADR amendment) |
| 4. Meeting record | Task 7 (record recomposition), Task 8 (meeting chat alignment) |
| 5. Remaining destinations | Task 9 (token sweep + responsive/reduced-motion polish), Task 10 (docs + acceptance) |

## Codebase facts the implementer needs (verified 2026-08-08)

- `frontend/src/index.css` (3148 lines, shared with the landing page — touch only dashboard blocks): `--db-*` dark tokens at **1015-1037**, `.theme-light` overrides at **1038-1057**, `.dashboard-page` at 1119-1134, `.dashboard-island` at 1136-1148, `.dashboard-status-island` at 1153-1168, `.dashboard-popup` at 1195-1204, island positioning at 1241-1290, home grid at 1291-1345, focus ring at 1350-1353, 900px home collapse at 1355+, mobile shell block `@media (max-width: 1023px)` at ~1377-1439.
- `frontend/src/components/dashboard/dashboardStyles.js` (15 lines): exports `glassCard`, `cardGlowStyle`, `eyebrow`, `cardTitle`, `bodyText`, `subtleText`, `divider`, `tableRow`. Keep the export **names** stable — ~27 files import them.
- `frontend/src/components/DashboardPage.jsx` (2001 lines): `activeView` values `'home'|'meeting'|'intelligence'|'knowledge'|'standin'|'calendar'|'live'|'shared'`; lazy-init at 735-744 with the `'actions'`→`'intelligence'` rewrite at **740-741**; `persistView(view)` at 808-812; render switch at 1697-1863; docked meeting `ChatPanel` mount at 1867 + 1899-1921; `NewMeetingPanel` (module scope, line 284) with `Tabs` values `join|paste|record|upload` (record gated on `props.micSupported`).
- `frontend/src/components/dashboard/DashboardSidebar.jsx` (481 lines): pinned nav at 141-147 (Home, Trend, Calendar, Knowledge, Stand-in), live row 248-272, meetings grouped via `meetingBucket` (`groupMeetings` 37-45), account footer 375-478 (Integrations, persona, theme toggle, sign out).
- `frontend/src/components/dashboard/DashboardTopbar.jsx` (119 lines): hamburger/back/title-marquee/`actions` slot/`StatusIsland`/search/bell.
- `frontend/src/lib/actionItems.js` (98 lines): `collectOpenActions(history, user)` → rows `{item, entry, index, isMine, unassigned}`; `scopeFilter(rows, 'all'|'mine'|'unassigned')`; `byPriority` (DUE_RANK overdue→soon→rest, then mine→unassigned→theirs, then meeting recency). `byUrgency` is a dead export.
- `frontend/src/App.jsx`: `toggleActionItem(index)` at 2622-2644 (live result), `toggleHistoryActionItem(entry, index)` at 2648-2666 (optimistic + `PATCH /meetings/{id}` + revert; sample tokens keep optimistic state). Passed to DashboardPage at 2888-2889.
- `frontend/src/components/ChatPanel.jsx` (1170 lines): global branch at 655-676 — `apiFetch('/chat/global', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ message, image_urls })})`, non-streaming; response `{response, tools_used, pending_confirmations, rag_context}`. Module-scope helpers: `MarkdownMessage` (line 27), `SourceCard` (line 191). Confirmations POST `/chat/confirm-tool`.
- `frontend/src/components/dashboard/TaskHub.jsx` (86 lines): scope pills All/Yours/Unassigned + `ActionItemRow` list. `IntelligenceView.jsx` (192 lines): StatsHero → narrative/locked banner → co-headline grid `lg:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]` (HealthTrend+Vitals left, TaskHub right) → CollapsibleSection "Threads & decisions" → ActionModal portal.
- `frontend/src/components/dashboard/StatsCanvas.jsx` (226 lines): `.dashboard-home-grid` with HeroRow (greeting + Join/Paste/Sample pills + `MeetingHero`) → `NeedsAttention` → `MeetingsCard` (recent 5). `MeetingHero` self-fetches `fetchMergedEvents()` from `UpcomingMeetings.jsx`.
- `frontend/src/components/dashboard/MeetingView.jsx` (654 lines): exit banner → lens control → hero grid (gauge/triangle + summary + pinned docs) → ContentAnalysisCard → Actions+Decisions grid → collapsed tail (Follow-up CollapsibleSection with SuggestedActions/EmailCard/CalendarCard → SentimentCard → SpeakerCoachCard → RecordingPlayer → hand-rolled transcript panel). Header controls (back/share/export/move) live in DashboardPage's `MeetingActionsBar`, not here.
- Tests: `frontend/tests/*.test.mjs` (node:test + assert/strict, pure lib functions only). `npm test` runs the directory.

---

### Task 1: Matte Token Foundation (Slice 1)

**Files:**
- Modify: `frontend/src/index.css` (lines 1015-1057, 1136-1148, 1195-1204)
- Modify: `frontend/src/components/dashboard/dashboardStyles.js`
- Modify: `frontend/index.html` (remove redundant static Inter link)
- Create: `frontend/tests/themeTokens.test.mjs`
- Commit alongside: `docs/superpowers/specs/2026-08-08-prism-north-star-frontend-migration-design.md` (currently untracked) and this plan file

**Interfaces:**
- Consumes: nothing (first task).
- Produces: an 18th token `--db-card` (matte card surface) available to every later task; `cardGlowStyle` remains the object every card imports, now matte; all 18 tokens defined in BOTH `:root` and `.theme-light`.

- [ ] **Step 1: Write the token-parity test**

Create `frontend/tests/themeTokens.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../src/index.css'), 'utf8')

function tokensIn(blockRe) {
  const block = css.match(blockRe)?.[0] ?? ''
  return new Set([...block.matchAll(/--db-[a-z-]+(?=\s*:)/g)].map((m) => m[0]))
}

// :root dashboard block ends at the .theme-light selector; .theme-light block ends at .dark
const darkTokens = tokensIn(/── Dashboard theme tokens[\s\S]*?(?=\.theme-light)/)
const lightTokens = tokensIn(/\.theme-light\s*\{[\s\S]*?\}/)

test('every dashboard token is defined for both themes', () => {
  assert.ok(darkTokens.size >= 17, `expected ≥17 dark tokens, got ${darkTokens.size}`)
  assert.deepEqual([...darkTokens].sort(), [...lightTokens].sort())
})

test('the matte card surface token exists', () => {
  assert.ok(darkTokens.has('--db-card'))
})
```

- [ ] **Step 2: Run it to confirm the second test fails**

Run (from `frontend/`): `npm test -- --test-name-pattern "card surface"`
Expected: FAIL — `--db-card` does not exist yet. The parity test should PASS already (17/17).

- [ ] **Step 3: Re-value the dark tokens to matte graphite**

Replace `frontend/src/index.css` lines 1015-1037 (the dashboard token block inside `:root`) with:

```css
    /* ── Dashboard theme tokens (dark defaults; light class overrides below) ──
       Matte north-star (Aug 2026): charcoal canvas, solid low-contrast surfaces,
       bone-white text, cyan reserved for selection/action/focus/provenance.
       Glass (blur) survives only on transient layers: .dashboard-popup,
       .dashboard-status-island. */
    --db-chrome-bg: #0f0f10;
    --db-page-bg: #151517;
    --db-glass-top: rgba(255, 255, 255, 0.03);
    --db-glass-bottom: rgba(255, 255, 255, 0);
    --db-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35);
    --db-text: #eceae4;
    --db-text-soft: #c8c6bf;
    --db-text-muted: #9d9b94;
    --db-text-faint: #6d6c66;
    --db-fill: rgba(255, 255, 255, 0.045);
    --db-fill-strong: rgba(255, 255, 255, 0.075);
    --db-border: rgba(255, 255, 255, 0.08);
    --db-border-strong: rgba(255, 255, 255, 0.14);
    --db-accent: #22d3ee;
    --db-accent-text: #67e8f9;
    --db-accent-fill: rgba(34, 211, 238, 0.10);
    /* Solid island surface — matte chrome must not read through. */
    --db-island-base: #1a1a1c;
    /* Matte card surface for content cards (cardGlowStyle), one tone above canvas. */
    --db-card: #19191b;
```

- [ ] **Step 4: Re-value the light tokens to matte paper equivalents**

Replace lines 1038-1057 (`.theme-light` block) with:

```css
  .theme-light {
    --db-chrome-bg: #e9e7e2;
    --db-page-bg: #f1efeb;
    --db-glass-top: rgba(255, 255, 255, 0.55);
    --db-glass-bottom: rgba(255, 255, 255, 0);
    --db-shadow: 0 1px 0 rgba(255,255,255,0.85) inset, 0 6px 18px rgba(28,27,23,0.10);
    --db-text: #201f1c;
    --db-text-soft: #4a4842;
    --db-text-muted: #6e6c65;
    --db-text-faint: #a3a19a;
    --db-fill: rgba(32, 31, 28, 0.04);
    --db-fill-strong: rgba(32, 31, 28, 0.07);
    --db-border: rgba(32, 31, 28, 0.10);
    --db-border-strong: rgba(32, 31, 28, 0.16);
    --db-accent: #0891b2;
    --db-accent-text: #0e7490;
    --db-accent-fill: rgba(8, 145, 178, 0.10);
    --db-island-base: #fbfaf7;
    --db-card: #fbfaf7;
  }
```

- [ ] **Step 5: Make the chrome islands matte**

Replace the `.dashboard-island` rule (lines 1136-1148, including its comment) with:

```css
/* Matte chrome island — solid surface, hairline border, soft shadow. The old
   glass film (blur 26px over a translucent base) is retired for persistent
   chrome; blur remains only on transient layers (.dashboard-popup,
   .dashboard-status-island). */
.dashboard-island {
  background:
    linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%),
    var(--db-island-base);
  border: 1px solid var(--db-border);
  border-radius: 16px;
  box-shadow: var(--db-shadow);
}
```

(Deleting the two `backdrop-filter` lines is the change; `.dashboard-popup` and `.dashboard-status-island` keep theirs.)

- [ ] **Step 6: Make content cards matte**

Replace `cardGlowStyle` in `frontend/src/components/dashboard/dashboardStyles.js`:

```js
export const cardGlowStyle = {
  background: 'linear-gradient(180deg, var(--db-glass-top) 0%, var(--db-glass-bottom) 100%), var(--db-card)',
  boxShadow: 'var(--db-shadow)',
}
```

(Drop `backdropFilter`/`WebkitBackdropFilter`.) Update the file's top comment: tokens drive matte surfaces in both themes; glass survives only on transient layers. Keep every export name unchanged.

- [ ] **Step 7: Remove the redundant remote Inter stylesheet**

In `frontend/index.html`, delete the `fonts.googleapis.com/css2?family=Inter...` `<link>` and its two `preconnect` lines. Inter Variable is already self-hosted via `@import "@fontsource-variable/inter"` (`index.css:3`) and every dashboard font stack lists `"Inter Variable", Inter, ...`. (Poppins/Fontshare imports in `index.css` are landing-page dependencies — leave them.)

- [ ] **Step 8: Run tests and build**

Run (from `frontend/`): `npm test` then `npm run build`
Expected: all tests pass (token parity now 18/18, card test green); build succeeds.

- [ ] **Step 9: Browser smoke both themes**

Start the dev server, load the dashboard: verify (a) islands and cards are solid matte charcoal — no see-through chrome while scrolling, (b) toggle to light theme via the sidebar account menu → matte paper equivalents, no unreadable text, (c) landing page (`/`) is visually unchanged, (d) no horizontal overflow. Screenshot dark + light Home.

- [ ] **Step 10: Commit**

```bash
git add docs/superpowers/specs/2026-08-08-prism-north-star-frontend-migration-design.md docs/superpowers/plans/2026-08-08-north-star-frontend-migration.md frontend/src/index.css frontend/src/components/dashboard/dashboardStyles.js frontend/index.html frontend/tests/themeTokens.test.mjs
git commit -m "Matte token foundation: charcoal canvas, solid islands/cards, both themes; self-hosted Inter only"
```

### Task 2: Shell Recomposition (Slice 1)

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardSidebar.jsx`
- Modify: `frontend/src/components/dashboard/DashboardTopbar.jsx`
- Modify: `frontend/src/components/dashboard/WorkspaceIsland.jsx`
- Modify: `frontend/src/index.css` (dashboard shell blocks only)

**Interfaces:**
- Consumes: Task 1 tokens.
- Produces: the visual shell every later view sits in. No prop or behavior changes — all 30+ sidebar props, topbar slots, and workspace-island flows stay identical.

- [ ] **Step 1: Sidebar visual pass**

In `DashboardSidebar.jsx`, keeping the nav data, handlers, live row, `groupMeetings`, and footer logic byte-identical, recompose presentation to the spec's "compact navigation rows, thin neutral borders, content-dense, calm":
- Nav rows: reduce vertical padding to a compact 36-40px row height, 13px/medium labels using `--db-text-soft`, icons 16px at `--db-text-muted`; active row = `--db-fill-strong` background + `--db-text` label + a 2px `--db-accent` left indicator (cyan = selection only); hover = `--db-fill`.
- Section labels (meeting date-ladder group headers): use the `eyebrow` style from `dashboardStyles.js` at `--db-text-faint`.
- Meeting rows: single-line, 13px, muted; current meeting gets the same active treatment as nav rows.
- Dividers between nav / live row / meetings / footer: `border-t` with `--db-border`.
- Footer: same content, compact row.

- [ ] **Step 2: Topbar + workspace island visual pass**

`DashboardTopbar.jsx`: title at 15px/semibold tracking `-0.01em`; search pill = `--db-fill` background, `--db-border` border, no glass; keep marquee, `StatusIsland`, `actions`/`bell` slots untouched. `WorkspaceIsland.jsx`: scope pill matches the compact nav-row treatment; dropdown/dialog content inherits `.dashboard-popup` (unchanged — transient glass is allowed).

- [ ] **Step 3: Shell CSS**

In `index.css` dashboard blocks: tighten `--dashboard-topbar-h` from `76px` to `64px` and `--dashboard-edge` from `26px` to `20px` in `.dashboard-page` (1119-1134) — content density per spec. Verify `.dashboard-page::before` header backdrop (1241-1251) still covers the band (it derives from the same vars, so it follows automatically).

- [ ] **Step 4: Build + smoke**

Run: `npm run build`, then browser: desktop shell (both themes), collapsed rail (Ctrl+B), drawer below 1024px, workspace dropdown, notifications, search focus ring. All meeting history rows still open meetings; no layout overflow.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/DashboardSidebar.jsx frontend/src/components/dashboard/DashboardTopbar.jsx frontend/src/components/dashboard/WorkspaceIsland.jsx frontend/src/index.css
git commit -m "Matte shell: compact nav rows, cyan selection indicator, tighter chrome geometry"
```

### Task 3: Home Split + WorkspaceChatPanel (Slice 2)

**Files:**
- Create: `frontend/src/components/dashboard/WorkspaceChatPanel.jsx`
- Modify: `frontend/src/components/ChatPanel.jsx` (export two existing helpers — no behavior change)
- Modify: `frontend/src/components/dashboard/StatsCanvas.jsx`
- Modify: `frontend/src/components/DashboardPage.jsx` (home render branch only)
- Modify: `frontend/src/index.css` (home grid block 1291-1345 + the 900px rule at 1355)

**Interfaces:**
- Consumes: `apiFetch` from `lib/api.js`; `MarkdownMessage` and `SourceCard` from `ChatPanel.jsx` (newly exported); Task 1 tokens.
- Produces: `WorkspaceChatPanel({ user, onOpenMeeting })` — self-contained global assistant; `StatsCanvas` gains an `assistant` node prop rendering the right column.

- [ ] **Step 1: Export the shared chat renderers**

In `ChatPanel.jsx`, change `function MarkdownMessage(...)` (line 27) to `export function MarkdownMessage(...)` and `function SourceCard(...)` (line 191) to `export function SourceCard(...)`. No other edits.

- [ ] **Step 2: Create `WorkspaceChatPanel.jsx`**

```jsx
// Home's global assistant — asks across ALL saved meetings via /chat/global.
// Read-scope by design: it never receives a focused meeting, transcript, or
// result, so it cannot correct/rerun anything. Until the backend scopes
// /chat/global by workspace, the header says "Across your saved meetings".
import { useRef, useState, useEffect } from 'react'
import { Sparkles, SendHorizonal, RotateCcw } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { MarkdownMessage, SourceCard } from '../ChatPanel'
import { glassCard, cardGlowStyle, eyebrow, subtleText } from './dashboardStyles'

const SUGGESTIONS = [
  'What did we commit to this week?',
  'Which decisions are still unresolved?',
  'Summarize my last 3 meetings',
]

export default function WorkspaceChatPanel({ user, onOpenMeeting }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, loading])

  async function send(text) {
    const msg = (text ?? input).trim()
    if (!msg || loading) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      const res = await apiFetch('/chat/global', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      if (!res.ok) throw new Error(`global chat ${res.status}`)
      const data = await res.json()
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: data.response ?? 'No response from server.',
        toolsUsed: data.tools_used || [],
        ragContext: data.rag_context || null,
      }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', error: true, retryText: msg }])
    } finally {
      setLoading(false)
    }
  }

  if (!user) {
    return (
      <section className={`${glassCard} flex h-full flex-col items-center justify-center gap-2 p-6 text-center`} style={cardGlowStyle}>
        <Sparkles className="h-5 w-5 text-[color:var(--db-text-faint)]" />
        <p className={subtleText}>Sign in to ask Prism across your saved meetings.</p>
      </section>
    )
  }

  return (
    <section className={`${glassCard} flex h-full min-h-0 flex-col`} style={cardGlowStyle} aria-label="Ask Prism">
      <header className="border-b px-4 py-3" style={{ borderColor: 'var(--db-border)' }}>
        <div className="flex items-center gap-2 text-[color:var(--db-text)]">
          <Sparkles className="h-4 w-4 text-[color:var(--db-accent-text)]" />
          <span className="text-sm font-semibold">Ask Prism</span>
        </div>
        <p className={`${subtleText} mt-0.5`}>Across your saved meetings</p>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && !loading && (
          <div className="flex h-full flex-col justify-end gap-2">
            <p className={eyebrow}>Try asking</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)}
                className="rounded-xl border px-3 py-2 text-left text-sm text-[color:var(--db-text-soft)] hover:bg-[color:var(--db-fill)]"
                style={{ borderColor: 'var(--db-border)' }}>
                {s}
              </button>
            ))}
          </div>
        )}
        <div className="space-y-3">
          {messages.map((m, i) => m.role === 'user' ? (
            <div key={i} className="ml-8 rounded-2xl rounded-br-md bg-[color:var(--db-fill-strong)] px-3 py-2 text-sm text-[color:var(--db-text)]">{m.content}</div>
          ) : m.error ? (
            <div key={i} className="mr-8 rounded-2xl border px-3 py-2 text-sm text-[color:var(--db-text-muted)]" style={{ borderColor: 'var(--db-border)' }}>
              Couldn't reach Prism.
              <button onClick={() => send(m.retryText)} className="ml-2 inline-flex items-center gap-1 text-[color:var(--db-accent-text)]">
                <RotateCcw className="h-3 w-3" /> Retry
              </button>
            </div>
          ) : (
            <div key={i} className="mr-4 text-sm text-[color:var(--db-text-soft)]">
              <MarkdownMessage content={m.content} />
              {m.toolsUsed?.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {m.toolsUsed.map((t) => (
                    <span key={t} className="rounded-full border px-2 py-0.5 text-[10px] text-[color:var(--db-text-muted)]" style={{ borderColor: 'var(--db-border)' }}>✓ {t}</span>
                  ))}
                </div>
              )}
              {m.ragContext?.has_conflict && (
                <p className="mt-1.5 rounded-lg bg-amber-500/10 px-2 py-1 text-xs text-amber-500">Sources disagree — check the citations below.</p>
              )}
              {m.ragContext?.sources?.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  <p className={eyebrow}>Sources ({m.ragContext.sources.length})</p>
                  {m.ragContext.sources.map((s, j) => <SourceCard key={j} source={s} onOpenMeeting={onOpenMeeting} />)}
                </div>
              )}
            </div>
          ))}
          {loading && <p className={`${subtleText} animate-pulse`}>Searching your meetings…</p>}
        </div>
      </div>

      <form className="flex items-end gap-2 border-t px-3 py-3" style={{ borderColor: 'var(--db-border)' }}
        onSubmit={(e) => { e.preventDefault(); send() }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
          rows={1}
          placeholder="Ask across your meetings…"
          className="max-h-32 min-h-[40px] flex-1 resize-none rounded-xl border bg-transparent px-3 py-2 text-sm text-[color:var(--db-text)] outline-none placeholder:text-[color:var(--db-text-faint)]"
          style={{ borderColor: 'var(--db-border)' }}
        />
        <button type="submit" disabled={loading || !input.trim()} aria-label="Send"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[color:var(--db-accent)] text-black disabled:opacity-40">
          <SendHorizonal className="h-4 w-4" />
        </button>
      </form>
    </section>
  )
}
```

Check `SourceCard`'s actual prop names at `ChatPanel.jsx:191` before wiring (`source`/`onOpenMeeting` are the expected shape — if it takes different prop names, match them here rather than changing `SourceCard`).

- [ ] **Step 3: Restructure the home grid to the split layout**

Replace `index.css` lines 1291-1345 (the `.dashboard-content.is-home` / `.dashboard-home-grid` block) and the 900px rule at 1355 with:

```css
/* Split Home (north-star): operational column scrolls with the page; the
   assistant is a viewport-height sticky right column. */
.dashboard-content.is-home {
  padding-bottom: var(--dashboard-gutter);
}
.dashboard-home-grid {
  display: grid;
  grid-template-columns: minmax(0, 13fr) minmax(380px, 7fr);
  gap: var(--dashboard-gutter);
  align-items: start;
}
.dashboard-home-ops {
  display: flex;
  flex-direction: column;
  gap: var(--dashboard-gutter);
  min-width: 0;
}
.dashboard-home-assistant {
  position: sticky;
  top: calc(var(--dashboard-edge) + var(--dashboard-topbar-h) + var(--dashboard-gutter));
  height: calc(100dvh - (var(--dashboard-edge) * 2) - var(--dashboard-topbar-h) - var(--dashboard-gutter));
  min-height: 420px;
  min-width: 0;
}
/* Below the shell breakpoint Home is one column; the assistant column hides
   behind the Ask Prism sheet (Task 4). */
@media (max-width: 1023px) {
  .dashboard-home-grid { grid-template-columns: 1fr; }
  .dashboard-home-assistant { display: none; }
}
```

Delete the now-unused `.dashboard-home-hero` / `.dashboard-home-attention` / `.dashboard-home-meetings` grid-area rules, the `.is-home-empty` overrides, and the `max-height: 800px` home block (the page scrolls naturally now, so the short-viewport relief is obsolete). Search `DashboardPage.jsx` for `is-home-empty` and remove that className logic too if present.

- [ ] **Step 4: Rework `StatsCanvas.jsx` composition**

Add an `assistant = null` prop. Return becomes:

```jsx
<div className="dashboard-home-grid">
  <div className="dashboard-home-ops">
    {/* existing HeroRow, NeedsAttention (when !isEmpty), MeetingsCard — unchanged children, now a vertical stack */}
  </div>
  {assistant && <div className="dashboard-home-assistant">{assistant}</div>}
</div>
```

Keep the first-run/empty state inside `dashboard-home-ops` (free-flowing copy + CTAs, per spec never fabricated data).

Leave `HeroRow`, `NeedsAttention`, and `MeetingsCard` **content, props, and behavior** unchanged — but the old grid gave them a definite viewport height, and the new stack does not, so their internal scroll containers (`max-h-*`/`overflow-y-auto` with `min-h-0`) may collapse or grow unbounded. Adjusting those container height/overflow classes is in scope and expected: each card should size to its content with its own internal cap (e.g. `MeetingsCard`'s 5-row list, `NeedsAttention`'s bounded slice). Verify no card renders zero-height and no card grows past the viewport.

- [ ] **Step 5: Mount the assistant from DashboardPage**

At the `StatsCanvas` render site (`DashboardPage.jsx:1714-1750`), add:

```jsx
assistant={<WorkspaceChatPanel user={props.user} onOpenMeeting={(meta) => meta?.meeting_id && handleOpenMeetingById(meta.meeting_id)} />}
```

with a lazy import alongside the others (line 55-59): `const WorkspaceChatPanel = lazy(() => import('./dashboard/WorkspaceChatPanel'))` — wrap the assistant node in the existing `Suspense` boundary pattern. Verify `handleOpenMeetingById` is the existing function used by `UpcomingMeetings`' Brief click-through; match `SourceCard`'s actual open-meeting callback shape.

- [ ] **Step 6: Build + smoke the real endpoint**

Run `npm run build`. Browser: signed in, ask "what did we commit to across all meetings" → real `/chat/global` response renders with tool pills/sources; kill the backend → error bubble with working Retry; signed out → sign-in gate card; 1023px → single column, no assistant (sheet comes next task); both themes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/dashboard/WorkspaceChatPanel.jsx frontend/src/components/ChatPanel.jsx frontend/src/components/dashboard/StatsCanvas.jsx frontend/src/components/DashboardPage.jsx frontend/src/index.css
git commit -m "Split Home: sticky Ask Prism assistant column over /chat/global, operational stack left"
```

### Task 4: Home Operational Column + Mobile Ask Prism Sheet (Slice 2)

**Files:**
- Modify: `frontend/src/components/dashboard/StatsCanvas.jsx`
- Modify: `frontend/src/components/DashboardPage.jsx` (capture-pill wiring + sheet state)
- Modify: `frontend/src/index.css` (small additions only)

**Interfaces:**
- Consumes: Task 3 layout; `NewMeetingPanel` tabs `join|paste|record|upload`; `props.micSupported` (already threaded to `NewMeetingPanel` from DashboardPage props).
- Produces: `StatsCanvas` props `onUploadRecording`, `onRecordAudio`, `micSupported`; an `Ask Prism` floating control + full-height sheet below 1024px.

- [ ] **Step 1: Complete the capture row**

In `StatsCanvas.jsx`'s `HeroRow` quick actions (lines 49-81): keep Join + Paste pills, add **Upload** and **Record** pills styled identically (Record hidden when `!micSupported`), keep "See a sample" only when `canLoadSample`. Add the spec's one-line product promise under the greeting (e.g. `Drop in a meeting — Prism turns it into decisions, actions, and follow-ups.`) styled with `subtleText`. New props: `onUploadRecording`, `onRecordAudio`, `micSupported=false`.

- [ ] **Step 2: Wire the new pills**

At the `StatsCanvas` render site in `DashboardPage.jsx`, mirroring the existing Join/Paste handlers (1721-1722):

```jsx
onUploadRecording={() => { props.setInputTab?.('upload'); setNewMeetingOpen(true) }}
onRecordAudio={() => { props.setInputTab?.('record'); setNewMeetingOpen(true) }}
micSupported={props.micSupported}
```

- [ ] **Step 3: Recompose the operational stack hierarchy**

Inside `dashboard-home-ops`: greeting + promise + capture pills as an uncarded header block (content on canvas, not a card); `MeetingHero` as the first full card (primary operational surface); `NeedsAttention` second; `MeetingsCard` last as a compact continuation ("Recent" list of 5 with its existing "View all meetings →"). No component API changes beyond Step 1.

- [ ] **Step 4: Mobile Ask Prism sheet**

Below the shell breakpoint (`matchMedia('(max-width: 1023px)')` — reuse the `isNarrow` state that already exists in `DashboardPage.jsx:887,933`), render on the home view: a fixed bottom-right `Ask Prism` pill button (min 44px target) that opens the assistant as a full-height overlay using the existing Radix `Dialog` primitive (`ui/dialog.tsx`) with content classes `fixed inset-x-0 bottom-0 top-[8dvh] rounded-t-2xl p-0` containing `<WorkspaceChatPanel .../>`. Radix provides Escape/focus trap/restoration. The sheet and the pill render only when `activeView === 'home'`.

- [ ] **Step 5: Build + smoke**

`npm run build`; browser at 1440px and 390px: all four capture pills open the correct NewMeetingPanel tab; sample pill only when eligible; mobile sheet opens/closes with Escape and backdrop, composer usable with on-screen keyboard space (top offset), both themes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/StatsCanvas.jsx frontend/src/components/DashboardPage.jsx frontend/src/index.css
git commit -m "Home operational column: full capture row, hero-first hierarchy, mobile Ask Prism sheet"
```

### Task 5: Standalone Actions Page (Slice 3)

**Files:**
- Create: `frontend/src/components/dashboard/ActionsView.jsx`
- Modify: `frontend/src/lib/actionItems.js` (add `dueBand`)
- Modify: `frontend/tests/actionItems.test.mjs`
- Modify: `frontend/src/components/DashboardPage.jsx` (view wiring)
- Modify: `frontend/src/components/dashboard/DashboardSidebar.jsx` (nav item + count)

**Interfaces:**
- Consumes: `collectOpenActions`, `scopeFilter`, `byPriority`, `ActionItemRow`, `dueInfo`; `persistView`; `props.toggleHistoryActionItem`; `handleSelectMeeting`.
- Produces: `dueBand(row) → 'overdue'|'soon'|'open'` in `lib/actionItems.js`; `ActionsView({ history, user, onToggleAction, onOpenMeeting, onOpenTrend })`; `activeView === 'actions'` as a first-class view; sidebar `actionsCount`.

- [ ] **Step 1: Write the failing `dueBand` test**

Append to `frontend/tests/actionItems.test.mjs` (match its existing imports/style):

```js
import { dueBand } from '../src/lib/actionItems.js'

test('dueBand buckets rows by live urgency, matching byPriority tiers', () => {
  const mk = (due, date = '2026-08-01T10:00') => ({ item: { task: 'x', due_date: due }, entry: { date } })
  const iso = (offsetDays) => new Date(Date.now() + offsetDays * 86400000).toISOString().slice(0, 10)

  assert.equal(dueBand(mk(iso(-2))), 'overdue')  // recently past
  assert.equal(dueBand(mk(iso(1))), 'soon')      // within 3 days
  assert.equal(dueBand(mk(iso(30))), 'open')     // far future
  assert.equal(dueBand(mk(undefined)), 'open')   // undated
  // A >14-day-old deadline is dueInfo status 'stale', which byPriority ranks
  // with the rest (DUE_RANK[...] ?? 2) — so the band must be 'open', never a
  // live-urgency band. This is the assertion that keeps the two in lockstep.
  assert.equal(dueBand(mk(iso(-40))), 'open')
})
```

Run (from `frontend/`): `npm test`
Expected: FAIL — `dueBand` is not exported.

- [ ] **Step 2: Implement `dueBand`**

In `frontend/src/lib/actionItems.js`, next to `byPriority`:

```js
/** Visual band for a row, aligned 1:1 with byPriority's DUE_RANK so banded
 *  rendering of a byPriority-sorted list is always contiguous. */
export function dueBand(row) {
  const rank = DUE_RANK[dueInfo(row.item, row.entry?.date).status] ?? 2
  return rank === 0 ? 'overdue' : rank === 1 ? 'soon' : 'open'
}
```

Run `npm test` — expected: PASS (all suites).

- [ ] **Step 3: Create `ActionsView.jsx`**

```jsx
// Standalone Actions page — the canonical execution surface for open action
// items in the active scope (spec 2026-08-08; supersedes ADR 0002's location
// decision only — byPriority remains THE order, chips remain filters).
import { useMemo, useState } from 'react'
import { ListTodo, ArrowRight } from 'lucide-react'
import { collectOpenActions, scopeFilter, byPriority, dueBand } from '../../lib/actionItems'
import ActionItemRow from './ActionItemRow'
import { glassCard, cardGlowStyle, eyebrow, cardTitle, subtleText } from './dashboardStyles'

const BAND_LABELS = { overdue: 'Overdue', soon: 'Due soon', open: 'Open' }
const SCOPES = [
  { key: 'all', label: 'All' },
  { key: 'mine', label: 'Yours' },
  { key: 'unassigned', label: 'Unassigned' },
]

export default function ActionsView({ history = [], user = null, onToggleAction, onOpenMeeting, onOpenTrend }) {
  const [scope, setScope] = useState('all')
  const { rows, total, mineCount, unassignedCount, overdue, soon } = useMemo(() => {
    const all = collectOpenActions(history, user)
    const sorted = scopeFilter(all, scope).sort(byPriority)
    return {
      rows: sorted,
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
      unassignedCount: all.filter((r) => r.unassigned).length,
      overdue: all.filter((r) => dueBand(r) === 'overdue').length,
      soon: all.filter((r) => dueBand(r) === 'soon').length,
    }
  }, [history, user, scope])

  const counts = { all: total, mine: mineCount, unassigned: unassignedCount }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(240px,3fr)] items-start">
      <section className={glassCard} style={cardGlowStyle} aria-label="Open action items">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3" style={{ borderColor: 'var(--db-border)' }}>
          <h2 className={`${cardTitle} flex items-center gap-2`}><ListTodo className="h-4 w-4 text-[color:var(--db-text-muted)]" /> Actions</h2>
          <div className="flex gap-1">
            {SCOPES.map((s) => (
              <button key={s.key} onClick={() => setScope(s.key)}
                className={`min-h-[36px] rounded-full border px-3 text-xs ${scope === s.key ? 'bg-[color:var(--db-fill-strong)] text-[color:var(--db-text)]' : 'text-[color:var(--db-text-muted)] hover:bg-[color:var(--db-fill)]'}`}
                style={{ borderColor: scope === s.key ? 'var(--db-border-strong)' : 'var(--db-border)' }}>
                {s.label} <span className="opacity-60">{counts[s.key]}</span>
              </button>
            ))}
          </div>
        </header>
        {rows.length === 0 ? (
          <p className={`${subtleText} px-4 py-8 text-center`}>
            {scope === 'all'
              ? 'Open action items from completed or newly analyzed meetings will appear here.'
              : scope === 'mine' ? 'Nothing assigned to you right now.' : 'No unassigned items right now.'}
          </p>
        ) : (
          <ul className="px-2 py-2">
            {rows.map((row, i) => {
              const band = dueBand(row)
              const bandStart = i === 0 || dueBand(rows[i - 1]) !== band
              return (
                <li key={`${row.entry.id}-${row.index}`}>
                  {bandStart && (
                    <p className={`${eyebrow} px-2 pb-1 ${i === 0 ? 'pt-1' : 'pt-4'}`}>{BAND_LABELS[band]}</p>
                  )}
                  <ActionItemRow row={row} onToggle={onToggleAction} onOpenMeeting={onOpenMeeting} showMeeting />
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <aside className={`${glassCard} p-4`} style={cardGlowStyle} aria-label="Queue context">
        <p className={eyebrow}>Right now</p>
        <dl className="mt-2 space-y-1.5 text-sm text-[color:var(--db-text-soft)]">
          <div className="flex justify-between"><dt>Open items</dt><dd className="text-[color:var(--db-text)]">{total}</dd></div>
          <div className="flex justify-between"><dt>Overdue</dt><dd className="text-[color:var(--db-text)]">{overdue || '—'}</dd></div>
          <div className="flex justify-between"><dt>Due soon</dt><dd className="text-[color:var(--db-text)]">{soon || '—'}</dd></div>
          <div className="flex justify-between"><dt>Yours</dt><dd className="text-[color:var(--db-text)]">{mineCount}</dd></div>
        </dl>
        <p className={`${subtleText} mt-4`}>
          Ranked by live urgency (overdue → due soon), then yours → unassigned → teammates', then newest meeting. Stale deadlines are history, not urgency.
        </p>
        {onOpenTrend && (
          <button onClick={onOpenTrend} className="mt-4 inline-flex min-h-[36px] items-center gap-1 text-sm text-[color:var(--db-accent-text)]">
            Cross-meeting intelligence <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </aside>
    </div>
  )
}
```

- [ ] **Step 4: Wire the view into DashboardPage**

1. Lazy import: `const ActionsView = lazy(() => import('./dashboard/ActionsView'))` beside the others (lines 55-59).
2. **Delete lines 740-741** (`if (stored === 'actions') return 'intelligence'`) — `'actions'` is a real destination again; the stored value now flows through `return stored || ...` naturally.
3. Render branch (beside the `'intelligence'` case at 1780-1795):

```jsx
) : activeView === 'actions' ? (
  <Suspense fallback={<div className="p-6 text-sm text-[color:var(--db-text-faint)]">Loading…</div>}>
    <ActionsView
      history={history}
      user={props.user}
      onToggleAction={props.toggleHistoryActionItem}
      onOpenMeeting={handleSelectMeeting}
      onOpenTrend={handleOpenTrend}
    />
  </Suspense>
```

Match the exact `history`/`handleSelectMeeting`/`handleOpenTrend` identifiers already used by the `IntelligenceView` branch (1780-1795).
4. Topbar title: find the title computation at the `DashboardTopbar` render site (~line 1582) and add the `'actions'` → `Actions` case following the existing pattern.

- [ ] **Step 5: Sidebar nav item + open count**

In `DashboardPage.jsx`, compute the count near other memos: `const actionsCount = useMemo(() => collectOpenActions(history, props.user).length, [history, props.user])` (import from `../lib/actionItems`), and pass `actionsCount={actionsCount}` + `onOpenActions={() => persistView('actions')}` to `<DashboardSidebar>`. In `DashboardSidebar.jsx`, insert the Actions item **between Home and Trend** (nav list, lines 141-147), icon `ListTodo`, active when `activeView === 'actions'`, with a right-aligned count pill styled like the existing `standinBadge` pill but neutral (`--db-fill-strong` bg, `--db-text-muted` text) — cyan stays reserved for selection. Hide the pill when the count is 0.

- [ ] **Step 6: Build + smoke**

`npm test` (lib changed) + `npm run build`. Browser: sidebar shows Actions with the true open count; page loads with banded queue (Overdue/Due soon/Open dividers in order); toggling a checkbox marks complete optimistically and PATCHes (verify in network tab), and the count pill + Home Needs-attention update in the same render; filters work; row's meeting link opens the exact meeting; refresh with `prism_active_view=actions` in sessionStorage restores the Actions view; empty state on a fresh account shows the honest copy.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/actionItems.js frontend/tests/actionItems.test.mjs frontend/src/components/dashboard/ActionsView.jsx frontend/src/components/DashboardPage.jsx frontend/src/components/dashboard/DashboardSidebar.jsx
git commit -m "Standalone Actions page: banded byPriority queue, scope filters, context rail, sidebar count"
```

### Task 6: Trend Separation + ADR Amendment (Slice 3)

**Files:**
- Modify: `frontend/src/components/dashboard/IntelligenceView.jsx`
- Modify: `frontend/src/components/dashboard/NeedsAttention.jsx`
- Modify: `frontend/src/components/dashboard/StatsCanvas.jsx`
- Modify: `frontend/src/components/DashboardPage.jsx`
- Delete: `frontend/src/components/dashboard/TaskHub.jsx`
- Modify: `docs/adr/0002-task-hub-lives-on-trend.md`

**Interfaces:**
- Consumes: `ActionsView` route from Task 5 (`onOpenActions`).
- Produces: `IntelligenceView` prop `onOpenActions`; Trend without the full task hub.

- [ ] **Step 1: Replace TaskHub with a compact summary on Trend**

In `IntelligenceView.jsx`: remove the `TaskHub` import and its co-headline right column (lines 137-142). Rebalance the grid to `lg:grid-cols-[minmax(0,7fr)_minmax(300px,4fr)]` with the right column now a compact "Open tasks" card built inline:

```jsx
<section className={`${glassCard} p-4`} style={cardGlowStyle} aria-label="Open tasks">
  <div className="flex items-center justify-between">
    <h3 className={cardTitle}>Open tasks</h3>
    <span className="text-2xl font-semibold text-[color:var(--db-text)]">{openTasks.total}</span>
  </div>
  <p className={`${subtleText} mt-1`}>{openTasks.overdue} overdue · {openTasks.soon} due soon</p>
  <ul className="mt-3 space-y-1">
    {openTasks.top.map((row) => (
      <ActionItemRow key={`${row.entry.id}-${row.index}`} row={row} onToggle={onToggleAction} onOpenMeeting={onSelectMeeting} showMeeting />
    ))}
  </ul>
  <button onClick={onOpenActions} className="mt-3 inline-flex min-h-[36px] items-center gap-1 text-sm text-[color:var(--db-accent-text)]">
    View all in Actions <ArrowRight className="h-3.5 w-3.5" />
  </button>
</section>
```

with `openTasks` memoized from the utilities TaskHub used:

```jsx
const openTasks = useMemo(() => {
  const all = collectOpenActions(safeHistory, user)
  return {
    total: all.length,
    overdue: all.filter((r) => dueBand(r) === 'overdue').length,
    soon: all.filter((r) => dueBand(r) === 'soon').length,
    top: [...all].sort(byPriority).slice(0, 3),
  }
}, [safeHistory, user])
```

Add prop `onOpenActions` to the signature; in `DashboardPage.jsx`'s IntelligenceView render (1780-1795) pass `onOpenActions={() => persistView('actions')}`.

- [ ] **Step 2: Delete `TaskHub.jsx`**

Its full-queue UI now lives in `ActionsView`. Grep for remaining `TaskHub` imports (should be none after Step 1) before deleting.

- [ ] **Step 3: Retarget Home's Needs-attention CTA to Actions**

`NeedsAttention.jsx`'s footer button reads "View all N tasks →" and currently calls its `onOpenTrend` prop. The canonical task destination is now Actions, so:

1. In `NeedsAttention.jsx`, rename that prop `onOpenTrend` → `onOpenActions` (signature + the button's `onClick`). Leave the label text as-is; it already says "tasks", which is Actions' subject.
2. In `StatsCanvas.jsx`, rename the prop it forwards to `NeedsAttention` to match, and add `onOpenActions` to `StatsCanvas`'s own signature (keep any separate `onOpenTrend` that other Home children use — verify with grep before removing anything).
3. At the `StatsCanvas` render site in `DashboardPage.jsx` (1714-1750), pass `onOpenActions={() => persistView('actions')}`.

Grep `onOpenTrend` across `frontend/src` afterward: every remaining use must be a genuine Trend link, not a task CTA.

- [ ] **Step 4: Amend ADR 0002**

Append to `docs/adr/0002-task-hub-lives-on-trend.md`:

```markdown
## Amendment (2026-08-08, north-star migration)

The location decision is superseded by the approved north-star direction
(docs/superpowers/specs/2026-08-08-prism-north-star-frontend-migration-design.md):
the full Task hub moves from Trend to a standalone top-level **Actions** page,
and Trend keeps a compact open-task summary that links to it. Everything else
in this record stands — `byPriority` remains THE one task order used
identically by every surface, ownership chips remain filters, and stale
deadlines remain history, not urgency.
```

- [ ] **Step 5: Build + smoke**

`npm run build`. Browser: Trend shows graph + vitals with the compact task card (top-3 rows toggle correctly, "View all in Actions" lands on the Actions page); the "Threads & decisions" disclosure and the Act-on-thread modal still work; Home's Needs-attention "View all N tasks →" now lands on **Actions** (Step 3), and any remaining Trend links still land on Trend; both themes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/IntelligenceView.jsx frontend/src/components/dashboard/NeedsAttention.jsx frontend/src/components/dashboard/StatsCanvas.jsx frontend/src/components/DashboardPage.jsx docs/adr/0002-task-hub-lives-on-trend.md
git rm frontend/src/components/dashboard/TaskHub.jsx
git commit -m "Trend keeps intelligence, links to Actions: compact task summary replaces full hub (ADR 0002 amended)"
```

### Task 7: Meeting Record Recomposition (Slice 4)

**Files:**
- Modify: `frontend/src/components/dashboard/MeetingView.jsx`

**Interfaces:**
- Consumes: Task 1 tokens; existing `CollapsibleSection`.
- Produces: no API change — same props, same callbacks, same cards; only hierarchy and presentation move.

- [ ] **Step 1: Make TL;DR/summary the strongest record surface**

Recompose the hero grid (lines 322-418) so the record leads:
1. First block, full width: TL;DR (one bold sentence, ~18px `--db-text`), then the full summary paragraph(s) (`bodyText`), then topics as neutral chips (`--db-fill` bg, `--db-text-muted`) and the verdict/improvement-tip line.
2. The score column (`SemicircularGauge`/`MeetingHealthTriangle` + badges) becomes a compact right rail beside the summary: grid `lg:grid-cols-[minmax(0,1fr)_240px]`, stacking below `lg`. Preserve the ungraded/null wireframe state exactly (missing score renders the ungraded triangle, never 0).
3. `pinnedSection` (meeting-pinned docs) moves below the summary/score block, full width, unchanged content.

Keep the exit-banner (281-297) first and the lens `MeetingTypeControl` (298-318) where it is but restyled as a quiet inline control (small select-style pill, `--db-text-muted`) so it doesn't compete with the record.

- [ ] **Step 2: Keep Actions + Decisions as the primary work grid**

The 2-column grid (422-565) stays functionally identical — checkbox toggles via `onToggleActionItem`, `compareDue` ordering, decision↔action links (`decisionByAction`), overdue/due-soon badges. Presentation aligns to matte: section headers use `eyebrow` + `cardTitle`, rows separated by `--db-border` hairlines.

- [ ] **Step 3: Unify the collapsed tail**

Order unchanged: Follow-up (`SuggestedActions`/`EmailCard`/`CalendarCard`), `SentimentCard` (`defaultOpen={false}`), `SpeakerCoachCard`, `RecordingPlayer`, Transcript. Convert the hand-rolled transcript collapsible (626-650) to the shared `CollapsibleSection` (`title="Transcript"`, `hint="full text · sync with recording"`, `defaultOpen={false}`) preserving its children exactly (line-seek behavior included). Delete the local `transcriptOpen` state.

- [ ] **Step 4: Build + smoke**

`npm run build`. Browser on a real analyzed meeting: summary dominates the first viewport; score rail correct for scored/ungraded/failed meetings; action toggle persists; decision links jump; every tail card opens and works (send email draft UI, calendar card, recording player if present, transcript expands and seeks); shared read-only view (`#share/...`) still renders (readOnly guards untouched); 390px width single column, 44px controls; both themes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/MeetingView.jsx
git commit -m "Meeting record: summary-first hierarchy with compact score rail; tail unified on CollapsibleSection"
```

### Task 8: Meeting Chat Visual Alignment (Slice 4)

**Files:**
- Modify: `frontend/src/components/ChatPanel.jsx` (presentation classes only)
- Modify: `frontend/src/components/DashboardPage.jsx` (docked container classes at 1899-1921 only)

**Interfaces:**
- Consumes: Task 1 tokens.
- Produces: nothing new — persistence, tools, corrections, intents, sessions, images all byte-identical.

- [ ] **Step 1: Restyle the docked chat surface**

Sweep both files' chat chrome for hardcoded glass/white-alpha styles and replace with tokens: container = `.dashboard-island`-equivalent matte (solid `--db-island-base`, `--db-border`, `--db-shadow`); bubbles/composer/header pills use `--db-fill`/`--db-fill-strong`/`--db-text-*`; keep cyan only on send, active persona chip, and source-card provenance. Do NOT touch `send()`, intent detection, session persistence, image handling, or confirmation logic — className/style edits only. Visual parity with `WorkspaceChatPanel` (Task 3) so the two assistants read as one product surface.

- [ ] **Step 2: Build + smoke**

`npm run build`. Browser on a meeting: send a message, restore a session from History, New chat, attach/paste an image, run a rename intent, run an agent rerun — all behaviors identical, new skin, both themes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatPanel.jsx frontend/src/components/DashboardPage.jsx
git commit -m "Meeting chat aligned to matte shell; behavior untouched"
```

### Task 9: Remaining Destinations + Responsive/Reduced-Motion Polish (Slice 5)

**Files:**
- Modify: `frontend/src/components/dashboard/CalendarView.jsx`, `KnowledgeBase.jsx` (path per repo: `frontend/src/components/KnowledgeBase.jsx` if top-level), `ProxyProfile.jsx`, `LiveMeetingView.jsx`, `StatusIsland.jsx`, `NewMeetingPanel` (in `DashboardPage.jsx`), `StandInComposer.jsx`, `IntegrationsModal.jsx` — presentation-only sweep
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: Task 1 tokens.
- Produces: one coherent matte surface across every dashboard destination.

- [ ] **Step 1: Token sweep**

Grep these components for hardcoded `rgba(255,255,255,...)` fills, `backdrop-blur`, `bg-white/N`, `bg-black/N`, and slate/zinc utility colors on *persistent* surfaces; replace with `--db-*` tokens or `glassCard`/`cardGlowStyle`. Transient overlays (Radix dialogs/popovers, `.dashboard-popup` consumers, toasts) may keep blur. Most cards already import `dashboardStyles` and inherited the matte change in Task 1 — this step catches stragglers. Check both themes per screen.

- [ ] **Step 2: Reduced-motion audit**

The shell transitions already respect `prefers-reduced-motion` (index.css 1228-1235; livedot 1183-1185). Extend the same guard to: the page-entrance `animate-fade-in-up` (wrap in `@media (prefers-reduced-motion: no-preference)` or add a reduce override killing the animation), the topbar title marquee (`dashboard-title-marquee` keyframes), and `useCountUp` (in `frontend/src/components/dashboard/useCountUp.js` — return the target immediately when `matchMedia('(prefers-reduced-motion: reduce)').matches`).

- [ ] **Step 3: Target-size and focus pass**

At 390×844 and 1440×900: every interactive control in the migrated surfaces ≥44px effective target (pad small icon buttons), visible focus ring on the new Actions/Home/assistant controls (the `:focus-visible` rule at index.css:1350 already applies — verify it's visible on matte in light theme; if the cyan ring washes out on paper, add a `.theme-light` focus override using `--db-accent` at higher alpha).

- [ ] **Step 4: Build + full smoke matrix**

`npm run build` + `npm test`. Browser: every view (Home, Actions, Trend, Calendar, Knowledge, Stand-in, a Meeting, Live if a token is available, `#share/` sample) × both themes × 1440/1024/390 widths. No horizontal overflow anywhere; drawer works below 1024.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "Matte sweep across remaining destinations; reduced-motion + target-size polish"
```

### Task 10: Documentation + Acceptance (Slice 5)

**Files:**
- Modify: `CLAUDE.md` (design-direction + Task-first IA paragraphs)
- Modify: `PRISM_AI_CONTEXT.md` (Landing Visual Layer / surface-language note)
- Create: nothing else

**Interfaces:**
- Consumes: all prior tasks.
- Produces: docs that match shipped reality; the preservation checklist verdict.

- [ ] **Step 1: Update CLAUDE.md**

Rewrite the "Current design direction" paragraph: the dashboard's default surface is now **matte** (`--db-card`/`--db-island-base` solids; glass reserved for transient layers: `.dashboard-popup`, `.dashboard-status-island`, dialogs/toasts). Update the Task-first IA paragraph: the Task hub now lives on the standalone **Actions** page (`ActionsView.jsx`, `activeView === 'actions'`); Trend keeps intelligence + a compact task summary; the `'actions'`→`'intelligence'` sessionStorage rewrite is gone; Home is the split operational + Ask-Prism layout with `WorkspaceChatPanel` (reads `/chat/global`, header truthfully says "Across your saved meetings"). Keep every still-true invariant (health scale, missing≠bad, cyan-is-interactive, tabular-nums, date ladder).

- [ ] **Step 2: Update PRISM_AI_CONTEXT.md**

Amend the "two surface languages" note: landing unchanged (glass as accent); dashboard's default is now matte per the north-star spec, tokens in `index.css` `--db-*`.

- [ ] **Step 3: Walk the preservation list**

Against the spec's §Explicit preservation list, verify each item still functions in the browser and record pass/fail in the task report: auth flows load, sample mode (`See a sample`) works, light theme toggles, workspace switch/settings/invite links, integrations modal opens with saved settings, all four capture tabs, an end-to-end paste analysis streams cards progressively, history search/delete/move/share/export, calendar view + upcoming events, notifications bell, Knowledge page lists docs, Stand-in page loads profile + representations, `#share/` public view, every meeting card renders on a real meeting, personas picker, action toggle syncs Home/Actions/Meeting + PATCHes, meeting chat sessions restore. Any regression = fix before commit or report BLOCKED.

- [ ] **Step 4: Final verification**

Run (from `frontend/`):

```text
npm test
npm run build
```

Expected: all pass. Run `git status` — no unintended files.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md PRISM_AI_CONTEXT.md
git commit -m "Docs: matte dashboard direction, standalone Actions IA, split Home assistant"
```

---

## Self-Review

- **Spec coverage:** Visual direction → Tasks 1-2, 9. Split Home + real assistant (`/chat/global`, truthful header, no local citations) → Tasks 3-4. Actions as canonical queue reusing `collectOpenActions`/`byPriority`/`scopeFilter`/`ActionItemRow`/`toggleHistoryActionItem`, All/Yours/Unassigned, rail without invented state → Task 5. Trend separation + compact summary + ADR supersession → Task 6. Meeting record (summary-first, every card preserved, callbacks untouched) → Task 7; chat alignment → Task 8. Remaining destinations progressive adoption + responsive/a11y/reduced-motion → Task 9. Rollout checks (`npm run build` + smoke per slice, unit tests when lib changes) → embedded per task. Preservation list → Task 10. Sidebar IA (spec order incl. Actions count, live row, grouped meetings, account) → Tasks 2 + 5. Error/empty states (first-run guidance, in-thread retryable chat failure, honest empty Actions copy, dash-never-zero) → Tasks 3, 4, 5, 7.
- **Placeholder scan:** no TBDs; every code step carries real code or exact line-anchored edit instructions. Two verify-before-wiring notes (SourceCard prop shape, NeedsAttention CTA label) direct the implementer to check named lines rather than guess.
- **Type consistency:** `dueBand` defined Task 5 Step 2, consumed Tasks 5-6; `ActionsView` props match its DashboardPage wiring; `WorkspaceChatPanel({ user, onOpenMeeting })` matches its mount; `onOpenActions` produced in Task 5 wiring and consumed by Task 6; sidebar `actionsCount`/`onOpenActions` produced and consumed in Task 5.
- **Non-goals honored:** no React Router, no backend edits, no demo artifacts, no new npm dependencies, landing page untouched except the redundant Inter link removal (which `index.css:3` already covers for both surfaces).

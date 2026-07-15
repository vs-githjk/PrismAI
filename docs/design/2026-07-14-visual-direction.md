# Visual Direction — "Codify Current" (Phase 2a)

**Decided:** Jul 14 · **Approach:** codify today's dark + cyan/sky glass aesthetic into tokens + canonical components, then migrate every surface onto them. **The look does not change** — this is a consistency + maintainability pass, not a redesign.

**Why zero adoption of `ui/button` today:** it's a stock shadcn button whose variants use theme CSS vars (`bg-primary`, `bg-muted`, `border-border`) that were never wired to the app's cyan palette — so its `default` looked wrong and everyone hand-rolled instead. The fix: re-skin the shared components to the app's *real* classes so adopting them is a visual no-op.

---

## Tokens (extracted from live UI)

**Accent (brand):** `cyan-400 #22d3ee` primary · `cyan-300 #67e8f9` hover/bright · `sky-*` secondary. Reserve cyan for interactive/primary — not decoration.

**Surfaces:** page `#07040f` → `#0c1118`; card = glass film (`linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.035))` + `blur(26px)`), border `white/[0.09]`. (Already `dashboardStyles.glassCard` + `cardGlowStyle`.)

**Text:** `white/90` heading · `white/85` body · `white/55`–`/80` secondary · `white/40` muted. (Already `cardTitle`/`bodyText`/`subtleText`/`eyebrow`.)

**Status:** `emerald-*` success/ready · `rose-*` danger/error · `amber-*` busy/warning.

**Radius:** `rounded-full` primary CTA pill · `rounded-lg` controls/inline actions · `rounded-2xl` cards/modals.

**Spacing:** 4pt scale (`gap-1.5/2/3`, `p-4/5`). **Borders/dividers:** `white/[0.07–0.09]`.

---

## Canonical components (match real looks; re-skin `components/ui/*`)

**Button** — re-skin `ui/button` variants to the app's actual patterns:
| variant | look (real classes) | used for |
|---|---|---|
| `primary` | `bg-cyan-400 text-[#07040f] rounded-full hover:bg-cyan-300` | main CTA (Analyze) |
| `accent` | `border-cyan-400/30 bg-cyan-400/10 text-cyan-200 rounded-lg` | inline actions (Review & file) |
| `ghost` | `border-white/10 bg-white/5 text-white/75 hover:bg-white/10` | secondary/cancel |
| `danger` | `border-rose-400/40 bg-rose-400/15 text-rose-200` | destructive confirm |
| `icon` | `h-7 w-7 / h-8 w-8` square, ghost surface | icon-only (needs `aria-label`) |
| `subtle` | `border-transparent bg-transparent text-white/40 hover:bg-white/[0.07]` | borderless icons (close ✕) — the 2nd real icon flavor |
| `link` | `text-cyan-300 hover:underline` | inline links |

> **Sizes** — beyond shadcn's compact fixed heights (`default h-8`, `sm h-7`, icon `size-6/7/8`), a `cta` size (`h-10 px-4 text-sm font-semibold`, pair with `w-full`) matches the app's real full-width panel CTA (Analyze). `icon` is a *size*, `subtle`/`ghost` are the surface variants.
>
> **Shape outliers (converge later, not silently):** some full-width ghost buttons use `rounded-xl` + `text-white/80` (Upload) vs canonical ghost `rounded-lg` + `text-white/75`; stateful toggles (Record: red↔ghost) don't map to one variant. These aren't no-op migrations — converging them shifts a corner radius / color, so they're a deliberate consistency decision for a later grouped PR, not part of the drop-in pass.

**Card** — standardize on `glassCard` + `cardGlowStyle` (already shared). One card, everywhere.

**Modal** — one `ui/dialog` (overlay `bg-black/70 backdrop-blur-sm`, centered, `rounded-2xl`, portaled to body — the transformed-ancestor `position:fixed` fix). Migrate the 7 hand-rolled `fixed inset-0` modals onto it.

**Chip / pill** — one component (status dot + label; sensitivity/label/persona chips).

**Toast / status** — collapse the ≥5 mechanisms (`notifyStatus`, `setWorkspaceToast`, `StatusIsland`, `setIntegrationToast`, `setInviteStatus`) onto one `StatusIsland`-based API.

**States** — canonical `Empty`, `Loading` (skeleton), `Error` (extend the already-good `ErrorCard`) patterns; every async surface uses them.

---

## Migration plan (Phase 2b — grouped PRs, area-by-area)
1. **Re-skin `ui/button`** to the variants above (foundation) + add `aria-label` guidance. No call sites yet.
2. Migrate buttons **by area** (dashboard → cards → modals → landing → knowledge → live → workspace), grouped PRs. Visual diff must be ~zero.
3. **Modal unification** onto `ui/dialog` (folds in the a11y + confirm-dialog wins).
4. **Toast unification.**
5. **Token file** for colors/radius/spacing (optional CSS-var layer) once components are settled.

**Guardrail:** each migration PR is a visual no-op — if a button/modal looks different after, that's a regression, not the goal. Screenshot-compare the touched area.

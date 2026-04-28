# Landing Page Build Brief

## What to build

Complete the landing page in `frontend/src/App.jsx` starting from the current hero state, adding:
1. Hero completion — 2 CTA buttons + scroll cue
2. Section 1 — How it works
3. Section 2 — Agent showcase

Do NOT touch the existing rotating text, tagline, or Prism WebGL animation.

---

## Current hero state (do not change)

- Rotating pain-point text (RotatingText component, top of hero)
- "Let _prism handle it." tagline below it
- WebGL Prism background animation
- LandingNav at the top

---

## Hero completion

### CTA buttons
Place below the tagline, centered. Layout: `[ Get started ]  or  [ Try it out ]`

- **Get started** — primary button (filled, high contrast white/dark). Opens a signup `<Dialog>` on the same page. Build the trigger and a placeholder dialog shell for now — user will provide a styled component later and ask to match the aesthetic.
- **or** — small muted text connector between buttons
- **Try it out** — ghost/text secondary button. Loads a pre-filled sample transcript and shows output (no signup). Wire to existing demo flow in App.jsx if present, otherwise scroll to input.

### Scroll cue
Anchored absolutely to the bottom of the hero section with padding. Very quiet:
- Small muted text: `see more below`
- Animated down-chevron beside it (gentle, no bounce — ease-in-out, subtle)
- Fades out once user scrolls past the hero fold (IntersectionObserver or scroll listener)

---

## Page structure after hero

Each section gets `scroll-snap-align: start`. Add `scroll-snap-type: y proximity` to the page scroll container. Sections have a subtle background shift from the base `#07040f` (very slight hue/lightness change per section — don't overdo it). As a section scrolls out of view it gets a soft blur via an overlay.

---

## Section 1 — How it works

**Layout**: 3 steps horizontal on desktop, stacked on mobile. Large muted step numbers (01, 02, 03) as structural anchors. Include a simple inline flow diagram alongside: transcript icon → prism shape → output cards (SVG or styled divs, monochrome/muted).

**Steps content**:
- `01` **Get it in** — Paste a transcript, record live audio, or upload a file.
- `02` **Seven agents, in parallel** — An orchestrator routes your meeting to specialized agents that run simultaneously.
- `03` **Clarity in ~30 seconds** — Decisions, owners, summaries, emails, and a health score stream back live.

**Motion**: Scroll-triggered staggered reveal — each step fades + translates Y 20px → 0, 500ms ease-out-quint, 60ms stagger between steps.

---

## Section 2 — Agent showcase

**Layout**: 7 agent cards in a grid (4+3 on desktop, 2-col on tablet, 1-col on mobile).

**Card structure** (important — build with future media in mind):
Each card must have a **background layer div** (empty, dark, clearly classed e.g. `agent-card-bg`) behind the content. This will hold video/image/interactive demos in the future. For now it's just a dark backdrop. Content sits above it: agent name (heading) + abstract description (1–2 lines).

**7 agents**:
| Agent | Description |
|-------|-------------|
| Summarizer | Condenses the meeting into a 2–3 sentence TL;DR |
| Action Items | Extracts who owns what, with due dates |
| Decisions | Identifies what was actually agreed or resolved |
| Sentiment | Scores the tone and flags conflict or tension |
| Email Drafter | Writes a ready-to-send follow-up email |
| Calendar Suggester | Recommends a follow-up meeting with timing |
| Health Score | Rates meeting quality 0–100 with a breakdown |

**Motion**: Same scroll-triggered reveal as Section 1. Cards stagger in 40ms apart.

---

## Design direction

**Premium, reliable, precise.** Read `.impeccable.md` in the project root for full design context.

Key rules for this build:
- No spring physics for scroll animations — ease-out-quint, 400–600ms
- No glow effects on hover — subtle lift (transform: translateY(-2px)) + border opacity increase
- No gradient text (existing `.gradient-text` usage in the hero stays, don't add more)
- No left/right border stripes on cards
- Spacing is generous — sections breathe
- Trust through specificity: agent names are real, descriptions are precise

---

## Files to touch

| File | What to do |
|------|-----------|
| `frontend/src/App.jsx` | Add CTA buttons + scroll cue to `LandingScreen`, add `HowItWorks` and `AgentShowcase` components/sections |
| `frontend/src/index.css` | Add scroll-snap rules, section transition styles, agent card styles, scroll-cue animation |
| New component files if needed | `HowItWorks.jsx`, `AgentShowcase.jsx` — keep App.jsx clean |

---

## What NOT to build yet

- Pricing section
- Testimonials / social proof
- The actual signup dialog content (just the shell trigger)
- Any backend wiring

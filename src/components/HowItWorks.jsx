import { useRef, useState, useEffect, useLayoutEffect } from 'react'
import {
  motion,
  AnimatePresence,
  useMotionValue,
  useTransform,
  useMotionValueEvent,
  useReducedMotion,
  useInView,
} from 'motion/react'
import './HowItWorks.css'

const PHASES = 4
// Transition band width as a fraction of one phase. The crossfade between two
// phases spans the last τ of the outgoing phase. Kept wide so the fade is
// genuinely tied to scroll motion (not a narrow boundary snap) — the user
// asked for "starts whenever scroll occurs," so a phase holds fully only for
// its middle (1−τ) and is actively blending the rest of the time. Primary
// tuning knob: smaller = snappier/more boundary-like, larger = more constant blend.
const TAU = 0.5

// "prism" is static across all phases; only the "is ___" suffix animates.
const SUFFIXES = ['is conversational', 'is active', 'is agentic', 'is yours']

const PARAGRAPHS = [
  "Talk to Prism like you'd talk to a teammate. Ask it anything in plain language and it answers straight from your company's internal docs. It remembers what was said in past meetings, so context never gets lost. No commands, no searching — just ask.",
  "Prism connects to the tools you already use. Ask it to send an email, schedule a meeting, draft a Notion spec or open a task — and it does it, right from the conversation.",
  "Hand Prism the hard stuff and watch it work. It opens its own workspace — moving across your tools with real access, spawning agents to split the job, designing and building until it's shipped. Jump in and steer whenever you want.",
  'Prism is as customizable as you prefer — choose its persona, assign exactly the access it gets, and upload the docs you want it to know. Monitor every past meeting and surface the trends, all from your command center.',
]

/* ─────────────────────────────────────────────────────────────────
 * Layout mode — pinned (desktop, motion ok) vs stacked (narrow / reduced)
 * ───────────────────────────────────────────────────────────────── */

function useLayoutMode() {
  const reduce = useReducedMotion()
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const onChange = () => setNarrow(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduce || narrow ? 'stacked' : 'pinned'
}

export default function HowItWorks() {
  const mode = useLayoutMode()
  return mode === 'stacked' ? <HowItWorksStacked /> : <HowItWorksPinned />
}

/* ─────────────────────────────────────────────────────────────────
 * Pinned (default) — sticky card, scroll-scrubbed phase crossfade
 * ───────────────────────────────────────────────────────────────── */

function HowItWorksPinned() {
  const sectionRef = useRef(null)
  const cardRef = useRef(null)

  // The landing page scrolls inside `.landing-page` (an overflow-y:scroll
  // absolute container), not the window — so framer-motion's useScroll can't
  // see it. Compute progress manually against whichever element actually
  // scrolls. progress = 0 when the section top hits the viewport top (pin
  // start), 1 when its bottom reaches the viewport bottom (pin end).
  const progress = useMotionValue(0)
  // Approach = how close the section is to pinning, separate from `progress`
  // (which only starts once pinned). 0 when the section top sits a full
  // viewport below the fold, 1 once it reaches the top and pins. Drives the
  // peek blur: the card pokes above the fold on the hero, softly blurred,
  // sharpening to crisp as it locks in.
  const approach = useMotionValue(0)
  useEffect(() => {
    const sec = sectionRef.current
    if (!sec) return
    const scroller = sec.closest('.landing-page') || window
    const compute = () => {
      const rect = sec.getBoundingClientRect()
      const ih = window.innerHeight
      const travel = rect.height - ih
      const p = travel > 0 ? Math.min(1, Math.max(0, -rect.top / travel)) : 0
      progress.set(p)
      approach.set(Math.min(1, Math.max(0, (ih - rect.top) / ih)))
    }
    compute()
    scroller.addEventListener('scroll', compute, { passive: true })
    window.addEventListener('resize', compute)
    return () => {
      scroller.removeEventListener('scroll', compute)
      window.removeEventListener('resize', compute)
    }
  }, [progress, approach])

  const phaseFloat = useTransform(progress, [0, 1], [0, PHASES])

  // Peek blur — ~7px while approaching on the hero, crisp by the time it pins.
  // Emitted as `none` at zero so the pinned card carries no filter layer.
  const cardFilter = useTransform(approach, [0.2, 0.85], [7, 0], { clamp: true })
  const cardFilterCss = useTransform(cardFilter, (b) => (b < 0.15 ? 'none' : `blur(${b}px)`))

  // Measure each suffix's rendered width so the slot can morph to the active
  // suffix as you scroll. This keeps the heading centered every phase (and
  // "prism" simply glides — it never fades, the one hard constraint).
  const measureRefs = useRef([])
  const [widths, setWidths] = useState(() => SUFFIXES.map(() => 0))
  useLayoutEffect(() => {
    const measure = () => {
      const w = measureRefs.current.map((el) => (el ? el.getBoundingClientRect().width : 0))
      if (w.some((x) => x > 0)) setWidths(w)
    }
    measure()
    if (document.fonts?.ready) document.fonts.ready.then(measure)
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])
  const slotWidth = useTransform(phaseFloat, [0, 1, 2, 3], widths)

  const [activePhase, setActivePhase] = useState(0)
  useMotionValueEvent(phaseFloat, 'change', (v) => {
    const p = Math.min(PHASES - 1, Math.max(0, Math.floor(v)))
    setActivePhase((prev) => (prev === p ? prev : p))
  })

  // Gate Phase 1's scripted timeline on the card actually being pinned in
  // view — otherwise activePhase===0 on mount would play it before the user
  // ever scrolls to the section.
  const inView = useInView(cardRef, { amount: 0.6 })

  return (
    <section
      id="product"
      ref={sectionRef}
      className="hiw-section scroll-section"
      style={{ height: `calc(100vh * ${PHASES + 1})` }}
    >
      <div className="hiw-pin">
        <motion.div className="hiw-card" ref={cardRef} style={{ filter: cardFilterCss }}>
          <div className="hiw-noise" aria-hidden="true" />

          <div className="hiw-grid">
            {/* Left — demos (crossfade only, no slide) */}
            <div className="hiw-left">
              <PhaseDemo index={0} phaseFloat={phaseFloat}>
                <Phase1Conversational active={inView && activePhase === 0} />
              </PhaseDemo>
              <PhaseDemo index={1} phaseFloat={phaseFloat}>
                <Phase2Active active={inView && activePhase === 1} />
              </PhaseDemo>
              <PhaseDemo index={2} phaseFloat={phaseFloat}>
                <Phase3Agentic active={inView && activePhase === 2} />
              </PhaseDemo>
              <PhaseDemo index={3} phaseFloat={phaseFloat}>
                <Phase4Yours active={inView && activePhase === 3} />
              </PhaseDemo>
            </div>

            {/* Right — heading + paragraph (fade + vertical slide) */}
            <div className="hiw-right">
              <h2 className="hiw-h2">
                <span className="hiw-prism">prism</span>{' '}
                <motion.span className="hiw-suffix-slot" style={{ width: slotWidth }}>
                  <span className="hiw-suffix-measure" aria-hidden="true">
                    {SUFFIXES.map((s, i) => (
                      <span key={i} ref={(el) => (measureRefs.current[i] = el)}>
                        {s}
                      </span>
                    ))}
                  </span>
                  {SUFFIXES.map((s, i) => (
                    <PhaseText key={i} index={i} phaseFloat={phaseFloat} className="hiw-suffix">
                      {s}
                    </PhaseText>
                  ))}
                </motion.span>
              </h2>

              <div className="hiw-para-stack">
                {PARAGRAPHS.map((p, i) => (
                  <PhaseText key={i} index={i} phaseFloat={phaseFloat} className="hiw-para">
                    {p}
                  </PhaseText>
                ))}
              </div>
            </div>
          </div>

          <div className="hiw-dots" aria-hidden="true">
            {Array.from({ length: PHASES }).map((_, i) => (
              <span key={i} className={`hiw-dot${i === activePhase ? ' is-active' : ''}`} />
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}

// Opacity/translate ranges for a phase layer. First phase never fades in
// (visible from the top), last phase never fades out (stays through unpin).
function phaseRanges(i) {
  if (i === 0) {
    return { input: [0, 1 - TAU, 1], opacity: [1, 1, 0], y: [0, 0, -28] }
  }
  if (i === PHASES - 1) {
    return { input: [i - TAU, i, PHASES], opacity: [0, 1, 1], y: [28, 0, 0] }
  }
  return { input: [i - TAU, i, i + 1 - TAU, i + 1], opacity: [0, 1, 1, 0], y: [28, 0, 0, -28] }
}

// Left demo — opacity crossfade only (no translate, per spec).
function PhaseDemo({ index, phaseFloat, children }) {
  const r = phaseRanges(index)
  const opacity = useTransform(phaseFloat, r.input, r.opacity)
  return (
    <motion.div className="hiw-layer" style={{ opacity }}>
      {children}
    </motion.div>
  )
}

// Right text / header suffix — fade + vertical slide.
function PhaseText({ index, phaseFloat, className, children }) {
  const r = phaseRanges(index)
  const opacity = useTransform(phaseFloat, r.input, r.opacity)
  const y = useTransform(phaseFloat, r.input, r.y)
  return (
    <motion.span className={`hiw-text-layer ${className}`} style={{ opacity, y }}>
      {children}
    </motion.span>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Stacked fallback — narrow viewports + reduced motion. No pin, no
 * scrubbing; each phase is a normal block (demo over text), static.
 * ───────────────────────────────────────────────────────────────── */

function HowItWorksStacked() {
  const demos = [
    <Phase1Conversational key="0" active={false} staticMode />,
    <Phase2Active key="1" active={false} staticMode />,
    <Phase3Agentic key="2" active={false} staticMode />,
    <Phase4Yours key="3" active={false} staticMode />,
  ]
  return (
    <section id="product" className="hiw-section hiw-section-stacked scroll-section">
      {SUFFIXES.map((s, i) => (
        <div key={i} className="hiw-card hiw-card-stacked">
          <div className="hiw-noise" aria-hidden="true" />
          <div className="hiw-stacked-demo">{demos[i]}</div>
          <div className="hiw-right hiw-right-stacked">
            <h2 className="hiw-h2">
              <span className="hiw-prism">prism</span> <span className="hiw-suffix">{s}</span>
            </h2>
            {PARAGRAPHS[i] && <p className="hiw-para">{PARAGRAPHS[i]}</p>}
          </div>
        </div>
      ))}
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 1 — "prism is conversational"
 * Meet-flavored dark-grey call. Alex + Prism (center) + Jordan, symmetric
 * row. Scripted timeline gated on `active`: Prism springs into the middle
 * seat, then each Q&A turn zooms its speaker in place (others dim) with a
 * caption popup of what they're saying.
 * ───────────────────────────────────────────────────────────────── */

/* Caption keyword highlighting — each phase tints its key words a signature
 * color so the three scenes read differently even where the frame is similar:
 * Phase 1 cyan = retrieved facts (docs/memory), Phase 2 per-tool brand color =
 * the tool being driven, Phase 3 violet = delegated work / agents.
 * buildParts splits a caption into plain + highlighted segments. */
function buildParts(text, spans) {
  if (!spans || !spans.length) return [{ text }]
  const marks = []
  for (const [phrase, c] of spans) {
    const idx = text.indexOf(phrase)
    if (idx >= 0) marks.push({ idx, phrase, c })
  }
  marks.sort((a, b) => a.idx - b.idx)
  const parts = []
  let cur = 0
  for (const m of marks) {
    if (m.idx < cur) continue // skip overlaps
    if (m.idx > cur) parts.push({ text: text.slice(cur, m.idx) })
    parts.push({ text: m.phrase, c: m.c })
    cur = m.idx + m.phrase.length
  }
  if (cur < text.length) parts.push({ text: text.slice(cur) })
  return parts
}

// Build a focus entry. `phrases` items are a bare string (uses the curried
// `color`) or a [phrase, color] pair (Phase 2 overrides per tool).
const mkFocus = (color) => (who, label, text, phrases = []) => ({
  who,
  label,
  text,
  parts: buildParts(text, phrases.map((p) => (Array.isArray(p) ? p : [p, color]))),
})
const mkCyan = mkFocus('cyan')
const mkBrand = mkFocus(null) // Phase 2 — always pass explicit [phrase, color]
const mkViolet = mkFocus('violet')

// step → cumulative ms offset from activation.
const BEATS = [0, 700, 1700, 5200, 8000, 11400, 14000, 17600]

// Each scripted beat focuses one participant; the others dim. Step 2 is Prism's
// intro; 3–6 are the Q&A turns. Cyan highlights = the facts Prism pulls from
// docs/memory.
const FOCI = {
  2: mkCyan('prism', 'Prism', "Hi, I'm Prism — ask me anything from your docs or past meetings.", ['docs', 'past meetings']),
  3: mkCyan('alex', 'Alex', "Prism, what's the spec for the new onboarding flow?", ['spec', 'onboarding flow']),
  4: mkCyan('prism', 'Prism', 'Per the spec doc: email + SSO first, profile setup deferred to step 2.', ['spec doc', 'email + SSO', 'step 2']),
  5: mkCyan('jordan', 'Jordan', 'What did we decide about the mobile launch last week?', ['mobile launch', 'last week']),
  6: mkCyan('prism', 'Prism', 'You agreed to push v2 mobile to Q4 and ship onboarding first.', ['v2 mobile', 'Q4', 'onboarding']),
}

function Phase1Conversational({ active, staticMode = false }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (staticMode) return
    if (!active) {
      setStep(0)
      return
    }
    const timers = BEATS.map((t, i) => setTimeout(() => setStep(i), t))
    return () => timers.forEach(clearTimeout)
  }, [active, staticMode])

  const effStep = staticMode ? 1 : step
  const prismJoined = effStep >= 1
  const focus = staticMode ? null : FOCI[step] || null
  const activeWho = focus?.who || null
  const showPop = !staticMode

  return (
    <div className="hiw-meet">
      <div className="hiw-meet-stage">
        <div className="hiw-meet-tiles">
          <MeetTile
            name="Alex"
            initials="A"
            color="#a78bfa"
            layoutSlide
            active={activeWho === 'alex'}
            dimmed={!!activeWho && activeWho !== 'alex'}
          />
          <AnimatePresence>
            {prismJoined && (
              <MeetTile
                key="prism"
                name="Prism"
                initials="P"
                color="#22d3ee"
                isPrism
                popIn={showPop}
                active={activeWho === 'prism'}
                dimmed={!!activeWho && activeWho !== 'prism'}
              />
            )}
          </AnimatePresence>
          <MeetTile
            name="Jordan"
            initials="J"
            color="#f472b6"
            layoutSlide
            active={activeWho === 'jordan'}
            dimmed={!!activeWho && activeWho !== 'jordan'}
          />
        </div>

        {/* Caption — lower-third popup overlaying the video. The flex wrapper
            centers it so Framer's y/scale transform stays free for the pop. */}
        <div className="hiw-cap-wrap">
          <AnimatePresence mode="wait">
            {focus && (
              <Caption key={`cap-${effStep}`} text={focus.text} parts={focus.parts} label={focus.label} prism={focus.who === 'prism'} />
            )}
          </AnimatePresence>
        </div>

        <div className="hiw-meet-bar" aria-hidden="true">
          <span className="hiw-meet-ctrl" />
          <span className="hiw-meet-ctrl" />
          <span className="hiw-meet-ctrl hiw-meet-ctrl-end" />
        </div>
      </div>
    </div>
  )
}

// A camera tile. `layoutSlide` (Alex/Jordan only) lets them slide apart as
// Prism takes the center seat; Prism itself skips `layout` so its scale-pop
// entrance isn't swallowed by a layout transform. `active` zooms it forward;
// `dimmed` pushes the others back.
function MeetTile({ name, initials, color, isPrism = false, active = false, dimmed = false, popIn = false, layoutSlide = false }) {
  return (
    <motion.div
      layout={layoutSlide}
      className={`hiw-tile${isPrism ? ' is-prism' : ''}${active ? ' is-active' : ''}`}
      initial={popIn ? { opacity: 0, scale: 0.3 } : false}
      animate={{ opacity: dimmed ? 0.4 : 1, scale: active ? 1.14 : dimmed ? 0.95 : 1 }}
      /* Phase 1 motion signature — gentle, conversational push-in/pull-back
         (soft spring); the join pop keeps a bit more snap. */
      transition={{ type: 'spring', stiffness: popIn ? 300 : 210, damping: popIn ? 24 : 30 }}
      style={{ zIndex: active ? 5 : 1 }}
    >
      <div className="hiw-tile-avatar" style={{ background: color }}>
        {initials}
      </div>
      <span className="hiw-tile-name">
        {name}
        {isPrism && <span className="hiw-tile-listening">listening</span>}
      </span>
    </motion.div>
  )
}

// Caption popup with a smooth word-by-word reveal (each word fades up as its
// blur clears). `parts` carries per-segment highlight colors (see buildParts);
// falls back to the plain `text` when no parts are given.
function Caption({ text, parts, label, prism, animate = true }) {
  const segs = parts && parts.length ? parts : [{ text }]

  // Static mode (stacked / reduced-motion): render plainly, keeping highlights.
  if (!animate) {
    return (
      <div className={`hiw-cap${prism ? ' is-prism' : ''}`}>
        <span className="hiw-cap-label">{label}</span>
        <span className="hiw-cap-text">
          {segs.map((s, i) => (
            <span key={i} className={s.c ? `hl-${s.c}` : undefined}>
              {s.text}
            </span>
          ))}
        </span>
      </div>
    )
  }

  // Tokenize into words + whitespace, carrying each segment's color. Words
  // animate (blur-up); spaces stay static so punctuation/spacing is preserved
  // across highlight boundaries.
  const tokens = []
  segs.forEach((s) => {
    s.text.split(/(\s+)/).forEach((t) => {
      if (t) tokens.push({ t, c: s.c, space: /^\s+$/.test(t) })
    })
  })
  let wi = 0
  return (
    <motion.div
      className={`hiw-cap${prism ? ' is-prism' : ''}`}
      initial={{ opacity: 0, y: 12, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.97 }}
      transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
    >
      <span className="hiw-cap-label">{label}</span>
      <span className="hiw-cap-text">
        {tokens.map((tk, i) => {
          if (tk.space) return <span key={i} className="hiw-cap-sp">{tk.t}</span>
          const d = wi++
          return (
            <motion.span
              key={i}
              className={`hiw-cap-word${tk.c ? ' hl-' + tk.c : ''}`}
              initial={{ opacity: 0, filter: 'blur(5px)' }}
              animate={{ opacity: 1, filter: 'blur(0px)' }}
              transition={{ delay: 0.1 + d * 0.04, duration: 0.42, ease: 'easeOut' }}
            >
              {tk.t}
            </motion.span>
          )
        })}
      </span>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 2 — "prism is active"
 * Same Meet call as Phase 1, continued — but Prism is the persistent
 * focal tile (never shrinks). Humans give Prism commands; Prism executes
 * them and each completed tool call surfaces as a logo'd action chip
 * docked top-right of the frame. Chips for a multi-action command stack
 * and stay visible. Brand glyphs are lifted from IntegrationsModal.jsx.
 * ───────────────────────────────────────────────────────────────── */

// Brand glyphs + accent per integration. Gmail/Notion paths match the inline
// SVGs in IntegrationsModal.jsx; Asana (no repo SVG) is a three-dot mark.
const INTEGRATION_ICONS = {
  gmail: {
    label: 'Gmail',
    bg: '#EA4335',
    fg: '#ffffff',
    path: 'M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z',
  },
  notion: {
    label: 'Notion',
    bg: '#ffffff',
    fg: '#0b0b0b',
    path: 'M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.14c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z',
  },
  asana: {
    label: 'Asana',
    bg: '#F06A6A',
    fg: '#ffffff',
    // Three-dot Asana mark.
    circles: [
      { cx: 12, cy: 5.6, r: 3.4 },
      { cx: 5.9, cy: 16, r: 3.4 },
      { cx: 18.1, cy: 16, r: 3.4 },
    ],
  },
}

// Completed tool calls per integration (already-done state — no pending stage).
const ACTION_CHIPS = {
  gmail: { app: 'gmail', status: 'Email sent' },
  notion: { app: 'notion', status: 'Page created' },
  asana: { app: 'asana', status: 'Task created' },
}

// step → cumulative ms. The Asana chip (step 5) lands ~400ms after the Notion
// chip (step 4) so the two-action Q2 still reads as two distinct actions.
const BEATS2 = [0, 900, 4400, 8000, 11800, 12200, 15600]

// Caption per beat (mirrors Phase 1's FOCI). Steps 4 & 5 share Prism's reply
// so the caption holds steady while the second chip drops in. Highlights use
// each tool's brand color — the word lights up in the same color as the chip
// it fires (Gmail red, Notion white, Asana coral).
const FOCI2 = {
  1: mkBrand('alex', 'Alex', 'Prism, email the design team the onboarding recap.', [['email', 'gmail']]),
  2: mkBrand('prism', 'Prism', 'Done — sent it to the design team.', [['sent', 'gmail']]),
  3: mkBrand('jordan', 'Jordan', 'Draft a spec from this call in Notion and open a task to build the SSO flow.', [['Notion', 'notion'], ['task', 'asana']]),
  4: mkBrand('prism', 'Prism', 'On it — spec saved and the task is created.', [['spec saved', 'notion'], ['task', 'asana']]),
  5: mkBrand('prism', 'Prism', 'On it — spec saved and the task is created.', [['spec saved', 'notion'], ['task', 'asana']]),
}

// Which chips are on screen at each step. Chips clear when a human takes the
// turn (steps 1, 3) and accumulate while Prism acts (2; 4→5 stacks).
const CHIPS_AT = {
  2: ['gmail'],
  4: ['notion'],
  5: ['notion', 'asana'],
  6: ['notion', 'asana'],
}

function Phase2Active({ active, staticMode = false }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (staticMode) return
    if (!active) {
      setStep(0)
      return
    }
    const timers = BEATS2.map((t, i) => setTimeout(() => setStep(i), t))
    return () => timers.forEach(clearTimeout)
  }, [active, staticMode])

  // Static (stacked / reduced-motion) renders the settled final frame: both
  // tool calls done, both chips shown, Prism's confirmation caption present.
  const effStep = staticMode ? 5 : step

  const focus = FOCI2[effStep] || null
  const activeWho = focus?.who || null
  const chips = CHIPS_AT[effStep] || []

  return (
    <div className="hiw-meet hiw-meet-active">
      <div className="hiw-meet-stage">
        <div className="hiw-meet-tiles">
          <MeetTile2 name="Alex" initials="A" color="#a78bfa" active={activeWho === 'alex'} dimmed={!!activeWho && activeWho !== 'alex'} />
          <MeetTile2 name="Prism" initials="P" color="#22d3ee" isPrism firing={activeWho === 'prism'} />
          <MeetTile2 name="Jordan" initials="J" color="#f472b6" active={activeWho === 'jordan'} dimmed={!!activeWho && activeWho !== 'jordan'} />
        </div>

        {/* Action chips — overlay docked right beside Prism's tile so the
            actions read as firing out of Prism. Kept OUT of the caption's
            AnimatePresence (they coexist on Prism's turn) and NOT parented to
            the scaling Prism tile (a transform there would distort them).
            `layout` lets a landed chip slide to make room for the next. */}
        <div className="hiw-act-stack" aria-hidden="true">
          <AnimatePresence>
            {chips.map((key) => (
              <ActionChip key={key} chip={ACTION_CHIPS[key]} animate={!staticMode} />
            ))}
          </AnimatePresence>
        </div>

        {/* Caption — keyed by text so a repeated line (steps 4→5) doesn't
            remount mid-stack. */}
        <div className="hiw-cap-wrap">
          <AnimatePresence mode="wait">
            {focus && (
              <Caption
                key={`cap2-${focus.text}`}
                text={focus.text}
                parts={focus.parts}
                label={focus.label}
                prism={focus.who === 'prism'}
                animate={!staticMode}
              />
            )}
          </AnimatePresence>
        </div>

        <div className="hiw-meet-bar" aria-hidden="true">
          <span className="hiw-meet-ctrl" />
          <span className="hiw-meet-ctrl" />
          <span className="hiw-meet-ctrl hiw-meet-ctrl-end" />
        </div>
      </div>
    </div>
  )
}

// Phase-2 tile. Prism stays the focal point — always largest, never dimmed —
// but it visibly *pulses* bigger + glows brighter each time it fires an action
// (`firing`). The asking human pushes forward with a bouncy spring (a softer
// echo of Phase 1's camera-push) so the turn-taking still has give-and-take.
function MeetTile2({ name, initials, color, isPrism = false, active = false, dimmed = false, firing = false }) {
  const scale = isPrism ? (firing ? 1.34 : 1.18) : active ? 1.02 : 0.8
  const opacity = isPrism ? 1 : dimmed ? 0.4 : 1
  return (
    <motion.div
      className={`hiw-tile${isPrism ? ' is-prism is-active' : ''}${active && !isPrism ? ' is-active' : ''}${firing ? ' is-firing' : ''}`}
      animate={{ opacity, scale }}
      /* Phase 2 motion signature — short, punchy pulses (stiff/low-damping
         spring) so Prism "snaps" each time it fires an action. */
      transition={{ type: 'spring', stiffness: 460, damping: 16, mass: 0.6 }}
      style={{ zIndex: isPrism ? 5 : active ? 4 : 1 }}
    >
      <div className="hiw-tile-avatar" style={{ background: color }}>
        {initials}
      </div>
      <span className="hiw-tile-name">
        {name}
        {isPrism && <span className="hiw-tile-listening">acting</span>}
      </span>
    </motion.div>
  )
}

// A completed-action chip: brand glyph + app name + status + green check.
// Pops out of Prism (starts small + offset toward Prism, springs out with
// overshoot). `layout` lets an already-landed chip glide down as the next one
// arrives so the stack grows with motion, not a hard jump.
function ActionChip({ chip, animate = true }) {
  const icon = INTEGRATION_ICONS[chip.app]
  const motionProps = animate
    ? {
        layout: true,
        initial: { opacity: 0, scale: 0.4, x: -22, y: 6 },
        animate: { opacity: 1, scale: 1, x: 0, y: 0 },
        exit: { opacity: 0, scale: 0.6, transition: { duration: 0.18 } },
        transition: { type: 'spring', stiffness: 480, damping: 17, mass: 0.6 },
      }
    : {}
  return (
    <motion.div className="hiw-act-chip" {...motionProps}>
      <span className="hiw-act-icon" style={{ background: icon.bg, color: icon.fg }}>
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          {icon.circles
            ? icon.circles.map((c, i) => <circle key={i} cx={c.cx} cy={c.cy} r={c.r} />)
            : <path d={icon.path} />}
        </svg>
      </span>
      <span className="hiw-act-body">
        <span className="hiw-act-app">{icon.label}</span>
        <span className="hiw-act-status">
          {chip.status}
          <svg className="hiw-act-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </span>
      </span>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 3 — "prism is agentic"
 * Continues the Meet call: a human hands Prism a big build task; Prism
 * replies, the call dissolves, and we step into Prism's desktop
 * "playground" where it autonomously works across real tools
 * (Slack → Figma → editor → GitHub), spawning sub-agents. A top-right
 * activity panel shows the task list + nested spawned agents ticking off,
 * Claude-Code style. Mirrors Phase2Active's ({ active, staticMode }) contract.
 * ───────────────────────────────────────────────────────────────── */

// Desktop app glyphs. Slack path lifted from IntegrationsModal.jsx; GitHub is
// the simple-icons octocat; Figma/editor use a text glyph (the window title bar
// carries the brand name, so the tile only needs a colored accent). Kept apart
// from Phase 2's INTEGRATION_ICONS so that chip map stays untouched.
const SLACK_PATH =
  'M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z'
const GITHUB_PATH =
  'M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222 0 1.606-.014 2.898-.014 3.293 0 .322.216.694.825.576C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12'

const DESK_APPS = {
  slack: { label: 'Slack', accent: '#e01e5a', path: SLACK_PATH, fg: '#ffffff', bg: '#4A154B' },
  figma: { label: 'Figma', accent: '#F24E1E', glyph: 'F', fg: '#ffffff', bg: '#F24E1E' },
  editor: { label: 'workspace', accent: '#22d3ee', glyph: '⌘', fg: '#04181c', bg: '#22d3ee' },
  github: { label: 'GitHub', accent: '#e6edf3', path: GITHUB_PATH, fg: '#0d1117', bg: '#e6edf3' },
}

// step → cumulative ms. The opening is a tight single-Prism shot (no Meet grid
// replay), so the recap dissolves early (step 3 / 4s) and the desktop work owns
// ~70% of the ~13.6s band.
const BEATS3 = [0, 600, 2600, 4000, 5400, 7200, 9400, 11800, 13600]
const P3_FINAL = 8

// Meet-stage captions (steps before the dissolve). Violet highlights = the
// delegated work Prism is about to autonomously carry out.
const FOCI3 = {
  1: mkViolet('jordan', 'Jordan', 'Prism, build the new login flow from the spec in our notes.', ['build', 'login flow']),
  2: mkViolet('prism', 'Prism', 'On it — opening my workspace.', ['workspace']),
}

// Which windows are open at each step (array order = z-stack; last = front).
const WINS_AT = {
  3: [],
  4: ['slack'],
  5: ['slack', 'figma'],
  6: ['slack', 'figma', 'editor'],
  7: ['slack', 'figma', 'editor', 'github'],
  8: ['slack', 'figma', 'editor', 'github'],
}

// Streaming activity log — terminal-style feed. Each entry appears once its
// step is reached (`at` = effStep threshold); the feed accumulates as Prism
// works. `kind` drives the line glyph/color (run / spawn / done).
const P3_LOG = [
  { at: 3, kind: 'run', text: 'reading the request' },
  { at: 4, kind: 'done', text: 'read request · Slack' },
  { at: 5, kind: 'spawn', text: 'spawning design-agent' },
  { at: 5, kind: 'done', text: 'pulled design · Figma' },
  { at: 6, kind: 'spawn', text: 'spawning ui-agent · test-agent' },
  { at: 6, kind: 'run', text: 'building components' },
  { at: 7, kind: 'done', text: 'components built' },
  { at: 7, kind: 'done', text: 'opened pull request #42' },
  { at: 8, kind: 'done', text: 'done — login flow shipped' },
]

function Phase3Agentic({ active, staticMode = false }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (staticMode) return
    if (!active) {
      setStep(0)
      return
    }
    const timers = BEATS3.map((t, i) => setTimeout(() => setStep(i), t))
    return () => timers.forEach(clearTimeout)
  }, [active, staticMode])

  const effStep = staticMode ? P3_FINAL : step
  const stage = effStep >= 3 ? 'desk' : 'meet'
  const focus = stage === 'meet' ? FOCI3[effStep] || null : null
  const activeWho = focus?.who || null
  const windows = WINS_AT[effStep] || []
  const allDone = effStep >= P3_FINAL

  return (
    <div className="hiw-p3">
      <AnimatePresence>
        {stage === 'meet' ? (
          <motion.div
            key="meet"
            className="hiw-p3-stage hiw-p3-meet"
            initial={false}
            exit={staticMode ? undefined : { opacity: 0, scale: 1.04, filter: 'blur(6px)' }}
            transition={{ duration: 0.5, ease: 'easeInOut' }}
          >
            <div className="hiw-meet-stage">
              {/* Single-Prism opening — no Alex/Jordan grid (that would be a
                  third near-identical Meet scene). The team's command arrives
                  as the caption; only Prism is on screen, ready to act, before
                  it dissolves into the desktop. */}
              <div className="hiw-meet-tiles hiw-p3-solo">
                <MeetTile2 name="Prism" initials="P" color="#22d3ee" isPrism firing={activeWho === 'prism'} />
              </div>
              <div className="hiw-cap-wrap">
                <AnimatePresence mode="wait">
                  {focus && (
                    <Caption key={`cap3-${focus.text}`} text={focus.text} parts={focus.parts} label={focus.label} prism={focus.who === 'prism'} animate={!staticMode} />
                  )}
                </AnimatePresence>
              </div>
              <div className="hiw-meet-bar" aria-hidden="true">
                <span className="hiw-meet-ctrl" />
                <span className="hiw-meet-ctrl" />
                <span className="hiw-meet-ctrl hiw-meet-ctrl-end" />
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="desk"
            className="hiw-p3-stage hiw-desk"
            initial={staticMode ? false : { opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <div className="hiw-desk-bar" aria-hidden="true">
              <span className="hiw-desk-dot" />
              <span className="hiw-desk-menus" />
            </div>

            {/* Window stack — cascade with the newest in front, readable; older
                windows tuck behind dimmed. Each window is its own content node
                (safe to transform — no overlay children to distort). */}
            <div className="hiw-desk-windows">
              <AnimatePresence>
                {windows.map((appKey, i) => {
                  const depth = windows.length - 1 - i // 0 = frontmost
                  return (
                    <DeskWindow
                      key={appKey}
                      appKey={appKey}
                      depth={depth}
                      front={depth === 0}
                      running={!allDone && depth === 0}
                      animate={!staticMode}
                    />
                  )
                })}
              </AnimatePresence>
            </div>

            {/* Activity log — reserved top-right lane (own overlay layer). */}
            <LogFeed step={effStep} done={allDone} animate={!staticMode} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// A cascaded desktop window: chrome (traffic lights + brand dot + title) over
// app-specific stylized content. `depth` drives the behind-stacking; `front`
// gets full opacity + a cyan focus ring.
function DeskWindow({ appKey, depth, front, running, animate = true }) {
  const app = DESK_APPS[appKey]
  const motionProps = animate
    ? {
        initial: { opacity: 0, scale: 0.92, y: 14 },
        animate: {
          opacity: depth > 2 ? 0 : 1 - depth * 0.22,
          scale: 1 - depth * 0.05,
          x: -depth * 22,
          y: -depth * 17,
        },
        exit: { opacity: 0, scale: 0.94, transition: { duration: 0.16 } },
        /* Phase 3 motion signature — snappy, mechanical window entrances
           (stiff spring, low mass) to read as machine work, paired with the
           streaming log. */
        transition: { type: 'spring', stiffness: 420, damping: 24, mass: 0.6 },
      }
    : {
        style: {
          opacity: depth > 2 ? 0 : 1 - depth * 0.22,
          transform: `translate(${-depth * 22}px, ${-depth * 17}px) scale(${1 - depth * 0.05})`,
        },
      }
  return (
    <motion.div className={`hiw-win${front ? ' is-front' : ''}`} style={{ zIndex: 10 - depth }} {...motionProps}>
      <div className="hiw-win-bar">
        <span className="hiw-win-lights" aria-hidden="true">
          <i /><i /><i />
        </span>
        <span className="hiw-win-title">
          <span className="hiw-win-ico" style={{ background: app.bg, color: app.fg }}>
            {app.path ? (
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d={app.path} /></svg>
            ) : (
              <b>{app.glyph}</b>
            )}
          </span>
          {app.label}
        </span>
      </div>
      <div className={`hiw-win-body hiw-win-${appKey}`}>
        <DeskWindowBody appKey={appKey} running={running} animate={animate} />
      </div>
    </motion.div>
  )
}

function DeskWindowBody({ appKey, running, animate }) {
  if (appKey === 'slack') {
    return (
      <div className="hiw-slack">
        <div className="hiw-slack-head"># product</div>
        <div className="hiw-slack-msg">
          <span className="hiw-slack-av" style={{ background: '#a78bfa' }} />
          <span className="hiw-slack-lines"><i style={{ width: '34%' }} /><i style={{ width: '78%' }} /></span>
        </div>
        <div className="hiw-slack-msg is-ask">
          <span className="hiw-slack-av" style={{ background: '#f472b6' }} />
          <span className="hiw-slack-lines"><i style={{ width: '40%' }} /><i style={{ width: '90%' }} /><i style={{ width: '64%' }} /></span>
        </div>
      </div>
    )
  }
  if (appKey === 'figma') {
    return (
      <div className="hiw-figma">
        <div className="hiw-figma-frame">
          <span className="hiw-figma-rect" style={{ top: '12%', left: '10%', width: '80%', height: '18%' }} />
          <span className="hiw-figma-rect" style={{ top: '38%', left: '10%', width: '52%', height: '12%' }} />
          <span className="hiw-figma-rect" style={{ top: '38%', left: '66%', width: '24%', height: '12%' }} />
          <span className="hiw-figma-rect is-accent" style={{ top: '60%', left: '10%', width: '80%', height: '16%' }} />
        </div>
      </div>
    )
  }
  if (appKey === 'editor') {
    const lines = [
      [['kw', 18], ['fn', 30], ['pl', 12]],
      [['pl', 10], ['st', 40], ['pl', 16]],
      [['kw', 14], ['var', 26], ['pl', 20], ['num', 8]],
      [['pl', 22], ['fn', 34]],
      [['kw', 16], ['var', 22], ['st', 30]],
    ]
    return (
      <div className="hiw-editor">
        <div className="hiw-editor-rail" aria-hidden="true"><i /><i /><i className="is-on" /><i /></div>
        <div className="hiw-editor-code">
          {lines.map((toks, li) => (
            <div className="hiw-code-line" key={li} style={animate ? { animationDelay: `${li * 140}ms` } : undefined}>
              {toks.map(([cls, w], ti) => (
                <span key={ti} className={`hiw-tok hiw-tok-${cls}`} style={{ width: `${w}px` }} />
              ))}
            </div>
          ))}
          {running && <span className="hiw-code-caret" />}
        </div>
      </div>
    )
  }
  // github
  return (
    <div className="hiw-gh">
      <div className="hiw-gh-head">
        <span className="hiw-gh-title">Add login flow</span>
        <span className="hiw-gh-num">#42</span>
        <span className="hiw-gh-pill">Open</span>
      </div>
      <div className="hiw-gh-meta"><span className="hiw-gh-branch">prism:login-flow → main</span></div>
      <div className="hiw-gh-diff">
        <span className="hiw-gh-add" style={{ width: '64%' }} />
        <span className="hiw-gh-add" style={{ width: '40%' }} />
        <span className="hiw-gh-del" style={{ width: '22%' }} />
        <span className="hiw-gh-add" style={{ width: '52%' }} />
      </div>
    </div>
  )
}

// Activity log — terminal-style streaming feed. Lines accumulate as the step
// advances; the latest non-final line trails a blinking caret to read as live.
const LOG_GLYPH = { done: '✓', spawn: '↳', run: '▸' }

function LogFeed({ step, done, animate = true }) {
  const lines = P3_LOG.filter((l) => l.at <= step)
  return (
    <motion.div
      className="hiw-log"
      initial={animate ? { opacity: 0, x: 12 } : false}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <div className="hiw-log-head">
        <span className={`hiw-log-orb${done ? ' is-done' : ''}`} />
        <span className="hiw-log-title">prism · activity</span>
      </div>
      <div className="hiw-log-body">
        <AnimatePresence initial={false}>
          {lines.map((l, i) => (
            <motion.div
              key={`${l.at}-${i}`}
              className={`hiw-log-line is-${l.kind}`}
              initial={animate ? { opacity: 0, y: 5 } : false}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.26, ease: 'easeOut' }}
            >
              <span className="hiw-log-glyph">{LOG_GLYPH[l.kind]}</span>
              <span className="hiw-log-text">{l.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
        {!done && <span className="hiw-log-caret" aria-hidden="true" />}
      </div>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 4 — "prism is yours"
 * The closer. One PrismAI app window with a persistent mini left sidebar;
 * an animated fake cursor takes a guided tour across five product
 * surfaces (command center → meeting → trends → knowledge → personas),
 * clicking sidebar items + cards. The app UI stays cyan (authentic to
 * the real product); the tour layer — cursor, click ripple, per-screen
 * section label — is warm amber, Phase 4's signature color. Motion
 * signature: a calm, deliberate soft spring, distinct from P1 gentle /
 * P2 punchy / P3 snappy. Mirrors Phase3Agentic's ({ active, staticMode }).
 * ───────────────────────────────────────────────────────────────── */

// Screens in tour order. `nav` = which sidebar item lights; `label` = the
// amber section-name pill. The "meeting" + "trends" screens are reached from
// within the content area (a meeting card / the insights icon), so the Home
// nav item stays lit for them.
const P4_SCREENS = [
  { key: 'home', nav: 'home', label: 'Command center' },
  { key: 'meeting', nav: 'home', label: 'Meeting' },
  { key: 'trends', nav: 'home', label: 'Trends' },
  { key: 'knowledge', nav: 'knowledge', label: 'Knowledge base' },
  { key: 'personas', nav: 'personas', label: 'Personas' },
]

// step → cumulative ms from activation. Each target gets a glide beat (cursor
// travels in) then a click beat (ripple over the still-visible target). The
// destination screen is revealed on the *following* beat — kept short (~420ms
// after the click) so the navigation feels responsive, not laggy. Glide+click
// pairs run ~1080ms. The final gap (step 9→10) is the long one on purpose: the
// Personas screen breathes for ~2.4s before the Wise-veteran card is selected —
// the emotional landing.
const BEATS4 = [0, 950, 2000, 2420, 3500, 3920, 5000, 5420, 6500, 6920, 9320]
const P4_FINAL = BEATS4.length - 1

// step → screen index. The screen lags one beat behind the click so the click
// fires while its target is still on screen, then the next beat crossfades to
// the destination (e.g. click the insights icon on Meeting → Trends appears).
// The reveal beat sits only ~420ms after the click (see BEATS4) so the swap
// reads as a snappy nav. Beats per screen: home 0-2, meeting 3-4, trends 5-6,
// knowledge 7-8, personas 9-10.
const P4_SCREEN_AT = [0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]

// step → cursor tip position as % of the frame (overlay = frame, so % places
// the tip directly; the cursor SVG is drawn tip-at-0,0 — no translate needed).
// Coordinates are the cursor TIP (top-left of the arrow) as % of the frame,
// measured against the live DOM centers of each target so the tip lands on the
// thing it clicks (the previous eyeballed values sat ~10% low on the nav rail —
// the "click Knowledge" beat had the tip resting on the Personas row).
const P4_CURSOR = [
  { x: 52, y: 46 }, // 0  home settles
  { x: 56, y: 32 }, // 1  glide to a meeting card (middle card @ 63,35)
  { x: 56, y: 32 }, // 2  click card → meeting
  { x: 94, y: 8 },  // 3  glide to the insights icon (@ 96,7)
  { x: 94, y: 8 },  // 4  click insights → trends
  { x: 11, y: 22 }, // 5  glide to Knowledge nav (@ 13,23)
  { x: 11, y: 22 }, // 6  click Knowledge
  { x: 11, y: 30 }, // 7  glide to Personas nav (@ 13,32)
  { x: 11, y: 30 }, // 8  click Personas
  { x: 78, y: 44 }, // 9  glide to the "Wise veteran" behavior card (@ 81,46)
  { x: 78, y: 44 }, // 10 click → select persona (closer)
]

// Steps where the cursor clicks (ripple fires + the screen/selection changes).
const P4_CLICK_STEPS = new Set([2, 4, 6, 8, 10])

// Sidebar nav items (mini rail). `home` is pinned active for the first three
// screens; Knowledge/Personas light when their screen is reached.
const P4_NAV = [
  { key: 'home', label: 'Home' },
  { key: 'knowledge', label: 'Knowledge' },
  { key: 'personas', label: 'Personas' },
]

// Stroke-glyph paths for the rail + insights icon (lucide-style, fill:none).
const P4_GLYPH = {
  home: 'M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  knowledge: 'M4 19V5a1 1 0 0 1 1-1h10a3 3 0 0 1 3 3v12M4 19a2 2 0 0 0 2 2h12M4 19a2 2 0 0 1 2-2h12',
  personas: 'M16 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 20v-1a4 4 0 0 0-3-3.85',
  insights: 'm12 3 2.1 6.3L20.5 9l-5 3.9 1.9 6.1L12 15.3 6.6 19l1.9-6.1-5-3.9 6.4.3z',
}

const P4_DOCS = [
  { name: 'Onboarding spec', kind: 'file', status: 'ready', pill: 'Internal', tone: 'emerald' },
  { name: 'Q4 roadmap', kind: 'file', status: 'ready', pill: 'Team', tone: 'sky' },
  { name: 'Customer notes', kind: 'globe', status: 'processing', pill: 'Sensitive', tone: 'rose' },
  { name: 'Brand guide', kind: 'file', status: 'ready', pill: 'Public', tone: 'emerald' },
]

const P4_PERSONAS = ['Smart intern', 'Wise veteran', 'Friendly PM', 'Straight shooter']
const P4_VOICES = ['Calm', 'Warm', 'Crisp', 'Bold']

// Catmull-Rom → cubic-Bézier smoothing so the Trends sparkline reads as a fluid
// curve instead of a cheap jagged polyline. pts = [[x,y]…] in viewBox units.
function smoothLine(pts) {
  if (pts.length < 2) return ''
  const d = [`M ${pts[0][0]} ${pts[0][1]}`]
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] || p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d.push(`C ${c1x} ${c1y} ${c2x} ${c2y} ${p2[0]} ${p2[1]}`)
  }
  return d.join(' ')
}
// Data inset from the viewBox edges (x 2→97, y 4→30 of 0,0,100,36) so the round
// caps + endpoint dot sit inside the frame rather than clipping at the border.
const P4_SPARK_PATH = smoothLine([[2, 30], [16, 23], [30, 26], [44, 15], [58, 18], [72, 8], [86, 11], [97, 4]])

function Phase4Yours({ active, staticMode = false }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (staticMode) return
    if (!active) {
      setStep(0)
      return
    }
    const timers = BEATS4.map((t, i) => setTimeout(() => setStep(i), t))
    return () => timers.forEach(clearTimeout)
  }, [active, staticMode])

  const effStep = staticMode ? P4_FINAL : step

  const screenIndex = P4_SCREEN_AT[effStep]
  const screen = P4_SCREENS[screenIndex]
  const cursor = P4_CURSOR[effStep]
  const clicking = !staticMode && P4_CLICK_STEPS.has(effStep)
  // One behavior card starts selected; the final click moves the selection to
  // the cursor's target (the "make it yours" beat).
  const selectedPersona = effStep >= P4_FINAL ? 1 : 0
  const animate = !staticMode

  const ScreenBody = { home: P4Home, meeting: P4Meeting, trends: P4Trends, knowledge: P4Knowledge, personas: P4Personas }[screen.key]

  return (
    <div className="hiw-p4">
      <div className="hiw-win-bar hiw-p4-bar">
        <span className="hiw-win-lights" aria-hidden="true"><i /><i /><i /></span>
        <span className="hiw-p4-bar-dot" aria-hidden="true" />
      </div>

      <div className="hiw-p4-body">
        {/* Persistent mini sidebar — only the active item lights per step. */}
        <div className="hiw-p4-rail" aria-hidden="true">
          <div className="hiw-p4-ws">
            <span className="hiw-p4-ws-sq">P</span>
            <span className="hiw-p4-bar-line" style={{ width: '54%' }} />
          </div>
          <div className="hiw-p4-rail-nav">
            {P4_NAV.map((item) => (
              <div key={item.key} className={`hiw-p4-rail-item${screen.nav === item.key ? ' is-active' : ''}`}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d={P4_GLYPH[item.key]} />
                </svg>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          <div className="hiw-p4-rail-section">Meetings</div>
          <div className="hiw-p4-rail-list">
            {[0.7, 0.5, 0.62, 0.44].map((w, i) => (
              <div key={i} className="hiw-p4-rail-mtg">
                <span className="hiw-p4-rail-dot" />
                <span className="hiw-p4-bar-line" style={{ width: `${w * 100}%` }} />
              </div>
            ))}
          </div>
        </div>

        {/* Content area — screens crossfade here, keyed by string id so a
            screen spanning two steps doesn't remount. */}
        <div className="hiw-p4-content">
          <AnimatePresence initial={false}>
            <motion.div
              key={screen.key}
              className="hiw-p4-screen"
              initial={animate ? { opacity: 0 } : false}
              animate={{ opacity: 1 }}
              exit={animate ? { opacity: 0 } : undefined}
              transition={{ duration: 0.3, ease: 'easeInOut' }}
            >
              <ScreenBody selectedPersona={selectedPersona} animate={animate} />
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Tour layer (amber) — cursor + ripple + section label. Own absolute
            overlay, sibling of content (never a child of a scaling node). */}
        <div className="hiw-p4-tour" aria-hidden="true">
          <AnimatePresence mode="wait">
            <motion.span
              key={screen.label}
              className="hiw-p4-label"
              initial={animate ? { opacity: 0, y: 6 } : false}
              animate={{ opacity: 1, y: 0 }}
              exit={animate ? { opacity: 0, y: -6 } : undefined}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            >
              {screen.label}
            </motion.span>
          </AnimatePresence>

          {clicking && (
            <span className="hiw-p4-ripple-wrap" style={{ left: `${cursor.x}%`, top: `${cursor.y}%` }}>
              <motion.span
                key={effStep}
                className="hiw-p4-ripple"
                initial={{ opacity: 0.7, scale: 0.3 }}
                animate={{ opacity: 0, scale: 1.9 }}
                transition={{ duration: 0.55, ease: 'easeOut' }}
              />
            </span>
          )}

          {animate && (
            <motion.span
              className="hiw-p4-cursor"
              initial={false}
              animate={{ left: `${cursor.x}%`, top: `${cursor.y}%`, scale: clicking ? 0.86 : 1 }}
              /* Phase 4 motion signature — calm, deliberate soft spring. */
              transition={{ left: { type: 'spring', stiffness: 170, damping: 26 }, top: { type: 'spring', stiffness: 170, damping: 26 }, scale: { duration: 0.16 } }}
            >
              <svg viewBox="0 0 14 18" fill="none">
                <path d="M0 0 L0 14 L3.6 10.6 L6.2 16.4 L8.2 15.5 L5.6 9.7 L10.4 9.7 Z" fill="#fbbf24" stroke="#1a1205" strokeWidth="0.9" strokeLinejoin="round" />
              </svg>
            </motion.span>
          )}
        </div>
      </div>
    </div>
  )
}

// Insights icon (top-right of Home/Meeting) — the cursor's route into Trends.
function P4Insights() {
  return (
    <span className="hiw-p4-insights">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d={P4_GLYPH.insights} />
      </svg>
    </span>
  )
}

function P4Home() {
  return (
    <div className="hiw-p4-home">
      <div className="hiw-p4-head">
        <div className="hiw-p4-head-text">
          <span className="hiw-p4-eyebrow">Command center</span>
          <span className="hiw-p4-bar-line is-title" style={{ width: '46%' }} />
        </div>
        <P4Insights />
      </div>
      <div className="hiw-p4-mtgs">
        {[
          { band: 'good', title: 'Q2 Planning Sync', v: 70 },
          { band: 'mid', title: 'Design Review', v: 52 },
          { band: 'good', title: 'Customer Call — Acme', v: 64 },
        ].map((m, i) => (
          <div key={i} className="hiw-p4-mtgcard">
            <span className={`hiw-p4-band is-${m.band}`} />
            <div className="hiw-p4-mtgcard-body">
              <span className="hiw-p4-mtg-title">{m.title}</span>
              <span className="hiw-p4-bar-line is-verdict" style={{ width: `${m.v}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function P4Meeting() {
  return (
    <div className="hiw-p4-meeting">
      <div className="hiw-p4-head">
        <div className="hiw-p4-head-text">
          <span className="hiw-p4-eyebrow">Meeting</span>
          <span className="hiw-p4-bar-line is-title" style={{ width: '52%' }} />
        </div>
        <P4Insights />
      </div>
      <div className="hiw-p4-meeting-grid">
        <div className="hiw-p4-gauge">
          <svg viewBox="0 0 80 44" className="hiw-p4-gauge-arc">
            <path d="M6 42 A34 34 0 0 1 74 42" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="7" strokeLinecap="round" />
            <path d="M6 42 A34 34 0 0 1 67 20" fill="none" stroke="#22d3ee" strokeWidth="7" strokeLinecap="round" />
          </svg>
          <span className="hiw-p4-gauge-num">82</span>
        </div>
        <div className="hiw-p4-breakdown">
          <span className="hiw-p4-bk-title">Healthy &amp; on track</span>
          <span className="hiw-p4-bar-line is-faint" style={{ width: '44%' }} />
        </div>
      </div>
      <div className="hiw-p4-actions">
        {[
          { done: true, text: 'Ship onboarding fix' },
          { done: false, text: 'Draft Q4 roadmap' },
          { done: false, text: 'Sync with design' },
        ].map((a, i) => (
          <div key={i} className="hiw-p4-action">
            <span className={`hiw-p4-check${a.done ? ' is-done' : ''}`} />
            <span className={`hiw-p4-action-text${a.done ? ' is-done' : ''}`}>{a.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function P4Trends() {
  return (
    <div className="hiw-p4-trends">
      <div className="hiw-p4-head">
        <div className="hiw-p4-head-text">
          <span className="hiw-p4-eyebrow">Trends</span>
          <span className="hiw-p4-bar-line is-title" style={{ width: '44%' }} />
        </div>
      </div>
      <div className="hiw-p4-spark">
        <svg viewBox="0 0 100 36" preserveAspectRatio="none" className="hiw-p4-spark-svg">
          <defs>
            <linearGradient id="hiwP4Spark" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#0891b2" />
              <stop offset="1" stopColor="#67e8f9" />
            </linearGradient>
          </defs>
          <path d={P4_SPARK_PATH} fill="none" stroke="url(#hiwP4Spark)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <span className="hiw-p4-spark-dot" />
      </div>
      <div className="hiw-p4-patterns">
        <div className="hiw-p4-pattern">
          <span className="hiw-p4-eyebrow is-dim">Owner load</span>
          {[78, 54, 40].map((w, i) => (
            <div key={i} className="hiw-p4-meter is-violet"><span className="hiw-p4-meter-fill" style={{ width: `${w}%` }} /></div>
          ))}
        </div>
      </div>
    </div>
  )
}

function P4Knowledge() {
  return (
    <div className="hiw-p4-knowledge">
      <div className="hiw-p4-head">
        <div className="hiw-p4-head-text">
          <span className="hiw-p4-eyebrow">Knowledge base</span>
          <span className="hiw-p4-bar-line is-title" style={{ width: '40%' }} />
        </div>
        <span className="hiw-p4-add">+ Add document</span>
      </div>
      <div className="hiw-p4-docs">
        {P4_DOCS.map((d, i) => (
          <div key={i} className="hiw-p4-doc">
            <span className="hiw-p4-doc-ico">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                {d.kind === 'globe' ? (
                  <>
                    <circle cx="12" cy="12" r="9" />
                    <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
                  </>
                ) : (
                  <>
                    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
                    <path d="M14 3v5h5" />
                  </>
                )}
              </svg>
            </span>
            <span className="hiw-p4-doc-name">{d.name}</span>
            <span className="hiw-p4-doc-foot">
              <span className={`hiw-p4-dot is-${d.status}`} />
              <span className={`hiw-p4-pill is-${d.tone}`} />
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function P4Personas({ selectedPersona }) {
  return (
    <div className="hiw-p4-personas">
      <div className="hiw-p4-head">
        <div className="hiw-p4-head-text">
          <span className="hiw-p4-eyebrow">Personas</span>
          <span className="hiw-p4-bar-line is-title" style={{ width: '38%' }} />
        </div>
      </div>

      <div className="hiw-p4-row">
        <span className="hiw-p4-row-label">Voice</span>
        <div className="hiw-p4-voices">
          {P4_VOICES.map((v, i) => (
            <span key={v} className={`hiw-p4-voice${i === 0 ? ' is-on' : ''}`}>{v}</span>
          ))}
        </div>
      </div>

      <div className="hiw-p4-row is-behavior">
        <span className="hiw-p4-row-label">Behavior</span>
        <div className="hiw-p4-persona-grid">
          {P4_PERSONAS.map((p, i) => (
            <div key={p} className={`hiw-p4-persona${i === selectedPersona ? ' is-sel' : ''}`}>
              <span className="hiw-p4-persona-av" />
              <span className="hiw-p4-persona-name">{p}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

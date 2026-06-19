import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  AlertTriangle,
  CalendarPlus,
  CheckCircle2,
  Check,
  FileCheck2,
  Lock,
  RotateCcw,
  Send,
  Users,
  Video,
  Wifi,
  X,
} from 'lucide-react'

// Leading icon for a transient notification, by `kind` (see lib/statusNotify).
const NOTIFY_ICONS = {
  success: CheckCircle2,
  bot: Video,
  calendar: CalendarPlus,
  send: Send,
  doc: FileCheck2,
  team: Users,
  reconnect: Wifi,
}

// Sunburst spinner — a ring of 12 short tapered rays (per the reference image),
// rendered white and spun steadily. Replaces the lucide Loader2 for Analysing.
function Sunburst({ spin }) {
  const rays = Array.from({ length: 12 })
  return (
    <svg
      viewBox="0 0 24 24"
      className={`status-island-glow-white h-[23px] w-[23px] ${spin ? 'animate-spin' : ''}`}
      aria-hidden="true"
    >
      {rays.map((_, i) => (
        <line
          key={i}
          x1="12"
          y1="1.8"
          x2="12"
          y2="7.8"
          stroke="#ffffff"
          strokeWidth="2.6"
          strokeLinecap="round"
          transform={`rotate(${i * 30} 12 12)`}
        />
      ))}
    </svg>
  )
}

/**
 * StatusIsland — a bespoke Dynamic-Island-style status pill for the center of
 * the dashboard topbar. It is a *dumb renderer*: the active state is derived
 * upstream (see `deriveStatus` in DashboardPage) and handed down as a single
 * `status = { state, detail }` prop.
 *
 * States: live | analysing | analysed | shared | notify | error | idle.
 *
 * Motion model (locked in the plan):
 *  - Default is a small "tiny" pill. The "pop" is the tiny -> enlarged spring.
 *  - A new state pops only if currently tiny. If already enlarged, the content
 *    cross-fades (no re-pop). Width is `layout`-animated, so an enlarged->enlarged
 *    content swap that keeps a similar width reads as a swap, not a pop.
 *  - live / shared stay enlarged & persistent.
 *  - analysed pops, then auto-collapses to a neutral tiny pill after a beat;
 *    hovering re-expands it (mouse-leave collapses again).
 *  - Live -> Analysing -> Analysed is one continuous enlarged run (all three want
 *    enlarged, so it pops once and swaps through), then analysed auto-collapses.
 *  - idle is a neutral tiny pill (identical to collapsed-analysed).
 *
 * Per-state colors / final visuals are intentionally placeholder here — the user
 * supplies those state-by-state in Step 2. Keep the chrome neutral for now.
 */

const AUTO_COLLAPSE_MS = 3500

// Per-state content descriptors. `kind` selects the leading icon; `tone` drives
// the text color. Sub-details (time, sharer) slot in via `detail`, separated by a
// plain gap (no middle dot). Spinner needs the `spin` flag so it's built in JSX.
function renderState(state, detail, notifyKind) {
  // `attachLabel` keeps the label glued to the icon inside the tight cluster, so
  // the wide separator gap lands AFTER the label (used by live: "● Live" ··· time).
  // Otherwise the cluster is just the icon and the gap lands before the label.
  switch (state) {
    case 'live':
      // Red dot + red "Live" stay together; the time reads white after the gap.
      return { kind: 'live', label: 'Live', detail: detail || null, tone: 'red', detailTone: 'white', attachLabel: true }
    case 'analysing':
      return { kind: 'spinner', label: 'Analysing', detail: null, tone: 'white' }
    case 'analysed':
      // White label, cyan tick (handled by `kind`).
      return { kind: 'check', label: 'Analysed', detail: null, tone: 'white' }
    case 'shared':
      // Single phrase, tight to the lock (no separator gap): "Shared by Alex".
      return { kind: 'lock', label: detail ? `Shared ${detail}` : 'Shared', detail: null, tone: 'white', attachLabel: true }
    case 'notify':
      // Transient toast: notify icon (by kind) + the message, glued together.
      return { kind: 'notify', notifyKind: notifyKind || 'success', label: detail || '', detail: null, tone: 'white', attachLabel: true }
    default:
      return null // idle -> neutral tiny pill, no content
  }
}

const TONE_TEXT = {
  red: 'text-rose-400',
  white: 'text-white/95',
}

// Enter/exit "pop" — a uniform scale + fade so the enlarged pill scales down
// cleanly into the tiny pill (and vice-versa). No width morph = no warp.
const POP_SPRING = { type: 'spring', stiffness: 480, damping: 32, mass: 0.7 }

// The inner cluster of an enlarged pill (icon + label[s]), with a keyed crossfade
// so live→analysing→analysed swaps the content without re-popping the shell.
// Shared by the desktop in-cell pill and the mobile portal overlay.
function PillContent({ state, content, reduce }) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={state}
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={reduce ? { duration: 0 } : { duration: 0.12, ease: 'easeOut' }}
        className="flex items-center gap-2.5"
      >
        {/* icon cluster (kept tight); label tags along only when attachLabel */}
        <span className="flex items-center gap-2">
          {content.kind === 'live' ? (
            <span className="status-island-livedot relative h-3 w-3 shrink-0 rounded-full bg-rose-500" aria-hidden="true" />
          ) : content.kind === 'spinner' ? (
            <Sunburst spin={!reduce} />
          ) : content.kind === 'check' ? (
            <Check className="status-island-glow-cyan h-[23px] w-[23px] shrink-0 text-cyan-400" strokeWidth={3} aria-hidden="true" />
          ) : content.kind === 'lock' ? (
            <Lock className="status-island-glow-white h-[21px] w-[21px] shrink-0 text-white/95" aria-hidden="true" />
          ) : content.kind === 'notify' ? (
            (() => {
              const NotifyIcon = NOTIFY_ICONS[content.notifyKind] || NOTIFY_ICONS.success
              return <NotifyIcon className="status-island-glow-cyan h-[20px] w-[20px] shrink-0 text-cyan-300" strokeWidth={2.4} aria-hidden="true" />
            })()
          ) : null}
          {content.attachLabel ? (
            <span className={`truncate text-[17px] font-bold leading-none tracking-[-0.01em] ${TONE_TEXT[content.tone] || TONE_TEXT.white}`}>
              {content.label}
            </span>
          ) : null}
        </span>
        {/* the wide gap lands here, between the icon cluster and the trailing text */}
        {(content.attachLabel ? content.detail : content.label) ? (
          <span className={`ml-3 truncate text-[17px] font-bold leading-none tracking-[-0.01em] ${TONE_TEXT[(content.attachLabel ? content.detailTone : content.tone) || content.tone] || TONE_TEXT.white}`}>
            {content.attachLabel ? content.detail : content.label}
          </span>
        ) : null}
      </motion.div>
    </AnimatePresence>
  )
}

// Mobile (per the plan): no idle pill, no spring "pop" — active states fade in/out
// fast and may sit over content. Desktop keeps the tiny idle capsule + spring pop.
function useIsMobile() {
  const [mobile, setMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 640px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const onChange = (e) => setMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

export default function StatusIsland({ status }) {
  const reduce = useReducedMotion()
  const mobile = useIsMobile()
  // `flat` collapses the spring/scale pop to a plain fade — for reduced-motion
  // users AND on mobile (fast fade overlay, no pop).
  const flat = reduce || mobile

  const effective = status || { state: 'idle' }
  const { state, detail } = effective
  const isError = state === 'error'

  // analysed auto-collapse: once analysed lands, start a one-shot timer to drop
  // back to the tiny neutral pill. The timer does NOT reset on a same-state swap.
  const [analysedCollapsed, setAnalysedCollapsed] = useState(false)
  const [hovered, setHovered] = useState(false)
  const wasAnalysed = useRef(false)

  useEffect(() => {
    if (state === 'analysed') {
      if (!wasAnalysed.current) {
        // First entry into analysed (from a different state): arm the collapse.
        wasAnalysed.current = true
        setAnalysedCollapsed(false)
        const t = setTimeout(() => setAnalysedCollapsed(true), AUTO_COLLAPSE_MS)
        return () => clearTimeout(t)
      }
      // Same-state swap while still analysed: leave the running timer alone.
      return undefined
    }
    // Left analysed entirely: reset so the next entry re-arms.
    wasAnalysed.current = false
    setAnalysedCollapsed(false)
    return undefined
  }, [state])

  // Which states want the enlarged form. analysed only until it auto-collapses,
  // with hover overriding the collapse.
  const baseExpanded =
    state === 'live' || state === 'analysing' || state === 'shared' || state === 'notify'
      ? true
      : state === 'analysed'
        ? !analysedCollapsed
        : false
  const expanded = baseExpanded || (hovered && state === 'analysed')

  const content = renderState(state, detail, effective.kind)
  const popTransition = reduce
    ? { duration: 0 }
    : mobile
      ? { duration: 0.16, ease: 'easeOut' } // fast fade overlay on mobile
      : POP_SPRING

  // Desktop pills are absolutely centered within the 72px topbar cell.
  const pillStyle = { left: '50%', top: '50%' }

  // MOBILE: the topbar's center cell is squeezed hard to the right (title + search
  // eat the row) AND it sits inside a transformed ancestor, so neither in-cell
  // absolute nor `position:fixed` lands on the true viewport center. Per the plan,
  // mobile is an overlay that may sit on top of content — so portal it to <body>
  // (escaping the transformed ancestor) and flex-center on the real viewport. No
  // idle pill, opacity-only fade, max-width so the interactive error pill never
  // pushes its Retry/Dismiss buttons off-screen.
  if (mobile) {
    let node = null
    if (isError) {
      node = <ErrorPill key="error" detail={detail} onRetry={effective.onRetry} onDismiss={effective.onDismiss} reduce={reduce} mobile />
    } else if (expanded && content) {
      node = (
        <motion.div
          key="big"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={popTransition}
          className="dashboard-status-island pointer-events-auto flex h-12 max-w-[92vw] items-center justify-center rounded-full px-5"
          aria-live="polite"
        >
          <PillContent state={state} content={content} reduce={reduce} />
        </motion.div>
      )
    }
    return createPortal(
      <div className="pointer-events-none fixed inset-x-0 top-2 z-[70] flex justify-center px-3">
        <AnimatePresence initial={false}>{node}</AnimatePresence>
      </div>,
      document.body,
    )
  }

  return (
    // Hover target is this whole padded zone (not the exact pill) so the
    // collapsed-analysed pill re-expands when the cursor is in the general area.
    // Fixed height + absolutely-centered pills: the big/small swap happens in
    // place (no flex reflow), so closing shrinks toward the true center instead
    // of drifting into a corner. `select-none` keeps the cursor an arrow, never
    // a text caret.
    <div
      className="relative flex h-[72px] select-none items-center justify-center px-12"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {isError ? (
        <ErrorPill
          detail={detail}
          onRetry={effective.onRetry}
          onDismiss={effective.onDismiss}
          reduce={reduce}
        />
      ) : (
      <AnimatePresence initial={false}>
        {expanded && content ? (
          // Enlarged pill: one persistent element while expanded (keyed "big"),
          // so swapping live -> analysing -> analysed only crossfades the inner
          // content and never re-pops. Matches the search bar's height.
          // Centered via motion-owned x/y (-50%) so scale stays anchored to the
          // dead center and never conflicts with a Tailwind translate utility.
          <motion.div
            key="big"
            style={pillStyle}
            initial={flat ? { x: '-50%', y: '-50%', opacity: 0 } : { x: '-50%', y: '-50%', opacity: 0, scale: 0.6 }}
            animate={{ x: '-50%', y: '-50%', opacity: 1, scale: 1 }}
            exit={flat ? { x: '-50%', y: '-50%', opacity: 0 } : { x: '-50%', y: '-50%', opacity: 0, scale: 0.55 }}
            transition={popTransition}
            className="dashboard-status-island absolute flex h-12 items-center justify-center whitespace-nowrap rounded-full px-5"
            aria-live="polite"
          >
            <PillContent state={state} content={content} reduce={reduce} />
          </motion.div>
        ) : mobile ? null : (
          // Tiny neutral pill (idle / collapsed-analysed): an empty capsule.
          // -30% length (48->34px), +10% height (~11px). Same absolute-center
          // anchor as the big pill so the swap shrinks/grows in place. On mobile
          // there is NO idle pill (rendered null above) — the island only appears
          // when there's something to say.
          <motion.span
            key="small"
            style={pillStyle}
            initial={flat ? { x: '-50%', y: '-50%', opacity: 0 } : { x: '-50%', y: '-50%', opacity: 0, scale: 0.6 }}
            animate={{ x: '-50%', y: '-50%', opacity: 1, scale: 1 }}
            exit={flat ? { x: '-50%', y: '-50%', opacity: 0 } : { x: '-50%', y: '-50%', opacity: 0, scale: 0.6 }}
            transition={popTransition}
            className="dashboard-status-island absolute block h-[11px] w-[34px] rounded-full"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
      )}
    </div>
  )
}

// Error pill — persistent, interactive. Red "Analysis failed" with Retry +
// Dismiss buttons on the right (padding between). Unlike the other pills this one
// is pointer-interactive and never auto-collapses. Retry re-runs the analysis;
// Dismiss clears the error (App `error` state). Buttons are optional — a live
// session error has no retry, so only the handlers passed in render.
function ErrorPill({ detail, onRetry, onDismiss, reduce, mobile = false }) {
  // Desktop: absolutely centered in the topbar cell with a spring pop. Mobile:
  // a relatively-positioned node inside the portal's flex-centered overlay, so it
  // just fades (the overlay handles centering + max-width keeps buttons on-screen).
  const popTransition = reduce ? { duration: 0 } : mobile ? { duration: 0.16, ease: 'easeOut' } : POP_SPRING
  const flat = reduce || mobile
  const center = mobile ? {} : { x: '-50%', y: '-50%' }
  return (
    <motion.div
      style={mobile ? undefined : { left: '50%', top: '50%' }}
      initial={flat ? { ...center, opacity: 0 } : { ...center, opacity: 0, scale: 0.6 }}
      animate={{ ...center, opacity: 1, scale: 1 }}
      exit={flat ? { ...center, opacity: 0 } : { ...center, opacity: 0, scale: 0.55 }}
      transition={popTransition}
      // max-w + a shrinkable, truncating label keep the Retry/Dismiss buttons
      // on-screen even in the cramped mobile topbar (the buttons are shrink-0).
      className={`dashboard-status-island pointer-events-auto flex h-12 max-w-[92vw] items-center rounded-full border border-rose-500/40 pl-5 pr-2 ${mobile ? '' : 'absolute'}`}
      role="alert"
    >
      <span className="flex min-w-0 items-center gap-2">
        <AlertTriangle className="status-island-glow-white h-[19px] w-[19px] shrink-0 text-rose-400" strokeWidth={2.6} aria-hidden="true" />
        <span className="truncate text-[17px] font-bold leading-none tracking-[-0.01em] text-rose-400">
          {detail || 'Analysis failed'}
        </span>
      </span>
      <span className="ml-4 flex shrink-0 items-center gap-1.5">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="flex h-8 items-center gap-1 rounded-full bg-white/10 px-3 text-[13px] font-semibold text-white/90 transition hover:bg-white/[0.18]"
          >
            <RotateCcw className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden="true" />
            Retry
          </button>
        ) : null}
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss error"
            className="flex h-8 w-8 items-center justify-center rounded-full text-white/55 transition hover:bg-white/10 hover:text-white/90"
          >
            <X className="h-4 w-4" strokeWidth={2.5} aria-hidden="true" />
          </button>
        ) : null}
      </span>
    </motion.div>
  )
}

/**
 * deriveStatus — single source of truth for the island's state. Lives here next
 * to the renderer so the mapping stays one file. Called upstream in DashboardPage.
 *   mode: 'live' | 'shared' | 'analysed' | null/idle
 *   loading: true while an analysis is streaming
 *   error: when set, the island shows the persistent error pill. `error.onRetry`
 *          / `error.onDismiss` (optional) wire the pill's buttons.
 */
export function deriveStatus(mode, loading, detail = {}, error = null) {
  if (error) {
    return {
      state: 'error',
      detail: error.detail || 'Analysis failed',
      onRetry: error.onRetry || null,
      onDismiss: error.onDismiss || null,
    }
  }
  if (loading) return { state: 'analysing', detail: detail.analysing || null }
  switch (mode) {
    case 'live':
      return { state: 'live', detail: detail.live || null }
    case 'shared':
      return { state: 'shared', detail: detail.shared || null }
    case 'analysed':
      return { state: 'analysed', detail: detail.analysed || null }
    default:
      return { state: 'idle' }
  }
}

import { useRef, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import './HowItWorks.css'

const PHASE_DURATIONS = { 1: 4000, 2: 7000, 3: 6000, 4: 7000 }

const FADE = { duration: 0.45, ease: [0.22, 1, 0.36, 1] }

export default function HowItWorks() {
  const [phase, setPhase] = useState(1)
  const [inView, setInView] = useState(false)
  const [paused, setPaused] = useState(false)
  const sectionRef = useRef(null)

  useEffect(() => {
    const node = sectionRef.current
    if (!node) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        setInView(entry.intersectionRatio > 0.15)
      },
      { threshold: [0, 0.15, 0.3, 1] }
    )
    obs.observe(node)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    if (!inView) {
      setPhase(1)
    }
  }, [inView])

  useEffect(() => {
    if (!inView || paused) return
    const dur = PHASE_DURATIONS[phase] ?? 4000
    const t = setTimeout(() => {
      setPhase((p) => (p >= 4 ? 1 : p + 1))
    }, dur)
    return () => clearTimeout(t)
  }, [phase, inView, paused])

  return (
    <section
      ref={sectionRef}
      id="product"
      className="how-it-works-section scroll-section"
      style={{ position: 'relative' }}
    >
      <div className="section-inner hiw-section-inner">
        <p className="section-eyebrow">See it in action</p>
        <h2 className="hiw-heading">
          Your AI teammate, <span className="hiw-heading-soft">end-to-end.</span>
        </h2>
        <p className="hiw-subline">
          From joining the call to organizing the aftermath — watch one loop.
        </p>

        <div
          className="hiw-frame"
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          aria-label="Animated product walkthrough"
        >
          <AnimatePresence mode="wait">
            {inView && phase === 1 && <Phase1Meeting key="p1" />}
            {inView && phase === 2 && <Phase2Acting key="p2" />}
            {inView && phase === 3 && <Phase3LiveView key="p3" />}
            {inView && phase === 4 && <Phase4Dashboard key="p4" />}
          </AnimatePresence>
        </div>
      </div>
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 1 — Bot joins
 * ───────────────────────────────────────────────────────────────── */

function Phase1Meeting() {
  return (
    <motion.div
      className="phase-root phase1-root"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={FADE}
    >
      <div className="meeting-mock">
        <div className="meeting-header">
          <span className="meeting-title">Sprint Planning · Live</span>
          <span className="meeting-time">00:14:32</span>
        </div>
        <div className="meeting-tiles">
          <ParticipantTile name="Alex M." initials="AM" color="#a78bfa" />
          <ParticipantTile name="Jordan K." initials="JK" color="#f472b6" />
          <ParticipantTile name="Sam R." initials="SR" color="#fbbf24" />
          <motion.div
            className="tile-slot"
            initial={{ opacity: 0, scale: 0.85, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ delay: 0.7, duration: 0.5, ease: 'easeOut' }}
          >
            <ParticipantTile name="Prism AI" initials="P" color="#22d3ee" isPrism />
          </motion.div>
        </div>
        <motion.div
          className="meeting-system-msg"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.5, duration: 0.4 }}
        >
          <span className="prism-mini-dot" />
          <span>Prism has joined the call.</span>
        </motion.div>
      </div>
    </motion.div>
  )
}

function ParticipantTile({ name, initials, color, isPrism = false, compact = false }) {
  return (
    <div className={`participant-tile${isPrism ? ' is-prism' : ''}${compact ? ' compact' : ''}`}>
      <div className="tile-avatar-wrap">
        <div className="tile-avatar" style={{ background: color, color: isPrism ? '#04090a' : '#0b0b0b' }}>
          {initials}
        </div>
        {isPrism && <div className="prism-tile-ring" />}
      </div>
      <div className="tile-name-row">
        <span className="tile-name">{name}</span>
        {isPrism && <span className="prism-listening">listening</span>}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 2 — Prism acts
 * ───────────────────────────────────────────────────────────────── */

const PHASE2_MESSAGES = [
  { delay: 0.3, text: "Got it — I'll track that decision." },
  { delay: 1.5, text: "I've added the Sprint Review to the calendar for Friday at 2pm." },
  { delay: 2.7, text: 'Heads up — Sam owned this same action item last week and it’s still open.', highlight: true },
  { delay: 3.9, text: "Issue created in GitHub: 'Fix onboarding tracking gap' → #482" },
]

const PHASE2_TOASTS = [
  { delay: 1.9, kind: 'calendar', text: 'Event added: Sprint Review — Friday 2pm' },
  { delay: 3.2, kind: 'github', text: 'Issue created: #482' },
  { delay: 4.5, kind: 'notion', text: 'Notion doc linked: Onboarding Spec v2' },
]

function Phase2Acting() {
  return (
    <motion.div
      className="phase-root phase2-root"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={FADE}
    >
      <div className="phase2-grid">
        <div className="meeting-mock compact">
          <div className="meeting-header">
            <span className="meeting-title">Sprint Planning · Live</span>
            <span className="meeting-time">00:18:04</span>
          </div>
          <div className="meeting-tiles compact">
            <ParticipantTile name="Alex M." initials="AM" color="#a78bfa" compact />
            <ParticipantTile name="Jordan K." initials="JK" color="#f472b6" compact />
            <ParticipantTile name="Sam R." initials="SR" color="#fbbf24" compact />
            <ParticipantTile name="Prism AI" initials="P" color="#22d3ee" isPrism compact />
          </div>
        </div>

        <div className="chat-panel">
          <div className="chat-header">
            <span>Meeting chat</span>
            <span className="chat-typing">
              <span className="prism-mini-dot" />
              Prism is typing
            </span>
          </div>
          <div className="chat-messages">
            {PHASE2_MESSAGES.map((m, i) => (
              <motion.div
                key={i}
                className={`chat-msg${m.highlight ? ' is-highlight' : ''}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: m.delay, duration: 0.4, ease: 'easeOut' }}
              >
                <span className="chat-avatar" aria-hidden="true">P</span>
                <div className="chat-body">
                  <div className="chat-meta">
                    <span className="chat-from">Prism AI</span>
                    <span className="chat-dot-sep">·</span>
                    <span className="chat-time">now</span>
                  </div>
                  <div className="chat-text">{m.text}</div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>

      <div className="toast-stack" aria-hidden="true">
        {PHASE2_TOASTS.map((t, i) => (
          <motion.div
            key={i}
            className={`toast-pill toast-${t.kind}`}
            initial={{ opacity: 0, x: 24, scale: 0.96 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            transition={{ delay: t.delay, duration: 0.4, ease: 'easeOut' }}
          >
            <span className="toast-icon">{toastIcon(t.kind)}</span>
            <span className="toast-text">{t.text}</span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}

function toastIcon(kind) {
  if (kind === 'calendar') return <CalendarIcon />
  if (kind === 'github') return <GitHubIcon />
  if (kind === 'notion') return <NotionIcon />
  return null
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4.5" width="18" height="16" rx="2" />
      <line x1="8" y1="2.5" x2="8" y2="6.5" />
      <line x1="16" y1="2.5" x2="16" y2="6.5" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <rect x="7.5" y="13" width="2" height="2" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="11" y="13" width="2" height="2" rx="0.5" fill="currentColor" stroke="none" />
      <rect x="14.5" y="13" width="2" height="2" rx="0.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  )
}

function NotionIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <rect x="2.5" y="2.5" width="19" height="19" rx="3" fill="#ffffff" />
      <path d="M8 7.5 v9 M8 7.5 L16 16.5 M16 7.5 v9" stroke="#000" strokeWidth="1.6" strokeLinecap="round" fill="none" />
    </svg>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 3 — Live view
 * ───────────────────────────────────────────────────────────────── */

const PHASE3_LINES = [
  { delay: 0.4, speaker: 'Alex',   color: '#a78bfa', text: "Let's confirm — shipping the onboarding flow by Friday." },
  { delay: 1.0, speaker: 'Jordan', color: '#f472b6', text: "Agreed. I'll own frontend. Sam, API side?" },
  { delay: 1.6, speaker: 'Sam',    color: '#fbbf24', text: "I'll be ready Thursday EOD." },
  { delay: 2.2, speaker: 'Alex',   color: '#a78bfa', text: 'What about the analytics tracking gap?' },
  { delay: 2.8, speaker: 'Jordan', color: '#f472b6', text: 'Patch post-launch. Delaying hits Q3.' },
  { delay: 3.4, speaker: 'Alex',   color: '#a78bfa', text: 'Decided. Moving forward.' },
]

function Phase3LiveView() {
  return (
    <motion.div
      className="phase-root phase3-root"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={FADE}
    >
      <div className="browser-mock">
        <div className="browser-chrome">
          <div className="browser-dots" aria-hidden="true">
            <span /><span /><span />
          </div>
          <div className="browser-url">
            <span className="browser-lock">🔒</span>
            <span>prism.ai/live/abc123</span>
          </div>
          <div className="live-badge">
            <span className="live-dot" />
            <span>Live</span>
          </div>
        </div>

        <div className="browser-body">
          <div className="live-transcript">
            <div className="transcript-title">Live transcript</div>
            <div className="transcript-scroll">
              {PHASE3_LINES.map((line, i) => (
                <motion.div
                  key={i}
                  className="transcript-line"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: line.delay, duration: 0.32, ease: 'easeOut' }}
                >
                  <span className="transcript-speaker" style={{ color: line.color }}>
                    {line.speaker}
                  </span>
                  <span className="transcript-text">{line.text}</span>
                </motion.div>
              ))}
            </div>

            <div className="live-input-row">
              <motion.div
                className="live-input"
                initial={{ opacity: 0 }}
                animate={{ opacity: [0, 1, 1, 0] }}
                transition={{
                  delay: 4.0,
                  duration: 1.4,
                  times: [0, 0.18, 0.78, 1],
                  ease: 'easeOut',
                }}
              >
                <span className="live-input-cursor" />
                <span>Summarize what we've decided so far</span>
              </motion.div>
              <motion.div
                className="prism-inline-reply"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 5.0, duration: 0.45, ease: 'easeOut' }}
              >
                <span className="prism-mini-dot" />
                <span>
                  Ship onboarding Friday · Jordan/frontend · Sam/API · analytics patch post-launch.
                </span>
              </motion.div>
            </div>
          </div>

          <motion.div
            className="brief-card"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.3, duration: 0.5, ease: 'easeOut' }}
          >
            <div className="brief-section">
              <div className="brief-title">Open from last week</div>
              <div className="brief-item">
                <span className="brief-bullet">•</span>
                <span>Sam — API auth fix</span>
                <span className="brief-tag overdue">overdue</span>
              </div>
              <div className="brief-item">
                <span className="brief-bullet">•</span>
                <span>Jordan — Design handoff</span>
              </div>
            </div>
            <div className="brief-section">
              <div className="brief-title">Recent decisions</div>
              <div className="brief-item">
                <span className="brief-bullet">•</span>
                <span>Delay v2 mobile to Q4</span>
              </div>
              <div className="brief-item">
                <span className="brief-bullet">•</span>
                <span>Use Stripe for billing</span>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
 * Phase 4 — Dashboard
 * ───────────────────────────────────────────────────────────────── */

function Phase4Dashboard() {
  const [tab, setTab] = useState('meeting')

  useEffect(() => {
    const t = setTimeout(() => setTab('intel'), 4800)
    return () => clearTimeout(t)
  }, [])

  return (
    <motion.div
      className="phase-root phase4-root"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={FADE}
    >
      <div className="dashboard-mock">
        <aside className="dash-rail">
          <div className="dash-rail-header">
            <span className="dash-logo-dot" />
            <span>PrismAI</span>
          </div>
          <div className="dash-rail-title">Meetings</div>
          <div className="dash-meeting-item is-active">
            <div className="dash-meeting-name">Sprint Planning</div>
            <div className="dash-meeting-when">Today</div>
          </div>
          <div className="dash-meeting-item">
            <div className="dash-meeting-name">Design Review</div>
            <div className="dash-meeting-when">Mon</div>
          </div>
          <div className="dash-meeting-item">
            <div className="dash-meeting-name">Q3 Kickoff</div>
            <div className="dash-meeting-when">Last week</div>
          </div>
        </aside>

        <main className="dash-center">
          <motion.div
            className="dash-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.4 }}
          >
            <div className="dash-card-title">Summary</div>
            <p className="dash-summary-text">
              Team aligned on Friday ship date for onboarding. Analytics gap to be patched
              post-launch. Sam owns API, Jordan owns frontend.
            </p>
          </motion.div>

          <motion.div
            className="dash-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.55, duration: 0.4 }}
          >
            <div className="dash-card-title">Action items</div>
            <div className="dash-action-list">
              <DashActionItem owner="Jordan" task="Frontend onboarding changes" when="Fri" />
              <DashActionItem owner="Sam" task="API integration" when="Thu EOD" />
              <DashActionItem owner="Alex" task="Stakeholder update email" when="Today" />
            </div>
          </motion.div>
        </main>

        <aside className="dash-right">
          <div className="dash-tabs">
            <span className={`dash-tab${tab === 'meeting' ? ' is-active' : ''}`}>Meeting</span>
            <span className={`dash-tab${tab === 'intel' ? ' is-active' : ''}`}>Intelligence</span>
          </div>

          <AnimatePresence mode="wait">
            {tab === 'meeting' ? (
              <motion.div
                key="meet-pane"
                className="dash-pane"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.32, ease: 'easeOut' }}
              >
                <div className="dash-card dash-health-card">
                  <div className="dash-card-title">Health score</div>
                  <div className="dash-health">
                    <span className="dash-health-num">81</span>
                    <span className="dash-health-label">Strong session</span>
                  </div>
                  <div className="dash-sparkline" aria-hidden="true">
                    {[10, 16, 13, 20, 15, 22, 18, 25].map((h, i) => (
                      <span key={i} className="dash-spark-bar" style={{ height: `${h}px` }} />
                    ))}
                  </div>
                  <div className="dash-badges">
                    <span className="dash-badge">Clear owners</span>
                    <span className="dash-badge">Decisions logged</span>
                    <span className="dash-badge">On schedule</span>
                  </div>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="intel-pane"
                className="dash-pane"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.32, ease: 'easeOut' }}
              >
                <div className="dash-card">
                  <div className="dash-card-title">Cross-meeting</div>
                  <DashStat num="3" label="recurring blockers" />
                  <DashStat num="40%" label="Jordan carrying open items" />
                  <DashStat num="4/6" label="meetings mention launch deadline" />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </aside>
      </div>
    </motion.div>
  )
}

function DashActionItem({ owner, task, when }) {
  return (
    <div className="dash-action-item">
      <span className="dash-check" />
      <span className="dash-action-text">
        <span className="dash-action-owner">{owner}</span>
        <span className="dash-action-dash"> — </span>
        {task}
      </span>
      <span className="dash-when">{when}</span>
    </div>
  )
}

function DashStat({ num, label }) {
  return (
    <div className="dash-stat">
      <div className="dash-stat-num">{num}</div>
      <div className="dash-stat-label">{label}</div>
    </div>
  )
}

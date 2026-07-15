import { useState, useEffect } from 'react'
import { Activity, TrendingUp, TrendingDown, Minus, AlertTriangle, ChevronDown } from 'lucide-react'
import { cardGlowStyle, eyebrow, glassCard, subtleText } from './dashboardStyles'

function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (target === undefined || target === null) return
    let start = null
    const step = (timestamp) => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(eased * target))
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [target, duration])
  return display
}

// Maps each overall label to a color + short blurb the UI surfaces.
// Keep in sync with the vocabulary in backend/agents/sentiment.py.
const LABEL_META = {
  collaborative:    { color: '#34d399', tint: 'rgba(52,211,153,0.10)', border: 'rgba(52,211,153,0.28)', blurb: 'Open energy; speakers built on each other' },
  aligned:          { color: '#34d399', tint: 'rgba(52,211,153,0.10)', border: 'rgba(52,211,153,0.28)', blurb: 'Strong consensus and shared direction' },
  'decision-making': { color: '#22d3ee', tint: 'rgba(34,211,238,0.10)', border: 'rgba(34,211,238,0.28)', blurb: 'Focused; choices were committed to' },
  exploratory:      { color: '#a78bfa', tint: 'rgba(167,139,250,0.10)', border: 'rgba(167,139,250,0.28)', blurb: 'Open-ended; productive uncertainty' },
  frictional:       { color: '#fbbf24', tint: 'rgba(251,191,36,0.10)', border: 'rgba(251,191,36,0.28)', blurb: 'Disagreement surfaced; tension present' },
  divergent:        { color: '#fb923c', tint: 'rgba(251,146,60,0.10)', border: 'rgba(251,146,60,0.28)', blurb: 'No agreement; pulling in different directions' },
  rushed:           { color: '#fbbf24', tint: 'rgba(251,191,36,0.10)', border: 'rgba(251,191,36,0.28)', blurb: 'Short on time; items deferred or skipped' },
  draining:         { color: '#f87171', tint: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.28)', blurb: 'Low energy; one-sided or unproductive' },
  neutral:          { color: '#94a3b8', tint: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.28)', blurb: 'Informational; no strong dynamic' },
}

const TONE_COLOR = {
  collaborative: '#34d399',
  enthusiastic:  '#34d399',
  neutral:       '#94a3b8',
  reserved:      '#94a3b8',
  resistant:     '#fbbf24',
  frustrated:    '#f87171',
}

function ArcIndicator({ arc }) {
  const map = {
    improving:   { Icon: TrendingUp,   color: '#34d399', label: 'Improving' },
    declining:   { Icon: TrendingDown, color: '#f87171', label: 'Declining' },
    stable:      { Icon: Minus,        color: '#94a3b8', label: 'Stable' },
    unresolved:  { Icon: AlertTriangle, color: '#fbbf24', label: 'Unresolved' },
  }
  const info = map[arc] || map.stable
  const { Icon, color, label } = info
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
      style={{ borderColor: `${color}3a`, color, background: `${color}14` }}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {label}
    </span>
  )
}

function ScoreBar({ score, color }) {
  const displayed = useCountUp(score ?? 0, 1000)
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className="h-1 rounded-full"
          style={{ width: `${displayed}%`, background: color, transition: 'width 16ms linear', boxShadow: `0 0 6px ${color}60` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right font-mono text-[10px] text-white/50">{displayed}/100</span>
    </div>
  )
}

function SpeakerRow({ speaker, isLast }) {
  const { name, tone, score } = speaker
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const color = TONE_COLOR[tone] || TONE_COLOR.neutral
  return (
    <div className={`flex items-center gap-3 px-3 py-2 ${isLast ? '' : 'border-b border-white/[0.06]'}`}>
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-white/[0.14] bg-white/[0.05] text-[10px] font-bold text-white/70">
        {initials}
      </div>
      <span className="min-w-0 flex-1 truncate text-[13px] text-white/86">{name}</span>
      <span
        className="rounded-full border px-2 py-0.5 text-[10.5px] font-medium capitalize"
        style={{ borderColor: `${color}3a`, color, background: `${color}14` }}
      >
        {tone || 'neutral'}
      </span>
      {typeof score === 'number' && (
        <span className="w-9 shrink-0 text-right font-mono text-[10px] text-white/40">{score}</span>
      )}
    </div>
  )
}

export default function SentimentCard({ sentiment }) {
  // Keystone insight — collapsible (like Speaker Coaching / Transcript) so the
  // meeting view can be tidied, but default OPEN and with the headline (overall
  // label + arc) always in the header so it stays a keystone, not a hidden card.
  const [open, setOpen] = useState(true)
  if (!sentiment?.overall) return null
  const labelKey = String(sentiment.overall).toLowerCase()
  const meta = LABEL_META[labelKey] || LABEL_META.neutral
  const speakers = sentiment.speakers || []
  const tensions = sentiment.tension_moments || []

  return (
    <section className={glassCard} style={cardGlowStyle}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 p-4"
      >
        <Activity className="h-4 w-4 shrink-0 text-cyan-200/70" aria-hidden="true" />
        <p className={eyebrow}>Sentiment</p>
        <span
          className="rounded-full border px-2.5 py-0.5 text-[12px] font-semibold capitalize"
          style={{ borderColor: meta.border, color: meta.color, background: meta.tint }}
        >
          {sentiment.overall}
        </span>
        {sentiment.arc && <ArcIndicator arc={sentiment.arc} />}
        <ChevronDown
          className={`ml-auto h-4 w-4 shrink-0 text-white/70 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {open && (
      <div className="border-t border-white/[0.07] px-4 pb-4 pt-3">
      <div className="mb-3">
        <ScoreBar score={sentiment.score} color={meta.color} />
      </div>

      <p className="mb-3 text-[13px] leading-5 text-white/68">
        {sentiment.notes || meta.blurb}
      </p>

      {speakers.length > 0 && (
        <div className="mb-3 overflow-hidden rounded-lg border border-white/[0.07]">
          <div className="border-b border-white/[0.07] px-3 py-1.5">
            <span className={subtleText}>Per-speaker tone</span>
          </div>
          {speakers.map((s, i) => (
            <SpeakerRow key={s.name || i} speaker={s} isLast={i === speakers.length - 1} />
          ))}
        </div>
      )}

      {tensions.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-amber-400/[0.18] bg-amber-400/[0.04]">
          <div className="flex items-center gap-1.5 border-b border-amber-400/[0.14] px-3 py-1.5">
            <AlertTriangle className="h-3 w-3 text-amber-300/80" aria-hidden="true" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-200/90">
              Tension moments
            </span>
          </div>
          <ul className="divide-y divide-amber-400/[0.10]">
            {tensions.map((t, i) => {
              // Backward-compat: legacy entries are plain strings.
              const text = typeof t === 'string' ? t : t?.moment
              const status = typeof t === 'string' ? null : t?.status
              const carried = status === 'carried_over'
              return (
                <li key={i} className="px-3 py-2">
                  <p className="text-[12.5px] leading-5 text-white/82">{text}</p>
                  {status && (
                    <span
                      className={`mt-1 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide ${
                        carried
                          ? 'border-red-400/30 bg-red-400/[0.10] text-red-300'
                          : 'border-emerald-400/30 bg-emerald-400/[0.10] text-emerald-300'
                      }`}
                    >
                      {carried ? '→ Carried over · needs follow-up' : '✓ Resolved'}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      </div>
      )}
    </section>
  )
}

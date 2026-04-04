import { useState, useEffect } from 'react'

function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (target === undefined || target === null) return
    let start = null
    const step = (timestamp) => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(eased * target))
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [target, duration])
  return display
}

const SCORE_COLOR = (score) => {
  if (score >= 80) return { stroke: '#10b981', text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/25', accent: 'linear-gradient(90deg, #10b981, #34d399, transparent)', label: 'Excellent' }
  if (score >= 60) return { stroke: '#6366f1', text: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/25', accent: 'linear-gradient(90deg, #6366f1, #818cf8, transparent)', label: 'Good' }
  if (score >= 40) return { stroke: '#f59e0b', text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/25', accent: 'linear-gradient(90deg, #f59e0b, #fbbf24, transparent)', label: 'Fair' }
  return { stroke: '#ef4444', text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/25', accent: 'linear-gradient(90deg, #ef4444, #f87171, transparent)', label: 'Needs Work' }
}

const BADGE_POSITIVE = new Set(['Clear Decisions', 'Action-Oriented', 'Well-Facilitated', 'Concise', 'Engaged Team', 'Inclusive'])

function CircleGauge({ score, color }) {
  const radius = 46
  const circumference = 2 * Math.PI * radius
  const displayed = useCountUp(score, 1000)
  const offset = circumference - (displayed / 100) * circumference

  return (
    <div className="relative w-28 h-28 flex-shrink-0">
      <svg className="w-28 h-28 -rotate-90" viewBox="0 0 112 112">
        {/* Track */}
        <circle cx="56" cy="56" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
        {/* Progress */}
        <circle
          cx="56" cy="56" r={radius}
          fill="none"
          stroke={color.stroke}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ filter: `drop-shadow(0 0 6px ${color.stroke}80)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-2xl font-bold ${color.text}`}>{displayed}</span>
        <span className="text-[10px] text-gray-500 font-medium">/100</span>
      </div>
    </div>
  )
}

function BreakdownBar({ label, value, color }) {
  const displayed = useCountUp(value, 1000)
  return (
    <div>
      <div className="flex justify-between mb-1">
        <span className="text-[11px] text-gray-500">{label}</span>
        <span className="text-[11px] text-gray-400 font-medium">{displayed}</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div
          className="h-1.5 rounded-full"
          style={{ width: `${displayed}%`, background: color.stroke, transition: 'width 16ms linear' }}
        ></div>
      </div>
    </div>
  )
}

export default function HealthScoreCard({ healthScore }) {
  if (!healthScore || healthScore.score === undefined || healthScore.score === null) return null

  const { score, verdict, badges = [], breakdown = {} } = healthScore
  const color = SCORE_COLOR(score)

  return (
    <div className={`rounded-2xl border ${color.border} overflow-hidden transition-transform duration-200 hover:-translate-y-0.5`} style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div className="h-0.5 w-full" style={{ background: color.accent }}></div>
      <div className="p-5">
        {/* Header */}
        <div className="flex items-center gap-2 mb-5">
          <div className={`w-7 h-7 rounded-lg ${color.bg} border ${color.border} flex items-center justify-center`}>
            <svg className={`w-3.5 h-3.5 ${color.text}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h3 className={`text-sm font-semibold ${color.text}`}>Meeting Health</h3>
          <span className={`ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-full ${color.bg} border ${color.border} ${color.text}`}>
            {color.label}
          </span>
        </div>

        {/* Score + breakdown */}
        <div className="flex items-start gap-5">
          <CircleGauge score={score} color={color} />
          <div className="flex-1 min-w-0">
            <p className="text-gray-100 text-[15px] font-medium leading-relaxed mb-4">{verdict}</p>
            <div className="space-y-2.5">
              {breakdown.clarity !== undefined && (
                <BreakdownBar label="Clarity" value={breakdown.clarity} color={color} />
              )}
              {breakdown.action_orientation !== undefined && (
                <BreakdownBar label="Action-Oriented" value={breakdown.action_orientation} color={color} />
              )}
              {breakdown.engagement !== undefined && (
                <BreakdownBar label="Engagement" value={breakdown.engagement} color={color} />
              )}
            </div>
          </div>
        </div>

        {/* Badges */}
        {badges.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-white/5">
            {badges.map((badge) => {
              const isPositive = BADGE_POSITIVE.has(badge)
              return (
                <span
                  key={badge}
                  className={`text-xs px-2.5 py-1 rounded-full border font-medium ${
                    isPositive
                      ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
                      : 'bg-red-500/10 border-red-500/25 text-red-300'
                  }`}
                >
                  {isPositive ? '✓' : '!'} {badge}
                </span>
              )
            })}
          </div>
        )}

        <div className="mt-4 pt-4 border-t border-white/5 flex items-start gap-2">
          <svg className="w-3.5 h-3.5 text-gray-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            PrismAI uses transcript-based heuristics for this score. Treat it as a decision-support signal, not a final judgment.
          </p>
        </div>
      </div>
    </div>
  )
}

import { cardGlowStyle, glassCard } from './dashboardStyles'

function formatResolvedDate(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function CalendarCard({ suggestion }) {
  if (!suggestion || (!suggestion.recommended && !suggestion.reason)) return null

  const resolvedLabel = [suggestion.resolved_day, formatResolvedDate(suggestion.resolved_date)].filter(Boolean).join(' · ')

  return (
    <section className={`${glassCard} p-5`} style={cardGlowStyle}>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-bold tracking-[-0.01em] text-white">Follow-up meeting</h2>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
            suggestion.recommended
              ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
              : 'border-white/[0.10] bg-white/[0.04] text-white/50'
          }`}
        >
          {suggestion.recommended ? 'Recommended' : 'Optional'}
        </span>
      </div>

      {suggestion.suggested_timeframe && (
        <p className="text-[15px] font-semibold leading-snug text-white">
          {suggestion.suggested_timeframe}
          {resolvedLabel && <span className="ml-2 text-xs font-medium text-white/45">{resolvedLabel}</span>}
        </p>
      )}
      <p className="mt-2 text-sm leading-7 text-white/75">{suggestion.reason}</p>
    </section>
  )
}

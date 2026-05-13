import { Calendar } from 'lucide-react'
import { cardGlowStyle, eyebrow, glassCard, subtleText } from './dashboardStyles'

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
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3 flex items-center gap-2">
        <Calendar className="h-4 w-4 text-cyan-200/70" aria-hidden="true" />
        <p className={eyebrow}>Follow-up Meeting</p>
        <span className={`ml-auto rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
          suggestion.recommended
            ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-300'
            : 'border-white/[0.10] bg-white/[0.04] text-white/50'
        }`}>
          {suggestion.recommended ? 'Recommended' : 'Optional'}
        </span>
      </div>

      <div className="overflow-hidden rounded-lg border border-white/[0.08]">
        {suggestion.suggested_timeframe && (
          <div className="border-b border-white/[0.07] px-3 py-2.5">
            <span className={subtleText}>When: </span>
            <span className="text-sm font-medium text-white">{suggestion.suggested_timeframe}</span>
            {resolvedLabel && <span className={`ml-2 ${subtleText}`}>{resolvedLabel}</span>}
          </div>
        )}
        <div className="px-3 py-2.5">
          <p className="text-sm leading-6 text-white/78">{suggestion.reason}</p>
        </div>
      </div>

      <p className={`mt-3 ${subtleText}`}>
        Scheduling suggestion inferred from context — not a calendar commitment.
      </p>
    </section>
  )
}

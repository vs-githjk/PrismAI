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
    <div className="rounded-2xl overflow-hidden card-glow-pink transition-transform duration-200 hover:-translate-y-0.5" style={{ background: 'rgba(236,72,153,0.06)', border: '1px solid rgba(236,72,153,0.22)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #ec4899, #a855f7, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg bg-pink-500/20 border border-pink-500/30 flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-pink-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-pink-400">Follow-up Meeting</h3>
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          <span className={`text-[11px] px-2.5 py-1 rounded-full border ${
            suggestion.recommended
              ? 'bg-pink-500/10 border-pink-500/25 text-pink-300'
              : 'bg-white/5 border-white/8 text-gray-400'
          }`}>
            {suggestion.recommended ? 'Recommended' : 'Optional'}
          </span>
          {suggestion.suggested_timeframe && (
            <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
              {suggestion.suggested_timeframe}
            </span>
          )}
          {resolvedLabel && (
            <span className="text-[11px] px-2.5 py-1 rounded-full bg-pink-500/10 border border-pink-500/25 text-pink-200">
              {resolvedLabel}
            </span>
          )}
        </div>

        <div className="flex items-start gap-4">
          {suggestion.suggested_timeframe && (
            <div className="flex-shrink-0 px-3 py-2.5 rounded-xl bg-pink-500/10 border border-pink-500/25 text-center min-w-[80px]">
              <p className="text-xs text-pink-400/70 leading-none mb-1">Next meeting</p>
              <p className="text-sm font-bold text-pink-300 leading-snug">{suggestion.suggested_timeframe}</p>
              {resolvedLabel && <p className="text-[11px] text-pink-200/80 mt-1 leading-snug">{resolvedLabel}</p>}
            </div>
          )}
          <div>
            <p className="text-gray-200 text-sm leading-relaxed">{suggestion.reason}</p>
          </div>
        </div>

        <div className="mt-4 pt-4 border-t border-white/5 flex items-start gap-2">
          <svg className="w-3.5 h-3.5 text-gray-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            This is a scheduling suggestion inferred from context, not a calendar commitment. Adjust based on urgency, attendees, and team rhythm.
          </p>
        </div>
      </div>
    </div>
  )
}

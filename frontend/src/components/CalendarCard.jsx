export default function CalendarCard({ suggestion }) {
  if (!suggestion || !suggestion.recommended) return null

  return (
    <div className="rounded-2xl border border-pink-500/20 overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #ec4899, #f472b6, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg bg-pink-500/20 border border-pink-500/30 flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-pink-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
          <h3 className="text-xs font-semibold text-pink-400 uppercase tracking-widest">Calendar Suggestion</h3>
        </div>

        <div className="flex items-start gap-4">
          {suggestion.suggested_timeframe && (
            <div className="flex-shrink-0 px-3 py-2.5 rounded-xl bg-pink-500/10 border border-pink-500/25 text-center min-w-[80px]">
              <p className="text-xs text-pink-400/70 leading-none mb-1">Next meeting</p>
              <p className="text-sm font-bold text-pink-300 leading-snug">{suggestion.suggested_timeframe}</p>
            </div>
          )}
          <div>
            <p className="text-gray-200 text-sm leading-relaxed">{suggestion.reason}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

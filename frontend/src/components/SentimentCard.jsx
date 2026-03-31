const SENTIMENT_CONFIG = {
  positive: {
    badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    bar: 'from-emerald-500 to-green-400',
    label: 'Positive',
    emoji: '😊',
    accent: 'linear-gradient(90deg, #10b981, #34d399, transparent)',
  },
  neutral: {
    badge: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
    bar: 'from-yellow-500 to-amber-400',
    label: 'Neutral',
    emoji: '😐',
    accent: 'linear-gradient(90deg, #eab308, #fbbf24, transparent)',
  },
  tense: {
    badge: 'bg-red-500/15 text-red-300 border-red-500/30',
    bar: 'from-red-500 to-rose-400',
    label: 'Tense',
    emoji: '😤',
    accent: 'linear-gradient(90deg, #ef4444, #f87171, transparent)',
  },
  unresolved: {
    badge: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
    bar: 'from-orange-500 to-amber-400',
    label: 'Unresolved',
    emoji: '😟',
    accent: 'linear-gradient(90deg, #f97316, #fb923c, transparent)',
  },
}

export default function SentimentCard({ sentiment }) {
  if (!sentiment) return null

  const config = SENTIMENT_CONFIG[sentiment.overall] || SENTIMENT_CONFIG.neutral
  const score = Math.max(0, Math.min(100, sentiment.score ?? 50))

  return (
    <div className="rounded-2xl border border-white/8 overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div className="h-0.5 w-full" style={{ background: config.accent }}></div>
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg bg-yellow-500/20 border border-yellow-500/30 flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-xs font-semibold text-yellow-400 uppercase tracking-widest">Sentiment Analysis</h3>
        </div>

        <div className="flex items-center gap-4 mb-5">
          <div className="text-4xl animate-float">{config.emoji}</div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold border ${config.badge}`}>
                {config.label}
              </span>
              <span className="text-sm font-bold text-gray-300">{score}<span className="text-xs text-gray-500 font-normal">/100</span></span>
            </div>
            <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.08)' }}>
              <div
                className={`h-2 rounded-full bg-gradient-to-r ${config.bar} transition-all duration-1000`}
                style={{ width: `${score}%` }}
              ></div>
            </div>
          </div>
        </div>

        {sentiment.notes && (
          <p className="text-gray-400 text-sm leading-relaxed border-t border-white/5 pt-3">{sentiment.notes}</p>
        )}
      </div>
    </div>
  )
}

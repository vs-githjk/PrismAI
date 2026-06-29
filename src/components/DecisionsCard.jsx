const IMPORTANCE_CONFIG = {
  1: { label: 'Critical',    classes: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30' },
  2: { label: 'Significant', classes: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  3: { label: 'Minor',       classes: 'bg-teal-500/15 text-teal-400 border-teal-500/30' },
}

export default function DecisionsCard({ decisions }) {
  if (!decisions || decisions.length === 0) return null

  const sorted = [...decisions].sort((a, b) => (a.importance ?? 3) - (b.importance ?? 3))
  const criticalCount = sorted.filter((d) => (d.importance ?? 3) === 1).length

  return (
    <div className="rounded-2xl overflow-hidden transition-transform duration-200 hover:-translate-y-0.5" style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.2)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #06b6d4, #0ea5e9, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-7 h-7 rounded-lg bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center">
            <svg className="w-3.5 h-3.5 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-sm font-semibold text-cyan-400">Decisions</h3>
          <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/25 text-cyan-300">
            {sorted.length} decision{sorted.length !== 1 ? 's' : ''}
          </span>
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          <span className="text-[11px] px-2.5 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-200">
            {criticalCount} critical
          </span>
          <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
            Agreement-focused, not discussion-focused
          </span>
        </div>

        <ul className="space-y-2.5">
          {sorted.map((item, i) => {
            const imp = IMPORTANCE_CONFIG[item.importance] || IMPORTANCE_CONFIG[3]
            return (
              <li
                key={i}
                className="flex items-start gap-3 p-3 rounded-xl border border-white/5 bg-white/2 hover:bg-white/4 transition-all"
              >
                <span className="mt-0.5 text-cyan-500 font-bold text-sm shrink-0 w-5 text-center">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-gray-200 text-sm">{item.decision}</p>
                  <div className="flex flex-wrap gap-3 mt-1.5">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${imp.classes}`}>
                      {imp.label}
                    </span>
                    {item.owner && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                        <span className="text-gray-400">{item.owner}</span>
                      </span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>

        <div className="mt-4 pt-4 border-t border-white/5 flex items-start gap-2">
          <svg className="w-3.5 h-3.5 text-gray-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-[11px] text-gray-500 leading-relaxed">
            PrismAI only tries to capture what sounds resolved or agreed. If something was merely debated, it should not live here.
          </p>
        </div>
      </div>
    </div>
  )
}

export default function ActionItemsCard({ actionItems, onToggle }) {
  if (!actionItems || actionItems.length === 0) return null

  const toggle = (i) => onToggle?.(i)
  const doneCount = actionItems.filter(item => item.completed).length

  return (
    <div className="rounded-2xl overflow-hidden card-glow-violet" style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)' }}>
      <div className="h-0.5 w-full" style={{ background: 'linear-gradient(90deg, #8b5cf6, #db2777, transparent)' }}></div>
      <div className="p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
            </div>
            <h3 className="text-xs font-semibold text-purple-400 uppercase tracking-widest">Action Items</h3>
          </div>
          {doneCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/25 text-purple-300">
              {doneCount}/{actionItems.length} done
            </span>
          )}
        </div>

        <ul className="space-y-2.5">
          {actionItems.map((item, i) => (
            <li
              key={i}
              className={`flex items-start gap-3 p-3 rounded-xl border transition-all ${
                item.completed
                  ? 'border-purple-500/15 bg-purple-500/5 opacity-50'
                  : 'border-white/5 bg-white/2 hover:bg-white/4'
              }`}
            >
              <button
                onClick={() => toggle(i)}
                className={`mt-0.5 w-5 h-5 rounded-md border-2 flex-shrink-0 flex items-center justify-center transition-all ${
                  item.completed
                    ? 'bg-purple-500 border-purple-500 shadow-sm shadow-purple-500/40'
                    : 'border-gray-600 hover:border-purple-400'
                }`}
              >
                {item.completed && (
                  <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </button>
              <div className={`flex-1 min-w-0 ${item.completed ? 'line-through' : ''}`}>
                <p className="text-gray-200 text-sm">{item.task}</p>
                <div className="flex flex-wrap gap-3 mt-1.5">
                  {item.owner && item.owner !== 'Unassigned' && (
                    <span className="flex items-center gap-1 text-xs text-gray-500">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      <span className="text-gray-400">{item.owner}</span>
                    </span>
                  )}
                  {item.due && item.due !== 'TBD' && (
                    <span className="flex items-center gap-1 text-xs text-gray-500">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      <span className="text-purple-400/80">{item.due}</span>
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

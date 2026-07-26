import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

function borderWidth(importance) {
  if (importance <= 1) return 'border-l-4'
  if (importance === 2) return 'border-l-2'
  return 'border-l'
}

export default function DecisionMemory({ insights, onSelect }) {
  const decisions = insights.recentDecisions || []

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Memory</p>
        <h2 className={cardTitle}>Decision memory</h2>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-white/46">Recent significant decisions</p>
        {decisions.length ? (
          <div className="overflow-hidden rounded-lg border border-white/[0.08]">
            {decisions.slice(0, 5).map((decision) => (
              <button
                type="button"
                key={decision.id}
                onClick={() => decision.meeting && onSelect?.(decision.meeting)}
                className={`w-full border-b border-white/[0.07] border-l-violet-300 bg-black/18 px-3 py-2 text-left transition last:border-b-0 hover:bg-white/[0.055] ${borderWidth(decision.importance)}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="line-clamp-1 text-sm font-medium text-white">{decision.title}</p>
                  <span className="text-[10px] text-white/38">P{decision.importance || 3}</span>
                </div>
                <p className={subtleText}>{decision.owner || 'No owner recorded'}</p>
              </button>
            ))}
          </div>
        ) : (
          <p className={subtleText}>No decision memory yet.</p>
        )}
      </div>
    </section>
  )
}

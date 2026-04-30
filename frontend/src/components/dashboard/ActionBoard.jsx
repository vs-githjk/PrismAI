import { Zap } from 'lucide-react'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

function Block({ title, children }) {
  return (
    <div className="min-h-0 rounded-lg border border-white/[0.09] bg-black/20">
      <p className="border-b border-white/[0.07] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-white/46">{title}</p>
      <div className="p-2.5">
      {children}
      </div>
    </div>
  )
}

export default function ActionBoard({ result, insights, hideOpen = false }) {
  const openItems = (result?.action_items || []).filter((item) => !item.completed).slice(0, 5)
  const blockers = insights.recurringBlockers || []
  const nextSteps = insights.recommendedActions || []

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Focus</p>
          <h2 className={cardTitle}>Action board</h2>
        </div>
        <Zap className="h-5 w-5 text-cyan-200/80" aria-hidden="true" />
      </div>

      <div className={`grid gap-2 ${hideOpen ? 'xl:grid-cols-2' : 'xl:grid-cols-3'}`}>
        {!hideOpen && (
          <Block title="Open">
            {openItems.length ? (
              <div className="space-y-1.5">
                {openItems.map((item, index) => (
                  <div key={`${item.task}-${index}`} className="rounded-lg border border-white/[0.07] bg-black/20 px-2.5 py-1.5">
                    <p className="line-clamp-1 text-sm font-medium text-white">{item.task}</p>
                    <p className={subtleText}>{item.owner || 'Unowned'}{item.due ? ` · ${item.due}` : ''}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className={subtleText}>No open action items in the active meeting.</p>
            )}
          </Block>
        )}

        <Block title="Recurring blockers">
          {blockers.length ? (
            <div className="space-y-1.5">
              {blockers.slice(0, 3).map((blocker) => (
                <p key={blocker.snippet} className="line-clamp-1 rounded-lg border border-amber-200/14 bg-amber-300/8 px-2.5 py-1.5 text-sm leading-5 text-amber-50/88">
                  {blocker.snippet}
                </p>
              ))}
            </div>
          ) : (
            <p className={subtleText}>No repeated blockers detected yet.</p>
          )}
        </Block>

        <Block title="Next steps">
          {nextSteps.length ? (
            <div className="space-y-1.5">
              {nextSteps.slice(0, 3).map((step) => (
                <div key={step.id || step.title} className="rounded-lg border border-cyan-200/14 bg-cyan-300/8 px-2.5 py-1.5">
                  <p className="text-sm font-medium text-cyan-50">{step.title}</p>
                  <p className={`line-clamp-1 ${subtleText}`}>{step.description}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className={subtleText}>Recommendations appear after more meetings are analyzed.</p>
          )}
        </Block>
      </div>
    </section>
  )
}

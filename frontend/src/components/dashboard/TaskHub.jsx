import { useMemo, useState } from 'react'
import { ListTodo } from 'lucide-react'
import { collectOpenActions, byPriority, scopeFilter } from '../../lib/actionItems'
import { cardGlowStyle, glassCard, subtleText } from './dashboardStyles'
import ActionItemRow from './ActionItemRow'

/**
 * The Task hub — the canonical list of open action items for the active scope
 * (see docs/adr/0002). Lives on Trend, co-headline with the health graph.
 *
 * Sort = byPriority, THE one task order (urgency → yours → unowned → recency;
 * CONTEXT.md "Task priority") — identical to Home's Needs-attention feed. The
 * Yours | All | Unassigned chips are filters layered on top.
 */
export default function TaskHub({ history = [], user = null, onToggle, onOpenMeeting }) {
  const [scope, setScope] = useState('all')

  const { rows, total, mineCount, unassignedCount } = useMemo(() => {
    const all = collectOpenActions(history, user)
    return {
      rows: scopeFilter(all, scope).sort(byPriority),
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
      unassignedCount: all.filter((r) => r.unassigned).length,
    }
  }, [history, user, scope])

  const tabs = [
    { key: 'all', label: 'All', count: total },
    { key: 'mine', label: 'Yours', count: mineCount },
    { key: 'unassigned', label: 'Unassigned', count: unassignedCount },
  ]

  return (
    // The height bound lives ON the section (not a wrapper): a max-h'd wrapper
    // without clipping let a 40-task list paint straight over the sections
    // below it. The list scrolls internally past this cap.
    <section className={`${glassCard} flex max-h-[36rem] min-h-0 flex-col overflow-hidden`} style={cardGlowStyle}>
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color:var(--db-border)] px-4 py-3">
        <h2 className="text-xl font-bold tracking-[-0.01em] text-[color:var(--db-text)]">Tasks</h2>
        <div className="ml-auto flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setScope(t.key)}
              aria-pressed={scope === t.key}
              className={`rounded-lg px-2.5 py-1 text-[12px] font-medium transition ${
                scope === t.key
                  ? 'bg-cyan-400/[0.14] text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.22)]'
                  : 'text-[color:var(--db-text-muted)] hover:bg-[var(--db-fill-strong)] hover:text-[color:var(--db-text)]'
              }`}
            >
              {t.label}
              <span className="ml-1 text-[color:var(--db-text-faint)]">{t.count}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {rows.length === 0 ? (
          <div className="px-2 py-8 text-center">
            <ListTodo className="mx-auto mb-2 h-5 w-5 text-[color:var(--db-text-faint)]" aria-hidden="true" />
            <p className={subtleText}>
              {scope === 'mine' ? 'Nothing assigned to you right now.'
                : scope === 'unassigned' ? 'Every open task has an owner.'
                  : 'No open tasks — they appear here as meetings assign them.'}
            </p>
          </div>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((row) => (
              <ActionItemRow
                key={`${row.entry.id}-${row.index}`}
                row={row}
                onToggle={onToggle}
                onOpenMeeting={onOpenMeeting}
                showMeeting
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

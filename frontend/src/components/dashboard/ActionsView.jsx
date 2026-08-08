// Standalone Actions page — the canonical execution surface for open action
// items in the active scope (spec 2026-08-08; supersedes ADR 0002's location
// decision only — byPriority remains THE order, chips remain filters).
import { useMemo, useState } from 'react'
import { ListTodo, ArrowRight } from 'lucide-react'
import { collectOpenActions, scopeFilter, byPriority, dueBand } from '../../lib/actionItems'
import ActionItemRow from './ActionItemRow'
import { glassCard, cardGlowStyle, eyebrow, cardTitle, subtleText } from './dashboardStyles'

const BAND_LABELS = { overdue: 'Overdue', soon: 'Due soon', open: 'Open' }
const SCOPES = [
  { key: 'all', label: 'All' },
  { key: 'mine', label: 'Yours' },
  { key: 'unassigned', label: 'Unassigned' },
]

export default function ActionsView({ history = [], user = null, onToggleAction, onOpenMeeting, onOpenTrend }) {
  const [scope, setScope] = useState('all')
  const { rows, total, mineCount, unassignedCount, overdue, soon } = useMemo(() => {
    const all = collectOpenActions(history, user)
    const sorted = scopeFilter(all, scope).sort(byPriority)
    return {
      rows: sorted,
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
      unassignedCount: all.filter((r) => r.unassigned).length,
      overdue: all.filter((r) => dueBand(r) === 'overdue').length,
      soon: all.filter((r) => dueBand(r) === 'soon').length,
    }
  }, [history, user, scope])

  const counts = { all: total, mine: mineCount, unassigned: unassignedCount }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(240px,3fr)] items-start">
      <section className={glassCard} style={cardGlowStyle} aria-label="Open action items">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3" style={{ borderColor: 'var(--db-border)' }}>
          <h2 className={`${cardTitle} flex items-center gap-2`}><ListTodo className="h-4 w-4 text-[color:var(--db-text-muted)]" /> Actions</h2>
          <div className="flex gap-1">
            {SCOPES.map((s) => (
              <button key={s.key} onClick={() => setScope(s.key)}
                className={`min-h-[36px] rounded-full border px-3 text-xs ${scope === s.key ? 'bg-[color:var(--db-fill-strong)] text-[color:var(--db-text)]' : 'text-[color:var(--db-text-muted)] hover:bg-[color:var(--db-fill)]'}`}
                style={{ borderColor: scope === s.key ? 'var(--db-border-strong)' : 'var(--db-border)' }}>
                {s.label} <span className="opacity-60">{counts[s.key]}</span>
              </button>
            ))}
          </div>
        </header>
        {rows.length === 0 ? (
          <p className={`${subtleText} px-4 py-8 text-center`}>
            {scope === 'all'
              ? 'Open action items from completed or newly analyzed meetings will appear here.'
              : scope === 'mine' ? 'Nothing assigned to you right now.' : 'No unassigned items right now.'}
          </p>
        ) : (
          <ul className="px-2 py-2">
            {rows.map((row, i) => {
              const band = dueBand(row)
              const bandStart = i === 0 || dueBand(rows[i - 1]) !== band
              return (
                <li key={`${row.entry.id}-${row.index}`}>
                  {bandStart && (
                    <p className={`${eyebrow} px-2 pb-1 ${i === 0 ? 'pt-1' : 'pt-4'}`}>{BAND_LABELS[band]}</p>
                  )}
                  <ActionItemRow row={row} onToggle={onToggleAction} onOpenMeeting={onOpenMeeting} showMeeting />
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <aside className={`${glassCard} p-4`} style={cardGlowStyle} aria-label="Queue context">
        <p className={eyebrow}>Right now</p>
        <dl className="mt-2 space-y-1.5 text-sm text-[color:var(--db-text-soft)]">
          <div className="flex justify-between"><dt>Open items</dt><dd className="text-[color:var(--db-text)]">{total}</dd></div>
          <div className="flex justify-between"><dt>Overdue</dt><dd className="text-[color:var(--db-text)]">{overdue}</dd></div>
          <div className="flex justify-between"><dt>Due soon</dt><dd className="text-[color:var(--db-text)]">{soon}</dd></div>
          <div className="flex justify-between"><dt>Yours</dt><dd className="text-[color:var(--db-text)]">{mineCount}</dd></div>
        </dl>
        <p className={`${subtleText} mt-4`}>
          Ranked by live urgency (overdue → due soon), then yours → unassigned → teammates', then newest meeting. Stale deadlines are history, not urgency.
        </p>
        {onOpenTrend && (
          <button onClick={onOpenTrend} className="mt-4 inline-flex min-h-[36px] items-center gap-1 text-sm text-[color:var(--db-accent-text)]">
            Cross-meeting intelligence <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </aside>
    </div>
  )
}

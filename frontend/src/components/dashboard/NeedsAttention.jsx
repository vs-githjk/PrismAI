import { useMemo } from 'react'
import { ChevronRight, ListTodo, MessagesSquare } from 'lucide-react'
import { collectOpenActions, byPriority } from '../../lib/actionItems'
import ActionItemRow from './ActionItemRow'

const island = 'dashboard-island flex min-h-0 flex-col overflow-hidden'

/**
 * Home's "Needs attention" feed — a BOUNDED slice of the full task queue
 * (ADR 0002, amended Aug 2026 — the queue now lives on the standalone Actions
 * page): the top 5 tasks by the one true priority order, then the top
 * unresolved threads (which still live on Trend), then the door to Actions.
 * Never grows into a second task surface.
 */
export default function NeedsAttention({ history = [], user = null, openThreads = [], onToggle, onOpenMeeting, onOpenTrend, onOpenActions }) {
  const { rows, total } = useMemo(() => {
    const all = collectOpenActions(history, user)
    return { rows: [...all].sort(byPriority).slice(0, 5), total: all.length }
  }, [history, user])

  const threads = openThreads.slice(0, 3)
  const empty = rows.length === 0 && threads.length === 0

  return (
    <section className={island}>
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5">
        <h2 className="text-[18px] font-semibold tracking-[-0.015em] text-[color:var(--db-text)] sm:text-[22px]">
          Needs attention
        </h2>
        {total > 0 && (
          <span className="shrink-0 text-[11.5px] text-[color:var(--db-text-faint)]">{total} open</span>
        )}
      </div>
      {/* Rows are already capped (top 5 + top 3 threads); max-h is a defensive
          cap now that the grid no longer gives this card a definite height to
          flex-fill — without it, long-wrapped rows could push the card past
          the viewport instead of scrolling internally. */}
      <div className="max-h-[50vh] overflow-y-auto p-3">
        {empty ? (
          <div className="px-2 py-6 text-center">
            <ListTodo className="mx-auto mb-2 h-5 w-5 text-[color:var(--db-text-faint)]" aria-hidden="true" />
            <p className="text-sm leading-6 text-[color:var(--db-text-muted)]">
              Nothing needs your attention right now.
            </p>
          </div>
        ) : (
          <>
            {rows.length > 0 && (
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
            {threads.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
                  Still unresolved
                </p>
                <ul className="space-y-1">
                  {threads.map((t, i) => (
                    <li key={i}>
                      <button
                        type="button"
                        onClick={onOpenTrend}
                        className="group flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left transition hover:bg-[var(--db-fill-strong)]"
                      >
                        <MessagesSquare className="h-3.5 w-3.5 shrink-0 text-amber-300/70" aria-hidden="true" />
                        <span className="min-w-0 flex-1 truncate text-[12.5px] text-[color:var(--db-text-muted)]">{t.thread}</span>
                        <ChevronRight className="h-3 w-3 shrink-0 text-[color:var(--db-text-faint)] transition group-hover:translate-x-0.5" aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(total > rows.length || threads.length > 0) && (
              <button
                type="button"
                onClick={onOpenActions}
                className="mt-2.5 w-full rounded-lg border border-[color:var(--db-border)] py-2 text-[12.5px] font-medium text-[color:var(--db-text-muted)] transition hover:border-[color:var(--db-accent)] hover:bg-[color:var(--db-accent-fill)] hover:text-[color:var(--db-accent-text)]"
              >
                View all {total} task{total === 1 ? '' : 's'} →
              </button>
            )}
          </>
        )}
      </div>
    </section>
  )
}

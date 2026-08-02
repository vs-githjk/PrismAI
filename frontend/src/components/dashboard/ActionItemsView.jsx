import { useMemo, useState } from 'react'
import { ListTodo } from 'lucide-react'
import { deriveDisplayTitle, formatMeetingDate } from '../../lib/insights'
import { collectOpenActions, groupByMeetingDate, scopeFilter } from '../../lib/actionItems'
import ActionItemRow from './ActionItemRow'

/**
 * Full-page view of every open action item.
 *
 * Home shows only the four most urgent — this is where the rest live. Grouped by
 * the calendar period of the meeting that assigned the work (Today · Yesterday ·
 * This week · This month · Last month · Last 6 months · This year · Older), then
 * by meeting within each period, with overdue items leading each meeting.
 */
export default function ActionItemsView({
  history = [],
  user = null,
  onOpenMeeting,
  onToggleAction,
  workspaceName = null,
}) {
  const [scope, setScope] = useState('all')

  const { groups, total, mineCount, unassignedCount, firstName } = useMemo(() => {
    const all = collectOpenActions(history, user)
    return {
      groups: groupByMeetingDate(scopeFilter(all, scope)),
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
      unassignedCount: all.filter((r) => r.unassigned).length,
      firstName: (user?.user_metadata?.full_name || '').split(/\s+/)[0] || 'you',
    }
  }, [history, user, scope])

  const tabs = [
    { key: 'all', label: 'All', count: total },
    { key: 'mine', label: 'Yours', count: mineCount },
    { key: 'unassigned', label: 'Unassigned', count: unassignedCount },
  ]

  return (
    <div className="mx-auto max-w-4xl pb-12">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <p className="text-[13px] text-[color:var(--db-text-muted)]">
            Everything still open{workspaceName ? ` in ${workspaceName}` : ''}, grouped by the meeting that assigned it.
          </p>
        </div>
        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setScope(t.key)}
              aria-pressed={scope === t.key}
              className={`rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition ${
                scope === t.key
                  ? 'bg-cyan-400/[0.14] text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.22)]'
                  : 'text-[color:var(--db-text-muted)] hover:bg-[var(--db-fill-strong)] hover:text-[color:var(--db-text)]'
              }`}
            >
              {t.label}
              <span className="ml-1.5 text-[color:var(--db-text-faint)]">{t.count}</span>
            </button>
          ))}
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[color:var(--db-border)] px-6 py-14 text-center">
          <ListTodo className="mx-auto mb-3 h-6 w-6 text-[color:var(--db-text-faint)]" aria-hidden="true" />
          <p className="text-[14px] font-medium text-[color:var(--db-text-muted)]">
            {scope === 'mine'
              ? `Nothing assigned to ${firstName} right now.`
              : scope === 'unassigned'
                ? 'Every open item has an owner.'
                : 'No open action items.'}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-[12.5px] text-[color:var(--db-text-faint)]">
            {scope === 'all'
              ? 'They appear here as your meetings assign them.'
              : 'Switch tabs to see the rest.'}
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((bucket) => (
            <section key={bucket.key}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[color:var(--db-text-faint)]">
                  {bucket.label}
                </h2>
                <span className="text-[11.5px] text-[color:var(--db-text-faint)]">{bucket.count}</span>
                <span className="h-px flex-1 bg-[color:var(--db-border)]" />
              </div>
              <div className="space-y-3">
                {bucket.meetings.map((mtg) => (
                  <div key={mtg.entry.id} className="rounded-2xl border border-[color:var(--db-border)] bg-[var(--db-fill)] p-3.5">
                    <button
                      type="button"
                      onClick={() => onOpenMeeting?.(mtg.entry)}
                      className="group mb-2 flex w-full items-baseline gap-2 text-left"
                    >
                      <span className="truncate text-[13.5px] font-semibold text-[color:var(--db-text)] transition group-hover:text-cyan-200">
                        {deriveDisplayTitle(mtg.entry)}
                      </span>
                      <span className="shrink-0 text-[11.5px] text-[color:var(--db-text-faint)]">
                        {formatMeetingDate(mtg.entry.date)}
                      </span>
                      <span className="ml-auto shrink-0 text-[11px] text-[color:var(--db-text-faint)]">
                        {mtg.items.length} open
                      </span>
                    </button>
                    <ul className="space-y-1.5">
                      {mtg.items.map((row) => (
                        <ActionItemRow
                          key={`${row.entry.id}-${row.index}`}
                          row={row}
                          onToggle={onToggleAction}
                          onOpenMeeting={onOpenMeeting}
                        />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

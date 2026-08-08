import { Check, Clock, UserRound } from 'lucide-react'
import { dueInfo, dueLabel } from '../../lib/dueStatus'
import { deriveDisplayTitle } from '../../lib/insights'

// Same due-badge styling as MeetingView and Home, so every surface agrees.
const DUE_STYLE = {
  overdue: 'border-[color:var(--db-danger)] bg-[color:var(--db-danger-fill)] text-[color:var(--db-danger)]',
  soon: 'border-[color:var(--db-warn)] bg-[color:var(--db-warn-fill)] text-[color:var(--db-warn)]',
}

/**
 * One open action item. Shared by Home's compact preview and the full Action
 * items page — the ownership treatment and due badges must be identical in both.
 *
 * `showMeeting` adds the source meeting inline; the full page groups BY meeting so
 * it doesn't need it, while Home's flat preview does.
 */
export default function ActionItemRow({ row, onToggle, onOpenMeeting, showMeeting = false }) {
  const { item, entry, index, isMine, unassigned } = row
  // Anchor phrase resolution to the MEETING date — "tomorrow" said weeks ago is a
  // fixed past date, not a perpetual DUE TOMORROW. Stale deadlines get quiet text.
  const due = dueInfo(item, entry?.date)
  const hard = due.status === 'overdue' || due.status === 'soon'
  const soft = due.status === 'later' || due.status === 'stale'
    ? dueLabel(due)
    : (item.due && String(item.due).trim().toUpperCase() !== 'TBD' ? item.due : '')

  return (
    <li
      className={`flex items-start gap-2.5 rounded-lg px-3 py-2 transition ${
        // Flat rows — a border around every row inside an already-bordered card was
        // the "boxes in boxes" clutter. Ownership reads from the tint + cyan "You".
        isMine
          ? 'bg-cyan-400/[0.06] hover:bg-cyan-400/[0.10]'
          : 'hover:bg-[var(--db-fill-strong)]'
      }`}
    >
      <button
        type="button"
        onClick={() => onToggle?.(entry, index)}
        aria-pressed={!!item.completed}
        aria-label={item.completed ? 'Mark as not done' : 'Mark as done'}
        className="mt-[3px] flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-full border border-[color:var(--db-border-strong)] text-transparent transition hover:border-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/40"
      >
        <Check className="h-2.5 w-2.5" aria-hidden="true" />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-medium leading-snug text-[color:var(--db-text)]">{item.task}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11.5px]">
          {/* Owner, with YOU called out explicitly. */}
          {isMine ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[color:var(--db-accent)] bg-[color:var(--db-accent-fill)] px-1.5 py-0.5 font-semibold text-[color:var(--db-accent-text)]">
              <UserRound className="h-3 w-3 shrink-0" aria-hidden="true" />You
            </span>
          ) : unassigned ? (
            <span className="inline-flex items-center gap-1 text-[color:var(--db-warn)]">
              <UserRound className="h-3 w-3 shrink-0" aria-hidden="true" />Unassigned
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[color:var(--db-text-faint)]">
              <UserRound className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate">{item.owner}</span>
            </span>
          )}
          {hard && (
            <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${DUE_STYLE[due.status]}`}>
              {dueLabel(due)}
            </span>
          )}
          {!hard && soft && (
            <span className="inline-flex items-center gap-1 text-[color:var(--db-text-faint)]">
              <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
              <span className="truncate">{soft}</span>
            </span>
          )}
          {showMeeting && (
            <button
              type="button"
              onClick={() => onOpenMeeting?.(entry)}
              className="ml-auto max-w-[45%] shrink-0 truncate text-[11px] text-[color:var(--db-text-faint)] transition hover:text-[color:var(--db-accent-text)]"
            >
              {deriveDisplayTitle(entry)}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

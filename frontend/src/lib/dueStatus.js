import { resolveDatePhrase } from './resolveDate.js'

// An overdue this much older than the deadline is STALE — history, not an alarm.
// Without this, a phrase like "tomorrow" from a weeks-old meeting wore a red
// urgency badge forever (and, re-anchored to today, never even became overdue).
const STALE_AFTER_DAYS = 14

// Resolve an action item's deadline to a concrete date + status. Prefers the
// backend-resolved `due_date`; falls back to client-parsing the free-text `due`
// label (covers meetings analyzed before due-date resolution shipped).
// `reference` is the date the phrase was SAID (the meeting date) — "tomorrow" in
// a June 13 meeting means June 14, not tomorrow-forever. Defaults to today only
// for fresh, not-yet-saved analyses.
// status: 'overdue' | 'soon' (<=3 days) | 'later' | 'stale' | null (no date).
export function dueInfo(item, reference) {
  if (!item) return { date: '', status: null }
  let iso = item.due_date
  if (!iso && item.due && String(item.due).trim().toUpperCase() !== 'TBD') {
    let ref = reference ? new Date(reference) : new Date()
    if (Number.isNaN(ref.getTime())) ref = new Date()
    iso = resolveDatePhrase(item.due, ref).date
  }
  if (!iso) return { date: '', status: null }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return { date: '', status: null }
  const diffDays = Math.round((d - today) / 86400000)
  const status =
    diffDays < -STALE_AFTER_DAYS ? 'stale'
      : diffDays < 0 ? 'overdue'
        : diffDays <= 3 ? 'soon'
          : 'later'
  return { date: iso, status, diffDays }
}

// Short human label for a badge: "Overdue", "Due today", "Due in 2d", "Mar 14".
export function dueLabel({ date, status, diffDays }) {
  if (!status) return ''
  if (status === 'stale') {
    return `Was due ${new Date(`${date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
  }
  if (status === 'overdue') return diffDays === -1 ? 'Overdue 1d' : `Overdue ${-diffDays}d`
  if (diffDays === 0) return 'Due today'
  if (status === 'soon') return diffDays === 1 ? 'Due tomorrow' : `Due in ${diffDays}d`
  return new Date(`${date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Sort comparator for two dueInfo results: live urgency first (overdue, then due
// soon, then upcoming), stale history after, undated last.
const STATUS_ORDER = { overdue: 0, soon: 1, later: 2, stale: 3 }
export function compareDue(a, b) {
  const ra = a.status ? STATUS_ORDER[a.status] : 4
  const rb = b.status ? STATUS_ORDER[b.status] : 4
  if (ra !== rb) return ra - rb
  return a.diffDays - b.diffDays
}

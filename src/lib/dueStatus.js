import { resolveDatePhrase } from './resolveDate'

// Resolve an action item's deadline to a concrete date + status. Prefers the
// backend-resolved `due_date`; falls back to client-parsing the free-text `due`
// label (covers meetings analyzed before due-date resolution shipped).
// status: 'overdue' | 'soon' (<=3 days) | 'later' | null (no parseable date).
export function dueInfo(item) {
  if (!item) return { date: '', status: null }
  let iso = item.due_date
  if (!iso && item.due && String(item.due).trim().toUpperCase() !== 'TBD') {
    iso = resolveDatePhrase(item.due).date
  }
  if (!iso) return { date: '', status: null }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return { date: '', status: null }
  const diffDays = Math.round((d - today) / 86400000)
  const status = diffDays < 0 ? 'overdue' : diffDays <= 3 ? 'soon' : 'later'
  return { date: iso, status, diffDays }
}

// Short human label for a badge: "Overdue", "Due today", "Due in 2d", "Mar 14".
export function dueLabel({ date, status, diffDays }) {
  if (!status) return ''
  if (status === 'overdue') return diffDays === -1 ? 'Overdue 1d' : `Overdue ${-diffDays}d`
  if (diffDays === 0) return 'Due today'
  if (status === 'soon') return diffDays === 1 ? 'Due tomorrow' : `Due in ${diffDays}d`
  return new Date(`${date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Sort comparator for two dueInfo results: overdue/soonest first, undated last.
export function compareDue(a, b) {
  if (!a.status && !b.status) return 0
  if (!a.status) return 1
  if (!b.status) return -1
  return a.diffDays - b.diffDays
}

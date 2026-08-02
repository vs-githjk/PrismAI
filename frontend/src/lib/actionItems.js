/**
 * Open action items, collected across meeting history.
 *
 * Shared by Home's compact preview and the full Action items page so the two can
 * never disagree about what's open, who owns it, or how it's grouped.
 *
 * Deliberately NOT time-windowed. Home used to cut this at 14 days, which in real
 * data hid every open item (43 of 43, 41 of them from meetings over a month old).
 * Age is expressed through the date grouping instead, where it's visible.
 */

import { dueInfo } from './dueStatus.js'
import { meetingBucket } from './dateGroups.js'

// Owner strings the analysis emits when nobody owns the item. These are REAL
// values in the data (14 of 43 open items in one audited account read
// "Unassigned"), not blanks — so a truthy-owner check treats them as owned and
// they hide in plain sight.
const UNASSIGNED_OWNERS = new Set([
  '', 'unassigned', 'unowned', 'tbd', 'tbc', 'none', 'n/a', 'na', 'null',
  'team', 'everyone', 'all', 'attendees', 'group', 'someone', 'anyone', 'nobody', '-', '?',
])

export const isUnassignedOwner = (owner) => UNASSIGNED_OWNERS.has((owner || '').trim().toLowerCase())

/** Candidate names for the signed-in user, lowercased. */
export function userNameTokens(user) {
  const full = (user?.user_metadata?.full_name || user?.user_metadata?.name || '').trim().toLowerCase()
  const emailLocal = (user?.email || '').split('@')[0].replace(/[._\d]+/g, ' ').trim().toLowerCase()
  const out = new Set()
  if (full) {
    out.add(full)
    out.add(full.split(/\s+/)[0])
  }
  if (emailLocal) {
    out.add(emailLocal)
    out.add(emailLocal.split(/\s+/)[0])
  }
  return [...out].filter((n) => n.length >= 3)
}

/** Does this item's owner refer to the signed-in user? Name-match, because action
 *  items carry display names from the transcript, not user ids. */
export function ownedByUser(owner, userNames) {
  const o = (owner || '').trim().toLowerCase()
  if (!o || !userNames.length) return false
  // Owners can be a list: "Vidyut Sriram, Devaj Solanki, Abhinav Dasari".
  const parts = o.split(/[,/&]| and /).map((p) => p.trim()).filter(Boolean)
  return parts.some((part) =>
    userNames.some((n) => part === n || part.startsWith(`${n} `) || part.split(/\s+/)[0] === n),
  )
}

/** Every open action item across history, tagged with ownership. */
export function collectOpenActions(history = [], user = null) {
  const names = userNameTokens(user)
  return (history || []).flatMap((entry) =>
    (entry?.result?.action_items || [])
      .map((item, index) => ({
        item,
        entry,
        index,
        isMine: ownedByUser(item.owner, names),
        unassigned: isUnassignedOwner(item.owner),
      }))
      .filter(({ item }) => !item.completed && (item.task || '').trim()),
  )
}

export const scopeFilter = (rows, scope) => (
  scope === 'mine' ? rows.filter((r) => r.isMine)
    : scope === 'unassigned' ? rows.filter((r) => r.unassigned)
      : rows
)

const DUE_RANK = { overdue: 0, soon: 1 }
/** Overdue first, then due-soon, then everything else. */
export function byUrgency(a, b) {
  const ra = DUE_RANK[dueInfo(a.item).status] ?? 2
  const rb = DUE_RANK[dueInfo(b.item).status] ?? 2
  if (ra !== rb) return ra - rb
  // Tie-break on the meeting date so the ordering is stable, newest first.
  return new Date(b.entry.date).getTime() - new Date(a.entry.date).getTime()
}

const OWN_RANK = (r) => (r.isMine ? 0 : r.unassigned ? 1 : 2)
/** Home's preview order: YOUR items first, then unassigned (nobody else will claim
 *  those), then teammates' — urgency within each tier. A pure-urgency sort made the
 *  personal dashboard lead with other people's work. */
export function byMineFirst(a, b) {
  return OWN_RANK(a) - OWN_RANK(b) || byUrgency(a, b)
}

/**
 * Group rows by the calendar bucket of the MEETING that assigned them (i.e. when
 * the work was handed over), then by meeting within each bucket.
 * @returns {Array<{key, label, count, meetings: Array<{entry, items}>}>}
 */
export function groupByMeetingDate(rows, now = new Date()) {
  const byBucket = new Map()
  for (const row of rows) {
    const b = meetingBucket(row.entry.date, now)
    if (!byBucket.has(b.key)) byBucket.set(b.key, { ...b, items: [], meetings: new Map() })
    const bucket = byBucket.get(b.key)
    bucket.items.push(row)
    if (!bucket.meetings.has(row.entry.id)) bucket.meetings.set(row.entry.id, { entry: row.entry, items: [] })
    bucket.meetings.get(row.entry.id).items.push(row)
  }
  return [...byBucket.values()]
    .sort((a, b) => a.rank - b.rank)
    .map((bucket) => ({
      key: bucket.key,
      label: bucket.label,
      count: bucket.items.length,
      meetings: [...bucket.meetings.values()]
        .sort((a, b) => new Date(b.entry.date).getTime() - new Date(a.entry.date).getTime())
        .map((m) => ({ entry: m.entry, items: [...m.items].sort(byUrgency) })),
    }))
}

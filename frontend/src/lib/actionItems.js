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
/** LIVE urgency first (overdue, due-soon), then everything else — 'stale' ranks
 *  with the rest, so a weeks-old missed deadline can't outrank real work. Phrase
 *  resolution is anchored to each item's meeting date. */
export function byUrgency(a, b) {
  const ra = DUE_RANK[dueInfo(a.item, a.entry?.date).status] ?? 2
  const rb = DUE_RANK[dueInfo(b.item, b.entry?.date).status] ?? 2
  if (ra !== rb) return ra - rb
  // Tie-break on the meeting date so the ordering is stable, newest first.
  return new Date(b.entry.date).getTime() - new Date(a.entry.date).getTime()
}

const OWN_RANK = (r) => (r.isMine ? 0 : r.unassigned ? 1 : 2)
/** THE task priority (CONTEXT.md "Task priority", amended Aug 2026) — used
 *  identically by every task surface: live due urgency (overdue → due soon),
 *  then ownership tiers among the equally urgent (yours → unowned →
 *  teammates'), then source-meeting recency. */
export function byPriority(a, b) {
  const ra = DUE_RANK[dueInfo(a.item, a.entry?.date).status] ?? 2
  const rb = DUE_RANK[dueInfo(b.item, b.entry?.date).status] ?? 2
  if (ra !== rb) return ra - rb
  if (OWN_RANK(a) !== OWN_RANK(b)) return OWN_RANK(a) - OWN_RANK(b)
  return new Date(b.entry.date).getTime() - new Date(a.entry.date).getTime()
}

/** Visual band for a row, aligned 1:1 with byPriority's DUE_RANK so banded
 *  rendering of a byPriority-sorted list is always contiguous. */
export function dueBand(row) {
  const rank = DUE_RANK[dueInfo(row.item, row.entry?.date).status] ?? 2
  return rank === 0 ? 'overdue' : rank === 1 ? 'soon' : 'open'
}

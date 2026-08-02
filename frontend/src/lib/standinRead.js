/**
 * Read-state for stand-in follow-up briefs.
 *
 * Lives here, not in ProxyProfile, because the sidebar badge (DashboardPage) and
 * the Stand-in page must agree on the key, and ProxyProfile is lazy-loaded — the
 * badge cannot import from it without pulling the whole view into the shell bundle.
 *
 * Scoped per user: an unscoped key meant a second account on the same browser
 * inherited the first account's read marks. Still DEVICE-local — there is no
 * server-side read flag, so reading a brief on your laptop leaves it unread on
 * your phone. Fixing that properly needs a column on proxy_representations.
 */

export const seenKeyFor = (userId) => `prismai:standin-briefs-seen:${userId || 'anon'}`

export function loadSeen(userId) {
  try {
    return new Set(JSON.parse(localStorage.getItem(seenKeyFor(userId)) || '[]'))
  } catch {
    return new Set()
  }
}

export function persistSeen(userId, set) {
  try {
    localStorage.setItem(seenKeyFor(userId), JSON.stringify([...set]))
  } catch {
    /* quota / private mode — read-state is best-effort */
  }
}

/** Fired when a brief is marked read, so the sidebar badge updates immediately. */
export const STANDIN_READ_EVENT = 'prism:standin-read'

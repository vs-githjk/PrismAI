// Pure state derivation for Home's Meeting hero (state-aware Home, Aug 2026 —
// see ADR 0002 amendment). Given the merged calendar events and whether the
// bot is live, decide what the hero shows:
//   'live' — Prism is in a call right now (bot recording/joining)
//   'now'  — the nearest event has already started (within the last hour)
//   'soon' — the nearest event starts within SOON_MINUTES (escalated treatment)
//   'next' — a future event exists beyond the soon window
//   'none' — nothing scheduled in the fetch window
// Pure and clock-injected so every state is unit-testable.

export const SOON_MINUTES = 30
const STARTED_GRACE_MINUTES = 60

export function minutesUntil(iso, now = new Date()) {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return Math.round((t - now.getTime()) / 60000)
}

/** Minutes of a meeting, from its start/end — null when either is missing. */
export function eventDurationMinutes(event) {
  if (!event?.start || !event?.end) return null
  const mins = minutesUntil(event.end, new Date(event.start))
  return mins !== null && mins > 0 ? mins : null
}

/**
 * @param events merged calendar events ({start, end, title, meeting_link, ...})
 * @returns {{ mode, event, minutes, others }} — `event` is the featured meeting
 *          (null for live/none), `others` the next 1-2 compact entries.
 */
export function deriveHeroState({ events = [], botLive = false, now = new Date() } = {}) {
  if (botLive) return { mode: 'live', event: null, minutes: null, others: [] }

  const dated = events
    .map((e) => ({ e, mins: minutesUntil(e.start, now) }))
    .filter(({ mins }) => mins !== null && mins >= -STARTED_GRACE_MINUTES)
    .sort((a, b) => a.mins - b.mins)

  if (!dated.length) return { mode: 'none', event: null, minutes: null, others: [] }

  const [{ e: nearest, mins }, ...rest] = dated
  const mode = mins <= 0 ? 'now' : mins <= SOON_MINUTES ? 'soon' : 'next'
  return { mode, event: nearest, minutes: mins, others: rest.slice(0, 2).map(({ e }) => e) }
}

/** "in 18 min" / "in 3h 05m" / "started 12 min ago" — the countdown label. */
export function countdownLabel(minutes) {
  if (minutes === null || minutes === undefined) return ''
  if (minutes <= 0) {
    const ago = -minutes
    return ago <= 1 ? 'started just now' : `started ${ago} min ago`
  }
  if (minutes < 60) return `in ${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `in ${h}h ${String(m).padStart(2, '0')}m` : `in ${h}h`
}

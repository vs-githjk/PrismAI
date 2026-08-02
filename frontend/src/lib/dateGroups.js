/**
 * Calendar-relative date buckets for grouping meetings by when they happened.
 *
 * The point: these are CALENDAR periods, not rolling day-counts. An earlier
 * version bucketed "< 30 days" as "This month", so on Aug 2 a meeting from Jul 17
 * was labelled "This month" — it is not in this month — and anything older
 * collapsed into a single "Earlier" pile of 41 items.
 *
 * The ladder, checked in order (first match wins, so the most specific label a
 * date qualifies for is the one it gets):
 *
 *   Today · Yesterday · This week · This month · Last month ·
 *   Last 6 months · This year · Older
 *
 * Ordering matters at boundaries: on Sunday Aug 2, a meeting from Thursday Jul 30
 * is in neither this calendar week nor this calendar month, so it lands in "Last
 * month" — correct, because July *is* last month. But a meeting from Tue Jul 28 in
 * a week that started Sun Jul 26 would be caught by "This week" first, which is
 * also what you want: recency beats the coarser label.
 *
 * Weeks start Sunday, matching the app's en-US locale and CalendarView's WEEKDAYS.
 */

export const BUCKET_ORDER = [
  'today', 'yesterday', 'week', 'month', 'lastMonth', 'sixMonths', 'year', 'older', 'undated',
]

const LABELS = {
  today: 'Today',
  yesterday: 'Yesterday',
  week: 'This week',
  month: 'This month',
  lastMonth: 'Last month',
  sixMonths: 'Last 6 months',
  year: 'This year',
  older: 'Older',
  undated: 'No date',
}

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

/**
 * @param {string|number|Date} dateValue
 * @param {Date|number} [nowValue] injectable for tests
 * @returns {{key: string, label: string, rank: number}}
 */
export function meetingBucket(dateValue, nowValue = new Date()) {
  const now = nowValue instanceof Date ? nowValue : new Date(nowValue)
  const bucket = (key) => ({ key, label: LABELS[key], rank: BUCKET_ORDER.indexOf(key) })
  // null/undefined/'' BEFORE constructing a Date: `new Date(null)` is epoch 0,
  // which is a perfectly finite timestamp, so a missing date would be filed under
  // "Older" (1970) instead of "No date". Same trap as `Number(null) === 0`.
  if (dateValue === null || dateValue === undefined || dateValue === '') return bucket('undated')
  const d = dateValue instanceof Date ? dateValue : new Date(dateValue)
  const t = d.getTime()
  if (!Number.isFinite(t)) return bucket('undated')

  const today = startOfDay(now)
  const day = startOfDay(d)

  if (day === today) return bucket('today')
  if (day === today - 86400000) return bucket('yesterday')

  // Current week, MONDAY-start (ISO). Not a rolling 7 days — that is the rolling-
  // window-labelled-as-a-calendar-period mistake this module exists to avoid — but
  // Monday start rather than Sunday for a real reason: on Sunday 2 Aug, a
  // Sunday-start week begins that same day, so Friday 31 Jul (two days earlier)
  // would skip "This week" and land in "Last month". ISO weeks treat Sunday as the
  // week's LAST day, so that week spans 27 Jul – 2 Aug and recent days read
  // naturally while 17 Jul still correctly reads "Last month".
  // Future-dated rows also land here rather than in a past bucket.
  const isoOffset = (now.getDay() + 6) % 7 // Mon=0 … Sun=6
  const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - isoOffset).getTime()
  if (day >= weekStart) return bucket('week')

  if (d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()) return bucket('month')

  // Previous calendar month, crossing a year boundary in January.
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  if (d.getFullYear() === prev.getFullYear() && d.getMonth() === prev.getMonth()) return bucket('lastMonth')

  // Six calendar months INCLUDING the current one, so with this month and last
  // month already claimed this covers the four before them.
  const sixStart = new Date(now.getFullYear(), now.getMonth() - 5, 1).getTime()
  if (day >= sixStart) return bucket('sixMonths')

  if (d.getFullYear() === now.getFullYear()) return bucket('year')
  return bucket('older')
}

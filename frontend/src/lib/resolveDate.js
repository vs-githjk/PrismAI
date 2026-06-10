// Client-side fallback for resolving a natural-language scheduling phrase
// ("next Monday at 9am") into a concrete date + time. Mirrors the backend
// calendar_resolution.py for the common cases, so the follow-up card can show
// a real date and pre-fill the Add-to-Calendar editor even when the saved
// meeting predates the backend resolver (or it left the fields blank).

const WEEKDAYS = { sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6 }
const TIME_OF_DAY = { morning: '09:00', noon: '12:00', midday: '12:00', afternoon: '14:00', evening: '17:00', night: '19:00' }

const pad = (n) => String(n).padStart(2, '0')
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const dayName = (d) => d.toLocaleDateString('en-US', { weekday: 'long' })

function nextWeekday(ref, targetDow, includeToday) {
  let delta = (targetDow - ref.getDay() + 7) % 7
  if (delta === 0 && !includeToday) delta = 7
  const d = new Date(ref)
  d.setDate(d.getDate() + delta)
  return d
}

function parseTime(lowered) {
  let m = /\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/.exec(lowered)
  if (m) {
    let h = parseInt(m[1], 10) % 12
    if (m[3] === 'pm') h += 12
    const min = m[2] ? parseInt(m[2], 10) : 0
    if (h >= 0 && h <= 23 && min >= 0 && min <= 59) return `${pad(h)}:${pad(min)}`
  }
  m = /\b([01]?\d|2[0-3]):([0-5]\d)\b/.exec(lowered)
  if (m) return `${pad(parseInt(m[1], 10))}:${m[2]}`
  for (const [word, clock] of Object.entries(TIME_OF_DAY)) {
    if (new RegExp(`\\b${word}\\b`).test(lowered)) return clock
  }
  return ''
}

function resolveDateOnly(lowered, ref) {
  for (const [name, dow] of Object.entries(WEEKDAYS)) {
    if (lowered.includes(`this ${name}`)) return nextWeekday(ref, dow, true)
    if (lowered.includes(`next ${name}`)) {
      const base = new Date(ref); base.setDate(base.getDate() + 7)
      return nextWeekday(base, dow, true)
    }
    if (new RegExp(`\\b${name}\\b`).test(lowered)) return nextWeekday(ref, dow, true)
  }
  if (/\bend of (the )?week\b/.test(lowered)) return nextWeekday(ref, 5, true) // Friday
  if (/\bend of (the )?month\b/.test(lowered)) {
    return new Date(ref.getFullYear(), ref.getMonth() + 1, 0)
  }
  let m = /\bin\s+(\d+)\s+day/.exec(lowered)
  if (m) { const d = new Date(ref); d.setDate(d.getDate() + parseInt(m[1], 10)); return d }
  m = /\bin\s+(\d+)\s+week/.exec(lowered)
  if (m) { const d = new Date(ref); d.setDate(d.getDate() + 7 * parseInt(m[1], 10)); return d }
  if (/\bin\s+(a|one)\s+month\b/.test(lowered) || /\bin\s+(\d+)\s+month/.test(lowered)) {
    const cnt = /\d+/.exec(lowered) ? parseInt(/\d+/.exec(lowered)[0], 10) : 1
    return new Date(ref.getFullYear(), ref.getMonth() + cnt, ref.getDate())
  }
  if (lowered.includes('next week')) { const d = new Date(ref); d.setDate(d.getDate() + 7); return d }
  if (lowered.includes('tomorrow')) { const d = new Date(ref); d.setDate(d.getDate() + 1); return d }
  if (lowered.includes('today')) return new Date(ref)
  // numeric M/D or M/D/YYYY
  m = /\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b/.exec(lowered)
  if (m) {
    const month = parseInt(m[1], 10) - 1, day = parseInt(m[2], 10)
    if (month >= 0 && month <= 11 && day >= 1 && day <= 31) {
      let year = m[3] ? parseInt(m[3], 10) : ref.getFullYear()
      if (year < 100) year += 2000
      let cand = new Date(year, month, day)
      if (!m[3] && cand < ref) cand = new Date(year + 1, month, day)
      return cand
    }
  }
  return null
}

/**
 * @returns {{date: string, day: string, time: string}} ISO date / weekday / "HH:MM"
 * Empty strings when the phrase can't be resolved.
 */
export function resolveDatePhrase(text, reference = new Date()) {
  const phrase = (text || '').trim()
  if (!phrase) return { date: '', day: '', time: '' }
  const lowered = phrase.toLowerCase()
  const ref = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate())
  const d = resolveDateOnly(lowered, ref)
  const time = parseTime(lowered)
  if (!d) return { date: '', day: '', time }
  return { date: toISO(d), day: dayName(d), time }
}

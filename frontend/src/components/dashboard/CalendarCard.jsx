import { useMemo, useState } from 'react'
import { CalendarPlus, Check, ExternalLink, Plus } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { cardGlowStyle, glassCard } from './dashboardStyles'
import DatePopover from './DatePopover'
import TimePopover from './TimePopover'
import { resolveDatePhrase } from '../../lib/resolveDate'

function formatResolvedDate(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Best-effort "HH:MM" extracted from the source meeting's timestamp — used as a
// fallback start time when the follow-up didn't name a specific time.
function timeFromMeetingDate(value) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (hh === '00' && mm === '00') return '' // date-only timestamp, no real time
  return `${hh}:${mm}`
}

export default function CalendarCard({ suggestion, meetingDate = null, meetingTitle = '', readOnly = false, defaultEmails = [], suggestedEmails = [] }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const [invitees, setInvitees] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState(null) // { link }
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(null) // { type: 'duplicate'|'overlap', events: [] }

  // Resolve a concrete date/time for display + prefill. Prefer the backend's
  // resolved fields; fall back to client-side parsing of the timeframe phrase
  // (covers seed/older meetings the backend resolver never populated).
  const fallback = useMemo(
    () => resolveDatePhrase(suggestion?.suggested_timeframe || suggestion?.reason || ''),
    [suggestion?.suggested_timeframe, suggestion?.reason],
  )

  // calendar_suggester now always runs (routing is deterministic), so only
  // surface the card when it actually recommends a follow-up — not for the
  // "no follow-up needed" case.
  if (!suggestion?.recommended) return null

  const effDate = suggestion.resolved_date || fallback.date
  const effDay = suggestion.resolved_day || fallback.day
  const effTime = suggestion.resolved_time || fallback.time

  const formatTime12 = (hhmm) => {
    const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm || '')
    if (!m) return ''
    const h = +m[1]
    return `${h % 12 || 12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`
  }

  const resolvedLabel = [effDay, formatResolvedDate(effDate)].filter(Boolean).join(' · ')
  const agenda = suggestion.agenda || []
  const attendees = suggestion.attendees || []

  function openEditor() {
    const today = new Date().toISOString().slice(0, 10)
    setTitle(`Follow-up: ${meetingTitle || 'meeting'}`)
    setDate(effDate || today)
    // Time priority: what the meeting named → same time as this meeting → 10:00.
    setTime(effTime || timeFromMeetingDate(meetingDate) || '10:00')
    setInvitees((defaultEmails || []).join(', '))
    setError('')
    setCreated(null)
    setConflict(null)
    setOpen(true)
  }

  async function createEvent(confirm = false) {
    setError('')
    if (!date || !time) { setError('Pick a date and time.'); return }
    setBusy(true)
    try {
      const start = `${date}T${time}:00`
      const emails = invitees.split(/[\s,;]+/).map(e => e.trim()).filter(e => e.includes('@'))
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      const res = await apiFetch('/calendar/create-event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim() || 'Follow-up meeting',
          start,
          description: agenda.length ? agenda.map(a => `• ${a}`).join('\n') : (suggestion.reason || ''),
          attendees: emails,
          timezone: tz,
          confirm,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        if (res.status === 404) setError('Connect Google Calendar first (Integrations).')
        else setError(data.detail || 'Could not create the event.')
        return
      }
      const data = await res.json()
      if (data.conflict) { setConflict({ type: data.type, events: data.events || [] }); return }
      setConflict(null)
      setCreated({ link: data.link })
    } catch {
      setError('Network error — try again.')
    } finally {
      setBusy(false)
    }
  }

  function addInvitee(email) {
    const current = invitees.split(/[\s,;]+/).map(e => e.trim()).filter(Boolean)
    if (current.includes(email)) return
    setInvitees([...current, email].join(', '))
  }

  // Teammates not already added — offered as one-click chips under the field.
  const currentEmails = invitees.split(/[\s,;]+/).map(e => e.trim()).filter(Boolean)
  const availableSuggestions = (suggestedEmails || []).filter(e => e && !currentEmails.includes(e))

  return (
    <section className={`${glassCard} p-5`} style={cardGlowStyle}>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-bold tracking-[-0.01em] text-white">Follow-up meeting</h2>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
            suggestion.recommended
              ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
              : 'border-white/[0.10] bg-white/[0.04] text-white/50'
          }`}
        >
          {suggestion.recommended ? 'Recommended' : 'Optional'}
        </span>
      </div>

      {suggestion.suggested_timeframe && (
        <p className="text-[15px] font-semibold leading-snug text-white">
          {suggestion.suggested_timeframe}
          {resolvedLabel && <span className="ml-2 text-xs font-medium text-white/45">{resolvedLabel}</span>}
          {effTime && <span className="ml-1.5 text-xs font-medium text-cyan-300/80">{formatTime12(effTime)}</span>}
        </p>
      )}
      <p className="mt-2 text-sm leading-7 text-white/75">{suggestion.reason}</p>

      {suggestion.time_defaulted && !created && (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-2.5 py-1.5 text-[11.5px] leading-relaxed text-amber-200/90">
          <span className="mt-px">⚠</span>
          <span>No time was set in the meeting. Suggested slot: <span className="font-medium text-amber-100">{resolvedLabel}{effTime ? ` · ${formatTime12(effTime)}` : ''}</span> — confirm or change it before adding.</span>
        </p>
      )}

      {agenda.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-white/35">Proposed agenda</p>
          <ul className="space-y-1">
            {agenda.map((item, i) => (
              <li key={i} className="flex gap-2 text-[13px] leading-6 text-white/80">
                <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-cyan-300/70" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {attendees.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-white/35">Attendees</span>
          {attendees.map((name, i) => (
            <span key={i} className="rounded-full border border-white/[0.10] bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/70">
              {name}
            </span>
          ))}
        </div>
      )}

      {!readOnly && (
        <div className="mt-4">
          {created ? (
            <div className="flex items-center gap-2 text-[13px] font-medium text-emerald-300">
              <Check className="h-4 w-4" /> Event created.
              {created.link && (
                <a href={created.link} target="_blank" rel="noreferrer"
                   className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200">
                  Open <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}
            </div>
          ) : open ? (
            <div className="space-y-2.5 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
              <input
                value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Event title"
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 outline-none focus:border-cyan-400/40"
              />
              <div className="flex gap-2">
                <div className="min-w-0 flex-1">
                  <DatePopover value={date} onChange={(v) => { setDate(v); setConflict(null) }} />
                </div>
                <TimePopover value={time} onChange={(v) => { setTime(v); setConflict(null) }} />
              </div>
              <input
                value={invitees} onChange={(e) => setInvitees(e.target.value)}
                placeholder="Invite (emails, comma-separated) — optional"
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40"
              />
              {availableSuggestions.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10.5px] text-white/35">Teammates:</span>
                  {availableSuggestions.map((email) => (
                    <button
                      key={email}
                      type="button"
                      onClick={() => addInvitee(email)}
                      className="inline-flex items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/70 transition hover:border-cyan-400/40 hover:text-cyan-200"
                    >
                      <Plus className="h-3 w-3" /> {email}
                    </button>
                  ))}
                </div>
              )}
              {error && <p className="text-[11px] text-red-400">{error}</p>}
              {conflict && (
                <div className="rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-200/90">
                  <p className="font-medium text-amber-100">
                    {conflict.type === 'duplicate'
                      ? 'You already have this event at that time.'
                      : `You have ${conflict.events.length === 1 ? 'an event' : 'events'} that overlap this slot:`}
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {conflict.events.slice(0, 3).map((e, i) => (
                      <li key={i} className="text-amber-200/80">
                        • {e.title}{e.start ? ` — ${new Date(e.start).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit' })}` : ''}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-amber-200/70">Create it anyway, or change the time above.</p>
                </div>
              )}
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => createEvent(!!conflict)} disabled={busy}
                  className="rounded-full border border-cyan-400/30 bg-cyan-400/[0.10] px-3.5 py-1.5 text-[12px] font-semibold text-cyan-200 transition hover:bg-cyan-400/[0.18] disabled:opacity-50">
                  {busy ? 'Creating…' : conflict ? 'Create anyway' : 'Create event'}
                </button>
                <button type="button" onClick={() => setOpen(false)} disabled={busy}
                  className="rounded-full border border-white/[0.12] bg-white/[0.04] px-3.5 py-1.5 text-[12px] font-semibold text-white/70 transition hover:bg-white/[0.08]">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={openEditor}
              className="inline-flex items-center gap-2 rounded-full border border-cyan-400/30 bg-cyan-400/[0.08] px-3.5 py-1.5 text-[12px] font-semibold text-cyan-200 transition hover:bg-cyan-400/[0.16]">
              <CalendarPlus className="h-4 w-4" /> Add to Calendar
            </button>
          )}
        </div>
      )}
    </section>
  )
}

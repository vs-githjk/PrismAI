import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, CalendarPlus, ChevronDown, Radio, UserRound, Video } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { fetchMergedEvents, matchWorkspace, BriefPanel } from '../UpcomingMeetings'
import { deriveHeroState, countdownLabel, eventDurationMinutes } from '../../lib/meetingHero'
import { cardGlowStyle, glassCard } from './dashboardStyles'

const timeOf = (iso) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}
const dayOf = (iso, now = new Date()) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  if (d.toDateString() === now.toDateString()) return ''
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1)
  if (d.toDateString() === tomorrow.toDateString()) return 'Tomorrow'
  return d.toLocaleDateString([], { weekday: 'short' })
}

/**
 * Home's state-aware Meeting hero (ADR 0002 amendment): the single most
 * time-sensitive meeting, full width, above the columns.
 *   live → Prism is in a call: one line + Open live view
 *   now/soon → escalated countdown, Join dominant
 *   next → countdown, time, participants, Join / View context / Send Stand-in
 *   none → one compact status row, never a large empty card
 * The next 1-2 events ride along as compact rows. Countdown re-derives every
 * 30s from cached events; events refetch every 5 minutes.
 */
export default function MeetingHero({
  enabled = false,
  user = null,
  workspaces = [],
  botLive = false,
  liveAvailable = false,
  onOpenLive,
  onJoinEvent,
  onCantMakeIt,
  onOpenMeeting,
  onOpenCalendar,
  showConnectCalendar = false,
  onConnectCalendar,
}) {
  const [events, setEvents] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [, setTick] = useState(0)
  const [briefOpen, setBriefOpen] = useState(false)
  const [brief, setBrief] = useState(null)

  useEffect(() => {
    if (!enabled) { setLoaded(true); return undefined }
    let cancelled = false
    const load = async () => {
      const { events: merged } = await fetchMergedEvents()
      if (!cancelled) { setEvents(merged); setLoaded(true) }
    }
    load()
    const refetch = setInterval(load, 5 * 60_000)
    return () => { cancelled = true; clearInterval(refetch) }
  }, [enabled])

  // The countdown must move without a refetch.
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 30_000)
    return () => clearInterval(t)
  }, [])

  const { mode, event, minutes, others } = deriveHeroState({ events, botLive })
  const matchedWs = event ? matchWorkspace(event.attendee_emails, workspaces) : null

  const toggleBrief = useCallback(async () => {
    setBriefOpen((open) => !open)
    if (brief || !matchedWs) return
    setBrief({ loading: true })
    try {
      const res = await apiFetch(`/workspaces/${matchedWs.id}/brief`)
      if (!res.ok) throw new Error('failed')
      const data = await res.json()
      setBrief({ loading: false, items: data.open_items || [] })
    } catch {
      setBrief({ loading: false, items: [], error: true })
    }
  }, [brief, matchedWs])

  // ---- live: Prism is in the call right now ----
  if (mode === 'live') {
    return (
      <section className={`${glassCard} flex items-center gap-3 px-5 py-4`} style={cardGlowStyle}>
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-rose-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-rose-300/90">Live now</p>
          <p className="truncate text-[15px] font-semibold text-[color:var(--db-text)]">Prism is in your meeting</p>
        </div>
        {liveAvailable && (
          <button
            type="button"
            onClick={onOpenLive}
            className="inline-flex h-10 shrink-0 items-center gap-2 rounded-full bg-cyan-400 px-5 text-sm font-semibold text-[#04222a] transition hover:bg-cyan-300"
          >
            <Radio className="h-4 w-4" aria-hidden="true" />
            Open live view
          </button>
        )}
      </section>
    )
  }

  // ---- none: one compact status row — never a big empty card ----
  if (mode === 'none') {
    return (
      <section className={`${glassCard} flex flex-wrap items-center gap-3 px-5 py-3`} style={cardGlowStyle}>
        <CalendarDays className="h-4 w-4 shrink-0 text-[color:var(--db-text-faint)]" aria-hidden="true" />
        <p className="min-w-0 flex-1 truncate text-[13px] text-[color:var(--db-text-muted)]">
          {!enabled && showConnectCalendar
            ? 'Connect your calendar to see the next meeting here.'
            : loaded ? 'No upcoming meetings.' : 'Checking your calendar…'}
        </p>
        {!enabled && showConnectCalendar ? (
          <button
            type="button"
            onClick={onConnectCalendar}
            className="inline-flex shrink-0 items-center gap-1.5 text-[12.5px] font-semibold text-cyan-300 transition hover:text-cyan-200"
          >
            <CalendarPlus className="h-3.5 w-3.5" aria-hidden="true" />
            Connect →
          </button>
        ) : (
          <button
            type="button"
            onClick={onOpenCalendar}
            className="shrink-0 text-[12.5px] font-medium text-[color:var(--db-text-faint)] transition hover:text-cyan-200"
          >
            Open calendar →
          </button>
        )}
      </section>
    )
  }

  // ---- now / soon / next: the featured meeting ----
  const urgent = mode === 'now' || mode === 'soon'
  const participants = (event.attendee_emails || []).length
  const duration = eventDurationMinutes(event)
  const canStandIn = !!user && minutes !== null && minutes >= -60

  return (
    <section className={`${glassCard} overflow-hidden`} style={cardGlowStyle}>
      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <p className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${urgent ? 'text-cyan-300' : 'text-[color:var(--db-text-faint)]'}`}>
            {mode === 'now' ? 'Happening now' : 'Next meeting'}
            <span className={urgent ? 'text-cyan-200' : ''}> · {countdownLabel(minutes)}</span>
            {urgent && <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400 align-middle" />}
          </p>
          <h2 className={`mt-1 truncate font-semibold tracking-[-0.015em] text-[color:var(--db-text)] ${urgent ? 'text-[24px]' : 'text-[20px]'}`}>
            {event.title || 'Upcoming meeting'}
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12.5px] text-[color:var(--db-text-muted)]">
            <span>
              {dayOf(event.start) && `${dayOf(event.start)} · `}
              {timeOf(event.start)}{event.end ? `–${timeOf(event.end)}` : ''}
            </span>
            {duration && <span className="text-[color:var(--db-text-faint)]">{duration} min</span>}
            {participants > 0 && (
              <span className="inline-flex items-center gap-1 text-[color:var(--db-text-faint)]">
                <UserRound className="h-3 w-3" aria-hidden="true" />{participants} participant{participants === 1 ? '' : 's'}
              </span>
            )}
            {matchedWs && (
              <span className="rounded-md border border-cyan-400/[0.18] bg-cyan-400/[0.10] px-1.5 py-0.5 text-[10px] font-medium text-cyan-200">
                {matchedWs.name}
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {event.meeting_link && (
            <button
              type="button"
              onClick={() => onJoinEvent?.(event.meeting_link, matchedWs?.id ?? null)}
              className={`inline-flex items-center gap-2 rounded-full font-semibold transition ${
                urgent
                  ? 'h-11 bg-cyan-400 px-6 text-sm text-[#04222a] shadow-sm hover:bg-cyan-300'
                  : 'h-10 border border-cyan-400/40 bg-cyan-400/[0.12] px-5 text-[13px] text-cyan-200 hover:bg-cyan-400/[0.2]'
              }`}
            >
              <Video className="h-4 w-4" aria-hidden="true" />
              Join meeting
            </button>
          )}
          {matchedWs && (
            <button
              type="button"
              onClick={toggleBrief}
              aria-expanded={briefOpen}
              className="inline-flex h-10 items-center gap-1.5 rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill)] px-4 text-[13px] font-medium text-[color:var(--db-text-soft)] transition hover:bg-[var(--db-fill-strong)]"
            >
              View context
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${briefOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
            </button>
          )}
          {canStandIn && (
            <button
              type="button"
              onClick={() => onCantMakeIt?.({
                url: event.meeting_link,
                label: event.title,
                workspaceId: matchedWs?.id ?? null,
                scheduledFor: event.start,
              })}
              title="Can't make it? Prism joins and speaks for you"
              className="inline-flex h-10 items-center rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill)] px-4 text-[13px] font-medium text-[color:var(--db-text-soft)] transition hover:bg-[var(--db-fill-strong)]"
            >
              Send Stand-in
            </button>
          )}
        </div>
      </div>

      {briefOpen && matchedWs && (
        <BriefPanel state={brief} workspaceName={matchedWs.name} onItemClick={onOpenMeeting} />
      )}

      {others.length > 0 && (
        <div className="border-t border-[color:var(--db-border)] px-5 py-2">
          {others.map((ev) => (
            <div key={ev.id || ev.start} className="flex items-center gap-3 py-1">
              <span className="w-[74px] shrink-0 text-[11.5px] tabular-nums text-[color:var(--db-text-faint)]">
                {dayOf(ev.start) ? `${dayOf(ev.start)} ` : ''}{timeOf(ev.start)}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-[color:var(--db-text-muted)]">{ev.title}</span>
              {ev.meeting_link && (
                <button
                  type="button"
                  onClick={() => onJoinEvent?.(ev.meeting_link, matchWorkspace(ev.attendee_emails, workspaces)?.id ?? null)}
                  className="shrink-0 text-[11.5px] font-semibold text-cyan-300/80 transition hover:text-cyan-200"
                >
                  Join
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

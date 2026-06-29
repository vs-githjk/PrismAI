import { useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../lib/api'
import { dueInfo, dueLabel, compareDue } from '../lib/dueStatus'

const BRIEF_DUE_STYLE = {
  overdue: { color: '#fca5a5', bg: 'rgba(248,113,113,0.12)', border: 'rgba(248,113,113,0.30)' },
  soon: { color: '#fcd34d', bg: 'rgba(251,191,36,0.12)', border: 'rgba(251,191,36,0.30)' },
}

function useMarkedEvents() {
  const [marked, setMarked] = useState(
    () => new Set(JSON.parse(localStorage.getItem('prism_marked_events') || '[]'))
  )
  const toggle = useCallback((id) => {
    setMarked(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      localStorage.setItem('prism_marked_events', JSON.stringify([...next]))
      return next
    })
  }, [])
  return [marked, toggle]
}

function formatEventTime(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  const isTomorrow = d.toDateString() === tomorrow.toDateString()

  const timeStr = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (isToday) return `Today ${timeStr}`
  if (isTomorrow) return `Tomorrow ${timeStr}`
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ` ${timeStr}`
}

function minutesUntil(isoString) {
  if (!isoString) return null
  return Math.round((new Date(isoString) - new Date()) / 60000)
}

function MeetingLinkIcon({ link }) {
  if (!link) return null
  const lower = link.toLowerCase()
  if (lower.includes('zoom.us')) return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
      style={{ background: 'rgba(45,140,255,0.12)', color: '#60a5fa' }}>Zoom</span>
  )
  if (lower.includes('meet.google')) return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
      style={{ background: 'rgba(52,168,83,0.12)', color: '#4ade80' }}>Meet</span>
  )
  if (lower.includes('teams.microsoft') || lower.includes('teams.live')) return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
      style={{ background: 'rgba(98,100,167,0.18)', color: '#a5b4fc' }}>Teams</span>
  )
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
      style={{ background: 'rgba(255,255,255,0.07)', color: '#94a3b8' }}>Link</span>
  )
}

function formatRelativeDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.round((Date.now() - d.getTime()) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  if (days < 14) return 'last week'
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function BriefPanel({ state, workspaceName, onItemClick }) {
  if (!state || state.loading) {
    return (
      <div className="px-3 pb-3 pt-1">
        <div className="rounded-lg px-3 py-2 text-[10px] text-gray-500"
          style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
          Loading brief…
        </div>
      </div>
    )
  }
  if (state.error) {
    return (
      <div className="px-3 pb-3 pt-1">
        <div className="rounded-lg px-3 py-2 text-[10px] text-red-300/80"
          style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)' }}>
          Couldn't load brief.
        </div>
      </div>
    )
  }
  // Attach deadline status (client fallback covers items analyzed before
  // due-date resolution shipped) and re-sort overdue/soonest first.
  const items = (state.items || [])
    .map((item) => ({ ...item, _due: dueInfo(item) }))
    .sort((a, b) => compareDue(a._due, b._due))
  if (items.length === 0) {
    return (
      <div className="px-3 pb-3 pt-1">
        <div className="rounded-lg px-3 py-2 text-[10px] text-emerald-300/80"
          style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.16)' }}>
          All clear — no open items from recent {workspaceName} meetings.
        </div>
      </div>
    )
  }
  return (
    <div className="px-3 pb-3 pt-1">
      <div className="rounded-lg overflow-hidden"
        style={{ background: 'rgba(34,211,238,0.03)', border: '1px solid rgba(34,211,238,0.14)' }}>
        <div className="px-3 py-1.5 flex items-center justify-between"
          style={{ borderBottom: '1px solid rgba(34,211,238,0.10)' }}>
          <span className="text-[10px] font-semibold tracking-wide text-cyan-200/80">
            {items.length} open from {workspaceName}
          </span>
        </div>
        <ul className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
          {items.map((item, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => item.meeting_id && onItemClick?.(item.meeting_id)}
                disabled={!item.meeting_id || !onItemClick}
                className="w-full text-left px-3 py-2 flex items-start gap-2 hover:bg-cyan-400/[0.04] transition-colors disabled:cursor-default disabled:hover:bg-transparent">
                <span className="text-orange-400 text-[10px] mt-0.5 flex-shrink-0">○</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-[11px] text-gray-200 leading-snug">{item.task}</p>
                    {(item._due?.status === 'overdue' || item._due?.status === 'soon') && (
                      <span
                        className="shrink-0 rounded-full px-1.5 py-0.5 text-[8.5px] font-semibold uppercase tracking-wide"
                        style={{
                          color: BRIEF_DUE_STYLE[item._due.status].color,
                          background: BRIEF_DUE_STYLE[item._due.status].bg,
                          border: `1px solid ${BRIEF_DUE_STYLE[item._due.status].border}`,
                        }}
                      >
                        {dueLabel(item._due)}
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-gray-600 mt-0.5 truncate">
                    {[item.owner, item.due, item.meeting_title]
                      .filter(Boolean)
                      .concat([formatRelativeDate(item.meeting_date)].filter(Boolean))
                      .join(' · ')}
                  </p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function matchWorkspace(attendeeEmails, workspaces) {
  if (!attendeeEmails?.length || !workspaces?.length) return null
  const emailSet = new Set(attendeeEmails.map(e => e.toLowerCase()))
  let best = null
  let bestOverlap = 0
  for (const ws of workspaces) {
    const overlap = (ws.member_emails || []).filter(e => emailSet.has(e.toLowerCase())).length
    if (overlap > bestOverlap) { bestOverlap = overlap; best = ws }
  }
  return bestOverlap > 0 ? best : null
}

export default function UpcomingMeetings({ onJoin, workspaces = [], onOpenMeeting, user = null, onCantMakeIt }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const [marked, toggleMark] = useMarkedEvents()
  // Brief state — keyed by event.id. Each value: { loading, items, error }
  const [briefs, setBriefs] = useState({})
  const [expandedBriefId, setExpandedBriefId] = useState(null)

  const loadBrief = useCallback(async (eventId, workspaceId) => {
    if (briefs[eventId]?.items || briefs[eventId]?.loading) return
    setBriefs(prev => ({ ...prev, [eventId]: { loading: true } }))
    try {
      const res = await apiFetch(`/workspaces/${workspaceId}/brief`)
      if (!res.ok) throw new Error('Failed')
      const data = await res.json()
      setBriefs(prev => ({ ...prev, [eventId]: { loading: false, items: data.open_items || [] } }))
    } catch {
      setBriefs(prev => ({ ...prev, [eventId]: { loading: false, items: [], error: true } }))
    }
  }, [briefs])

  const toggleBrief = useCallback((eventId, workspaceId) => {
    setExpandedBriefId(prev => {
      const next = prev === eventId ? null : eventId
      if (next) loadBrief(eventId, workspaceId)
      return next
    })
  }, [loadBrief])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch('/calendar/events?days_ahead=3')
      if (res.status === 401) {
        setError('reconnect')
        return
      }
      if (!res.ok) throw new Error('Failed to load calendar')
      const data = await res.json()
      setEvents(data.events || [])
    } catch {
      setError('load')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function EmptyState({ title, message, actionLabel, onAction }) {
    return (
      <div className="rounded-xl px-3 py-3"
        style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ background: 'rgba(148,163,184,0.18)' }} />
          <span className="text-[11px] font-medium text-gray-400">{title}</span>
        </div>
        <p className="text-[11px] text-gray-500 mt-2">{message}</p>
        {actionLabel && onAction && (
          <button
            onClick={onAction}
            className="mt-2 text-[10px] font-medium px-2.5 py-1.5 rounded-lg"
            style={{ background: 'rgba(14,165,233,0.12)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.18)' }}
          >
            {actionLabel}
          </button>
        )}
      </div>
    )
  }

  if (error === 'reconnect') {
    return (
      <EmptyState
        title="Upcoming meetings"
        message="Reconnect Google Calendar to load upcoming meetings with supported join links."
        actionLabel="Retry"
        onAction={load}
      />
    )
  }

  if (error === 'load') {
    return (
      <EmptyState
        title="Upcoming meetings"
        message="Could not load upcoming meetings right now. You can still paste a meeting link manually."
        actionLabel="Retry"
        onAction={load}
      />
    )
  }

  if (loading) return (
    <div className="rounded-xl px-3 py-2.5 flex items-center gap-2"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <div className="w-3 h-3 rounded-full animate-pulse" style={{ background: 'rgba(255,255,255,0.15)' }} />
      <span className="text-[11px] text-gray-600">Loading calendar…</span>
    </div>
  )

  // Only show events with meeting links (others aren't actionable here)
  const joinable = events.filter(e => e.has_meeting_link)
  if (joinable.length === 0) {
    return (
      <EmptyState
        title="Upcoming meetings"
        message="No upcoming meetings with supported join links right now."
      />
    )
  }

  return (
    <div className="rounded-xl overflow-hidden"
      style={{ border: '1px solid rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.015)' }}>

      {/* Header */}
      <button
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/[0.02] transition-colors"
        onClick={() => setCollapsed(v => !v)}
      >
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-sky-400/80" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          <span className="text-[11px] font-medium text-gray-400">Upcoming meetings</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full text-sky-400/80"
            style={{ background: 'rgba(14,165,233,0.1)' }}>{joinable.length}</span>
        </div>
        <svg className={`w-3 h-3 text-gray-600 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
          <polyline points="18 15 12 9 6 15"/>
        </svg>
      </button>

      {/* Events list */}
      {!collapsed && (
        <div className="divide-y" style={{ borderTop: '1px solid rgba(255,255,255,0.05)', borderColor: 'rgba(255,255,255,0.05)' }}>
          {joinable.map(event => {
            const mins = minutesUntil(event.start)
            const isNow = mins !== null && mins >= -60 && mins <= 15
            const matchedWs = matchWorkspace(event.attendee_emails, workspaces)
            const briefExpanded = expandedBriefId === event.id
            const briefState = briefs[event.id]
            return (
              <div key={event.id}
                style={isNow ? { background: 'rgba(14,165,233,0.04)' } : {}}>
                <div className="px-3 py-2.5 group">

                  {/* Top: dot + info (full width) + mark star */}
                  <div className="flex items-start gap-2.5">
                    <div className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${isNow ? 'bg-sky-400 animate-pulse' : 'bg-gray-700'}`} />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-[11.5px] font-medium text-gray-200 truncate">{event.title}</span>
                        <MeetingLinkIcon link={event.meeting_link} />
                        {matchedWs ? (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
                            style={{ background: 'rgba(34,211,238,0.10)', color: '#67e8f9', border: '1px solid rgba(34,211,238,0.18)' }}>
                            {matchedWs.name}
                          </span>
                        ) : (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-md"
                            style={{ background: 'rgba(255,255,255,0.06)', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.10)' }}>
                            Personal
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-gray-600 mt-0.5 whitespace-nowrap">
                        {formatEventTime(event.start)}
                        {mins !== null && mins > 0 && mins < 60 && (
                          <span className="ml-1 text-sky-500/80">· in {mins}m</span>
                        )}
                        {mins !== null && mins <= 0 && mins > -60 && (
                          <span className="ml-1 text-emerald-500/80">· in progress</span>
                        )}
                      </p>
                    </div>

                    {/* Mark star */}
                    <button
                      onClick={() => toggleMark(event.id)}
                      aria-label={marked.has(event.id) ? 'Unmark event' : 'Mark for auto-join'}
                      className="flex-shrink-0 p-1 rounded-md transition-all"
                      style={{ color: marked.has(event.id) ? '#fbbf24' : 'transparent', opacity: marked.has(event.id) ? 1 : undefined }}
                      title={marked.has(event.id) ? 'Marked for auto-join' : 'Mark for auto-join'}>
                      <svg
                        className={`w-3.5 h-3.5 transition-all group-hover:opacity-100 ${marked.has(event.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-40'}`}
                        viewBox="0 0 24 24"
                        fill={marked.has(event.id) ? 'currentColor' : 'none'}
                        stroke="currentColor" strokeWidth="2">
                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                      </svg>
                    </button>
                  </div>

                  {/* Actions row — own line so nothing gets squeezed */}
                  <div className="mt-2 flex items-center justify-end gap-1.5">
                    {matchedWs && (
                      <button
                        onClick={() => toggleBrief(event.id, matchedWs.id)}
                        aria-label="View workspace brief"
                        aria-expanded={briefExpanded}
                        className="text-[10px] font-medium px-2 py-1.5 rounded-lg transition-all flex items-center gap-1"
                        style={{
                          background: briefExpanded ? 'rgba(34,211,238,0.18)' : 'rgba(255,255,255,0.04)',
                          color: briefExpanded ? '#67e8f9' : '#94a3b8',
                          border: `1px solid ${briefExpanded ? 'rgba(34,211,238,0.3)' : 'rgba(255,255,255,0.10)'}`,
                        }}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                        </svg>
                        Brief
                      </button>
                    )}

                    {/* Can't make it → stand-in. Only ≥10 min out (scheduled join needs join_at >10 min ahead). */}
                    {user && mins !== null && mins >= 10 && (
                      <button
                        onClick={() => onCantMakeIt?.({
                          url: event.meeting_link,
                          label: event.title,
                          workspaceId: matchedWs?.id ?? null,
                          scheduledFor: event.start,
                        })}
                        aria-label={`Can't make ${event.title} — have Prism represent you`}
                        title="Can't make it? Have Prism represent you"
                        className="text-[10px] font-medium px-2.5 py-1.5 rounded-lg transition-all"
                        style={{ background: 'rgba(255,255,255,0.04)', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.10)' }}>
                        Can't make it
                      </button>
                    )}

                    <button
                      onClick={() => onJoin(event.meeting_link, matchedWs?.id ?? null)}
                      aria-label={`Join ${event.title} with PrismAI`}
                      className="text-[10px] font-medium px-2.5 py-1.5 rounded-lg transition-all"
                      style={{ background: 'rgba(14,165,233,0.15)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                      Join
                    </button>
                  </div>
                </div>

                {/* Inline brief panel */}
                {briefExpanded && matchedWs && (
                  <BriefPanel
                    state={briefState}
                    workspaceName={matchedWs.name}
                    onItemClick={onOpenMeeting}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

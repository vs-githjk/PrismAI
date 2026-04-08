import { useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../lib/api'

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

export default function UpcomingMeetings({ onJoin }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const [marked, toggleMark] = useMarkedEvents()

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
            return (
              <div key={event.id}
                className="px-3 py-2.5 flex items-center gap-2.5 group"
                style={isNow ? { background: 'rgba(14,165,233,0.04)' } : {}}>

                {/* Status dot */}
                <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isNow ? 'bg-sky-400 animate-pulse' : 'bg-gray-700'}`} />

                {/* Event info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[11px] font-medium text-gray-300 truncate">{event.title}</span>
                    <MeetingLinkIcon link={event.meeting_link} />
                  </div>
                  <p className="text-[10px] text-gray-600 mt-0.5">
                    {formatEventTime(event.start)}
                    {mins !== null && mins > 0 && mins < 60 && (
                      <span className="ml-1 text-sky-500/80">· in {mins}m</span>
                    )}
                    {mins !== null && mins <= 0 && mins > -60 && (
                      <span className="ml-1 text-emerald-500/80">· now</span>
                    )}
                  </p>
                </div>

                {/* Mark button */}
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

                {/* Join button */}
                <button
                  onClick={() => onJoin(event.meeting_link)}
                  aria-label={`Join ${event.title} with PrismAI`}
                  className="flex-shrink-0 text-[10px] font-medium px-2.5 py-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                  style={{ background: 'rgba(14,165,233,0.15)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                  Join
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

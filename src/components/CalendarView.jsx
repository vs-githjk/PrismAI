import { useState, useMemo, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { apiFetch } from '../lib/api'
import {
  ChevronLeft, ChevronRight, CalendarDays, CircleDot, Clock, Activity,
  ListTodo, Users, Filter,
} from 'lucide-react'
import { overallHealth } from '../lib/healthScore'
import { deriveDisplayTitle } from '../lib/insights'

/**
 * Calendar view of meeting history (v2). Month / Week / Day, health-tinted chips,
 * filters, an insights side rail, hover previews, and an optional upcoming-events
 * overlay from the Google Calendar integration. Read-only — this is history, not a
 * planner, so no editing affordances. (No list view — that's what Home is.)
 */

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MAX_CHIPS = 3
const HOUR_PX = 46          // pixel height of one hour row in week/day
const BLOCK_PX = 34         // height of a meeting block (point-in-time, no duration)

function healthColor(score) {
  const v = Number(score)
  if (!Number.isFinite(v)) return '#94a3b8'
  if (v < 30) return '#ef4444'
  if (v < 60) return '#f59e0b'
  return '#22c55e'
}
function healthBucket(score) {
  const v = Number(score)
  if (!Number.isFinite(v)) return 'unknown'
  if (v < 30) return 'strained'
  if (v < 60) return 'mixed'
  return 'healthy'
}
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const fmtTime = (d) => (d.getHours() === 0 && d.getMinutes() === 0)
  ? '' : d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })

function toEntry(m) {
  return { id: m.id, date: new Date(m.date), title: deriveDisplayTitle(m), health: overallHealth(m.result?.health_score), result: m.result || {} }
}
const hasOpenActions = (e) => (e.result.action_items || []).some((a) => !a.completed && (a.task || '').trim())

export default function CalendarView({ history = [], onOpenMeeting, workspaceName = null, calendarConnected = false }) {
  const today = new Date()
  // Cursor is the focused date (defaults to today, so Week/Day open on the current
  // week/day). Month view only reads its year+month; Week/Day read the full date.
  const [cursor, setCursor] = useState(() => new Date())
  const [view, setView] = useState('month') // month | week | day
  const [filters, setFilters] = useState({ health: new Set(['healthy', 'mixed', 'strained']), openOnly: false })
  const [expandedDay, setExpandedDay] = useState(null)
  const [hover, setHover] = useState(null) // { entry, x, y }
  const [upcoming, setUpcoming] = useState([])

  const year = cursor.getFullYear()
  const month = cursor.getMonth()

  // Upcoming events overlay (future) from the calendar integration.
  useEffect(() => {
    if (!calendarConnected) { setUpcoming([]); return }
    let alive = true
    apiFetch('/calendar/events?days_ahead=45')
      .then((r) => (r.ok ? r.json() : { events: [] }))
      .then((d) => {
        if (!alive) return
        const evs = (d.events || [])
          .map((e, i) => ({ id: `evt-${i}`, date: new Date(e.start), title: e.title || 'Event', upcoming: true, link: e.meeting_link }))
          .filter((e) => !Number.isNaN(e.date.getTime()))
        setUpcoming(evs)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [calendarConnected])

  const matches = (e) => {
    const b = healthBucket(e.health)
    if (b !== 'unknown' && !filters.health.has(b)) return false
    if (filters.openOnly && !hasOpenActions(e)) return false
    return true
  }

  // All history → entries, indexed by day (filtered for display).
  const byDay = useMemo(() => {
    const map = {}
    for (const m of history) {
      if (!m?.date) continue
      const e = toEntry(m)
      if (Number.isNaN(e.date.getTime())) continue
      if (!matches(e)) continue
      ;(map[ymd(e.date)] ||= []).push(e)
    }
    for (const k in map) map[k].sort((a, b) => a.date - b.date)
    return map
  }, [history, filters])

  const upcomingByDay = useMemo(() => {
    const map = {}
    for (const e of upcoming) (map[ymd(e.date)] ||= []).push(e)
    return map
  }, [upcoming])

  // Insights — always the full month, unfiltered.
  const insights = useMemo(() => {
    const ms = history
      .map(toEntry)
      .filter((e) => !Number.isNaN(e.date.getTime()) && e.date.getFullYear() === year && e.date.getMonth() === month)
    const healths = ms.map((e) => e.health).filter((v) => Number.isFinite(Number(v)))
    const avg = healths.length ? Math.round(healths.reduce((a, b) => a + Number(b), 0) / healths.length) : null
    const owners = {}
    let openCount = 0
    for (const e of ms) for (const a of (e.result.action_items || [])) {
      if (a.completed || !(a.task || '').trim()) continue
      openCount++
      const o = (a.owner || '').trim()
      if (o && !['unassigned', 'tbd', 'team', 'everyone'].includes(o.toLowerCase())) owners[o] = (owners[o] || 0) + 1
    }
    const topOwners = Object.entries(owners).sort((a, b) => b[1] - a[1]).slice(0, 4)
    return { count: ms.length, avg, openCount, topOwners, maxOwner: topOwners[0]?.[1] || 1 }
  }, [history, year, month])

  const periodLabel = useMemo(() => {
    if (view === 'day') return cursor.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
    if (view === 'week') {
      const s = new Date(year, month, cursor.getDate() - cursor.getDay())
      const e = new Date(s); e.setDate(s.getDate() + 6)
      return `${s.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
    }
    return cursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  }, [cursor, view, year, month])

  const step = (dir) => {
    setExpandedDay(null)
    if (view === 'day') setCursor(new Date(year, month, cursor.getDate() + dir))
    else if (view === 'week') setCursor(new Date(year, month, cursor.getDate() + dir * 7))
    else setCursor(new Date(year, month + dir, Math.min(cursor.getDate(), 28)))
  }
  const goToday = () => { setExpandedDay(null); setCursor(new Date()) }
  const todayKey = ymd(today)

  // ── hover preview ──
  const enter = (entry, ev) => {
    // Anchor to the cursor (which is over the chip) — robust regardless of layout.
    const W = 300, H = 230
    let x = ev.clientX + 16
    let y = ev.clientY + 16
    if (x + W > window.innerWidth - 8) x = ev.clientX - W - 16
    if (y + H > window.innerHeight - 8) y = window.innerHeight - H - 8
    setHover({ entry, x: Math.max(8, x), y: Math.max(8, y) })
  }
  const leave = () => setHover(null)

  const Chip = ({ m }) => {
    const c = healthColor(m.health)
    const t = fmtTime(m.date)
    return (
      <button onClick={() => onOpenMeeting?.(m.id)} onMouseEnter={(e) => enter(m, e)} onMouseLeave={leave}
        className="ps-anim block w-full truncate rounded-md px-1.5 py-1 text-left text-[11px] leading-tight transition hover:brightness-125"
        style={{ background: `${c}1f`, borderLeft: `2.5px solid ${c}`, color: '#e7edf5' }}>
        {t && <span className="mr-1 font-semibold" style={{ color: c }}>{t}</span>}
        <span className="font-medium">{m.title}</span>
      </button>
    )
  }
  const UpChip = ({ e }) => (
    <div title={`Upcoming: ${e.title}`}
      className="flex items-center gap-1 truncate rounded-md border border-dashed border-white/15 bg-white/[0.02] px-1.5 py-1 text-[10.5px] text-white/45">
      <Clock className="h-2.5 w-2.5 shrink-0" />{fmtTime(e.date) && <span className="font-medium">{fmtTime(e.date)}</span>}
      <span className="truncate">{e.title}</span>
    </div>
  )

  return (
    <div className="mx-auto max-w-[1400px]">
      <style>{`
        .cal-scroll{scrollbar-width:thin;scrollbar-color:rgba(34,211,238,.3) transparent}
        .cal-scroll::-webkit-scrollbar{width:7px}
        .cal-scroll::-webkit-scrollbar-thumb{background:rgba(34,211,238,.26);border-radius:7px;border:2px solid transparent;background-clip:content-box}
        @media (prefers-reduced-motion: reduce){.ps-anim{transition:none!important}}
      `}</style>

      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl"
            style={{ background: 'linear-gradient(135deg,#22d3ee,#818cf8)', boxShadow: '0 0 20px rgba(34,211,238,0.4)' }}>
            <CalendarDays className="h-5 w-5 text-[#06080d]" />
          </span>
          <div>
            <h1 className="text-xl font-bold tracking-[-0.015em] text-white">{periodLabel}</h1>
            <p className="text-[11px] text-white/40">{insights.count} meeting{insights.count === 1 ? '' : 's'} this month{workspaceName ? ` · ${workspaceName}` : ''}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-white/[0.08] bg-white/[0.03] p-0.5">
            {['month', 'week', 'day'].map((v) => (
              <button key={v} onClick={() => setView(v)}
                className={`ps-anim rounded-md px-3 py-1 text-[12px] font-medium capitalize transition ${view === v ? 'bg-cyan-400/15 text-cyan-200' : 'text-white/45 hover:text-white/80'}`}>{v}</button>
            ))}
          </div>
          <button onClick={goToday} className="ps-anim rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-[12px] font-medium text-white/70 transition hover:text-white">Today</button>
          <div className="flex items-center gap-1">
            <button onClick={() => step(-1)} aria-label="Previous" className="ps-anim grid h-8 w-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-white/60 transition hover:text-white"><ChevronLeft className="h-4 w-4" /></button>
            <button onClick={() => step(1)} aria-label="Next" className="ps-anim grid h-8 w-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-white/60 transition hover:text-white"><ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Filter className="h-3.5 w-3.5 text-white/30" />
        {[['healthy', 'Healthy', '#22c55e'], ['mixed', 'Mixed', '#f59e0b'], ['strained', 'Strained', '#ef4444']].map(([k, label, c]) => {
          const on = filters.health.has(k)
          return (
            <button key={k} onClick={() => setFilters((f) => { const h = new Set(f.health); h.has(k) ? h.delete(k) : h.add(k); return { ...f, health: h } })}
              className="ps-anim flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition"
              style={on ? { color: c, background: `${c}1a`, borderColor: `${c}40` } : { color: 'rgba(255,255,255,0.35)', borderColor: 'rgba(255,255,255,0.10)' }}>
              <CircleDot className="h-2.5 w-2.5" style={{ color: on ? c : 'currentColor' }} />{label}
            </button>
          )
        })}
        <button onClick={() => setFilters((f) => ({ ...f, openOnly: !f.openOnly }))}
          className="ps-anim flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition"
          style={filters.openOnly ? { color: '#67e8f9', background: 'rgba(34,211,238,0.10)', borderColor: 'rgba(34,211,238,0.30)' } : { color: 'rgba(255,255,255,0.35)', borderColor: 'rgba(255,255,255,0.10)' }}>
          <ListTodo className="h-3 w-3" /> Has open actions
        </button>
      </div>

      {/* Main grid: calendar + insights rail */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_268px]">
        <div>
          {view === 'month' && <MonthGrid {...{ cursor, year, month, byDay, upcomingByDay, todayKey, expandedDay, setExpandedDay, Chip, UpChip }} />}
          {view === 'week' && <TimeGrid days={weekDays(cursor)} {...{ byDay, upcomingByDay, todayKey, onOpenMeeting, enter, leave }} />}
          {view === 'day' && <TimeGrid days={[new Date(cursor)]} single {...{ byDay, upcomingByDay, todayKey, onOpenMeeting, enter, leave }} />}
        </div>

        {/* Insights rail */}
        <aside className="space-y-3">
          <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4">
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/40">This month</h3>
            <div className="grid grid-cols-3 gap-2">
              <Stat icon={<CalendarDays className="h-3.5 w-3.5" />} value={insights.count} label="Meetings" color="#67e8f9" />
              <Stat icon={<Activity className="h-3.5 w-3.5" />} value={insights.avg ?? '—'} label="Avg health" color={insights.avg != null ? healthColor(insights.avg) : '#94a3b8'} />
              <Stat icon={<ListTodo className="h-3.5 w-3.5" />} value={insights.openCount} label="Open actions" color="#fbbf24" />
            </div>
          </div>
          <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4">
            <div className="mb-3 flex items-center gap-1.5"><Users className="h-3.5 w-3.5 text-violet-300" /><h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/40">Top owners</h3></div>
            {insights.topOwners.length === 0 ? (
              <p className="text-[11.5px] text-white/35">No open action owners this month.</p>
            ) : (
              <div className="space-y-2.5">
                {insights.topOwners.map(([name, n]) => (
                  <div key={name}>
                    <div className="mb-1 flex items-center justify-between text-[11.5px]"><span className="truncate text-white/75">{name}</span><span className="ml-2 shrink-0 font-semibold text-white/45">{n}</span></div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.05]"><div className="h-full rounded-full" style={{ width: `${(n / insights.maxOwner) * 100}%`, background: 'linear-gradient(90deg,#22d3ee,#818cf8)' }} /></div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 px-1 text-[10.5px] text-white/35">
            <span className="font-medium uppercase tracking-wide">Health</span>
            {[['#22c55e', 'Healthy'], ['#f59e0b', 'Mixed'], ['#ef4444', 'Strained']].map(([c, l]) => (
              <span key={l} className="flex items-center gap-1"><CircleDot className="h-2.5 w-2.5" style={{ color: c }} />{l}</span>
            ))}
          </div>
        </aside>
      </div>

      {/* Hover preview — portalled to body so position:fixed escapes the dashboard's
          transformed/animated ancestor (which would otherwise capture it). */}
      {hover && createPortal((
        <div className="pointer-events-none fixed z-[200] max-h-[240px] w-[300px] overflow-hidden rounded-xl border border-white/[0.12] bg-[#0d111b] p-3 shadow-2xl"
          style={{ left: hover.x, top: hover.y }}>
          <div className="flex items-start justify-between gap-2">
            <p className="text-[13px] font-semibold leading-snug text-white">{hover.entry.title}</p>
            {Number.isFinite(Number(hover.entry.health)) && (
              <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-bold" style={{ color: healthColor(hover.entry.health), background: `${healthColor(hover.entry.health)}1a` }}>{Math.round(hover.entry.health)}</span>
            )}
          </div>
          <p className="mt-0.5 text-[10.5px] text-white/40">{hover.entry.date.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>
          {(hover.entry.result.tldr || hover.entry.result.summary) && (
            <p className="mt-2 line-clamp-3 text-[11.5px] leading-relaxed text-white/65">{hover.entry.result.tldr || hover.entry.result.summary}</p>
          )}
          {(hover.entry.result.decisions || []).slice(0, 2).length > 0 && (
            <div className="mt-2 border-t border-white/[0.07] pt-2">
              <p className="mb-1 text-[9.5px] font-semibold uppercase tracking-wide text-white/30">Decisions</p>
              {(hover.entry.result.decisions || []).slice(0, 2).map((d, i) => (
                <p key={i} className="line-clamp-1 text-[11px] text-white/55">• {typeof d === 'string' ? d : d.decision}</p>
              ))}
            </div>
          )}
        </div>
      ), document.body)}
    </div>
  )
}

function weekDays(cursor) {
  const start = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate() - cursor.getDay())
  return Array.from({ length: 7 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
}

function Stat({ icon, value, label, color }) {
  return (
    <div className="rounded-xl bg-white/[0.03] px-2 py-2.5 text-center">
      <div className="flex items-center justify-center" style={{ color }}>{icon}</div>
      <div className="mt-1 text-[18px] font-bold leading-none" style={{ color }}>{value}</div>
      <div className="mt-1 text-[9px] uppercase tracking-wide text-white/35">{label}</div>
    </div>
  )
}

/* ── Month grid ─────────────────────────────────────────────────────────── */
function MonthGrid({ year, month, byDay, upcomingByDay, todayKey, expandedDay, setExpandedDay, Chip, UpChip }) {
  const first = new Date(year, month, 1)
  const start = new Date(year, month, 1 - first.getDay())
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  return (
    <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]">
      <div className="grid grid-cols-7 border-b border-white/[0.07]">
        {WEEKDAYS.map((w) => <div key={w} className="px-2 py-2 text-center text-[10.5px] font-semibold uppercase tracking-[0.1em] text-white/35">{w}</div>)}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d, i) => {
          const key = ymd(d)
          const inMonth = d.getMonth() === month
          const isToday = key === todayKey
          const meetings = byDay[key] || []
          const ups = upcomingByDay[key] || []
          const expanded = expandedDay === key
          const shown = expanded ? meetings : meetings.slice(0, MAX_CHIPS)
          const extra = meetings.length - shown.length
          return (
            <div key={i} className={`min-h-[110px] border-b border-r border-white/[0.05] p-1.5 ${i % 7 === 6 ? 'border-r-0' : ''} ${inMonth ? '' : 'bg-black/20'}`}
              style={isToday ? { background: 'rgba(34,211,238,0.06)' } : undefined}>
              <div className="mb-1 flex items-center justify-between px-0.5">
                <span className={`grid h-5 min-w-5 place-items-center rounded-full px-1 text-[11px] font-semibold ${isToday ? 'bg-cyan-400 text-[#06080d]' : inMonth ? 'text-white/70' : 'text-white/25'}`}>{d.getDate()}</span>
                {meetings.length > 0 && <span className="text-[9.5px] font-medium text-white/30">{meetings.length}</span>}
              </div>
              <div className={`space-y-1 ${expanded ? 'cal-scroll max-h-44 overflow-y-auto' : ''}`}>
                {shown.map((m) => <Chip key={m.id} m={m} />)}
                {extra > 0 && <button onClick={() => setExpandedDay(key)} className="ps-anim w-full rounded px-1.5 py-0.5 text-left text-[10.5px] font-medium text-cyan-300/70 transition hover:text-cyan-200">+{extra} more</button>}
                {ups.map((e) => <UpChip key={e.id} e={e} />)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── Week / Day time grid ───────────────────────────────────────────────── */
function hourLabel(h) {
  const hr = h % 12 === 0 ? 12 : h % 12
  return `${hr} ${h % 24 < 12 ? 'AM' : 'PM'}`
}
function hourRange(entries) {
  // Always show a comfortable window (8am–8pm), expanding to fit any meeting outside it
  // so nothing is ever cramped or clipped.
  let min = 8, max = 20
  entries.forEach((e) => { const h = e.date.getHours(); min = Math.min(min, h); max = Math.max(max, h + 1) })
  return [Math.max(0, min), Math.min(24, max)]
}
function layout(entries, rangeStart) {
  const placed = [...entries].sort((a, b) => a.date - b.date).map((e) => {
    const h = e.date.getHours() + e.date.getMinutes() / 60
    return { ...e, top: Math.max(0, (h - rangeStart) * HOUR_PX) }
  })
  const laneEnds = []
  placed.forEach((p) => {
    let lane = 0
    while (lane < laneEnds.length && laneEnds[lane] > p.top + 2) lane++
    p.lane = lane; laneEnds[lane] = p.top + BLOCK_PX
  })
  const lanes = placed.reduce((mx, p) => Math.max(mx, p.lane), 0) + 1
  placed.forEach((p) => { p.widthPct = 100 / lanes; p.leftPct = p.lane * (100 / lanes) })
  return placed
}

function TimeGrid({ days, single = false, byDay, upcomingByDay, todayKey, onOpenMeeting, enter, leave }) {
  const allEntries = days.flatMap((d) => [...(byDay[ymd(d)] || []), ...(upcomingByDay[ymd(d)] || [])])
  const [rs, re] = hourRange(allEntries)
  const hours = Array.from({ length: re - rs + 1 }, (_, i) => rs + i)
  const colHeight = (re - rs) * HOUR_PX + HOUR_PX
  const scrollRef = useRef(null)
  // Scroll so the first meeting of the period is in view (not buried below empty hours).
  useEffect(() => {
    const ms = days.flatMap((d) => byDay[ymd(d)] || [])
    if (!scrollRef.current) return
    if (!ms.length) { scrollRef.current.scrollTop = 0; return }
    const earliest = Math.min(...ms.map((m) => m.date.getHours() + m.date.getMinutes() / 60))
    scrollRef.current.scrollTop = Math.max(0, (earliest - rs) * HOUR_PX - 28)
  }, [days, byDay, rs])
  return (
    <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]">
      {/* day headers */}
      <div className="grid border-b border-white/[0.07]" style={{ gridTemplateColumns: `58px repeat(${days.length}, minmax(0,1fr))` }}>
        <div />
        {days.map((d, i) => {
          const isToday = ymd(d) === todayKey
          return (
            <div key={i} className={`px-2 py-2 text-center ${isToday ? 'bg-cyan-400/[0.06]' : ''}`}>
              <div className="text-[10px] font-semibold uppercase tracking-wide text-white/35">{d.toLocaleDateString('en-US', { weekday: single ? 'long' : 'short' })}</div>
              <div className={`text-[15px] font-bold ${isToday ? 'text-cyan-300' : 'text-white/75'}`}>{d.getDate()}</div>
            </div>
          )
        })}
      </div>
      {/* time grid */}
      <div ref={scrollRef} className="cal-scroll relative max-h-[64vh] overflow-y-auto">
        {days.every((d) => !(byDay[ymd(d)] || []).length && !(upcomingByDay[ymd(d)] || []).length) && (
          <div className="pointer-events-none absolute inset-x-0 top-16 z-10 text-center">
            <p className="text-[13px] font-medium text-white/45">No meetings {single ? 'on this day' : 'this week'}.</p>
            <p className="mt-1 text-[11px] text-white/30">Use ‹ › to browse, or switch to Month.</p>
          </div>
        )}
        <div className="grid" style={{ gridTemplateColumns: `58px repeat(${days.length}, minmax(0,1fr))` }}>
          {/* hour gutter */}
          <div>
            {hours.map((h) => (
              <div key={h} className="relative border-b border-white/[0.04]" style={{ height: HOUR_PX }}>
                <span className="absolute -top-1.5 right-2 whitespace-nowrap text-[9.5px] text-white/30">{hourLabel(h)}</span>
              </div>
            ))}
          </div>
          {/* day columns */}
          {days.map((d, ci) => {
            const meetings = layout(byDay[ymd(d)] || [], rs)
            const ups = layout(upcomingByDay[ymd(d)] || [], rs)
            const isToday = ymd(d) === todayKey
            return (
              <div key={ci} className={`relative border-l border-white/[0.05] ${isToday ? 'bg-cyan-400/[0.03]' : ''}`} style={{ height: colHeight }}>
                {hours.map((h) => <div key={h} className="border-b border-white/[0.04]" style={{ height: HOUR_PX }} />)}
                {meetings.map((m) => {
                  const c = healthColor(m.health)
                  return (
                    <button key={m.id} onClick={() => onOpenMeeting?.(m.id)} onMouseEnter={(e) => enter(m, e)} onMouseLeave={leave}
                      className="ps-anim absolute overflow-hidden rounded-md px-1.5 py-1 text-left transition hover:brightness-125"
                      style={{ top: m.top, height: BLOCK_PX, left: `calc(${m.leftPct}% + 3px)`, width: `calc(${m.widthPct}% - 6px)`, background: `${c}26`, borderLeft: `2.5px solid ${c}` }}>
                      <span className="block truncate text-[10.5px] font-semibold leading-tight" style={{ color: '#e7edf5' }}>{m.title}</span>
                      <span className="block truncate text-[9px]" style={{ color: c }}>{fmtTime(m.date)}</span>
                    </button>
                  )
                })}
                {ups.map((e) => (
                  <div key={e.id} title={`Upcoming: ${e.title}`}
                    className="absolute overflow-hidden rounded-md border border-dashed border-white/20 bg-white/[0.03] px-1.5 py-1"
                    style={{ top: e.top, height: BLOCK_PX, left: `calc(${e.leftPct}% + 3px)`, width: `calc(${e.widthPct}% - 6px)` }}>
                    <span className="flex items-center gap-1 truncate text-[10px] text-white/50"><Clock className="h-2.5 w-2.5 shrink-0" />{e.title}</span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

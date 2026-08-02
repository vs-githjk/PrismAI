import { useState, useEffect, useCallback, useMemo } from 'react'
import { apiFetch } from '../lib/api'
import { dueInfo, dueLabel } from '../lib/dueStatus'
import { loadSeen, persistSeen, STANDIN_READ_EVENT } from '../lib/standinRead'
import {
  ListTodo, Scale, Sparkles, ArrowUpRight, Calendar, CalendarClock,
  CircleDot, CornerDownRight, AlertTriangle, Loader2, RefreshCw, Mail, UserRoundCheck,
} from 'lucide-react'

/**
 * Stand-in command center.
 *
 * Ordered by the job, not by the data model. The page answers three questions in
 * this order, top to bottom:
 *   1. Am I covered?          → the readiness band (4 tiles, each a jump target)
 *   2. What needs me now?     → upcoming meetings you could miss, stand-ins in
 *                               flight, and briefs waiting from ones you missed
 *   3. What does Prism know?  → the standing profile, the default stand-in, and
 *                               the work it speaks from (right rail, reference)
 *
 * It used to be the reverse: two read-only reference lists held the wide column
 * while the actual product state ("your stand-ins") was the third card in the
 * narrow rail, inside a 320px inner scroller, with the follow-up brief — the
 * feature's whole payoff — collapsed by default behind a toggle in there.
 *
 * Visual rules followed here: flat surfaces + hairline borders (no gradient
 * heroes), cyan reserved for interactive/selected state, status carried by small
 * semantic pills, one type scale (see T), figures in tabular numerals (inherited
 * from .dashboard-page).
 */

// One type scale for the page. Nine ad-hoc text-[Npx] sizes is not a hierarchy.
const T = {
  kpi: 'text-[26px] font-semibold leading-none tracking-[-0.02em]',
  h1: 'text-[15px] font-semibold tracking-[-0.01em]',
  h2: 'text-[13px] font-semibold',
  body: 'text-[13px] leading-relaxed',
  meta: 'text-[11.5px] leading-relaxed',
  micro: 'text-[10.5px]',
}

const STATUS_META = {
  draft: { label: 'Draft', color: '#94a3b8' },
  pending: { label: 'Scheduled', color: '#67e8f9' },
  delivered: { label: 'Delivered', color: '#86efac' },
  expired: { label: 'Ended', color: '#94a3b8' },
}

// A stand-in whose meeting time has already passed is no longer "scheduled" — even if
// its DB status is still pending (delivery may never have flipped it). Treat it as ended.
const repTimePast = (r) => {
  const t = r?.join_at || r?.scheduled_for
  if (!t) return false
  const d = new Date(t)
  return !Number.isNaN(d.getTime()) && d.getTime() < Date.now()
}
const effStatus = (r) => (r.status === 'pending' && repTimePast(r) ? 'expired' : r.status)

// Decision importance → label + accent. 1=critical, 2=significant, 3=minor.
const IMPORTANCE = {
  1: { label: 'Critical', color: '#f87171', tint: 'rgba(248,113,113,0.12)', border: 'rgba(248,113,113,0.32)' },
  2: { label: 'Significant', color: '#fbbf24', tint: 'rgba(251,191,36,0.12)', border: 'rgba(251,191,36,0.32)' },
  3: { label: 'Minor', color: '#94a3b8', tint: 'rgba(148,163,184,0.12)', border: 'rgba(148,163,184,0.30)' },
}
const DUE_TINT = {
  overdue: { color: '#fca5a5', bg: 'rgba(248,113,113,0.12)', border: 'rgba(248,113,113,0.30)' },
  soon: { color: '#fcd34d', bg: 'rgba(251,191,36,0.10)', border: 'rgba(251,191,36,0.30)' },
  later: { color: 'rgba(255,255,255,0.55)', bg: 'rgba(255,255,255,0.04)', border: 'rgba(255,255,255,0.12)' },
}

const JUNK = ['(none)', 'none', '(empty)', 'n/a']
const clean = (s) => (JUNK.includes((s || '').trim().toLowerCase()) ? '' : (s || ''))



const fmtWhen = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** "in 12 min" / "in 3 h" / "in 2 days" / "now" — for a join time. */
const countdown = (iso) => {
  if (!iso) return ''
  const ms = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(ms)) return ''
  if (ms <= 0) return 'now'
  const mins = Math.round(ms / 60000)
  if (mins < 60) return `in ${mins} min`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `in ${hrs} h`
  return `in ${Math.round(hrs / 24)} day${Math.round(hrs / 24) === 1 ? '' : 's'}`
}

export default function ProxyProfile({
  user = null, workspaceId = null, workspaceName = null,
  onOpenMeeting, onCantMakeIt = null, calendarConnected = false,
}) {
  const [roleFocus, setRoleFocus] = useState('')
  const [notes, setNotes] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saveState, setSaveState] = useState('idle')
  const [reps, setReps] = useState([])
  const [openBrief, setOpenBrief] = useState(null)
  const [seen, setSeen] = useState(() => loadSeen(user?.id))

  const [digest, setDigest] = useState({ action_items: [], decisions: [] })
  const [digestLoading, setDigestLoading] = useState(true)
  const [upcoming, setUpcoming] = useState([])

  const [defaultStandin, setDefaultStandin] = useState('')
  // Mirror of what is actually persisted, so Readiness reports saved state rather
  // than whatever is currently typed into the boxes.
  const [savedProfile, setSavedProfile] = useState({ role: '', notes: '', defaultStandin: '' })
  const [previewing, setPreviewing] = useState(false)
  const [defaultSaveState, setDefaultSaveState] = useState('idle')
  const [previewThin, setPreviewThin] = useState(false)

  const authorName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || ''
  const authorEmail = user?.email || ''
  const scopeLabel = workspaceName || 'Personal'

  const loadProfileAndReps = useCallback(async () => {
    try {
      const [pRes, rRes] = await Promise.all([
        apiFetch('/proxy/profile' + (workspaceId ? `?workspace_id=${workspaceId}` : '')),
        apiFetch('/proxy/representations' + (workspaceId ? `?workspace_id=${workspaceId}` : '')),
      ])
      if (pRes.ok) {
        const { profile } = await pRes.json()
        const role = profile?.role_focus || ''
        const noteText = clean(profile?.standing_notes)
        const dflt = profile?.default_standin || ''
        setRoleFocus(role)
        setNotes(noteText)
        setDefaultStandin(dflt)
        setSavedProfile({ role, notes: noteText, defaultStandin: dflt })
      }
      if (rRes.ok) {
        const { representations } = await rRes.json()
        setReps(representations || [])
      }
    } catch { /* leave empty */ }
    finally { setLoaded(true) }
  }, [workspaceId])

  const loadDigest = useCallback(async () => {
    setDigestLoading(true)
    try {
      const qs = new URLSearchParams()
      if (workspaceId) qs.set('workspace_id', workspaceId)
      if (authorName) qs.set('author_name', authorName)
      if (authorEmail) qs.set('author_email', authorEmail)
      const res = await apiFetch(`/proxy/digest?${qs.toString()}`)
      if (res.ok) setDigest(await res.json())
      else setDigest({ action_items: [], decisions: [] })
    } catch { setDigest({ action_items: [], decisions: [] }) }
    finally { setDigestLoading(false) }
  }, [workspaceId, authorName, authorEmail])

  // Upcoming meetings you could hand to Prism. Same source UpcomingMeetings uses;
  // only meetings with a join link can take a stand-in. Best-effort — a calendar
  // that isn't connected simply yields nothing and the block hides itself.
  const loadUpcoming = useCallback(async () => {
    if (!calendarConnected || !onCantMakeIt) return
    try {
      const results = await Promise.allSettled([
        apiFetch('/calendar/events?days_ahead=3'),
        apiFetch('/ms-calendar/events?days_ahead=3'),
      ])
      const events = []
      for (const r of results) {
        if (r.status !== 'fulfilled' || !r.value.ok) continue
        const data = await r.value.json().catch(() => ({}))
        for (const ev of (data.events || [])) if (ev.has_meeting_link) events.push(ev)
      }
      const byKey = new Map()
      for (const ev of events) byKey.set(ev.meeting_link || `${ev.start}|${ev.title}`, ev)
      setUpcoming([...byKey.values()]
        .filter((ev) => new Date(ev.start).getTime() > Date.now() - 60 * 60 * 1000)
        .sort((a, b) => new Date(a.start) - new Date(b.start))
        .slice(0, 4))
    } catch { setUpcoming([]) }
  }, [calendarConnected, onCantMakeIt])

  useEffect(() => { loadProfileAndReps() }, [loadProfileAndReps])
  useEffect(() => { loadDigest() }, [loadDigest])
  useEffect(() => { loadUpcoming() }, [loadUpcoming])
  useEffect(() => { setPreviewThin(false); setDefaultSaveState('idle') }, [workspaceId])

  useEffect(() => {
    const reload = () => { loadProfileAndReps(); loadDigest(); loadUpcoming() }
    window.addEventListener('focus', reload)
    window.addEventListener('prism:standin-changed', reload)
    return () => {
      window.removeEventListener('focus', reload)
      window.removeEventListener('prism:standin-changed', reload)
    }
  }, [loadProfileAndReps, loadDigest, loadUpcoming])

  const save = async () => {
    setSaveState('saving')
    try {
      const res = await apiFetch('/proxy/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role_focus: roleFocus, standing_notes: notes, workspace_id: workspaceId || null }),
      })
      setSaveState(res.ok ? 'saved' : 'idle')
      if (res.ok) {
        setSavedProfile((p) => ({ ...p, role: roleFocus, notes }))
        setTimeout(() => setSaveState('idle'), 1800)
      }
    } catch { setSaveState('idle') }
  }

  const generateDefault = async () => {
    setPreviewing(true); setPreviewThin(false); setDefaultSaveState('idle')
    try {
      const res = await apiFetch('/proxy/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, author_name: authorName, author_email: authorEmail }),
      })
      const data = await res.json().catch(() => ({}))
      if (data.grounded === false || !data.preview) setPreviewThin(true)
      else setDefaultStandin(data.preview)
    } catch { setPreviewThin(true) }
    finally { setPreviewing(false) }
  }

  const saveDefault = async () => {
    setDefaultSaveState('saving')
    try {
      const res = await apiFetch('/proxy/default-standin', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ default_standin: defaultStandin, workspace_id: workspaceId || null }),
      })
      setDefaultSaveState(res.ok ? 'saved' : 'idle')
      if (res.ok) {
        setSavedProfile((p) => ({ ...p, defaultStandin }))
        setTimeout(() => setDefaultSaveState('idle'), 1800)
      }
    } catch { setDefaultSaveState('idle') }
  }

  const cancelRep = async (id) => {
    try {
      await apiFetch(`/proxy/representations/${id}/cancel`, { method: 'POST' })
      setReps((r) => r.filter((x) => x.id !== id))
    } catch { /* ignore */ }
  }

  const open = (mid) => { if (mid && onOpenMeeting) onOpenMeeting(mid) }

  // Everything not yet delivered/ended — what the In-flight card LISTS.
  const active = reps.filter((r) => ['draft', 'pending'].includes(effStatus(r)))
  // What the KPI COUNTS: only reps Prism will genuinely attend — status pending
  // AND a join time on record. A draft is unfinished, and a pending rep with no
  // join_at is one whose bot was never scheduled (failure, or the scheduling
  // flag off) — counting those claimed attendance we can't back up, which is how
  // one card could read "Scheduled" and "Not scheduled yet" at the same time.
  const scheduledReps = reps.filter((r) => effStatus(r) === 'pending' && !!r.join_at)
  const unscheduledDrafts = active.length - scheduledReps.length
  // Briefs are ordered by when the MEETING happened, not when the stand-in was
  // created — the backend returns creation order, which let an old stand-in's
  // brief outrank one from this morning.
  const briefed = useMemo(() => reps
    .filter((r) => (r.followup_brief || '').trim())
    .sort((a, b) => new Date(b.followup_sent_at || b.join_at || 0) - new Date(a.followup_sent_at || a.join_at || 0)),
  [reps])
  const pastNoBrief = reps.filter((r) => ['delivered', 'expired'].includes(effStatus(r)) && !(r.followup_brief || '').trim())
  const unreadBriefs = briefed.filter((r) => !seen.has(String(r.id)))

  const actions = digest.action_items || []
  const decisions = digest.decisions || []
  const material = actions.length + decisions.length

  const profileEmpty = loaded && !roleFocus.trim() && !notes.trim()
  const roleOnlyMissing = loaded && !roleFocus.trim() && !!notes.trim()
  // Counts SAVED values only. Reading the live textarea state let a user see
  // "3 of 3" from unsaved typing — including when the save then failed.
  const readySteps = [!!savedProfile.role.trim(), !!savedProfile.notes.trim(), !!savedProfile.defaultStandin.trim()]
  const readyCount = readySteps.filter(Boolean).length

  // Newest unread brief opens by default — the payoff shouldn't need a click to find.
  useEffect(() => {
    if (openBrief !== null || !unreadBriefs.length) return
    // Auto-open AND mark read: expanding it without marking left the sidebar
    // badge claiming unread for a brief the user is looking at.
    setOpenBrief(unreadBriefs[0].id)
    markSeen(unreadBriefs[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unreadBriefs.length])

  const markSeen = (id) => {
    setSeen((prev) => {
      if (prev.has(String(id))) return prev
      const next = new Set(prev).add(String(id))
      persistSeen(user?.id, next)
      // Tell the shell so the sidebar badge drops immediately instead of waiting
      // for a navigation or a reload.
      window.dispatchEvent(new Event(STANDIN_READ_EVENT))
      return next
    })
  }

  const jump = (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-10">
      <style>{`
        .ps-scroll{scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.22) transparent}
        .ps-scroll::-webkit-scrollbar{width:8px}
        .ps-scroll::-webkit-scrollbar-thumb{background:rgba(255,255,255,.18);border-radius:8px;border:2px solid transparent;background-clip:content-box}
        .ps-scroll::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.3);background-clip:content-box}
        .ps-scroll::-webkit-scrollbar-track{background:transparent}
        @media (prefers-reduced-motion: reduce){.ps-anim{transition:none!important;animation:none!important}}
      `}</style>

      {/* Title line. No gradient hero: the topbar already says "Stand-in", so a
          second gradient-text copy of the word was pure decoration. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className={`${T.body} max-w-2xl text-[color:var(--db-text-muted)]`}>
          When you can’t attend, Prism speaks for you — from your work and the context you give it here.
        </p>
        <span className={`${T.meta} shrink-0 rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill)] px-2.5 py-1 text-[color:var(--db-text-muted)]`}>
          {scopeLabel}
        </span>
      </div>

      {/* Readiness band — the "am I covered?" answer, and the page's jump targets. */}
      <div className="grid grid-cols-2 overflow-hidden rounded-2xl border border-[color:var(--db-border)] bg-[var(--db-fill)] lg:grid-cols-4">
        <Kpi
          label="In flight" value={scheduledReps.length}
          def={unscheduledDrafts > 0
            ? `scheduled — ${unscheduledDrafts} more not scheduled yet`
            : 'meetings Prism will speak at for you'}
          state={unscheduledDrafts > 0 ? 'warn' : 'none'}
          onClick={() => jump('standin-inflight')}
        />
        <Kpi
          label="Briefs waiting" value={unreadBriefs.length}
          def="recaps from meetings you missed"
          state={unreadBriefs.length > 0 ? 'warn' : 'none'}
          onClick={() => jump('standin-briefs')}
        />
        <Kpi
          label="Material" value={material}
          value={digestLoading ? '—' : material}
          def={digestLoading
            ? 'checking your recent work…'
            : material === 0 ? 'Prism has nothing concrete to report' : 'work items Prism can speak to'}
          state={!digestLoading && material === 0 ? 'warn' : 'none'}
          onClick={() => jump('standin-material')}
        />
        <Kpi
          label="Readiness" value={`${readyCount} of 3`}
          def="role · notes · default stand-in"
          state={loaded && readyCount < 3 ? 'warn' : 'ok'}
          onClick={() => jump('standin-profile')}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* ── PRIMARY: what needs you ─────────────────────────────────────── */}
        <div className="min-w-0 space-y-5">
          {/* Hand a meeting to Prism, from here. The only trigger used to live
              inside the New Meeting popover, so this page's empty state gave
              written directions to a button you couldn't reach from it. */}
          {onCantMakeIt && upcoming.length > 0 && (
            <Card
              id="standin-upcoming"
              icon={<CalendarClock className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
              title="Coming up — could you miss one?"
              onRefresh={loadUpcoming}
            >
              <ul className="divide-y divide-[color:var(--db-border)]">
                {upcoming.map((ev) => (
                  <li key={ev.meeting_link || ev.start} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                    <div className="min-w-0 flex-1">
                      <p className={`${T.h2} truncate text-[color:var(--db-text)]`}>{ev.title || 'Meeting'}</p>
                      <p className={`${T.micro} text-[color:var(--db-text-faint)]`}>
                        {fmtWhen(ev.start)} · {countdown(ev.start)}
                      </p>
                    </div>
                    <button
                      onClick={() => onCantMakeIt({
                        url: ev.meeting_link, label: ev.title,
                        workspaceId: workspaceId || null, scheduledFor: ev.start,
                      })}
                      className={`${T.meta} ps-anim shrink-0 rounded-lg border border-cyan-400/30 px-3 py-1.5 font-medium text-cyan-200 transition hover:bg-cyan-400/10`}
                    >
                      Have Prism stand in
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* In flight — every pending rep as a full card. Replaces the old
              single-rep banner, which lied whenever there were two. */}
          <Card
            id="standin-inflight"
            icon={<UserRoundCheck className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
            title="In flight"
            count={active.length}
          >
            {!loaded ? (
              <p className={`${T.meta} text-[color:var(--db-text-faint)]`}>Loading…</p>
            ) : active.length === 0 ? (
              <Empty
                text="No stand-ins scheduled."
                sub={onCantMakeIt && upcoming.length === 0
                  ? 'When a meeting you can’t attend is on your calendar, it shows up above with a one-click hand-off.'
                  : 'Pick a meeting above and Prism will speak for you.'}
              />
            ) : (
              <ul className="space-y-2.5">
                {active.map((rep) => {
                  const meta = STATUS_META[effStatus(rep)] || STATUS_META.draft
                  const body = rep.approved_body || rep.draft_body || ''
                  return (
                    <li key={rep.id} className="rounded-xl border border-[color:var(--db-border)] bg-[var(--db-fill)] p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className={`${T.h1} truncate text-[color:var(--db-text)]`}>{rep.meeting_label || 'Meeting'}</p>
                          <p className={`${T.micro} mt-0.5 text-[color:var(--db-text-faint)]`}>
                            {rep.join_at ? <>{fmtWhen(rep.join_at)} · <span className="text-[color:var(--db-text-muted)]">{countdown(rep.join_at)}</span></> : 'Not scheduled yet'}
                          </p>
                        </div>
                        <Pill color={meta.color}>{meta.label}</Pill>
                      </div>
                      {/* Full text, not line-clamp-2: this is what Prism will say
                          out loud on your behalf — you should be able to read it. */}
                      {body && (
                        <p className={`${T.body} mt-3 whitespace-pre-wrap break-words rounded-lg border border-[color:var(--db-border)] bg-black/20 px-3 py-2.5 text-[color:var(--db-text-soft)]`}>
                          {body}
                        </p>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <button onClick={() => cancelRep(rep.id)}
                          className={`${T.meta} ps-anim rounded-lg border border-[color:var(--db-border)] px-3 py-1.5 font-medium text-[color:var(--db-text-muted)] transition hover:border-rose-400/40 hover:text-rose-300`}>
                          Cancel
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>

          {/* Briefs — the payoff. Newest first, newest unread open by default. */}
          <Card
            id="standin-briefs"
            icon={<Mail className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
            title="Your briefs"
            count={briefed.length}
            badge={unreadBriefs.length ? `${unreadBriefs.length} new` : null}
          >
            {briefed.length === 0 ? (
              <Empty
                text="No briefs yet."
                sub="After a meeting Prism sat in for you, it writes up what you missed, what was decided, and what’s now on you — and emails it."
              />
            ) : (
              <ul className="space-y-2.5">
                {briefed.map((rep) => {
                  const isUnread = !seen.has(String(rep.id))
                  const isOpen = openBrief === rep.id
                  return (
                    <li key={rep.id} className="rounded-xl border border-[color:var(--db-border)] bg-[var(--db-fill)]">
                      <button
                        onClick={() => { setOpenBrief(isOpen ? null : rep.id); markSeen(rep.id) }}
                        aria-expanded={isOpen}
                        className="ps-anim flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-[var(--db-fill-strong)]"
                      >
                        {isUnread
                          ? <span className="h-2 w-2 shrink-0 rounded-full bg-cyan-400" aria-label="Unread" />
                          : <span className="h-2 w-2 shrink-0" />}
                        <div className="min-w-0 flex-1">
                          <p className={`${T.h2} truncate text-[color:var(--db-text)]`}>{rep.meeting_label || 'Meeting'}</p>
                          <p className={`${T.micro} text-[color:var(--db-text-faint)]`}>
                            {rep.followup_sent_at ? `Briefed ${fmtWhen(rep.followup_sent_at)} · emailed` : 'Brief ready'}
                          </p>
                        </div>
                        <span className={`${T.meta} shrink-0 text-[color:var(--db-text-faint)]`}>{isOpen ? 'Hide' : 'Read'}</span>
                      </button>
                      {isOpen && (
                        <div className="border-t border-[color:var(--db-border)] px-4 py-3">
                          <p className={`${T.body} whitespace-pre-wrap break-words text-[color:var(--db-text)]`}>{rep.followup_brief}</p>
                          {rep.followup_meeting_id && (
                            <button onClick={() => open(rep.followup_meeting_id)}
                              className={`${T.meta} ps-anim mt-2.5 inline-flex items-center gap-1 font-medium text-cyan-300 transition hover:text-cyan-200`}>
                              Open the full meeting <ArrowUpRight className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </Card>

          {/* Delivered / ended without a brief — history, kept compact. */}
          {pastNoBrief.length > 0 && (
            <Card
              icon={<Calendar className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
              title="Past stand-ins"
              count={pastNoBrief.length}
            >
              <ul className="divide-y divide-[color:var(--db-border)]">
                {pastNoBrief.map((rep) => {
                  const meta = STATUS_META[effStatus(rep)] || STATUS_META.expired
                  return (
                    <li key={rep.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                      <div className="min-w-0 flex-1">
                        <p className={`${T.h2} truncate text-[color:var(--db-text)]`}>{rep.meeting_label || 'Meeting'}</p>
                        <p className={`${T.meta} line-clamp-2 text-[color:var(--db-text-muted)]`}>{rep.approved_body || rep.draft_body || '—'}</p>
                      </div>
                      <Pill color={meta.color}>{meta.label}</Pill>
                    </li>
                  )
                })}
              </ul>
            </Card>
          )}
        </div>

        {/* ── RAIL: what Prism knows (reference + setup) ───────────────────── */}
        <aside className="min-w-0 space-y-5">
          <Card id="standin-profile" title="What Prism knows about you">
            <p className={`${T.meta} -mt-1 mb-3 text-[color:var(--db-text-faint)]`}>
              Specific to <span className="text-[color:var(--db-text-muted)]">{scopeLabel}</span> — each space keeps its own, so team and personal context never mix.
            </p>
            {profileEmpty && (
              <p className={`${T.meta} ps-anim mb-3 flex items-start gap-2 rounded-lg border border-[color:var(--db-border)] bg-[var(--db-fill)] px-3 py-2 text-[color:var(--db-text-muted)]`}>
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-300" />
                Add your role and a note or two — Prism represents you noticeably better when it knows what you own.
              </p>
            )}
            <div className="space-y-4">
              <Field label="Role / focus" hint={roleOnlyMissing ? 'Add your role so Prism leads with who you are.' : ''}>
                <input value={roleFocus} onChange={(e) => setRoleFocus(e.target.value)}
                  placeholder="e.g. Backend lead — payments & API" disabled={!loaded}
                  className={`${T.body} w-full rounded-lg border bg-[var(--db-fill)] px-3 py-2 text-[color:var(--db-text)] outline-none placeholder:text-[color:var(--db-text-faint)] focus:border-cyan-400/45 ${roleOnlyMissing ? 'border-cyan-400/30' : 'border-[color:var(--db-border)]'}`} />
              </Field>
              <Field label="Standing notes" hint="Auto-updated when you approve a stand-in.">
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
                  placeholder="Ongoing responsibilities, projects you own, anything Prism should mention on your behalf…"
                  disabled={!loaded}
                  className={`${T.body} ps-scroll w-full resize-none rounded-lg border border-[color:var(--db-border)] bg-[var(--db-fill)] px-3 py-2 text-[color:var(--db-text)] outline-none placeholder:text-[color:var(--db-text-faint)] focus:border-cyan-400/45`} />
              </Field>
              <button onClick={save} disabled={saveState === 'saving' || !loaded}
                className={`${T.h2} ps-anim rounded-lg bg-cyan-400 px-4 py-2 text-[#06080d] transition hover:bg-cyan-300 disabled:opacity-40`}>
                {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved' : 'Save'}
              </button>
            </div>
          </Card>

          <Card title="Your default stand-in">
            <p className={`${T.meta} -mt-1 mb-3 text-[color:var(--db-text-faint)]`}>
              What Prism leads with if you’re pulled into a {scopeLabel} meeting with no time to compose — it pre-fills the draft so you’re one click from approving.
            </p>
            <textarea
              value={defaultStandin}
              onChange={(e) => { setDefaultStandin(e.target.value); setPreviewThin(false) }}
              rows={5}
              placeholder="Generate one from your work, or write your own…"
              className={`${T.body} ps-scroll w-full resize-none rounded-lg border border-[color:var(--db-border)] bg-[var(--db-fill)] px-3 py-2 text-[color:var(--db-text-soft)] outline-none placeholder:text-[color:var(--db-text-faint)] focus:border-cyan-400/45`}
            />
            {previewThin && (
              <p className={`${T.meta} mt-2 flex items-start gap-1.5 text-[color:var(--db-text-muted)]`}>
                <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-cyan-300" />
                Not enough recent work in {scopeLabel} to draft one — write your own, or add your role and notes above.
              </p>
            )}
            <div className="mt-3 flex items-center gap-2">
              <button onClick={generateDefault} disabled={previewing}
                className={`${T.meta} ps-anim flex flex-1 items-center justify-center gap-2 rounded-lg border border-[color:var(--db-border)] bg-[var(--db-fill)] py-2 font-medium text-[color:var(--db-text-soft)] transition hover:bg-[var(--db-fill-strong)] disabled:opacity-50`}>
                {previewing ? <><Loader2 className="ps-anim h-3.5 w-3.5 animate-spin" /> Generating…</> : <><Sparkles className="h-3.5 w-3.5" /> {defaultStandin.trim() ? 'Regenerate' : 'Generate from my work'}</>}
              </button>
              <button onClick={saveDefault} disabled={defaultSaveState === 'saving' || !defaultStandin.trim()}
                className={`${T.meta} ps-anim rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-[#06080d] transition hover:bg-cyan-300 disabled:opacity-40`}>
                {defaultSaveState === 'saving' ? 'Saving…' : defaultSaveState === 'saved' ? 'Saved' : 'Save'}
              </button>
            </div>
          </Card>

          {/* Reference material — what Prism speaks FROM. Demoted from the primary
              column: it's input, not state. */}
          <div id="standin-material" className="space-y-5">
            <Card
              icon={<ListTodo className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
              title="Your open action items"
              hint="Overdue first"
              count={actions.length}
              loading={digestLoading}
              emptyWhileLoading={actions.length === 0}
              onRefresh={loadDigest}
              scroll
            >
              {actions.length === 0 ? (
                <Empty text={`Nothing open under your name in ${scopeLabel}.`} sub="Tasks meetings assign you show up here, and feed your stand-in." />
              ) : (
                <ul className="space-y-1.5">
                  {actions.map((a, i) => {
                    const di = dueInfo({ due_date: a.due_date })
                    const dt = di.status ? DUE_TINT[di.status] : null
                    return (
                      <li key={i}>
                        <button onClick={() => open(a.meeting_id)} disabled={!a.meeting_id}
                          className="ps-anim group flex w-full items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition hover:border-[color:var(--db-border)] hover:bg-[var(--db-fill)] disabled:cursor-default">
                          <CircleDot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)]" />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className={`${T.h2} truncate text-[color:var(--db-text)]`}>{a.task}</span>
                              {dt && <Pill color={dt.color} bg={dt.bg} border={dt.border}>{dueLabel(di)}</Pill>}
                            </span>
                            {a.from_decision && (
                              <span className={`${T.micro} mt-0.5 flex items-center gap-1 text-[color:var(--db-text-muted)]`}>
                                <CornerDownRight className="h-3 w-3 shrink-0" />
                                <span className="line-clamp-1">From decision: {a.from_decision}</span>
                              </span>
                            )}
                            <span className={`${T.micro} mt-0.5 block truncate text-[color:var(--db-text-faint)]`}>{a.meeting}</span>
                          </span>
                          {a.meeting_id && <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)]" />}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>

            <Card
              icon={<Scale className="h-4 w-4 text-[color:var(--db-text-muted)]" />}
              title="Your decisions"
              hint="Most important first"
              count={decisions.length}
              loading={digestLoading}
              emptyWhileLoading={decisions.length === 0}
              onRefresh={loadDigest}
              scroll
            >
              {decisions.length === 0 ? (
                <Empty text={`No decisions tied to you in ${scopeLabel} yet.`} sub="Decisions you make (or that drive your action items) collect here." />
              ) : (
                <ul className="space-y-1.5">
                  {decisions.map((d, i) => {
                    const imp = IMPORTANCE[d.importance] || IMPORTANCE[3]
                    return (
                      <li key={i}>
                        <button onClick={() => open(d.meeting_id)} disabled={!d.meeting_id}
                          className="ps-anim group flex w-full items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition hover:border-[color:var(--db-border)] hover:bg-[var(--db-fill)] disabled:cursor-default"
                          style={{ borderLeft: `2px solid ${imp.color}` }}>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className={`${T.h2} truncate text-[color:var(--db-text)]`}>{d.decision}</span>
                              <Pill color={imp.color} bg={imp.tint} border={imp.border}>{imp.label}</Pill>
                            </span>
                            {d.rationale && <span className={`${T.meta} mt-0.5 line-clamp-2 block text-[color:var(--db-text-faint)]`}>{d.rationale}</span>}
                            <span className={`${T.micro} mt-1 flex items-center gap-2 text-[color:var(--db-text-faint)]`}>
                              <span className="truncate">{d.meeting}</span>
                              {!d.has_action && (
                                <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold" style={{ color: '#fbbf24' }}>
                                  <AlertTriangle className="h-2.5 w-2.5" /> No action
                                </span>
                              )}
                            </span>
                          </span>
                          {d.meeting_id && <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)]" />}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>
          </div>
        </aside>
      </div>
    </div>
  )
}

/* ── Primitives ───────────────────────────────────────────────────────────── */

/** KPI tile: figure + plain-English definition, whole tile is the jump target. */
function Kpi({ label, value, def, state = 'none', onClick }) {
  // Same colour language as Home's band: attention states are amber/rose,
  // complete is emerald, neutral information is plain. Cyan is interactive-only,
  // so it lives on the tile's hover, never on a value.
  const valueColor = state === 'warn' ? 'text-amber-300'
    : state === 'bad' ? 'text-rose-300'
    : state === 'ok' ? 'text-emerald-300'
    : 'text-[color:var(--db-text)]'
  return (
    <button
      onClick={onClick}
      className="ps-anim border-b border-r border-[color:var(--db-border)] p-4 text-left transition last:border-r-0 hover:bg-[var(--db-fill-strong)] lg:border-b-0"
    >
      <p className={`${T.meta} font-medium text-[color:var(--db-text-muted)]`}>{label}</p>
      <p className={`${T.kpi} mt-2 ${valueColor}`}>{value}</p>
      <p className={`${T.micro} mt-1.5 leading-snug text-[color:var(--db-text-faint)]`}>{def}</p>
    </button>
  )
}

/** Flat card: hairline border, no gradient stripe, no forced inner scroller
 *  unless `scroll` (reference lists in the rail, where a cap is the point). */
function Card({ id, icon, title, hint, count, badge, loading, emptyWhileLoading = false, onRefresh, scroll = false, children }) {
  return (
    <section id={id} className="rounded-2xl border border-[color:var(--db-border)] bg-[var(--db-fill)] p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <h2 className={`${T.h1} truncate text-[color:var(--db-text)]`}>{title}</h2>
          {typeof count === 'number' && count > 0 && (
            <span className={`${T.meta} shrink-0 text-[color:var(--db-text-faint)]`}>{count}</span>
          )}
          {badge && (
            <span className={`${T.micro} shrink-0 rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2 py-0.5 font-semibold text-cyan-200`}>{badge}</span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {hint && <span className={`${T.micro} text-[color:var(--db-text-faint)]`}>{hint}</span>}
          {onRefresh && (
            <button onClick={onRefresh} title="Refresh" aria-label="Refresh"
              className="ps-anim grid h-6 w-6 place-items-center rounded-md text-[color:var(--db-text-faint)] transition hover:bg-[var(--db-fill-strong)] hover:text-[color:var(--db-text-muted)]">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'ps-anim animate-spin' : ''}`} />
            </button>
          )}
        </div>
      </div>
      <div className={scroll ? 'ps-scroll max-h-[340px] overflow-y-auto pr-1' : ''}>
        {/* An empty state is a CLAIM ("you have nothing"). Never render it over an
            unanswered request — only the refresh icon used to spin, so the cards
            asserted "Nothing open" while the digest was still in flight. */}
        {loading && emptyWhileLoading
          ? <p className={`${T.meta} px-1 py-3 text-[color:var(--db-text-faint)]`}>Loading…</p>
          : children}
      </div>
    </section>
  )
}

function Field({ label, hint, children }) {
  return (
    <div>
      <label className={`${T.meta} mb-1.5 block font-medium text-[color:var(--db-text-muted)]`}>{label}</label>
      {children}
      {hint && <p className={`${T.micro} mt-1 text-[color:var(--db-text-faint)]`}>{hint}</p>}
    </div>
  )
}

function Pill({ color, bg, border, children }) {
  return (
    <span
      className={`${T.micro} shrink-0 rounded-full px-2 py-0.5 font-semibold`}
      style={{ color, background: bg || `${color}1a`, border: `1px solid ${border || `${color}33`}` }}
    >
      {children}
    </span>
  )
}

function Empty({ text, sub }) {
  return (
    <div className="rounded-xl border border-dashed border-[color:var(--db-border)] px-4 py-5 text-center">
      <p className={`${T.h2} text-[color:var(--db-text-muted)]`}>{text}</p>
      {sub && <p className={`${T.meta} mx-auto mt-1 max-w-md text-[color:var(--db-text-faint)]`}>{sub}</p>}
    </div>
  )
}

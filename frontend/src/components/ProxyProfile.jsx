import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../lib/api'
import { dueInfo, dueLabel } from '../lib/dueStatus'
import {
  UserRoundCheck, ListTodo, Scale, Sparkles, ArrowUpRight, Calendar,
  CircleDot, CornerDownRight, AlertTriangle, Loader2, RefreshCw,
} from 'lucide-react'

/**
 * Stand-in command center. The page that powers Prism representing you when you
 * can't attend. Three layers, top to bottom:
 *   1. What Prism knows about your work  → your open action items + your decisions
 *      (the raw material it speaks from), scoped to the active workspace.
 *   2. Who you are                       → the standing profile + a live preview of
 *      how Prism would represent you right now.
 *   3. Where it's representing you        → your active + past stand-ins.
 */

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

export default function ProxyProfile({ user = null, workspaceId = null, workspaceName = null, onOpenMeeting }) {
  const [roleFocus, setRoleFocus] = useState('')
  const [notes, setNotes] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saveState, setSaveState] = useState('idle')
  const [reps, setReps] = useState([])

  const [digest, setDigest] = useState({ action_items: [], decisions: [] })
  const [digestLoading, setDigestLoading] = useState(true)

  const [preview, setPreview] = useState('')
  const [previewing, setPreviewing] = useState(false)

  const authorName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || ''
  const authorEmail = user?.email || ''
  const scopeLabel = workspaceName || 'Personal'

  const loadProfileAndReps = useCallback(async () => {
    try {
      const [pRes, rRes] = await Promise.all([
        apiFetch('/proxy/profile'),
        apiFetch('/proxy/representations' + (workspaceId ? `?workspace_id=${workspaceId}` : '')),
      ])
      if (pRes.ok) {
        const { profile } = await pRes.json()
        setRoleFocus(profile?.role_focus || '')
        setNotes(clean(profile?.standing_notes))
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

  useEffect(() => { loadProfileAndReps() }, [loadProfileAndReps])
  useEffect(() => { loadDigest() }, [loadDigest])
  // Reset the preview when the scope changes — it's no longer relevant.
  useEffect(() => { setPreview('') }, [workspaceId])

  useEffect(() => {
    const reload = () => { loadProfileAndReps(); loadDigest() }
    window.addEventListener('focus', reload)
    window.addEventListener('prism:standin-changed', reload)
    return () => {
      window.removeEventListener('focus', reload)
      window.removeEventListener('prism:standin-changed', reload)
    }
  }, [loadProfileAndReps, loadDigest])

  const save = async () => {
    setSaveState('saving')
    try {
      const res = await apiFetch('/proxy/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role_focus: roleFocus, standing_notes: notes }),
      })
      setSaveState(res.ok ? 'saved' : 'idle')
      if (res.ok) setTimeout(() => setSaveState('idle'), 1800)
    } catch { setSaveState('idle') }
  }

  const runPreview = async () => {
    setPreviewing(true); setPreview('')
    try {
      const res = await apiFetch('/proxy/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, author_name: authorName, author_email: authorEmail }),
      })
      const data = await res.json().catch(() => ({}))
      setPreview(data.preview || "I couldn't find enough about your work to preview a stand-in yet.")
    } catch { setPreview('Something went wrong generating the preview.') }
    finally { setPreviewing(false) }
  }

  const cancelRep = async (id) => {
    try {
      await apiFetch(`/proxy/representations/${id}/cancel`, { method: 'POST' })
      setReps((r) => r.filter((x) => x.id !== id))
    } catch { /* ignore */ }
  }

  const open = (mid) => { if (mid && onOpenMeeting) onOpenMeeting(mid) }

  const active = reps.filter((r) => ['draft', 'pending'].includes(effStatus(r)))
  const past = reps.filter((r) => ['delivered', 'expired'].includes(effStatus(r)))
  // Banner only for a genuinely upcoming stand-in (future-dated, still pending).
  const scheduled = reps.find((r) => effStatus(r) === 'pending')
  const profileEmpty = loaded && !roleFocus.trim() && !notes.trim()
  const roleOnlyMissing = loaded && !roleFocus.trim() && !!notes.trim()
  const actions = digest.action_items || []
  const decisions = digest.decisions || []

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <style>{`
        .ps-scroll{scrollbar-width:thin;scrollbar-color:rgba(34,211,238,.35) transparent}
        .ps-scroll::-webkit-scrollbar{width:8px}
        .ps-scroll::-webkit-scrollbar-thumb{background:rgba(34,211,238,.28);border-radius:8px;border:2px solid transparent;background-clip:content-box}
        .ps-scroll::-webkit-scrollbar-thumb:hover{background:rgba(34,211,238,.5);background-clip:content-box}
        .ps-scroll::-webkit-scrollbar-track{background:transparent}
        @media (prefers-reduced-motion: reduce){.ps-anim{transition:none!important;animation:none!important}}
      `}</style>

      {/* Hero */}
      <header className="relative overflow-hidden rounded-2xl border border-white/[0.08] p-6"
        style={{ background: 'linear-gradient(135deg, rgba(34,211,238,0.10), rgba(56,189,248,0.05) 40%, rgba(167,139,250,0.10))' }}>
        <div className="absolute -right-10 -top-12 h-44 w-44 rounded-full blur-3xl"
          style={{ background: 'radial-gradient(circle, rgba(34,211,238,0.28), transparent 70%)' }} />
        <div className="relative flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="grid h-9 w-9 place-items-center rounded-xl"
                style={{ background: 'linear-gradient(135deg,#22d3ee,#818cf8)', boxShadow: '0 0 22px rgba(34,211,238,0.45)' }}>
                <UserRoundCheck className="h-5 w-5 text-[#06080d]" />
              </span>
              <h1 className="text-2xl font-bold tracking-[-0.015em]"
                style={{ background: 'linear-gradient(90deg,#67e8f9,#a5b4fc)', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' }}>
                Stand-in
              </h1>
            </div>
            <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-white/55">
              When you can’t attend, Prism represents you — using your work below and the context you give it. It learns more each time you approve a stand-in.
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-cyan-400/25 bg-cyan-400/[0.08] px-3 py-1 text-[11px] font-medium text-cyan-200">
            {scopeLabel}
          </span>
        </div>
      </header>

      {/* Active stand-in banner */}
      {scheduled && (
        <div className="ps-anim flex items-center gap-3 rounded-xl border px-4 py-3 transition"
          style={{ borderColor: 'rgba(34,211,238,0.30)', background: 'linear-gradient(90deg, rgba(34,211,238,0.10), rgba(167,139,250,0.06))', boxShadow: '0 0 0 1px rgba(34,211,238,0.06)' }}>
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/60 ps-anim" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-cyan-400" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-white">
              Prism is standing in for you{scheduled.meeting_label ? <> at <span className="text-cyan-200">{scheduled.meeting_label}</span></> : ''}
            </p>
            {scheduled.join_at && (
              <p className="text-[11px] text-white/45">{new Date(scheduled.join_at).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>
            )}
          </div>
          <button onClick={() => cancelRep(scheduled.id)}
            className="ps-anim shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-[11px] font-medium text-white/55 transition hover:border-red-400/30 hover:text-red-300">
            Cancel
          </button>
        </div>
      )}

      {/* Two-column command center */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* LEFT — your work */}
        <div className="space-y-5">
          {/* Open action items */}
          <Panel
            icon={<ListTodo className="h-4 w-4 text-cyan-300" />}
            title="Your open action items"
            hint="Overdue first"
            count={actions.length}
            countColor="#67e8f9"
            accent="linear-gradient(90deg,#22d3ee,#38bdf8)"
            loading={digestLoading}
            onRefresh={loadDigest}
          >
            {actions.length === 0 ? (
              <Empty text={`No open action items under your name in ${scopeLabel}.`} sub="When meetings assign you tasks, they show up here — and feed your stand-in." />
            ) : (
              <ul className="space-y-1.5">
                {actions.map((a, i) => {
                  const di = dueInfo({ due_date: a.due_date })
                  const dt = di.status ? DUE_TINT[di.status] : null
                  return (
                    <li key={i}>
                      <button onClick={() => open(a.meeting_id)} disabled={!a.meeting_id}
                        className="ps-anim group flex w-full items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition hover:border-white/[0.08] hover:bg-white/[0.03] disabled:cursor-default">
                        <CircleDot className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-400/70" />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-[13px] font-medium text-white">{a.task}</span>
                            {dt && (
                              <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                                style={{ color: dt.color, background: dt.bg, border: `1px solid ${dt.border}` }}>
                                {dueLabel(di)}
                              </span>
                            )}
                          </span>
                          {a.from_decision && (
                            <span className="mt-0.5 flex items-center gap-1 text-[11px] text-violet-300/80">
                              <CornerDownRight className="h-3 w-3 shrink-0" />
                              <span className="line-clamp-1">From decision: {a.from_decision}</span>
                            </span>
                          )}
                          <span className="mt-0.5 block truncate text-[10.5px] text-white/35">{a.meeting}</span>
                        </span>
                        {a.meeting_id && <ArrowUpRight className="ps-anim mt-0.5 h-3.5 w-3.5 shrink-0 text-white/0 transition group-hover:text-white/40" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Panel>

          {/* Decisions */}
          <Panel
            icon={<Scale className="h-4 w-4 text-violet-300" />}
            title="Your decisions"
            hint="Most important first"
            count={decisions.length}
            countColor="#c4b5fd"
            accent="linear-gradient(90deg,#a78bfa,#f0abfc)"
            loading={digestLoading}
            onRefresh={loadDigest}
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
                        className="ps-anim group flex w-full items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition hover:border-white/[0.08] hover:bg-white/[0.03] disabled:cursor-default"
                        style={{ borderLeft: `2px solid ${imp.color}` }}>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-[13px] font-medium text-white">{d.decision}</span>
                            <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                              style={{ color: imp.color, background: imp.tint, border: `1px solid ${imp.border}` }}>
                              {imp.label}
                            </span>
                          </span>
                          {d.rationale && <span className="mt-0.5 line-clamp-2 block text-[11.5px] leading-relaxed text-white/50">{d.rationale}</span>}
                          <span className="mt-1 flex items-center gap-2 text-[10.5px] text-white/35">
                            <span className="truncate">{d.meeting}</span>
                            {!d.has_action && (
                              <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold uppercase tracking-wide"
                                style={{ color: '#fbbf24', background: 'rgba(251,191,36,0.10)', border: '1px solid rgba(251,191,36,0.28)' }}>
                                <AlertTriangle className="h-2.5 w-2.5" /> No action
                              </span>
                            )}
                          </span>
                        </span>
                        {d.meeting_id && <ArrowUpRight className="ps-anim mt-0.5 h-3.5 w-3.5 shrink-0 text-white/0 transition group-hover:text-white/40" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Panel>
        </div>

        {/* RIGHT — who you are + where Prism represents you */}
        <aside className="space-y-5">
          {/* Profile */}
          <section className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
            <h2 className="text-[12px] font-semibold uppercase tracking-wide text-white/45">What Prism should know about you</h2>
            {profileEmpty && (
              <p className="ps-anim mt-3 flex items-start gap-2 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.06] px-3 py-2 text-[11.5px] leading-relaxed text-cyan-100/90">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-300" />
                Add your role and a note or two — Prism represents you noticeably better when it knows what you own.
              </p>
            )}
            <div className="mt-4 space-y-4">
              <div>
                <label className="text-[12px] font-medium text-white/70">Role / focus</label>
                <input value={roleFocus} onChange={(e) => setRoleFocus(e.target.value)}
                  placeholder="e.g. Backend lead — payments & API" disabled={!loaded}
                  className={`mt-1.5 w-full rounded-lg border bg-white/[0.04] px-3 py-2 text-[13px] text-white outline-none placeholder:text-white/30 focus:border-cyan-400/40 ${roleOnlyMissing ? 'border-cyan-400/30' : 'border-white/[0.08]'}`} />
                {roleOnlyMissing && (
                  <p className="mt-1 text-[10.5px] text-cyan-300/70">Add your role so Prism leads with who you are.</p>
                )}
              </div>
              <div>
                <label className="text-[12px] font-medium text-white/70">Standing notes</label>
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
                  placeholder="Ongoing responsibilities, projects you own, anything Prism should mention on your behalf…"
                  disabled={!loaded}
                  className="ps-scroll mt-1.5 w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[13px] leading-relaxed text-white outline-none placeholder:text-white/30 focus:border-cyan-400/40" />
                <p className="mt-1 text-[10.5px] text-white/35">Auto-updated when you approve a stand-in.</p>
              </div>
              <button onClick={save} disabled={saveState === 'saving' || !loaded}
                className="ps-anim w-full rounded-lg bg-cyan-400 py-2 text-[12.5px] font-semibold text-[#06080d] transition hover:bg-cyan-300 disabled:opacity-40">
                {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? '✓ Saved' : 'Save'}
              </button>
            </div>
          </section>

          {/* Preview my stand-in */}
          <section className="overflow-hidden rounded-2xl border p-5"
            style={{ borderColor: 'rgba(167,139,250,0.22)', background: 'linear-gradient(160deg, rgba(167,139,250,0.07), rgba(240,171,252,0.04))' }}>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-300" />
              <h2 className="text-[12px] font-semibold uppercase tracking-wide text-violet-200/80">Preview your stand-in</h2>
            </div>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-white/50">
              See how Prism would represent you right now in <span className="font-medium text-violet-200/90">{scopeLabel}</span> — from your work above and your profile.
            </p>
            {preview && (
              <div className="ps-scroll mt-3 max-h-44 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/[0.07] bg-black/30 px-3 py-2.5 text-[12.5px] leading-relaxed text-white/85">
                {preview}
              </div>
            )}
            <button onClick={runPreview} disabled={previewing}
              className="ps-anim mt-3 flex w-full items-center justify-center gap-2 rounded-lg py-2 text-[12.5px] font-semibold text-[#06080d] transition disabled:opacity-50"
              style={{ background: 'linear-gradient(90deg,#c4b5fd,#f0abfc)' }}>
              {previewing ? <><Loader2 className="ps-anim h-3.5 w-3.5 animate-spin" /> Generating…</> : <><Sparkles className="h-3.5 w-3.5" /> {preview ? 'Regenerate' : 'Preview my stand-in'}</>}
            </button>
          </section>
          {/* Your stand-ins — in the rail, scrollable */}
          <section className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Calendar className="h-4 w-4 text-cyan-300" />
          <h2 className="text-[12px] font-semibold uppercase tracking-wide text-white/45">Your stand-ins</h2>
        </div>
        {!loaded ? (
          <p className="text-[12px] text-white/40">Loading…</p>
        ) : active.length === 0 && past.length === 0 ? (
          <Empty text="No stand-ins yet." sub="On an upcoming meeting you can’t attend, hit “Can’t make it”." />
        ) : (
          <div className="ps-scroll max-h-80 space-y-2 overflow-y-auto pr-1">
            {[...active, ...past].map((rep) => {
              const es = effStatus(rep)
              const meta = STATUS_META[es] || STATUS_META.draft
              return (
                <div key={rep.id} className="flex items-start gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-[13px] font-medium text-white">{rep.meeting_label || 'Meeting'}</p>
                      <span className="shrink-0 rounded-full px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                        style={{ color: meta.color, background: `${meta.color}1a`, border: `1px solid ${meta.color}33` }}>
                        {meta.label}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-white/55">{rep.approved_body || rep.draft_body || '—'}</p>
                  </div>
                  {['draft', 'pending'].includes(es) && (
                    <button onClick={() => cancelRep(rep.id)}
                      className="ps-anim shrink-0 text-[11px] font-medium text-white/40 transition hover:text-red-300">
                      Cancel
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
          </section>
        </aside>
      </div>
    </div>
  )
}

/* ── Reusable scrollable panel for the work boxes ──────────────────────────── */
function Panel({ icon, title, hint, count, countColor, accent, loading, onRefresh, children }) {
  return (
    <section className="relative overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]">
      <div className="h-[3px] w-full" style={{ background: accent, opacity: 0.85 }} />
      <div className="flex items-center justify-between px-5 pt-4">
        <div className="flex items-center gap-2">
          {icon}
          <div className="leading-tight">
            <h2 className="text-[14px] font-semibold tracking-[-0.01em] text-white">{title}</h2>
            {hint && count > 0 && <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-white/30">{hint}</p>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onRefresh} title="Refresh"
            className="ps-anim grid h-6 w-6 place-items-center rounded-md text-white/30 transition hover:bg-white/[0.05] hover:text-white/70">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'ps-anim animate-spin' : ''}`} />
          </button>
          <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
            style={{ color: countColor, background: `${countColor}1a`, border: `1px solid ${countColor}33` }}>
            {count}
          </span>
        </div>
      </div>
      <div className="ps-scroll max-h-[380px] overflow-y-auto px-3 pb-3 pt-2">
        {loading && count === 0 ? <p className="px-2 py-3 text-[12px] text-white/35">Loading…</p> : children}
      </div>
    </section>
  )
}

function Empty({ text, sub }) {
  return (
    <div className="rounded-xl border border-dashed border-white/[0.08] bg-white/[0.01] px-4 py-5 text-center">
      <p className="text-[12.5px] font-medium text-white/55">{text}</p>
      {sub && <p className="mt-1 text-[11px] text-white/35">{sub}</p>}
    </div>
  )
}

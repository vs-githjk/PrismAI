import { useState, useEffect, useCallback } from 'react'
import { apiFetch } from '../lib/api'

/**
 * Stand-in section — your standing "represent me" profile + your active/past
 * stand-ins. The profile (role/focus + standing notes) is personal context Prism
 * draws from when drafting a stand-in, and it's auto-enriched each time you approve.
 */
const STATUS_META = {
  draft: { label: 'Draft', color: '#94a3b8' },
  pending: { label: 'Scheduled', color: '#67e8f9' },
  delivered: { label: 'Delivered', color: '#86efac' },
  expired: { label: 'Expired', color: '#fca5a5' },
}

export default function ProxyProfile() {
  const [roleFocus, setRoleFocus] = useState('')
  const [notes, setNotes] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saveState, setSaveState] = useState('idle') // idle | saving | saved
  const [reps, setReps] = useState([])

  const load = useCallback(async () => {
    try {
      const [pRes, rRes] = await Promise.all([
        apiFetch('/proxy/profile'),
        apiFetch('/proxy/representations'),
      ])
      if (pRes.ok) {
        const { profile } = await pRes.json()
        setRoleFocus(profile?.role_focus || '')
        // Guard against a stale placeholder ('(none)' etc.) ever showing as content.
        const n = (profile?.standing_notes || '').trim()
        setNotes(['(none)', 'none', '(empty)', 'n/a'].includes(n.toLowerCase()) ? '' : (profile?.standing_notes || ''))
      }
      if (rRes.ok) {
        const { representations } = await rRes.json()
        setReps(representations || [])
      }
    } catch { /* leave empty */ }
    finally { setLoaded(true) }
  }, [])

  useEffect(() => { load() }, [load])

  // Refresh on tab focus AND on an explicit signal from the composer, so a
  // just-approved/canceled stand-in shows up without navigating away and back.
  useEffect(() => {
    const reload = () => load()
    window.addEventListener('focus', reload)
    window.addEventListener('prism:standin-changed', reload)
    return () => {
      window.removeEventListener('focus', reload)
      window.removeEventListener('prism:standin-changed', reload)
    }
  }, [load])

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

  const cancelRep = async (id) => {
    try {
      await apiFetch(`/proxy/representations/${id}/cancel`, { method: 'POST' })
      setReps((r) => r.filter((x) => x.id !== id))
    } catch { /* ignore */ }
  }

  const active = reps.filter((r) => ['draft', 'pending'].includes(r.status))
  const past = reps.filter((r) => ['delivered', 'expired'].includes(r.status))

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-[-0.01em] text-white">Stand-in</h1>
        <p className="mt-1 text-[13px] text-white/55">
          When you can’t attend a meeting, Prism represents you. This is the context it uses —
          and it learns more each time you approve a stand-in.
        </p>
      </div>

      {/* Profile */}
      <section className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-white/45">
          What Prism should know about you
        </h2>
        <div className="mt-4 space-y-4">
          <div>
            <label className="text-[12px] font-medium text-white/70">Role / focus</label>
            <input
              value={roleFocus}
              onChange={(e) => setRoleFocus(e.target.value)}
              placeholder="e.g. Backend lead — payments & API"
              disabled={!loaded}
              className="mt-1.5 w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[13px] text-white outline-none placeholder:text-white/30 focus:border-cyan-400/40"
            />
          </div>
          <div>
            <label className="text-[12px] font-medium text-white/70">Standing notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder="Ongoing responsibilities, projects you own, anything Prism should mention on your behalf…"
              disabled={!loaded}
              className="mt-1.5 w-full resize-none rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[13px] leading-relaxed text-white outline-none placeholder:text-white/30 focus:border-cyan-400/40"
            />
            <p className="mt-1 text-[10.5px] text-white/35">Auto-updated when you approve a stand-in.</p>
          </div>
          <button
            onClick={save}
            disabled={saveState === 'saving' || !loaded}
            className="rounded-lg bg-cyan-400 px-4 py-2 text-[12.5px] font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:opacity-40"
          >
            {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? '✓ Saved' : 'Save'}
          </button>
        </div>
      </section>

      {/* Active stand-ins */}
      <section>
        <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-white/45">
          Your stand-ins
        </h2>
        {!loaded ? (
          <p className="text-[12px] text-white/40">Loading…</p>
        ) : active.length === 0 && past.length === 0 ? (
          <p className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3 text-[12px] text-white/45">
            No stand-ins yet. On an upcoming meeting you can’t attend, hit “Can’t make it”.
          </p>
        ) : (
          <div className="space-y-2">
            {[...active, ...past].map((rep) => {
              const meta = STATUS_META[rep.status] || STATUS_META.draft
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
                    <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-white/55">
                      {rep.approved_body || rep.draft_body || '—'}
                    </p>
                  </div>
                  {['draft', 'pending'].includes(rep.status) && (
                    <button
                      onClick={() => cancelRep(rep.id)}
                      className="shrink-0 text-[11px] font-medium text-white/40 transition hover:text-red-300"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

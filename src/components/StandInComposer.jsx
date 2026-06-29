import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { apiFetch } from '../lib/api'

/**
 * Stand-in composer (Feature A) — a chat with Prism to build the update it'll
 * deliver on your behalf when you can't attend a meeting. Prism drafts from your
 * action items + standing profile; you refine by conversation and approve. The
 * approved text is frozen as your stand-in (delivery is wired in later slices).
 *
 * Props:
 *   meeting  – { url, label, workspaceId, scheduledFor }
 *   user     – the signed-in user (for author name/email)
 *   onClose  – () => void
 */
export default function StandInComposer({ meeting, user, onClose }) {
  const [repId, setRepId] = useState(null)
  const [thread, setThread] = useState([]) // [{ role:'prism'|'you', text }]
  const [draft, setDraft] = useState('')
  const [input, setInput] = useState('')
  const [phase, setPhase] = useState('loading') // loading | chatting | approved | error
  const [busy, setBusy] = useState(false)
  const [savedStatus, setSavedStatus] = useState(null) // existing rep status, if resumed
  const [approvedText, setApprovedText] = useState('') // frozen text when already approved
  const [scheduled, setScheduled] = useState(false) // whether a bot was actually scheduled
  const [borrowOptions, setBorrowOptions] = useState([]) // spaces offered to borrow from
  const scrollRef = useRef(null)

  // When already approved, the button should only re-activate if the draft was edited.
  const isApproved = savedStatus === 'pending'
  const isDirty = draft.trim() !== approvedText.trim()

  const authorName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || ''
  const authorEmail = user?.email || ''

  useEffect(() => {
    // Don't auto-scroll the initial draft — let the user read it from the top.
    // Only follow the conversation once they've started refining.
    if (thread.length <= 1) return
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [thread])

  const start = useCallback(async () => {
    setPhase('loading')
    try {
      const res = await apiFetch('/proxy/representations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          meeting_url: meeting.url,
          workspace_id: meeting.workspaceId || null,
          meeting_label: meeting.label || '',
          scheduled_for: meeting.scheduledFor || null,
          author_name: authorName,
          author_email: authorEmail,
        }),
      })
      if (!res.ok) throw new Error('start failed')
      const data = await res.json()
      setRepId(data.representation?.id)
      setDraft(data.draft || '')
      setSavedStatus(data.representation?.status || null)
      setBorrowOptions(data.awaiting_cross_workspace ? (data.borrow_options || []) : [])
      if (data.representation?.status === 'pending') setApprovedText(data.draft || '')
      const msgs = data.messages || []
      setThread(
        msgs.length
          ? msgs.map((m) => ({ role: m.role === 'user' ? 'you' : 'prism', text: m.content }))
          : [{ role: 'prism', text: data.draft || "Here's a draft — anything to change?" }]
      )
      setPhase('chatting')
    } catch {
      setPhase('error')
    }
  }, [meeting, authorName, authorEmail])

  useEffect(() => { start() }, [start])

  // One refine turn. `opts.borrowScopes` is set when the user clicked a "pull from"
  // chip — a borrow pick carries no typed message; the backend drafts from the widened
  // scope. `opts.youText` overrides the bubble shown for the user's turn.
  const turn = async (msg, opts = {}) => {
    if (busy || !repId) return
    const youText = opts.youText ?? msg
    const history = thread.map((m) => ({ role: m.role === 'you' ? 'user' : 'assistant', content: m.text }))
    setBorrowOptions([]) // a turn consumes the offer
    setThread((t) => [...t, { role: 'you', text: youText }, { role: 'prism', text: '…', pending: true }])
    setBusy(true)
    try {
      const res = await apiFetch(`/proxy/representations/${repId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, history, borrow_scopes: opts.borrowScopes ?? null }),
      })
      const data = await res.json()
      setThread((t) => {
        const copy = [...t]
        copy[copy.length - 1] = { role: 'prism', text: data.reply || '(no reply)' }
        return copy
      })
      if (data.draft) setDraft(data.draft)
    } catch {
      setThread((t) => {
        const copy = [...t]
        copy[copy.length - 1] = { role: 'prism', text: '(sorry, something went wrong)' }
        return copy
      })
    } finally {
      setBusy(false)
    }
  }

  const send = async (e) => {
    e?.preventDefault()
    const msg = input.trim()
    if (!msg) return
    setInput('')
    turn(msg)
  }

  const borrowFrom = (opt) => {
    turn('', { borrowScopes: [opt.id ?? null], youText: `Pull from ${opt.name}` })
  }

  const approve = async () => {
    const text = draft.trim()
    if (!text || busy || !repId) return
    setBusy(true)
    try {
      const res = await apiFetch(`/proxy/representations/${repId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_body: text }),
      })
      if (!res.ok) throw new Error('approve failed')
      const data = await res.json().catch(() => ({}))
      setScheduled(!!data.scheduled)
      setPhase('approved')
      window.dispatchEvent(new Event('prism:standin-changed'))
    } catch {
      /* keep editing */
    } finally {
      setBusy(false)
    }
  }

  return createPortal((
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.72)', backdropFilter: 'blur(4px)' }}>
      <div className="flex flex-col rounded-2xl overflow-hidden" style={{ width: 'min(900px, 94vw)', height: '88vh', maxHeight: '900px', background: '#0d0d12', border: '1px solid rgba(34,211,238,0.2)' }}>
        {/* Header */}
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-white">Have Prism represent you</p>
            <p className="text-[11px] text-gray-500 truncate">{meeting.label || 'Upcoming meeting'}</p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-lg leading-none px-1">×</button>
        </div>

        {phase === 'approved' ? (
          <div className="p-6 text-center space-y-2">
            <div className="text-2xl">✓</div>
            <p className="text-sm font-semibold text-cyan-200">Stand-in approved</p>
            <p className="text-[12px] text-gray-400 leading-relaxed">
              {scheduled ? (
                <>Prism will join <span className="text-gray-200">{meeting.label}</span> at its start time and share your update.</>
              ) : (
                <>Saved as your update for <span className="text-gray-200">{meeting.label}</span>. (Prism isn’t scheduled to attend this one yet.)</>
              )}
            </p>
            <button onClick={onClose} className="mt-3 rounded-lg bg-cyan-400/[0.14] px-4 py-2 text-[12px] font-semibold text-cyan-200 hover:bg-cyan-400/[0.22]">
              Done
            </button>
          </div>
        ) : phase === 'error' ? (
          <div className="p-6 text-center space-y-3">
            <p className="text-sm text-red-300">Couldn't start the stand-in.</p>
            <button onClick={start} className="rounded-lg bg-white/[0.06] px-4 py-2 text-[12px] font-semibold text-gray-200 hover:text-white">Retry</button>
          </div>
        ) : (
          <>
            {/* Chat thread */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2 min-h-[140px]">
              {phase === 'loading' && <p className="text-[12px] text-gray-500">Drafting from your action items…</p>}
              {thread.map((m, i) => (
                <div key={i} className={m.role === 'you' ? 'text-right' : ''}>
                  <div className={`inline-block max-w-[88%] rounded-xl px-3 py-1.5 text-left text-[12.5px] leading-relaxed ${
                    m.role === 'you' ? 'bg-cyan-400/10 text-cyan-100' : 'bg-white/[0.04] text-gray-200'
                  } ${m.pending ? 'opacity-60' : ''}`}>
                    {m.text}
                  </div>
                </div>
              ))}
            </div>

            {/* Borrow-from chips — shown when this space is too thin to draft. */}
            {borrowOptions.length > 0 && (
              <div className="px-4 pb-1 flex flex-wrap items-center gap-1.5">
                <span className="text-[10.5px] font-semibold uppercase tracking-wide text-gray-500 mr-1">Pull from</span>
                {borrowOptions.map((o) => (
                  <button
                    key={o.id ?? 'personal'}
                    onClick={() => borrowFrom(o)}
                    disabled={busy}
                    className="rounded-full border border-cyan-400/30 bg-cyan-400/[0.08] px-2.5 py-1 text-[11px] font-medium text-cyan-200 hover:bg-cyan-400/[0.16] disabled:opacity-40"
                  >
                    {o.name}
                  </button>
                ))}
              </div>
            )}

            {/* Chat input */}
            <form onSubmit={send} className="px-4 pb-2 flex items-center gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Refine your update…"
                disabled={busy || phase !== 'chatting'}
                className="flex-1 rounded-lg bg-white/[0.04] px-3 py-1.5 text-[12px] text-gray-100 placeholder:text-gray-600 outline-none focus:bg-white/[0.06] disabled:opacity-50"
              />
              <button type="submit" disabled={busy || !input.trim()} className="rounded-lg bg-white/[0.06] px-2.5 py-1.5 text-[11px] font-semibold text-gray-300 hover:text-white disabled:opacity-40">↑</button>
            </form>

            {/* Editable approve box */}
            <div className="px-4 pb-4 pt-2 space-y-2" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              {isApproved && (
                <p className="text-[10.5px] text-cyan-300/80">
                  ✓ Already approved for this meeting{isDirty ? ' — re-approve to save your edits.' : '.'}
                </p>
              )}
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-gray-500">
                Your stand-in update{isApproved ? '' : ' — edit before approving'}
              </p>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={4}
                disabled={phase !== 'chatting'}
                placeholder="Tell Prism above what to share or ask — your update will appear here. You can also type it directly."
                className="w-full resize-none rounded-lg bg-white/[0.04] px-3 py-2 text-[12.5px] leading-relaxed text-gray-100 outline-none placeholder:text-white/25 focus:bg-white/[0.06]"
              />
              {isApproved && !isDirty ? (
                // Already approved and unchanged — no action to take; show state, not a CTA.
                <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2">
                  <span className="text-[12px] font-medium text-cyan-300">✓ Approved — Prism will share this</span>
                  <button onClick={onClose} className="text-[11px] font-semibold text-gray-400 hover:text-white">Done</button>
                </div>
              ) : (
                <button
                  onClick={approve}
                  disabled={busy || !draft.trim() || phase !== 'chatting'}
                  className="w-full rounded-lg bg-cyan-400 py-2 text-[12.5px] font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isApproved ? '✓ Re-approve update' : '✓ Approve this stand-in'}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  ), document.body)
}

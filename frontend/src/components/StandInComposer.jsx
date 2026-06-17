import { useState, useEffect, useRef, useCallback } from 'react'
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
  const scrollRef = useRef(null)

  const authorName = user?.user_metadata?.full_name || user?.email?.split('@')[0] || ''
  const authorEmail = user?.email || ''

  useEffect(() => {
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
      setThread([{ role: 'prism', text: data.draft || "Here's a draft — anything to change?" }])
      setPhase('chatting')
    } catch {
      setPhase('error')
    }
  }, [meeting, authorName, authorEmail])

  useEffect(() => { start() }, [start])

  const send = async (e) => {
    e?.preventDefault()
    const msg = input.trim()
    if (!msg || busy || !repId) return
    setInput('')
    const history = thread.map((m) => ({ role: m.role === 'you' ? 'user' : 'assistant', content: m.text }))
    setThread((t) => [...t, { role: 'you', text: msg }, { role: 'prism', text: '…', pending: true }])
    setBusy(true)
    try {
      const res = await apiFetch(`/proxy/representations/${repId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, history }),
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
      setPhase('approved')
    } catch {
      /* keep editing */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}>
      <div className="w-full max-w-lg rounded-2xl overflow-hidden flex flex-col" style={{ maxHeight: '85vh', background: '#0d0d12', border: '1px solid rgba(34,211,238,0.2)' }}>
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
              Saved as your update for <span className="text-gray-200">{meeting.label}</span>.
              Prism will share it when the meeting runs.
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
              <p className="text-[10.5px] font-semibold uppercase tracking-wide text-gray-500">Your stand-in update — edit before approving</p>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={3}
                disabled={phase !== 'chatting'}
                className="w-full resize-none rounded-lg bg-white/[0.04] px-3 py-2 text-[12.5px] leading-relaxed text-gray-100 outline-none focus:bg-white/[0.06]"
              />
              <button
                onClick={approve}
                disabled={busy || !draft.trim() || phase !== 'chatting'}
                className="w-full rounded-lg bg-cyan-400 py-2 text-[12.5px] font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
              >
                ✓ Approve this stand-in
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

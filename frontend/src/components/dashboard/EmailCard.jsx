import { useState, useEffect } from 'react'
import { Copy, Pencil, Plus, Send } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { notifyStatus } from '../../lib/statusNotify'
import { cardGlowStyle, glassCard, subtleText } from './dashboardStyles'

export default function EmailCard({ email, gmailConnected = false, suggestedEmails = [], onSave, viewerName = '', meetingId, transcript = '', result = null }) {
  const [copied, setCopied] = useState(false)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [sendError, setSendError] = useState(null)
  const [showSendForm, setShowSendForm] = useState(false)
  const [toInput, setToInput] = useState('')

  // Local override so edits apply immediately to Send/Copy even before (or without)
  // the parent persisting them. Re-synced if a fresh draft arrives (e.g. a chat re-run).
  const [editedEmail, setEditedEmail] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draftSubject, setDraftSubject] = useState('')
  const [draftBody, setDraftBody] = useState('')

  // Per-viewer authorship: the analysis writes the draft from the meeting owner, but
  // each person's follow-up should read as written by THEM. On view, regenerate the
  // draft FROM the current viewer (display-only — never persisted to the shared meeting,
  // so it doesn't overwrite anyone else's). Cached per session to avoid re-calling.
  const [personalized, setPersonalized] = useState(null)
  const [personalizing, setPersonalizing] = useState(false)

  useEffect(() => { setEditedEmail(null); setEditing(false); setPersonalized(null) }, [email])

  useEffect(() => {
    if (!viewerName || !email || (!email.subject && !email.body)) return
    const cacheKey = `prism_email_v1_${meetingId || 'x'}_${viewerName}`
    try {
      const cached = sessionStorage.getItem(cacheKey)
      if (cached) { setPersonalized(JSON.parse(cached)); return }
    } catch { /* ignore */ }
    let cancelled = false
    setPersonalizing(true)
    apiFetch('/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: 'email_drafter', transcript: transcript || '', result, owner_name: viewerName }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const e = data?.follow_up_email
        if (e && !cancelled) {
          setPersonalized(e)
          try { sessionStorage.setItem(cacheKey, JSON.stringify(e)) } catch { /* ignore */ }
        }
      })
      .catch(() => { /* keep the original draft on failure */ })
      .finally(() => { if (!cancelled) setPersonalizing(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId, viewerName, email])

  if (!email || (!email.subject && !email.body)) return null

  const view = editedEmail || personalized || email
  const wordCount = `${view.body || ''}`.trim().split(/\s+/).filter(Boolean).length

  const handleCopy = () => {
    const text = `Subject: ${view.subject}\n\n${view.body}`
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  function startEdit() {
    setDraftSubject(view.subject || '')
    setDraftBody(view.body || '')
    setEditing(true)
    setShowSendForm(false)
  }

  function saveEdit() {
    const updated = { ...view, subject: draftSubject.trim(), body: draftBody }
    setEditedEmail(updated)
    setEditing(false)
    onSave?.(updated) // persist into the meeting result + DB so the fix survives refresh
  }

  function addRecipient(addr) {
    const current = toInput.split(/[\s,;]+/).map(e => e.trim()).filter(Boolean)
    if (current.includes(addr)) return
    setToInput([...current, addr].join(', '))
    setSendError(null)
  }

  const currentRecipients = toInput.split(/[\s,;]+/).map(e => e.trim()).filter(Boolean)
  const availableSuggestions = (suggestedEmails || []).filter(e => e && !currentRecipients.includes(e))

  const handleSend = async () => {
    const to = toInput.split(/[\s,;]+/).map(e => e.trim()).filter(e => e.includes('@'))
    if (!to.length) {
      setSendError('Enter at least one valid email address.')
      return
    }
    setSending(true)
    setSendError(null)
    try {
      await apiFetch('/send-followup-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ to, subject: view.subject, body: view.body }),
      })
      setSent(true)
      setShowSendForm(false)
      notifyStatus({ kind: 'send', message: 'Email sent' })
      setTimeout(() => setSent(false), 4000)
    } catch (err) {
      setSendError(err?.message || 'Send failed — check Gmail connection.')
    } finally {
      setSending(false)
    }
  }

  const actionBtn =
    'flex items-center gap-1.5 rounded-lg border border-white/[0.10] bg-white/[0.04] px-2.5 py-1.5 text-[11px] font-medium text-white/60 transition hover:border-white/[0.18] hover:text-white/90'

  return (
    <section className={`${glassCard} p-5`} style={cardGlowStyle}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-[-0.01em] text-white">Follow-up email</h2>
          <p className="mt-1 text-xs font-medium text-white/45">
            {editing
              ? 'Editing draft'
              : personalizing && !personalized
                ? 'Personalizing for you…'
                : `Ready-to-edit draft · ${wordCount} words${personalized ? ' · written as you' : ''}`}
          </p>
        </div>
        {!editing && (
          <div className="flex items-center gap-2">
            <button type="button" onClick={startEdit} className={actionBtn}>
              <Pencil className="h-3 w-3" aria-hidden="true" />
              Edit
            </button>
            {gmailConnected && (
              sent ? (
                <span className="text-[11px] font-semibold text-emerald-300">Sent!</span>
              ) : (
                <button
                  type="button"
                  onClick={() => { setShowSendForm(s => !s); setSendError(null) }}
                  className={actionBtn}
                >
                  <Send className="h-3 w-3" aria-hidden="true" />
                  Send
                </button>
              )
            )}
            <button type="button" onClick={handleCopy} className={actionBtn}>
              <Copy className="h-3 w-3" aria-hidden="true" />
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        )}
      </div>

      {showSendForm && !editing && (
        <div className="mb-3 overflow-hidden rounded-lg border border-white/[0.08]">
          <div className="space-y-2 px-3 py-2.5">
            <label className={subtleText}>To: <span className="text-white/30">(separate with commas)</span></label>
            <input
              type="text"
              value={toInput}
              onChange={e => { setToInput(e.target.value); setSendError(null) }}
              onKeyDown={e => e.key === 'Enter' && handleSend()}
              placeholder="name@example.com"
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 outline-none placeholder:text-white/28 focus:border-cyan-400/40"
              autoFocus
            />
            {availableSuggestions.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10.5px] text-white/35">Teammates:</span>
                {availableSuggestions.map((addr) => (
                  <button
                    key={addr}
                    type="button"
                    onClick={() => addRecipient(addr)}
                    className="inline-flex items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.04] px-2 py-0.5 text-[11px] text-white/70 transition hover:border-cyan-400/40 hover:text-cyan-200"
                  >
                    <Plus className="h-3 w-3" /> {addr}
                  </button>
                ))}
              </div>
            )}
            {sendError && <p className="text-[11px] text-red-400">{sendError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { setShowSendForm(false); setSendError(null) }}
                className={subtleText + ' transition hover:text-white/80'}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSend}
                disabled={sending || !toInput.trim()}
                className="rounded-lg bg-cyan-400 px-3 py-1 text-[11px] font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:opacity-40"
              >
                {sending ? 'Sending…' : 'Send via Gmail'}
              </button>
            </div>
          </div>
        </div>
      )}

      {editing ? (
        <div className="space-y-2.5">
          <input
            type="text"
            value={draftSubject}
            onChange={e => setDraftSubject(e.target.value)}
            placeholder="Subject"
            className="w-full rounded-lg border border-white/[0.10] bg-white/[0.04] px-3 py-2 text-[15px] font-semibold text-white outline-none placeholder:text-white/28 focus:border-cyan-400/40"
          />
          <textarea
            value={draftBody}
            onChange={e => setDraftBody(e.target.value)}
            rows={12}
            placeholder="Email body"
            className="w-full resize-y rounded-lg border border-white/[0.10] bg-white/[0.04] px-3 py-2 text-sm leading-7 text-white/85 outline-none placeholder:text-white/28 focus:border-cyan-400/40"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setEditing(false)}
              className={subtleText + ' transition hover:text-white/80'}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={saveEdit}
              className="rounded-lg bg-cyan-400 px-3 py-1 text-[11px] font-semibold text-[#07040f] transition hover:bg-cyan-300"
            >
              Save changes
            </button>
          </div>
        </div>
      ) : (
        <>
          {view.subject && (
            <p className="text-[15px] font-semibold leading-snug text-white">{view.subject}</p>
          )}
          <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-white/75">{view.body}</p>
        </>
      )}
    </section>
  )
}

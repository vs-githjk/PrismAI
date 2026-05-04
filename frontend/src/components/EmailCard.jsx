import { useState } from 'react'
import { Copy, Mail, Send } from 'lucide-react'
import { apiFetch } from '../lib/api'
import { cardGlowStyle, eyebrow, glassCard, subtleText } from './dashboard/dashboardStyles'

export default function EmailCard({ email, gmailConnected = false }) {
  const [copied, setCopied] = useState(false)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [sendError, setSendError] = useState(null)
  const [showSendForm, setShowSendForm] = useState(false)
  const [toInput, setToInput] = useState('')

  if (!email || (!email.subject && !email.body)) return null

  const wordCount = `${email.body || ''}`.trim().split(/\s+/).filter(Boolean).length

  const handleCopy = () => {
    const text = `Subject: ${email.subject}\n\n${email.body}`
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

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
        body: JSON.stringify({ to, subject: email.subject, body: email.body }),
      })
      setSent(true)
      setShowSendForm(false)
      setTimeout(() => setSent(false), 4000)
    } catch (err) {
      setSendError(err?.message || 'Send failed — check Gmail connection.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Mail className="h-4 w-4 text-cyan-200/70" aria-hidden="true" />
          <p className={eyebrow}>Follow-up Email</p>
        </div>
        <div className="flex items-center gap-2">
          {gmailConnected && (
            sent ? (
              <span className="text-[11px] text-cyan-300">Sent!</span>
            ) : (
              <button
                type="button"
                onClick={() => { setShowSendForm(s => !s); setSendError(null) }}
                className="flex items-center gap-1.5 rounded-lg border border-white/[0.10] bg-white/[0.04] px-2.5 py-1 text-[11px] font-medium text-white/60 transition hover:border-white/[0.18] hover:text-white/90"
              >
                <Send className="h-3 w-3" aria-hidden="true" />
                Send
              </button>
            )
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-lg border border-white/[0.10] bg-white/[0.04] px-2.5 py-1 text-[11px] font-medium text-white/60 transition hover:border-white/[0.18] hover:text-white/90"
          >
            <Copy className="h-3 w-3" aria-hidden="true" />
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5">
        <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">Ready-to-edit draft</span>
        <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">{wordCount} words</span>
      </div>

      {showSendForm && (
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

      <div className="overflow-hidden rounded-lg border border-white/[0.08]">
        {email.subject && (
          <div className="border-b border-white/[0.07] px-3 py-2.5">
            <span className={subtleText}>Subject: </span>
            <span className="text-sm font-medium text-white">{email.subject}</span>
          </div>
        )}
        <div className="px-3 py-2.5">
          <p className="text-sm leading-6 text-white/78 whitespace-pre-wrap">{email.body}</p>
        </div>
      </div>

      <p className={`mt-3 ${subtleText}`}>
        {gmailConnected
          ? 'Review before sending. Use the Send button to deliver via your connected Gmail.'
          : 'Use this as a polished starting point. Review tone, promises, and dates before sending.'}
      </p>
    </section>
  )
}

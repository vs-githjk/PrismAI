import { useState, useRef, useEffect } from 'react'

/**
 * Private live catch-up — "Ask Prism (just you)".
 * Token-gated, streaming Q&A over the LIVE meeting state. Answers return ONLY to
 * this browser; nothing is spoken into the meeting or shown to other viewers.
 * Used on the live-share page and in the dashboard live area (same component).
 *
 * Props:
 *   liveToken    – the bot's live_token (required)
 *   accessToken  – Supabase access token, if signed in. Sent as Bearer so a
 *                  workspace member unlocks the knowledge-base fallback.
 */
export default function LiveCatchup({ liveToken, accessToken = null }) {
  const [thread, setThread] = useState([]) // [{ role:'you'|'prism', text, sources?, streaming? }]
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [thread])

  // Mutate the trailing Prism message as tokens stream in.
  const appendToken = (tok) =>
    setThread((t) => {
      const copy = [...t]
      const last = copy[copy.length - 1]
      if (last?.role === 'prism') copy[copy.length - 1] = { ...last, text: last.text + tok }
      return copy
    })
  const finishLast = (sources) =>
    setThread((t) => {
      const copy = [...t]
      const last = copy[copy.length - 1]
      if (last?.role === 'prism') copy[copy.length - 1] = { ...last, sources, streaming: false }
      return copy
    })

  const ask = async (mode, question) => {
    if (busy || !liveToken) return
    setBusy(true)
    setThread((t) => [
      ...t,
      { role: 'you', text: mode === 'catchup' ? 'Catch me up' : question },
      { role: 'prism', text: '', streaming: true },
    ])
    try {
      const headers = { 'Content-Type': 'application/json' }
      if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`
      const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/live/${liveToken}/ask`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ mode, question: question || '' }),
      })
      if (res.status === 429) {
        appendToken('One moment — too many questions in a row.')
        finishLast([])
        return
      }
      if (!res.ok || !res.body) {
        appendToken('Catch-up is unavailable right now.')
        finishLast([])
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let sources = []
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop()
        for (const line of parts) {
          if (!line.startsWith('data: ')) continue
          let payload
          try { payload = JSON.parse(line.slice(6)) } catch { continue }
          if (payload.token) appendToken(payload.token)
          if (payload.done) sources = payload.sources || []
        }
      }
      finishLast(sources)
    } catch {
      appendToken(' (sorry, something went wrong)')
      finishLast([])
    } finally {
      setBusy(false)
    }
  }

  const submit = (e) => {
    e?.preventDefault()
    const q = input.trim()
    if (!q || busy) return
    setInput('')
    ask('qa', q)
  }

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(34,211,238,0.18)' }}
    >
      <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        <svg className="w-3.5 h-3.5 text-cyan-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4-.8L3 21l1.3-3.9A7.96 7.96 0 013 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <span className="text-xs font-semibold text-cyan-200">Ask Prism</span>
        <span className="text-[10px] text-gray-500">· just you</span>
      </div>

      <div className="px-4 py-3 space-y-3">
        <p className="text-[10.5px] text-gray-500 leading-relaxed">
          Private — only you see this. Nothing is said in the meeting.
        </p>

        {thread.length > 0 && (
          <div ref={scrollRef} className="max-h-64 overflow-y-auto space-y-2 pr-1">
            {thread.map((m, i) => (
              <div key={i} className={m.role === 'you' ? 'text-right' : ''}>
                <div
                  className={`inline-block max-w-[88%] rounded-xl px-3 py-1.5 text-left text-[12.5px] leading-relaxed ${
                    m.role === 'you' ? 'bg-cyan-400/10 text-cyan-100' : 'bg-white/[0.04] text-gray-200'
                  }`}
                >
                  {m.text || (m.streaming ? '…' : '')}
                  {m.role === 'prism' && m.sources?.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {m.sources.map((s, j) => (
                        <span key={j} className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[9.5px] text-gray-400">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => ask('catchup', '')}
            disabled={busy}
            className="shrink-0 rounded-lg bg-cyan-400/[0.12] px-3 py-1.5 text-[11px] font-semibold text-cyan-200 transition hover:bg-cyan-400/[0.2] disabled:opacity-40"
          >
            ✨ Catch me up
          </button>
          <form onSubmit={submit} className="flex flex-1 items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about the meeting…"
              disabled={busy}
              className="flex-1 rounded-lg bg-white/[0.04] px-3 py-1.5 text-[12px] text-gray-100 placeholder:text-gray-600 outline-none focus:bg-white/[0.06] disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="shrink-0 rounded-lg bg-white/[0.06] px-2.5 py-1.5 text-[11px] font-semibold text-gray-300 transition hover:text-white disabled:opacity-40"
            >
              ↑
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

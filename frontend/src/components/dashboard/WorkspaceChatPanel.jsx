// Home's global assistant — asks across ALL saved meetings via /chat/global.
// Read-scope by design: it never receives a focused meeting, transcript, or
// result, so it cannot correct/rerun anything. Until the backend scopes
// /chat/global by workspace, the header says "Across your saved meetings".
import { useRef, useState, useEffect } from 'react'
import { Sparkles, SendHorizontal, RotateCcw } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { MarkdownMessage, SourceCard } from '../ChatPanel'
import { glassCard, cardGlowStyle, eyebrow, subtleText } from './dashboardStyles'

const SUGGESTIONS = [
  'What did we commit to this week?',
  'Which decisions are still unresolved?',
  'Summarize my last 3 meetings',
]

export default function WorkspaceChatPanel({ user, onOpenMeeting }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, loading])

  async function send(text) {
    const msg = (text ?? input).trim()
    if (!msg || loading) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      const res = await apiFetch('/chat/global', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      if (!res.ok) throw new Error(`global chat ${res.status}`)
      const data = await res.json()
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: data.response ?? 'No response from server.',
        toolsUsed: data.tools_used || [],
        ragContext: data.rag_context || null,
      }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', error: true, retryText: msg }])
    } finally {
      setLoading(false)
    }
  }

  if (!user) {
    return (
      <section className={`${glassCard} flex h-full flex-col items-center justify-center gap-2 p-6 text-center`} style={cardGlowStyle}>
        <Sparkles className="h-5 w-5 text-[color:var(--db-text-faint)]" />
        <p className={subtleText}>Sign in to ask Prism across your saved meetings.</p>
      </section>
    )
  }

  return (
    <section className={`${glassCard} flex h-full min-h-0 flex-col`} style={cardGlowStyle} aria-label="Ask Prism">
      <header className="border-b px-4 py-3" style={{ borderColor: 'var(--db-border)' }}>
        <div className="flex items-center gap-2 text-[color:var(--db-text)]">
          <Sparkles className="h-4 w-4 text-[color:var(--db-accent-text)]" />
          <span className="text-sm font-semibold">Ask Prism</span>
        </div>
        <p className={`${subtleText} mt-0.5`}>Across your saved meetings</p>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && !loading && (
          <div className="flex h-full flex-col justify-end gap-2">
            <p className={eyebrow}>Try asking</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)}
                className="rounded-xl border px-3 py-2 text-left text-sm text-[color:var(--db-text-soft)] hover:bg-[color:var(--db-fill)]"
                style={{ borderColor: 'var(--db-border)' }}>
                {s}
              </button>
            ))}
          </div>
        )}
        <div className="space-y-3">
          {messages.map((m, i) => m.role === 'user' ? (
            <div key={i} className="ml-8 rounded-2xl rounded-br-md bg-[color:var(--db-fill-strong)] px-3 py-2 text-sm text-[color:var(--db-text)]">{m.content}</div>
          ) : m.error ? (
            <div key={i} className="mr-8 rounded-2xl border px-3 py-2 text-sm text-[color:var(--db-text-muted)]" style={{ borderColor: 'var(--db-border)' }}>
              Couldn't reach Prism.
              <button onClick={() => send(m.retryText)} className="ml-2 inline-flex items-center gap-1 text-[color:var(--db-accent-text)]">
                <RotateCcw className="h-3 w-3" /> Retry
              </button>
            </div>
          ) : (
            <div key={i} className="mr-4 text-sm text-[color:var(--db-text-soft)]">
              <MarkdownMessage>{m.content}</MarkdownMessage>
              {m.toolsUsed?.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {m.toolsUsed.map((t) => (
                    <span key={t} className="rounded-full border px-2 py-0.5 text-[10px] text-[color:var(--db-text-muted)]" style={{ borderColor: 'var(--db-border)' }}>✓ {t}</span>
                  ))}
                </div>
              )}
              {m.ragContext?.has_conflict && (
                <p className="mt-1.5 rounded-lg bg-amber-500/10 px-2 py-1 text-xs text-amber-500">Sources disagree — check the citations below.</p>
              )}
              {m.ragContext?.sources?.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  <p className={eyebrow}>Sources ({m.ragContext.sources.length})</p>
                  {m.ragContext.sources.map((s, j) => <SourceCard key={j} source={s} />)}
                </div>
              )}
            </div>
          ))}
          {loading && <p className={`${subtleText} animate-pulse`}>Searching your meetings…</p>}
        </div>
      </div>

      <form className="flex items-end gap-2 border-t px-3 py-3" style={{ borderColor: 'var(--db-border)' }}
        onSubmit={(e) => { e.preventDefault(); send() }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
          rows={1}
          placeholder="Ask across your meetings…"
          className="max-h-32 min-h-[40px] flex-1 resize-none rounded-xl border bg-transparent px-3 py-2 text-sm text-[color:var(--db-text)] outline-none placeholder:text-[color:var(--db-text-faint)]"
          style={{ borderColor: 'var(--db-border)' }}
        />
        <button type="submit" disabled={loading || !input.trim()} aria-label="Send"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[color:var(--db-accent)] text-black disabled:opacity-40">
          <SendHorizontal className="h-4 w-4" />
        </button>
      </form>
    </section>
  )
}

import { useState, useRef, useEffect } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const SUGGESTED_QUESTIONS = [
  'What were the key decisions?',
  'Who owns what?',
  'What\'s the timeline?',
]

// Detect if the user wants to re-run an agent
function detectAgentIntent(msg) {
  const m = msg.toLowerCase()
  if (/redraft|rewrite|redo|revise|formal|casual|shorter|longer/.test(m) && /email/.test(m)) return 'email_drafter'
  if (/redo|regenerate|update|add|remove/.test(m) && /action item|task|owner|due/.test(m)) return 'action_items'
  if (/redo|regenerate|rewrite/.test(m) && /summar/.test(m)) return 'summarizer'
  if (/redo|reschedule|suggest/.test(m) && /calendar|meeting|follow.up/.test(m)) return 'calendar_suggester'
  if (/redo|regenerate|update/.test(m) && /decision|decided|agreed/.test(m)) return 'decisions'
  return null
}

export default function ChatPanel({ transcript, result, onResultUpdate }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text) => {
    const msg = (text || input).trim()
    if (!msg || loading) return

    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setInput('')
    setLoading(true)

    const agentIntent = result && transcript ? detectAgentIntent(msg) : null

    try {
      if (agentIntent) {
        // Re-run the specific agent with the user's instruction as extra context
        const res = await fetch(`${API}/agent`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent: agentIntent, transcript, instruction: msg }),
        })
        if (!res.ok) throw new Error('Agent call failed')
        const data = await res.json()

        // Update the relevant result card
        const agentKey = {
          email_drafter: 'follow_up_email',
          action_items: 'action_items',
          decisions: 'decisions',
          summarizer: 'summary',
          calendar_suggester: 'calendar_suggestion',
        }[agentIntent]

        if (agentKey && data[agentKey] !== undefined) {
          onResultUpdate({ [agentKey]: data[agentKey] })
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: `Done — I've updated the ${agentIntent.replace('_', ' ')} card with your changes.`,
            agentUpdated: agentIntent,
          }])
        } else {
          throw new Error('No result')
        }
      } else {
        // Regular chat
        const res = await fetch(`${API}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg, transcript }),
        })
        if (!res.ok) throw new Error('Chat failed')
        const data = await res.json()
        setMessages((prev) => [...prev, { role: 'assistant', content: data.response }])
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, something went wrong.' }])
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="rounded-2xl border border-white/8 overflow-hidden flex flex-col" style={{ background: 'rgba(255,255,255,0.03)', height: '360px' }}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2 flex-shrink-0">
        <div className="w-6 h-6 rounded-lg flex items-center justify-center"
          style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.25)' }}>
          <svg className="w-3.5 h-3.5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </div>
        <span className="text-xs font-semibold text-gray-300">Ask about this meeting</span>
        {result && (
          <span className="ml-1 text-[10px] px-2 py-0.5 rounded-full"
            style={{ background: 'rgba(14,165,233,0.1)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
            agent-aware
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5 px-2 py-1 rounded-full bg-white/5 border border-white/8">
          <div className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse"></div>
          <span className="text-[10px] text-gray-500">llama-3.3-70b</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-4 pt-4">
            <div className="w-10 h-10 rounded-2xl flex items-center justify-center"
              style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.2)' }}>
              <svg className="w-5 h-5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <p className="text-gray-600 text-xs text-center">Ask anything about the meeting transcript</p>
            {result && <p className="text-[11px] text-sky-900 text-center">Try: "redraft the email more formally" or "redo action items with deadlines"</p>}
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button key={q} onClick={() => send(q)}
                  className="text-xs px-3 py-1.5 rounded-full border border-white/8 text-gray-400 hover:text-gray-200 hover:border-sky-500/30 hover:bg-sky-500/10 transition-all">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in-up`}>
            {msg.role === 'assistant' && (
              <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mr-2 mt-0.5"
                style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.2)' }}>
                <svg className="w-3 h-3 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
            )}
            <div className={`max-w-[78%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user' ? 'text-white rounded-tr-sm' : 'text-gray-200 border border-white/8 rounded-tl-sm'
              }`}
              style={msg.role === 'user'
                ? { background: 'linear-gradient(135deg, #0284c7, #0d9488)' }
                : { background: 'rgba(255,255,255,0.05)' }}>
              {msg.content}
              {msg.agentUpdated && (
                <span className="block mt-1 text-[10px] text-sky-400 opacity-70">↑ card updated</span>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start items-center gap-2">
            <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.2)' }}>
              <svg className="w-3 h-3 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm border border-white/8" style={{ background: 'rgba(255,255,255,0.05)' }}>
              <div className="flex gap-1.5 items-center h-4">
                <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-1.5 h-1.5 bg-sky-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-white/5 flex gap-2 flex-shrink-0">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder={result ? 'Ask or say "redraft email more formally"...' : 'Ask a question...'}
          className="flex-1 text-gray-200 rounded-xl px-3.5 py-2.5 text-sm outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600 transition-colors"
          style={{ background: 'rgba(0,0,0,0.3)' }}
        />
        <button onClick={() => send()} disabled={!input.trim() || loading}
          className="w-10 h-10 flex items-center justify-center rounded-xl text-white disabled:opacity-30 disabled:cursor-not-allowed transition-all hover:scale-105 active:scale-95"
          style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
    </div>
  )
}

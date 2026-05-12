import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ClipboardList,
  History,
  ListChecks,
  MessagesSquare,
  Send,
  Sparkles,
  X,
} from 'lucide-react'
import { apiFetch } from '../lib/api'

// Pool of generic, meeting-agnostic prompts. 3 are picked at random on every new blank chat.
const SUGGESTED_QUESTIONS = [
  'What were the key decisions?',
  'Who owns what?',
  "What's the timeline?",
  'Summarize this meeting in 3 bullets.',
  'What action items came out of this?',
  'Were any risks or blockers raised?',
  "What's the overall sentiment?",
  'Draft a follow-up email.',
  "What didn't get resolved?",
  'Suggest a calendar follow-up.',
]

const SUGGESTION_ICONS = [Sparkles, ListChecks, ClipboardList, MessagesSquare]

function pickThree(pool, seed) {
  // Deterministic shuffle from seed so the same blank chat keeps the same suggestions
  const arr = pool.slice()
  let s = seed >>> 0 || 1
  for (let i = arr.length - 1; i > 0; i -= 1) {
    s = (s * 1664525 + 1013904223) >>> 0
    const j = s % (i + 1)
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr.slice(0, 3)
}

function detectGlobalIntent(msg) {
  const m = msg.toLowerCase()
  return (
    /last \d+ meetings?/.test(m) ||
    /across all meetings?/.test(m) ||
    /all (my )?meetings?/.test(m) ||
    /past meetings?/.test(m) ||
    /meeting history/.test(m) ||
    /what did (i|we) commit/.test(m) ||
    /which meetings?/.test(m) ||
    /recurring (action|task|item|issue)/.test(m) ||
    /(last|past) (week|month|quarter|year)/.test(m) ||
    /over time/.test(m) ||
    /trend/.test(m) ||
    /all time/.test(m) ||
    /history of/.test(m) ||
    /previous meetings?/.test(m)
  )
}

function detectAgentIntent(msg) {
  const m = msg.toLowerCase()
  if (/undo|revert|restore|back to (the )?(original|old|previous|last|before)|reset (the )?(card|email|summary|action|decision)/.test(m)) return 'undo'
  if (/email/.test(m) && /redraft|rewrite|redo|revise|make|formal|casual|shorter|longer|concise|tone|style|angry|angrier|polite|friendl|professional/.test(m)) return 'email_drafter'
  if (/action item|task|todo/.test(m) && /redo|regenerate|update|add|remove|change|rewrite/.test(m)) return 'action_items'
  if (/summar/.test(m) && /redo|regenerate|rewrite|update|change|shorten|shorter|longer|make|improve|concise/.test(m)) return 'summarizer'
  if (/calendar|follow.up time|reschedule/.test(m) && /redo|regenerate|suggest|change|update|set|move|shift|reschedule/.test(m)) return 'calendar_suggester'
  if (/decision|decided|agreed/.test(m) && /redo|regenerate|update|change|add|remove|rewrite/.test(m)) return 'decisions'
  if (/sentiment|tone|mood|emotion|tension/.test(m) && /redo|regenerate|reanalyze|rerun|check|analyze|update/.test(m)) return 'sentiment'
  if (/health.?score|meeting quality/.test(m) && /redo|regenerate|reanalyze|rerun|recalculate|update/.test(m)) return 'health_score'
  return null
}

function formatSessionDate(value) {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function ChatPanel({
  meetingId,
  initialMessages = [],
  pastSessions = [],
  onPastSessionsChange,
  onCommitOnExit,
  transcript,
  result,
  onResultUpdate,
  isSignedIn = false,
}) {
  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingGlobal, setLoadingGlobal] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [viewingSession, setViewingSession] = useState(null)
  const prevResultRef = useRef(null)
  const historyRef = useRef(null)
  const bottomRef = useRef(null)
  const messagesRef = useRef(messages)
  const onCommitOnExitRef = useRef(onCommitOnExit)

  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { onCommitOnExitRef.current = onCommitOnExit }, [onCommitOnExit])

  // On unmount (meeting switch via key change, or view switch away from Meeting), fire the
  // commit callback with this instance's own meetingId + final messages. The parent uses this
  // to POST /chat-sessions — relying on a parent ref would race with the new ChatPanel's mount.
  useEffect(() => {
    const myMeetingId = meetingId
    return () => {
      const cb = onCommitOnExitRef.current
      const finalMessages = messagesRef.current
      if (cb && myMeetingId && finalMessages.some((m) => m.role === 'user')) {
        cb(myMeetingId, finalMessages)
      }
    }
  }, [meetingId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, viewingSession])

  useEffect(() => {
    if (!showHistory) return undefined
    const handler = (e) => { if (!historyRef.current?.contains(e.target)) setShowHistory(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showHistory])

  // Pick 3 suggestion prompts; stable for the lifetime of a blank chat, fresh after messages clear.
  const suggestions = useMemo(() => {
    const seed = (meetingId ? Number(meetingId) : 0) ^ (messages.length === 0 ? Date.now() & 0xffff : 0)
    return pickThree(SUGGESTED_QUESTIONS, seed)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetingId, messages.length === 0])

  const send = async (text) => {
    if (viewingSession) return
    const msg = (text || input).trim()
    if (!msg || loading) return

    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setInput('')
    setLoading(true)

    const agentIntent = result && transcript ? detectAgentIntent(msg) : null
    const globalIntent = !agentIntent && detectGlobalIntent(msg)

    try {
      if (agentIntent === 'undo') {
        if (prevResultRef.current) {
          onResultUpdate(prevResultRef.current)
          prevResultRef.current = null
          setMessages((prev) => [...prev, { role: 'assistant', content: 'Restored the previous version.' }])
        } else {
          setMessages((prev) => [...prev, { role: 'assistant', content: 'Nothing to undo — no changes have been made yet.' }])
        }
      } else if (agentIntent) {
        const res = await apiFetch('/agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent: agentIntent, transcript, instruction: msg }),
        })
        if (!res.ok) throw new Error('Agent call failed')
        const data = await res.json()

        const agentKey = {
          email_drafter: 'follow_up_email',
          action_items: 'action_items',
          decisions: 'decisions',
          summarizer: 'summary',
          calendar_suggester: 'calendar_suggestion',
          sentiment: 'sentiment',
          health_score: 'health_score',
        }[agentIntent]

        if (agentKey && data[agentKey] !== undefined) {
          prevResultRef.current = { [agentKey]: result[agentKey] }
          onResultUpdate({ [agentKey]: data[agentKey] })
          setMessages((prev) => [...prev, {
            role: 'assistant',
            content: `Done — I've updated the ${agentIntent.replace(/_/g, ' ')} card with your changes.`,
            agentUpdated: agentIntent,
          }])
        } else {
          throw new Error('No result')
        }
      } else if (globalIntent) {
        if (!isSignedIn) {
          setMessages((prev) => [...prev, { role: 'assistant', content: 'Sign in to search across your saved meeting history.' }])
          return
        }
        setLoadingGlobal(true)
        const res = await apiFetch('/chat/global', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        })
        setLoadingGlobal(false)
        if (!res.ok) throw new Error('Global chat failed')
        const data = await res.json()
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: data.response ?? 'No response from server.',
          globalSearch: true,
          toolsUsed: data.tools_used || [],
          pendingConfirmations: data.pending_confirmations || [],
        }])
      } else {
        const res = await apiFetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg, transcript }),
        })
        if (!res.ok) throw new Error('Chat failed')
        const data = await res.json()
        setMessages((prev) => [...prev, {
          role: 'assistant',
          content: data.response ?? 'No response from server.',
          toolsUsed: data.tools_used || [],
          pendingConfirmations: data.pending_confirmations || [],
        }])
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Sorry, something went wrong.' }])
    } finally {
      setLoading(false)
      setLoadingGlobal(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const handleDeletePastSession = (sessionId) => {
    apiFetch(`/chat-sessions/${sessionId}`, { method: 'DELETE' }).catch(() => {})
    onPastSessionsChange?.((prev) => prev.filter((s) => s.id !== sessionId))
    if (viewingSession?.id === sessionId) setViewingSession(null)
  }

  const visibleMessages = viewingSession ? (viewingSession.messages || []) : messages
  const showEmptyState = !viewingSession && messages.length === 0

  return (
    <div className="dashboard-body-font flex h-full min-h-0 flex-col text-white">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-white/[0.08] px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-cyan-400/30 bg-cyan-400/[0.10]">
          <MessagesSquare className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-200/90">Chat</p>
          <p className="truncate text-sm font-semibold text-white">Ask about this meeting</p>
        </div>

        <div className="flex items-center gap-1.5">
          {result && (
            <span className="rounded-full border border-cyan-400/25 bg-cyan-400/[0.10] px-2 py-0.5 text-[9.5px] font-medium uppercase tracking-wider text-cyan-200/90">
              agent-aware
            </span>
          )}

          {isSignedIn && pastSessions.length > 0 && (
            <div className="relative" ref={historyRef}>
              <button
                type="button"
                onClick={() => setShowHistory((v) => !v)}
                className="flex items-center gap-1 rounded-md border border-white/[0.10] bg-white/[0.04] px-2 py-1 text-[10.5px] font-medium text-white/68 transition hover:border-white/[0.20] hover:text-white"
                aria-label="Show past chats for this meeting"
              >
                <History className="h-3 w-3" aria-hidden="true" />
                <span>History</span>
                <span className="ml-0.5 inline-flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-cyan-400/[0.18] px-1 text-[9px] font-semibold text-cyan-200">
                  {pastSessions.length}
                </span>
              </button>

              {showHistory && (
                <div className="absolute right-0 top-8 z-40 w-72 overflow-hidden rounded-xl border border-white/[0.12] bg-[#08090a] shadow-[0_16px_38px_rgba(0,0,0,0.45)]">
                  <div className="flex items-center justify-between border-b border-white/[0.08] px-3 py-2">
                    <p className="text-[11px] font-semibold text-white/86">Past chats</p>
                    <p className="text-[10px] text-white/40">{pastSessions.length} of 3</p>
                  </div>
                  <div className="max-h-60 overflow-y-auto">
                    {pastSessions.map((session) => {
                      const msgs = session.messages || []
                      const firstUser = msgs.find((m) => m.role === 'user')
                      return (
                        <div
                          key={session.id}
                          className="group flex items-stretch border-b border-white/[0.05] last:border-b-0"
                        >
                          <button
                            type="button"
                            onClick={() => { setViewingSession(session); setShowHistory(false) }}
                            className="min-w-0 flex-1 px-3 py-2.5 text-left transition hover:bg-white/[0.04]"
                          >
                            <p className="text-[11px] text-white/40">{formatSessionDate(session.created_at)}</p>
                            {firstUser && (
                              <p className="mt-0.5 truncate text-[12px] text-white/86">{firstUser.content}</p>
                            )}
                            <p className="mt-1 text-[10px] text-white/40">
                              {msgs.length} message{msgs.length !== 1 ? 's' : ''}
                            </p>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeletePastSession(session.id)}
                            aria-label="Delete chat session"
                            className="flex items-center px-3 text-white/30 opacity-0 transition group-hover:opacity-100 hover:text-red-300"
                          >
                            <X className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          <span className="hidden items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] px-2 py-0.5 text-[10px] text-white/50 sm:inline-flex">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
            llama-3.3-70b
          </span>
        </div>
      </div>

      {/* Viewing past session banner */}
      {viewingSession && (
        <div className="flex flex-shrink-0 items-center gap-2 border-b border-cyan-400/15 bg-cyan-400/[0.06] px-4 py-2">
          <button
            type="button"
            onClick={() => setViewingSession(null)}
            className="flex items-center gap-1 text-[11px] font-medium text-cyan-200 transition hover:text-cyan-100"
          >
            <X className="h-3 w-3" aria-hidden="true" />
            New chat
          </button>
          <span className="ml-auto truncate text-[10px] text-white/50">
            Viewing past chat · {formatSessionDate(viewingSession.created_at)}
          </span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {showEmptyState && (
          <div className="flex flex-col gap-3">
            <div className="px-1">
              <p className={"text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-200/90"}>Suggested</p>
              <p className="mt-0.5 text-sm text-white/68">Quick prompts to get going — or type your own below.</p>
            </div>
            <div className="flex flex-col gap-2">
              {suggestions.map((prompt, idx) => {
                const Icon = SUGGESTION_ICONS[idx % SUGGESTION_ICONS.length]
                return (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => send(prompt)}
                    className="group flex w-full items-center gap-3 rounded-lg border border-white/[0.08] bg-[#0d0e10] px-3 py-3 text-left transition hover:border-cyan-400/40 hover:bg-[#0f1113]"
                  >
                    <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md border border-cyan-400/25 bg-cyan-400/[0.10] text-cyan-300 transition group-hover:border-cyan-300/40 group-hover:bg-cyan-400/[0.15]">
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                    </span>
                    <span className="text-sm text-white/85 group-hover:text-white">{prompt}</span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {visibleMessages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in-up`}>
            {msg.role === 'assistant' && (
              <div className="mr-2 mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md border border-cyan-400/25 bg-cyan-400/[0.10]">
                <Sparkles className="h-3 w-3 text-cyan-300" aria-hidden="true" />
              </div>
            )}
            <div
              className={`max-w-[78%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'rounded-tr-sm bg-gradient-to-br from-[#0c4a6e] to-[#155e75] text-white'
                  : 'rounded-tl-sm border border-white/[0.08] bg-[#0d0e10] text-white/85'
              }`}
            >
              {msg.content}
              {msg.toolsUsed?.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {msg.toolsUsed.map((t, ti) => (
                    <span key={ti} className="inline-flex items-center gap-1 rounded-md border border-cyan-400/20 bg-cyan-400/[0.10] px-1.5 py-0.5 text-[9px] font-medium text-cyan-200">
                      <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {t.summary || t.tool}
                    </span>
                  ))}
                </div>
              )}
              {!viewingSession && msg.pendingConfirmations?.length > 0 && (
                <div className="mt-2 space-y-2">
                  {msg.pendingConfirmations.map((pc, ci) => (
                    <div key={ci} className="rounded-lg border border-yellow-400/25 bg-yellow-400/[0.07] p-2.5 text-[11px]">
                      <p className="mb-1 font-medium text-yellow-300">{pc.message || `Confirm: ${pc.tool}`}</p>
                      <pre className="mb-2 max-h-24 overflow-y-auto whitespace-pre-wrap text-[10px] text-white/55">
                        {typeof pc.preview === 'object' ? JSON.stringify(pc.preview, null, 2) : pc.preview}
                      </pre>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              const res = await apiFetch('/chat/confirm-tool', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ pending_id: pc.pending_id }),
                              })
                              if (!res.ok) throw new Error('Confirm failed')
                              const data = await res.json()
                              setMessages((prev) => prev.map((m, mi) => mi === i ? {
                                ...m,
                                pendingConfirmations: (m.pendingConfirmations || []).filter((_, idx) => idx !== ci),
                                toolsUsed: [...(m.toolsUsed || []), { tool: pc.tool, summary: data.summary || `Executed ${pc.tool}` }],
                              } : m))
                            } catch (err) {
                              console.warn('[ChatPanel] confirm-tool failed:', err)
                            }
                          }}
                          className="rounded-md bg-gradient-to-br from-cyan-500 to-cyan-400 px-3 py-1 text-[10px] font-semibold text-[#07040f] transition hover:from-cyan-400 hover:to-cyan-300"
                        >Confirm</button>
                        <button
                          type="button"
                          onClick={() => setMessages((prev) => prev.map((m, mi) => mi === i ? {
                            ...m,
                            pendingConfirmations: (m.pendingConfirmations || []).filter((_, idx) => idx !== ci),
                          } : m))}
                          className="rounded-md border border-white/[0.10] bg-white/[0.04] px-3 py-1 text-[10px] font-medium text-white/68 transition hover:text-white"
                        >Cancel</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {msg.agentUpdated && (
                <span className="mt-1 block text-[10px] text-cyan-300/80">↑ card updated</span>
              )}
              {msg.globalSearch && (
                <span className="mt-1 block text-[10px] text-violet-300/80">⊕ searched all meetings</span>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex items-center justify-start gap-2">
            <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md border border-cyan-400/25 bg-cyan-400/[0.10]">
              <Sparkles className="h-3 w-3 text-cyan-300" aria-hidden="true" />
            </div>
            <div className="rounded-xl rounded-tl-sm border border-white/[0.08] bg-[#0d0e10] px-3.5 py-2.5">
              {loadingGlobal ? (
                <span className="text-[11px] text-cyan-300 animate-pulse">Searching all meetings…</span>
              ) : (
                <div className="flex h-4 items-center gap-1.5">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style={{ animationDelay: '0ms' }} />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style={{ animationDelay: '150ms' }} />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-cyan-400" style={{ animationDelay: '300ms' }} />
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-white/[0.08] px-4 py-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={!!viewingSession}
          placeholder={
            viewingSession
              ? 'Viewing past chat — start a new chat to send messages'
              : result
              ? 'Ask or say "redraft email more formally"…'
              : 'Ask a question…'
          }
          className="flex-1 rounded-lg border border-white/[0.10] bg-[#0d0e10] px-3 py-2.5 text-sm text-white outline-none transition placeholder:text-white/35 focus:border-cyan-400/60 focus:ring-1 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => send()}
          disabled={!input.trim() || loading || !!viewingSession}
          aria-label="Send message"
          className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-500 to-cyan-400 text-[#07040f] transition hover:from-cyan-400 hover:to-cyan-300 disabled:cursor-not-allowed disabled:opacity-30"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

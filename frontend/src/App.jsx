import { useState, useRef, useEffect } from 'react'
import AgentTags from './components/AgentTags'
import HealthScoreCard from './components/HealthScoreCard'
import SummaryCard from './components/SummaryCard'
import ActionItemsCard from './components/ActionItemsCard'
import SentimentCard from './components/SentimentCard'
import EmailCard from './components/EmailCard'
import CalendarCard from './components/CalendarCard'
import ChatPanel from './components/ChatPanel'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const SAMPLE_TRANSCRIPT = `Sarah: Alright everyone, let's get started. Today we need to finalize the Q2 roadmap and discuss the upcoming product launch.

Mike: Sure. I've reviewed the feature list and I think we're overcommitting again. We have three major features slated for Q2 but engineering only has bandwidth for two.

Sarah: That's a valid concern, Mike. Which feature would you prioritize dropping?

Mike: Honestly, the analytics dashboard can wait. The core checkout improvements are more critical for revenue.

Lisa: I agree with Mike on the analytics dashboard. But I'm worried about the mobile app redesign timeline — we promised that to our enterprise clients by end of April.

Sarah: Okay, so we're agreed: checkout improvements and mobile redesign for Q2, analytics moves to Q3. Mike, can you update the roadmap by Thursday?

Mike: Yes, I'll have it done by Thursday EOD.

Sarah: Lisa, can you draft a message to the enterprise clients about the mobile redesign timeline confirmation?

Lisa: Will do, I'll send it out by Wednesday.

Sarah: Perfect. Also, we should schedule a follow-up sync in two weeks to check progress. Does the week of March 15th work for everyone?

Mike: Works for me.

Lisa: Same, I'll send a calendar invite.

Sarah: Great. One more thing — the marketing team needs the feature specs by next Friday for the launch campaign.

Mike: I'll loop in David from engineering to finalize specs. We'll get that done.

Sarah: Excellent. I think we're in good shape. Thanks everyone.`

const AGENTS_META = [
  { id: 'summarizer',        label: 'Summarizer',    icon: '📝', grad: 'from-sky-500 to-blue-600' },
  { id: 'action_items',      label: 'Action Items',  icon: '✅', grad: 'from-cyan-500 to-sky-500' },
  { id: 'sentiment',         label: 'Sentiment',     icon: '💬', grad: 'from-amber-400 to-orange-500' },
  { id: 'email_drafter',     label: 'Email Draft',   icon: '✉️', grad: 'from-emerald-400 to-teal-500' },
  { id: 'calendar_suggester',label: 'Calendar',      icon: '📅', grad: 'from-teal-400 to-cyan-600' },
  { id: 'health_score',      label: 'Health Score',  icon: '📊', grad: 'from-cyan-400 to-sky-500' },
]

const BG_STYLE = {
  background: '#020c18',
  backgroundImage: `
    radial-gradient(ellipse 60% 50% at 10% 5%,  rgba(2,132,199,0.22)  0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 90% 0%,  rgba(6,182,212,0.18)  0%, transparent 55%),
    radial-gradient(ellipse 55% 45% at 80% 95%, rgba(20,184,166,0.14) 0%, transparent 55%),
    radial-gradient(ellipse 40% 40% at 5%  90%, rgba(56,189,248,0.12) 0%, transparent 50%)
  `,
}

const PANEL_STYLE = {
  background: 'rgba(255,255,255,0.02)',
  borderRight: '1px solid rgba(14,165,233,0.1)',
}

const CARD_STYLE = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(14,165,233,0.1)',
}

// ── Generate markdown ───────────────────────────────────────────
function buildMarkdown(result) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const h = result.health_score
  let md = `# Meeting Summary — ${date}\n\n`
  if (h?.score) {
    md += `## Meeting Health: ${h.score}/100 — ${h.verdict}\n`
    if (h.badges?.length) md += h.badges.map(b => `\`${b}\``).join(' ') + '\n'
    md += '\n'
  }
  if (result.summary) md += `## Summary\n\n${result.summary}\n\n`
  if (result.action_items?.length) {
    md += `## Action Items\n\n`
    result.action_items.forEach(i => {
      md += `- [ ] ${i.task}${i.owner && i.owner !== 'Unassigned' ? ` *(${i.owner})*` : ''}${i.due && i.due !== 'TBD' ? ` — due ${i.due}` : ''}\n`
    })
    md += '\n'
  }
  if (result.sentiment) {
    md += `## Sentiment: ${result.sentiment.overall} (${result.sentiment.score}/100)\n\n`
    if (result.sentiment.notes) md += `${result.sentiment.notes}\n\n`
  }
  if (result.follow_up_email?.subject) {
    md += `## Follow-up Email\n\n**Subject:** ${result.follow_up_email.subject}\n\n${result.follow_up_email.body}\n\n`
  }
  if (result.calendar_suggestion?.recommended) {
    md += `## Calendar\n\n${result.calendar_suggestion.reason}${result.calendar_suggestion.suggested_timeframe ? ` — ${result.calendar_suggestion.suggested_timeframe}` : ''}\n`
  }
  return md
}

// ── Prism background ─────────────────────────────────────────────
function PrismBackground() {
  return (
    <div className="prism-bg">
      <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg" style={{ position: 'absolute', inset: 0 }}>
        <defs>
          <linearGradient id="pg1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.04" />
          </linearGradient>
          <linearGradient id="pg2" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0d9488" stopOpacity="0.14" />
            <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.04" />
          </linearGradient>
          <linearGradient id="pg3" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.1" />
            <stop offset="100%" stopColor="#0284c7" stopOpacity="0.03" />
          </linearGradient>
          <linearGradient id="pg4" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0891b2" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#14b8a6" stopOpacity="0.03" />
          </linearGradient>
        </defs>

        {/* Floating prism triangles */}
        <polygon className="animate-prism-1"
          points="130,90 200,210 60,210"
          fill="url(#pg1)" stroke="rgba(6,182,212,0.25)" strokeWidth="1"
          style={{ transformOrigin: '130px 150px' }} />

        <polygon className="animate-prism-2"
          points="0,0 80,140 -80,140"
          fill="url(#pg2)" stroke="rgba(20,184,166,0.2)" strokeWidth="1"
          style={{ transformOrigin: '0px 70px', transform: 'translate(820px, 160px)' }} />

        <polygon className="animate-prism-3"
          points="0,0 90,155 -90,155"
          fill="url(#pg3)" stroke="rgba(56,189,248,0.15)" strokeWidth="0.5"
          style={{ transformOrigin: '0px 78px', transform: 'translate(220px, 580px)' }} />

        <polygon className="animate-prism-1"
          points="0,0 55,95 -55,95"
          fill="url(#pg4)" stroke="rgba(6,182,212,0.12)" strokeWidth="0.5"
          style={{ transformOrigin: '0px 48px', transform: 'translate(1100px, 380px)', animationDelay: '4s' }} />

        {/* Spectrum light dispersion rays from top-left */}
        <line x1="0" y1="0" x2="650" y2="280" stroke="rgba(56,189,248,0.07)"  strokeWidth="1.5" className="animate-ray-pulse" />
        <line x1="0" y1="0" x2="520" y2="360" stroke="rgba(6,182,212,0.06)"   strokeWidth="1"   className="animate-ray-pulse" style={{ animationDelay: '0.8s' }} />
        <line x1="0" y1="0" x2="420" y2="440" stroke="rgba(20,184,166,0.05)"  strokeWidth="1"   className="animate-ray-pulse" style={{ animationDelay: '1.6s' }} />
        <line x1="0" y1="0" x2="720" y2="220" stroke="rgba(14,165,233,0.06)"  strokeWidth="1"   className="animate-ray-pulse" style={{ animationDelay: '2.4s' }} />
        <line x1="0" y1="0" x2="350" y2="500" stroke="rgba(2,132,199,0.04)"   strokeWidth="0.5" className="animate-ray-pulse" style={{ animationDelay: '3.2s' }} />
      </svg>
    </div>
  )
}

// ── Agent pipeline loader ────────────────────────────────────────
function AgentPipelineLoader() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 py-16 px-8">
      <div className="flex flex-col items-center gap-3 animate-fade-in-up card-delay-0">
        <div className="relative">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center animate-glow-pulse"
            style={{ background: 'linear-gradient(135deg, rgba(2,132,199,0.3), rgba(14,165,233,0.2))', border: '1px solid rgba(14,165,233,0.4)' }}>
            <svg className="w-8 h-8 text-sky-400 animate-spin-slow" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-400 rounded-full border-2 animate-pulse"
            style={{ borderColor: '#07040f' }}></span>
        </div>
        <div className="text-center">
          <p className="font-semibold text-sky-300">Orchestrator</p>
          <p className="text-xs text-gray-500 mt-0.5">LLaMA 3.3-70b · routing transcript</p>
        </div>
      </div>

      <div className="flex flex-col items-center gap-2 animate-fade-in-up card-delay-1">
        <div className="w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(14,165,233,0.7), rgba(6,182,212,0.3))' }}></div>
        <div className="text-xs text-gray-500 px-4 py-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
          dispatching 6 agents in parallel
        </div>
        <div className="w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(236,72,153,0.3), transparent)' }}></div>
      </div>

      <div className="grid grid-cols-3 gap-3 animate-fade-in-up card-delay-2">
        {AGENTS_META.map((a, i) => (
          <div key={a.id} className="flex flex-col items-center gap-2 px-4 py-3 rounded-2xl animate-pulse"
            style={{ animationDelay: `${i * 0.18}s`, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div className={`w-8 h-8 rounded-xl bg-gradient-to-br ${a.grad} flex items-center justify-center text-sm shadow-lg`}>{a.icon}</div>
            <span className="text-[11px] text-gray-400 font-medium text-center leading-tight">{a.label}</span>
            <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" style={{ animationDelay: `${i * 0.2}s` }}></div>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-600 animate-fade-in-up card-delay-3 text-center">
        Analyzing your meeting across 6 dimensions...
      </p>
    </div>
  )
}

// ── Empty state for right panel ──────────────────────────────────
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-10 px-8 py-16">
      <div className="text-center">
        <h2 className="text-2xl font-bold gradient-text mb-2">Ready to analyze</h2>
        <p className="text-gray-500 text-sm max-w-sm">Paste a transcript, record live audio, or upload an audio file — then hit Analyze Meeting.</p>
      </div>
      <div className="grid grid-cols-3 gap-4 w-full max-w-md">
        {AGENTS_META.map((a) => (
          <div key={a.id} className="flex flex-col items-center gap-2 p-4 rounded-2xl"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${a.grad} flex items-center justify-center text-base shadow-lg opacity-70`}>{a.icon}</div>
            <span className="text-[11px] text-gray-500 text-center leading-tight">{a.label}</span>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-gray-700">Powered by LLaMA 3.3-70b via Groq</p>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────
export default function App() {
  const [transcript, setTranscript] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const [recording, setRecording] = useState(false)
  const recognitionRef = useRef(null)
  const micSupported = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  const [transcribing, setTranscribing] = useState(false)
  const fileInputRef = useRef(null)

  // Join Meeting state
  const [inputTab, setInputTab] = useState('paste') // 'paste' | 'join'
  const [meetingUrl, setMeetingUrl] = useState('')
  const [botStatus, setBotStatus] = useState(null) // joining | recording | processing | done | error
  const [botError, setBotError] = useState(null)
  const pollRef = useRef(null)

  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('meeting-history') || '[]') } catch { return [] }
  })
  const [showHistory, setShowHistory] = useState(false)

  const joinMeeting = async () => {
    if (!meetingUrl.trim()) return
    setBotError(null)
    setBotStatus('joining')
    try {
      const res = await fetch(`${API}/join-meeting`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_url: meetingUrl }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to join meeting')
      const data = await res.json()
      setBotStatus(data.status)
      startPolling(data.bot_id)
    } catch (e) {
      setBotStatus('error')
      setBotError(e.message)
    }
  }

  const startPolling = (id) => {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/bot-status/${id}`)
        if (!res.ok) return
        const data = await res.json()
        setBotStatus(data.status)
        if (data.status === 'done') {
          clearInterval(pollRef.current)
          if (data.transcript) setTranscript(data.transcript)
          if (data.result) {
            setResult(data.result)
            saveToHistory(data.transcript || '', data.result)
          }
        } else if (data.status === 'error') {
          clearInterval(pollRef.current)
          setBotError(data.error || 'Bot encountered an error')
        }
      } catch { /* network hiccup, keep polling */ }
    }, 4000)
  }

  // Clean up poll on unmount
  useEffect(() => () => clearInterval(pollRef.current), [])

  const saveToHistory = (t, r) => {
    const entry = {
      id: Date.now(),
      date: new Date().toISOString(),
      transcript: t,
      result: r,
      title: r.summary?.slice(0, 65) || 'Meeting',
      score: r.health_score?.score,
    }
    const updated = [entry, ...history].slice(0, 8)
    setHistory(updated)
    localStorage.setItem('meeting-history', JSON.stringify(updated))
  }

  const loadFromHistory = (entry) => {
    setTranscript(entry.transcript)
    setResult(entry.result)
    setShowHistory(false)
  }

  const startRecording = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    const r = new SR()
    r.continuous = true
    r.interimResults = false
    r.lang = 'en-US'
    r.onresult = (e) => {
      const text = Array.from(e.results).map(r => r[0].transcript).join(' ')
      setTranscript(prev => prev ? prev + '\n' + text : text)
    }
    r.onerror = () => setRecording(false)
    r.onend = () => setRecording(false)
    r.start()
    recognitionRef.current = r
    setRecording(true)
  }

  const stopRecording = () => {
    recognitionRef.current?.stop()
    setRecording(false)
  }

  const handleAudioUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setTranscribing(true)
    setError(null)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API}/transcribe`, { method: 'POST', body: formData })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Transcription failed')
      const data = await res.json()
      setTranscript(data.transcript)
    } catch (e) {
      setError(e.message)
    } finally {
      setTranscribing(false)
      e.target.value = ''
    }
  }

  const analyze = async () => {
    if (!transcript.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Server error ${res.status}`)
      const data = await res.json()
      setResult(data)
      saveToHistory(transcript, data)
    } catch (e) {
      setError(e.message || 'Failed to analyze.')
    } finally {
      setLoading(false)
    }
  }

  const exportMarkdown = () => {
    if (!result) return
    const md = buildMarkdown(result)
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `meeting-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    if (!showHistory) return
    const h = (e) => { if (!e.target.closest('[data-history-panel]')) setShowHistory(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [showHistory])

  return (
    <div className="flex flex-col h-screen overflow-hidden" style={BG_STYLE}>
      <PrismBackground />

      {/* ── Header ── */}
      <header className="flex-shrink-0 flex items-center justify-between px-6 py-3 z-20"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'rgba(7,4,15,0.7)', backdropFilter: 'blur(20px)' }}>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center shadow-lg shadow-sky-500/30"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <div>
            <span className="text-sm font-bold gradient-text">PrismAI</span>
            <span className="hidden sm:inline text-[10px] text-gray-600 ml-2">meeting intelligence</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* History */}
          {history.length > 0 && (
            <div className="relative" data-history-panel>
              <button onClick={() => setShowHistory(v => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 transition-colors"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                History
                <span className="w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center"
                  style={{ background: 'rgba(14,165,233,0.25)', color: '#7dd3fc' }}>{history.length}</span>
              </button>

              {showHistory && (
                <div className="absolute right-0 top-10 w-80 rounded-2xl shadow-2xl z-30 overflow-hidden animate-fade-in-up"
                  style={{ background: '#100c1e', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                    <span className="text-xs font-semibold text-gray-300">Recent Meetings</span>
                    <button onClick={() => { setHistory([]); localStorage.removeItem('meeting-history'); setShowHistory(false) }}
                      className="text-[11px] text-gray-600 hover:text-red-400 transition-colors">Clear all</button>
                  </div>
                  <div className="max-h-72 overflow-y-auto">
                    {history.map((entry) => (
                      <button key={entry.id} onClick={() => loadFromHistory(entry)}
                        className="w-full text-left px-4 py-3 hover:bg-white/5 transition-colors group"
                        style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <div className="flex items-start gap-2">
                          <p className="text-xs text-gray-300 group-hover:text-white flex-1 line-clamp-2">{entry.title}</p>
                          {entry.score !== undefined && (
                            <span className={`text-[11px] font-bold flex-shrink-0 ${entry.score >= 80 ? 'text-emerald-400' : entry.score >= 60 ? 'text-cyan-400' : entry.score >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                              {entry.score}
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-gray-600 mt-1">
                          {new Date(entry.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </p>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] text-gray-400"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            llama-3.3-70b
          </div>
          <div className="flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-semibold"
            style={{ background: 'linear-gradient(135deg, rgba(14,165,233,0.2), rgba(6,182,212,0.15))', border: '1px solid rgba(14,165,233,0.3)', color: '#7dd3fc' }}>
            6 agents
          </div>
        </div>
      </header>

      {/* ── Main two-pane layout ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* LEFT PANEL — Input */}
        <div className="flex flex-col w-full lg:w-[420px] xl:w-[460px] flex-shrink-0 overflow-y-auto" style={PANEL_STYLE}>

          {/* Hero blurb */}
          <div className="px-6 pt-6 pb-4">
            <h1 className="text-xl font-bold text-white leading-snug">
              <span className="gradient-text">PrismAI</span> — one transcript,<br />six dimensions of clarity.
            </h1>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">
              Orchestrator routes your transcript to 6 parallel AI agents in real time.
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="mx-6 mb-3 px-4 py-3 rounded-xl text-xs text-red-300 flex items-start gap-2 animate-fade-in-up"
              style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
              <svg className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {error}
            </div>
          )}

          {/* Transcript card */}
          <div className="mx-6 mb-4 rounded-2xl overflow-hidden" style={CARD_STYLE}>

            {/* Tabs */}
            <div className="flex px-4 pt-3 pb-0 gap-1">
              {[
                { id: 'paste', label: 'Paste / Record' },
                { id: 'join',  label: 'Join Meeting' },
              ].map(tab => (
                <button key={tab.id} onClick={() => setInputTab(tab.id)}
                  className="px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all"
                  style={inputTab === tab.id
                    ? { background: 'rgba(14,165,233,0.15)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.3)' }
                    : { background: 'transparent', color: '#6b7280', border: '1px solid transparent' }}>
                  {tab.label}
                </button>
              ))}
              {inputTab === 'paste' && (
                <button onClick={() => setTranscript(SAMPLE_TRANSCRIPT)}
                  className="ml-auto text-[11px] px-2.5 py-1 rounded-lg transition-colors"
                  style={{ background: 'rgba(14,165,233,0.1)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                  Load sample
                </button>
              )}
            </div>

            {inputTab === 'paste' ? (<>
              {/* Toolbar */}
              <div className="px-4 pt-2 pb-2 flex items-center gap-2 flex-wrap">
                {micSupported && (
                  <button onClick={recording ? stopRecording : startRecording}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all ${recording ? 'animate-pulse' : ''}`}
                    style={recording
                      ? { background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.35)', color: '#fca5a5' }
                      : { background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#9ca3af' }}>
                    <svg className="w-3.5 h-3.5" fill={recording ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                    {recording ? 'Stop' : 'Record'}
                  </button>
                )}

                <button onClick={() => fileInputRef.current?.click()} disabled={transcribing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all disabled:opacity-40"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#9ca3af' }}>
                  {transcribing ? (
                    <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Transcribing...</>
                  ) : (
                    <><svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072M12 6v6m0 0v6m0-6h.01M9.172 16.172a4 4 0 015.656 0M6.343 9.343a8 8 0 0111.314 0" /></svg>Upload Audio</>
                  )}
                </button>
                <input ref={fileInputRef} type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm" className="hidden" onChange={handleAudioUpload} />

                {recording && (
                  <span className="text-[11px] text-red-400 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>Listening
                  </span>
                )}
              </div>

              <div className="px-4 pb-4">
                <textarea
                  value={transcript}
                  onChange={(e) => setTranscript(e.target.value)}
                  placeholder="Paste transcript, record, or upload audio..."
                  rows={8}
                  className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed placeholder-gray-700 transition-colors"
                  style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }}
                />
                <div className="flex items-center justify-between mt-3">
                  <span className="text-[11px] text-gray-600">
                    {transcript.length > 0 ? `${transcript.split(/\s+/).filter(Boolean).length} words` : 'No transcript'}
                  </span>
                  <button onClick={analyze} disabled={!transcript.trim() || loading}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
                    style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.35)' }}>
                    {loading ? (
                      <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Analyzing...</>
                    ) : (
                      <><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>
                    )}
                  </button>
                </div>
              </div>
            </>) : (
              /* Join Meeting tab */
              <div className="px-4 pt-3 pb-4">
                <p className="text-[11px] text-gray-500 mb-3 leading-relaxed">
                  Paste a Zoom, Google Meet, or Teams link. PrismAI will join the meeting, record, and automatically analyze it when it ends.
                </p>
                <input
                  type="url"
                  value={meetingUrl}
                  onChange={(e) => setMeetingUrl(e.target.value)}
                  placeholder="https://zoom.us/j/... or meet.google.com/..."
                  className="w-full rounded-xl px-3 py-2.5 text-xs text-gray-300 outline-none"
                  style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }}
                  disabled={botStatus && !['done', 'error'].includes(botStatus)}
                />

                {/* Status indicator */}
                {botStatus && !['done', 'error'].includes(botStatus) && (
                  <div className="mt-3 flex items-center gap-2 px-3 py-2.5 rounded-xl animate-fade-in-up"
                    style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.2)' }}>
                    <svg className="w-3.5 h-3.5 text-sky-400 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    <div>
                      <p className="text-[11px] font-medium text-sky-300">
                        {botStatus === 'joining'    && 'Bot is joining the meeting...'}
                        {botStatus === 'recording'  && 'Bot is recording...'}
                        {botStatus === 'processing' && 'Meeting ended — analyzing transcript...'}
                      </p>
                      {botStatus === 'recording' && (
                        <p className="text-[10px] text-gray-600 mt-0.5">Results will appear automatically when the meeting ends</p>
                      )}
                    </div>
                    {botStatus === 'recording' && (
                      <span className="ml-auto w-2 h-2 rounded-full bg-red-500 animate-pulse flex-shrink-0"></span>
                    )}
                  </div>
                )}

                {botStatus === 'error' && botError && (
                  <div className="mt-3 px-3 py-2.5 rounded-xl text-[11px] text-red-300 animate-fade-in-up"
                    style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)' }}>
                    {botError}
                  </div>
                )}

                {botStatus === 'done' && (
                  <div className="mt-3 px-3 py-2.5 rounded-xl text-[11px] text-emerald-300 flex items-center gap-2 animate-fade-in-up"
                    style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)' }}>
                    <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Analysis complete — results are ready
                  </div>
                )}

                <button
                  onClick={botStatus && !['done', 'error'].includes(botStatus) ? undefined : joinMeeting}
                  disabled={!meetingUrl.trim() || (botStatus && !['done', 'error'].includes(botStatus))}
                  className="mt-3 w-full flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
                  style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.3)' }}>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  {botStatus === 'joining'    ? 'Joining...' :
                   botStatus === 'recording'  ? 'Recording...' :
                   botStatus === 'processing' ? 'Processing...' :
                   'Join Meeting'}
                </button>
              </div>
            )}
          </div>

          {/* Chat panel */}
          <div className="mx-6 mb-6 flex-1">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.25)' }}>
                <svg className="w-3 h-3 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <span className="text-xs font-semibold text-gray-400">Chat with meeting</span>
            </div>
            <ChatPanel transcript={transcript} />
          </div>
        </div>

        {/* RIGHT PANEL — Results */}
        <div className="hidden lg:flex flex-1 flex-col overflow-y-auto">
          {loading ? (
            <AgentPipelineLoader />
          ) : result ? (
            <div className="p-6 space-y-4">
              {/* Top bar */}
              <div className="flex items-center justify-between">
                <AgentTags agents={result.agents_run || []} />
                <button onClick={exportMarkdown}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all flex-shrink-0 ml-3"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#9ca3af' }}>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Export .md
                </button>
              </div>

              {/* Health score — full width, prominent */}
              <div className="animate-fade-in-up card-delay-0">
                <HealthScoreCard healthScore={result.health_score} />
              </div>

              {/* 2-col row: summary + sentiment */}
              <div className="grid grid-cols-2 gap-4">
                <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
                <div className="animate-fade-in-up card-delay-2"><SentimentCard sentiment={result.sentiment} /></div>
              </div>

              {/* Action items — full width */}
              <div className="animate-fade-in-up card-delay-3">
                <ActionItemsCard actionItems={result.action_items} />
              </div>

              {/* Email + Calendar side by side */}
              <div className="grid grid-cols-2 gap-4">
                <div className="animate-fade-in-up card-delay-4"><EmailCard email={result.follow_up_email} /></div>
                <div className="animate-fade-in-up card-delay-5"><CalendarCard suggestion={result.calendar_suggestion} /></div>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}
        </div>

        {/* Mobile results (below input) */}
        <div className="lg:hidden w-full overflow-y-auto">
          {loading && (
            <div className="h-80"><AgentPipelineLoader /></div>
          )}
          {result && !loading && (
            <div className="px-4 pb-8 space-y-4">
              <div className="flex items-center justify-between pt-4">
                <AgentTags agents={result.agents_run || []} />
                <button onClick={exportMarkdown} className="text-xs px-3 py-1.5 rounded-lg text-gray-400 ml-2"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                  Export .md
                </button>
              </div>
              <div className="animate-fade-in-up card-delay-0"><HealthScoreCard healthScore={result.health_score} /></div>
              <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
              <div className="animate-fade-in-up card-delay-2"><ActionItemsCard actionItems={result.action_items} /></div>
              <div className="animate-fade-in-up card-delay-3"><SentimentCard sentiment={result.sentiment} /></div>
              <div className="animate-fade-in-up card-delay-4"><EmailCard email={result.follow_up_email} /></div>
              <div className="animate-fade-in-up card-delay-5"><CalendarCard suggestion={result.calendar_suggestion} /></div>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

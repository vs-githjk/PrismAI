import { useState, useRef, useEffect } from 'react'
import AgentTags from './components/AgentTags'
import HealthScoreCard from './components/HealthScoreCard'
import SummaryCard from './components/SummaryCard'
import ActionItemsCard from './components/ActionItemsCard'
import DecisionsCard from './components/DecisionsCard'
import SentimentCard from './components/SentimentCard'
import EmailCard from './components/EmailCard'
import CalendarCard from './components/CalendarCard'
import ChatPanel from './components/ChatPanel'
import SkeletonCard from './components/SkeletonCard'

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

// ROYGBIV — white = transcript/orchestrator input, then splits into 7 agent colors
const AGENTS_META = [
  { id: 'summarizer',         label: 'Summarizer',    icon: '📝', grad: 'from-red-500 to-red-400',         desc: 'Condenses the entire meeting into a clear summary of key topics and outcomes.' },
  { id: 'action_items',       label: 'Action Items',  icon: '✅', grad: 'from-orange-500 to-amber-400',    desc: 'Extracts every task, assigns owners, and flags due dates so nothing falls through the cracks.' },
  { id: 'decisions',          label: 'Decisions',     icon: '⚖️', grad: 'from-yellow-400 to-yellow-300',   desc: 'Logs every decision made in the meeting, ranked by importance, with the accountable owner.' },
  { id: 'sentiment',          label: 'Sentiment',     icon: '💬', grad: 'from-emerald-500 to-green-400',   desc: 'Reads the emotional tone — per speaker, mood arc, and moments where tension spiked.' },
  { id: 'email_drafter',      label: 'Email Draft',   icon: '✉️', grad: 'from-blue-500 to-blue-400',       desc: 'Writes a polished follow-up email ready to send to all attendees.' },
  { id: 'calendar_suggester', label: 'Calendar',      icon: '📅', grad: 'from-indigo-500 to-indigo-400',   desc: 'Detects if a follow-up meeting is needed and suggests the best timeframe.' },
  { id: 'health_score',       label: 'Health Score',  icon: '📊', grad: 'from-violet-500 to-purple-400',   desc: 'Scores the meeting out of 100 across clarity, engagement, and action-orientation.' },
]

const DEFAULT_RESULT = {
  summary: '',
  action_items: [],
  decisions: [],
  sentiment: { overall: 'neutral', score: 50, arc: 'stable', notes: '', speakers: [], tension_moments: [] },
  follow_up_email: { subject: '', body: '' },
  calendar_suggestion: { recommended: false, reason: '', suggested_timeframe: '' },
  health_score: { score: 0, verdict: '', badges: [], breakdown: { clarity: 0, action_orientation: 0, engagement: 0 } },
  agents_run: [],
}

function extractSpeakers(transcript) {
  const matches = transcript.match(/^([A-Z][a-zA-Z\s]{1,30}?):/gm) || []
  const names = [...new Set(matches.map(m => m.replace(/:$/, '').trim()))]
  return names
    .filter(n => !/^speaker\s*\d+$/i.test(n))
    .slice(0, 10)
    .map(name => ({ name, role: '' }))
}

const BG_STYLE = {
  background: 'transparent',
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
  if (result.decisions?.length) {
    md += `## Decisions\n\n`
    result.decisions.forEach(d => {
      const imp = d.importance === 1 ? 'Critical' : d.importance === 2 ? 'Significant' : 'Minor'
      md += `- **${d.decision}**${d.owner && d.owner !== 'Team' ? ` *(${d.owner})*` : ''} — ${imp}\n`
    })
    md += '\n'
  }
  if (result.sentiment?.overall) {
    md += `## Sentiment: ${result.sentiment.overall} (${result.sentiment.score ?? 50}/100)\n\n`
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
// ── Agent pipeline loader ────────────────────────────────────────
function AgentPipelineLoader() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 py-16 px-8">
      <div className="flex flex-col items-center gap-3 animate-fade-in-up card-delay-0">
        <div className="relative">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center animate-glow-pulse"
            style={{ background: 'linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.06))', border: '1px solid rgba(255,255,255,0.25)' }}>
            <svg className="w-8 h-8 text-white/80 animate-spin-slow" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-400 rounded-full border-2 animate-pulse"
            style={{ borderColor: '#07040f' }}></span>
        </div>
        <div className="text-center">
          <p className="font-semibold text-white/80">Orchestrator</p>
          <p className="text-xs text-gray-500 mt-0.5">LLaMA 3.3-70b · routing transcript</p>
        </div>
      </div>

      <div className="flex flex-col items-center gap-2 animate-fade-in-up card-delay-1">
        <div className="w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.4), rgba(255,255,255,0.15))' }}></div>
        <div className="text-xs text-gray-400 px-4 py-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)' }}>
          dispatching 7 agents in parallel
        </div>
        <div className="w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.15), transparent)' }}></div>
      </div>

      <div className="grid grid-cols-4 gap-3 animate-fade-in-up card-delay-2">
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
        Analyzing your meeting across 7 dimensions...
      </p>
    </div>
  )
}

// ── Empty state for right panel ──────────────────────────────────
function EmptyState({ onDemo }) {
  const [active, setActive] = useState(null)
  const gridRef = useRef(null)

  useEffect(() => {
    if (!active) return
    const handler = (e) => { if (!gridRef.current?.contains(e.target)) setActive(null) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [active])

  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 px-10 py-16">
      <div className="text-center">
        <h2 className="text-2xl font-bold gradient-text mb-2">Ready to analyze</h2>
        <p className="text-gray-500 text-sm max-w-sm">Paste a transcript, record live audio, or upload an audio file — then hit Analyze Meeting.</p>
        <button onClick={onDemo}
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium text-sky-400 transition-all hover:text-sky-300 hover:scale-[1.02]"
          style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.2)' }}>
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          See it in action
        </button>
      </div>
      <div ref={gridRef} className="grid grid-cols-4 gap-3 w-full max-w-2xl">
        {AGENTS_META.map((a) => {
          const isActive = active === a.id
          return (
            <button
              key={a.id}
              onClick={() => setActive(isActive ? null : a.id)}
              className="flex flex-col items-center gap-3 p-5 rounded-2xl text-left transition-all duration-200 cursor-pointer"
              style={{
                background: isActive ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.03)',
                border: isActive ? '1px solid rgba(255,255,255,0.18)' : '1px solid rgba(255,255,255,0.07)',
                transform: isActive ? 'scale(1.03)' : 'scale(1)',
              }}
            >
              <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${a.grad} flex items-center justify-center text-xl shadow-lg`}>{a.icon}</div>
              <span className="text-xs font-medium text-gray-300 text-center leading-tight w-full">{a.label}</span>
              {isActive && (
                <p className="text-[11px] text-gray-400 text-center leading-relaxed">{a.desc}</p>
              )}
            </button>
          )
        })}
      </div>
      <p className="text-[11px] text-gray-600">Tap an agent to learn what it does · Powered by LLaMA 3.3-70b via Groq</p>
    </div>
  )
}

// Detect share token synchronously so first render already knows we're in share mode
const INITIAL_SHARE_TOKEN = (() => {
  const match = window.location.hash.match(/^#share\/([a-f0-9]+)$/)
  return match ? match[1] : null
})()

// ── Landing / Hero screen ────────────────────────────────────────
function LandingScreen({ onDemo, onSkip, exiting }) {
  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-6 py-16"
      style={{
        background: '#07040f',
        opacity: exiting ? 0 : 1,
        transform: exiting ? 'scale(0.97)' : 'scale(1)',
        transition: 'opacity 0.35s ease, transform 0.35s ease',
      }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 mb-12 animate-fade-in-up" style={{ animationDelay: '0s' }}>
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
          style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 8px 40px rgba(2,132,199,0.5)' }}>
          <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
          </svg>
        </div>
        <div>
          <span className="text-3xl font-bold gradient-text">PrismAI</span>
          <p className="text-xs text-gray-600 mt-0.5">meeting intelligence</p>
        </div>
      </div>

      {/* Headline */}
      <div className="text-center mb-4 animate-fade-in-up" style={{ animationDelay: '0.08s' }}>
        <h1 className="text-4xl sm:text-5xl font-bold text-white leading-tight mb-5">
          Your meeting, analyzed<br />
          <span className="gradient-text">in 7 dimensions.</span>
        </h1>
        <p className="text-gray-400 max-w-lg mx-auto leading-relaxed text-sm sm:text-base">
          Paste any transcript and 7 parallel AI agents instantly produce a summary, action items, decisions, sentiment, a ready-to-send follow-up email, calendar suggestion, and a meeting health score.
        </p>
      </div>

      {/* Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 mt-10 mb-14 animate-fade-in-up" style={{ animationDelay: '0.16s' }}>
        <button onClick={onDemo}
          className="flex items-center justify-center gap-2.5 px-8 py-4 rounded-2xl text-base font-semibold text-white transition-all hover:scale-[1.03] active:scale-[0.98]"
          style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 8px 32px rgba(2,132,199,0.45)' }}>
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          See it in action
        </button>
        <button onClick={onSkip}
          className="flex items-center justify-center gap-2.5 px-8 py-4 rounded-2xl text-base font-medium text-gray-300 transition-all hover:text-white hover:scale-[1.02]"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)' }}>
          Use my own transcript
        </button>
      </div>

      {/* Agent grid — decorative preview */}
      <div className="grid grid-cols-7 gap-2 animate-fade-in-up" style={{ animationDelay: '0.24s' }}>
        {AGENTS_META.map((a, i) => (
          <div key={a.id}
            className="flex flex-col items-center gap-2 px-3 py-3 rounded-2xl"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: '1px solid rgba(255,255,255,0.07)',
              animationDelay: `${0.24 + i * 0.04}s`,
            }}>
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${a.grad} flex items-center justify-center text-lg shadow-lg`}>{a.icon}</div>
            <span className="text-[10px] text-gray-600 text-center leading-tight">{a.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────
export default function App() {
  const [transcript, setTranscript] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [analysisTime, setAnalysisTime] = useState(null) // seconds elapsed
  const analysisStartRef = useRef(null)
  const [mobileTab, setMobileTab] = useState('input') // 'input' | 'results'

  // Show landing only to first-time visitors (not returning users, not share links)
  const [showLanding, setShowLanding] = useState(
    () => !INITIAL_SHARE_TOKEN && !localStorage.getItem('prism_visited')
  )
  const [landingExiting, setLandingExiting] = useState(false)
  const [isDemoMode, setIsDemoMode] = useState(false)

  const exitLanding = (demo = false) => {
    localStorage.setItem('prism_visited', '1')
    setLandingExiting(true)
    setTimeout(() => {
      setShowLanding(false)
      if (demo) {
        setIsDemoMode(true)
        setTranscript(SAMPLE_TRANSCRIPT)
      }
    }, 370)
  }

  const [sessionId, setSessionId] = useState(0)
  const [meetingId, setMeetingId] = useState(null)
  const [initialMessages, setInitialMessages] = useState([])
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

  const [history, setHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [historySearch, setHistorySearch] = useState('')

  useEffect(() => {
    if (INITIAL_SHARE_TOKEN) return // skip auto-load for shared links
    fetch(`${API}/meetings`)
      .then(r => r.json())
      .then(async data => {
        if (!Array.isArray(data)) return
        setHistory(data)
        if (data.length > 0) {
          const latest = data[0]
          setTranscript(latest.transcript || '')
          setResult(latest.result || null)
          setMeetingId(latest.id)
          setShareToken(latest.share_token || null)
          try {
            const chat = await fetch(`${API}/chats/${latest.id}`).then(r => r.json())
            setInitialMessages(chat.messages || [])
          } catch { /* no chat saved yet */ }
        }
      })
      .catch(() => {})
  }, [])

  const [showSpeakerModal, setShowSpeakerModal] = useState(false)
  const [speakers, setSpeakers] = useState([])
  const [shareToken, setShareToken] = useState(null)
  const [shareMode, setShareMode] = useState(INITIAL_SHARE_TOKEN ? 'loading' : null)
  const [shareCopied, setShareCopied] = useState(false)

  // Handle #share/{token} on load
  useEffect(() => {
    if (!INITIAL_SHARE_TOKEN) return
    fetch(`${API}/share/${INITIAL_SHARE_TOKEN}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { setShareMode(data || null) })
      .catch(() => { setShareMode(null) })
  }, [])

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
          setTranscript('')
          setSessionId(s => s + 1)
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
    const id = Date.now()
    const share_token = crypto.randomUUID().replace(/-/g, '').slice(0, 16)
    const entry = {
      id,
      date: new Date().toISOString(),
      transcript: t,
      result: r,
      title: r.summary?.slice(0, 65) || 'Meeting',
      score: r.health_score?.score,
      share_token,
    }
    setHistory(prev => [entry, ...prev])
    setMeetingId(id)
    setShareToken(share_token)
    fetch(`${API}/meetings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    }).catch(() => {})
  }

  const loadFromHistory = async (entry) => {
    setTranscript(entry.transcript)
    setResult(entry.result)
    setMeetingId(entry.id)
    setShareToken(entry.share_token || null)
    setSessionId(s => s + 1)
    setShowHistory(false)
    try {
      const res = await fetch(`${API}/chats/${entry.id}`)
      const data = await res.json()
      setInitialMessages(data.messages || [])
    } catch {
      setInitialMessages([])
    }
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

  const handleAnalyzeClick = () => {
    if (!transcript.trim()) return
    const detected = extractSpeakers(transcript)
    if (detected.length === 0) { runAnalysis([]); return }
    setSpeakers(detected)
    setShowSpeakerModal(true)
  }

  const runAnalysis = async (speakersParam, transcriptOverride) => {
    setShowSpeakerModal(false)
    setLoading(true)
    setError(null)
    setResult(null)
    setAnalysisTime(null)
    analysisStartRef.current = Date.now()
    const t = transcriptOverride ?? transcript
    const validSpeakers = speakersParam.filter(s => s.name.trim())
    try {
      const res = await fetch(`${API}/analyze-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: t, speakers: validSpeakers }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Server error ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = { ...DEFAULT_RESULT }
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') {
            const elapsed = ((Date.now() - analysisStartRef.current) / 1000).toFixed(1)
            setAnalysisTime(parseFloat(elapsed))
            setMobileTab('results')
            saveToHistory(t, accumulated)
            break
          }
          try {
            const chunk = JSON.parse(raw)
            accumulated = { ...accumulated, ...chunk }
            setResult({ ...accumulated })
          } catch { /* malformed chunk, skip */ }
        }
      }
    } catch (e) {
      setError(e.message || 'Failed to analyze.')
    } finally {
      setLoading(false)
    }
  }

  const toggleActionItem = (index) => {
    const updated = result.action_items.map((item, i) =>
      i === index ? { ...item, completed: !item.completed } : item
    )
    const updatedResult = { ...result, action_items: updated }
    setResult(updatedResult)
    if (meetingId) {
      fetch(`${API}/meetings/${meetingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: updatedResult }),
      }).catch(() => {})
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

  // Auto-run analysis when demo mode starts
  useEffect(() => {
    if (!isDemoMode) return
    runAnalysis([], SAMPLE_TRANSCRIPT)
  }, [isDemoMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Landing screen — shown to first-time visitors
  if (showLanding) {
    return <LandingScreen onDemo={() => exitLanding(true)} onSkip={() => exitLanding(false)} exiting={landingExiting} />
  }

  // Share mode — loading state (token detected synchronously, waiting for fetch)
  if (shareMode === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: '#07040f' }}>
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center animate-pulse" style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <p className="text-xs text-gray-500">Loading shared meeting…</p>
        </div>
      </div>
    )
  }

  // Share mode — read-only view for shared links
  if (shareMode) {
    const r = shareMode.result || {}
    return (
      <div className="min-h-screen px-4 py-8 max-w-2xl mx-auto" style={{ background: '#07040f' }}>
        <div className="flex items-center gap-3 mb-6">
          <div className="w-8 h-8 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <div>
            <span className="text-sm font-bold gradient-text">PrismAI</span>
            <span className="text-[10px] text-gray-600 ml-2">shared meeting</span>
          </div>
        </div>
        <h1 className="text-lg font-semibold text-white mb-1">{shareMode.title || 'Meeting'}</h1>
        <p className="text-xs text-gray-600 mb-6">{shareMode.date ? new Date(shareMode.date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }) : ''}</p>
        <div className="space-y-4">
          <HealthScoreCard healthScore={r.health_score} />
          <SummaryCard summary={r.summary} />
          <ActionItemsCard actionItems={r.action_items} />
          <DecisionsCard decisions={r.decisions} />
          <SentimentCard sentiment={r.sentiment} />
          <EmailCard email={r.follow_up_email} />
          <CalendarCard suggestion={r.calendar_suggestion} />
        </div>
        <p className="text-center text-xs text-gray-700 mt-8">Shared via PrismAI · <a href={window.location.origin + window.location.pathname} className="text-sky-600 hover:text-sky-400">Analyze your own meeting</a></p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden" style={BG_STYLE}>

      {/* ── Speaker identification modal ── */}
      {showSpeakerModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}>
          <div className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden animate-fade-in-up"
            style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)' }}>

            {/* Modal header */}
            <div className="px-5 py-4" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
              <h3 className="text-sm font-semibold text-white">Who was in this meeting?</h3>
              <p className="text-[11px] text-gray-500 mt-0.5">Add roles so agents can attribute output correctly. Optional — skip to analyze without.</p>
            </div>

            {/* Speaker rows */}
            <div className="px-5 py-4 space-y-2 max-h-64 overflow-y-auto">
              {speakers.map((s, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={s.name}
                    onChange={e => setSpeakers(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                    placeholder="Name"
                    className="w-32 flex-shrink-0 text-xs text-gray-200 rounded-lg px-3 py-2 outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600"
                    style={{ background: 'rgba(0,0,0,0.3)' }}
                  />
                  <input
                    value={s.role}
                    onChange={e => setSpeakers(prev => prev.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}
                    placeholder="Role (e.g. Engineering Lead)"
                    className="flex-1 text-xs text-gray-200 rounded-lg px-3 py-2 outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600"
                    style={{ background: 'rgba(0,0,0,0.3)' }}
                  />
                  <button onClick={() => setSpeakers(prev => prev.filter((_, j) => j !== i))}
                    className="text-gray-700 hover:text-red-400 transition-colors flex-shrink-0">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
              <button
                onClick={() => setSpeakers(prev => [...prev, { name: '', role: '' }])}
                className="text-[11px] text-sky-500 hover:text-sky-400 transition-colors mt-1">
                + Add person
              </button>
            </div>

            {/* Modal footer */}
            <div className="px-5 py-3 flex items-center justify-end gap-2"
              style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}>
              <button
                onClick={() => runAnalysis([])}
                className="px-4 py-2 rounded-xl text-xs text-gray-400 hover:text-gray-200 transition-colors"
                style={{ background: 'rgba(255,255,255,0.05)' }}>
                Skip
              </button>
              <button
                onClick={() => runAnalysis(speakers)}
                className="px-4 py-2 rounded-xl text-xs text-white font-medium transition-all hover:scale-105"
                style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
                Analyze
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="app-content flex-shrink-0 flex items-center justify-between px-6 py-3"
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
                <div className="absolute right-0 top-10 w-80 rounded-2xl shadow-2xl z-50 overflow-hidden animate-fade-in-up"
                  style={{ background: '#100c1e', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                    <span className="text-xs font-semibold text-gray-300">Recent Meetings</span>
                    <button onClick={async () => {
                      await Promise.all(history.map(h => fetch(`${API}/meetings/${h.id}`, { method: 'DELETE' }).catch(() => {})))
                      setHistory([])
                      setShowHistory(false)
                    }} className="text-[11px] text-gray-600 hover:text-red-400 transition-colors">Clear all</button>
                  </div>
                  <div className="px-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                    <input
                      value={historySearch}
                      onChange={async e => {
                        setHistorySearch(e.target.value)
                        const res = await fetch(`${API}/meetings?q=${encodeURIComponent(e.target.value)}`).catch(() => null)
                        if (res?.ok) { const d = await res.json(); setHistory(Array.isArray(d) ? d : []) }
                      }}
                      placeholder="Search meetings..."
                      className="w-full text-xs text-gray-300 rounded-lg px-3 py-1.5 outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600"
                      style={{ background: 'rgba(0,0,0,0.3)' }}
                    />
                  </div>
                  <div className="max-h-72 overflow-y-auto">
                    {history.map((entry) => (
                      <div key={entry.id} className="flex items-center group"
                        style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <button onClick={() => loadFromHistory(entry)}
                          className="flex-1 text-left px-4 py-3 hover:bg-white/5 transition-colors">
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
                        <button
                          onClick={() => {
                            setHistory(prev => prev.filter(h => h.id !== entry.id))
                            fetch(`${API}/meetings/${entry.id}`, { method: 'DELETE' }).catch(() => {})
                          }}
                          className="px-3 py-3 text-gray-700 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {result && (
            <button
              onClick={() => { setTranscript(''); setResult(null); setError(null); setSessionId(s => s + 1) }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white transition-colors"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Meeting
            </button>
          )}

          <button
            onClick={() => { setIsDemoMode(true); setTranscript(SAMPLE_TRANSCRIPT); runAnalysis([], SAMPLE_TRANSCRIPT) }}
            className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] text-sky-400 transition-colors hover:text-sky-300"
            style={{ background: 'rgba(14,165,233,0.07)', border: '1px solid rgba(14,165,233,0.15)' }}>
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Demo
          </button>

          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] text-gray-400"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            llama-3.3-70b
          </div>
          <div className="flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-semibold"
            style={{ background: 'linear-gradient(135deg, rgba(14,165,233,0.2), rgba(6,182,212,0.15))', border: '1px solid rgba(14,165,233,0.3)', color: '#7dd3fc' }}>
            7 agents
          </div>
        </div>
      </header>

      {/* ── Demo banner ── */}
      {isDemoMode && (
        <div className="flex-shrink-0 flex items-center justify-between px-6 py-2 text-xs"
          style={{ background: 'rgba(2,132,199,0.1)', borderBottom: '1px solid rgba(14,165,233,0.2)' }}>
          <span className="text-sky-300">
            <span className="font-semibold">Demo mode</span> — this is a sample transcript. See how PrismAI analyzes your meetings.
          </span>
          <button
            onClick={() => { setIsDemoMode(false); setTranscript(''); setResult(null); setError(null); setSessionId(s => s + 1) }}
            className="text-sky-500 hover:text-sky-300 transition-colors ml-4 flex-shrink-0">
            Use my own transcript →
          </button>
        </div>
      )}

      {/* ── Main two-pane layout ── */}
      <div className="app-content flex flex-1 overflow-hidden">

        {/* LEFT PANEL — Input */}
        <div className={`flex flex-col w-full lg:w-[420px] xl:w-[460px] flex-shrink-0 overflow-y-auto pb-16 lg:pb-0 ${mobileTab === 'results' ? 'hidden lg:flex' : 'flex'}`} style={PANEL_STYLE}>

          {/* Hero blurb */}
          <div className="px-6 pt-6 pb-4">
            <h1 className="text-xl font-bold text-white leading-snug">
              <span className="gradient-text">PrismAI</span> — one transcript,<br />seven dimensions of clarity.
            </h1>
            <p className="text-xs text-gray-500 mt-2 leading-relaxed">
              Orchestrator routes your transcript to 7 parallel AI agents in real time.
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
          <div className="mx-6 mb-4 rounded-2xl overflow-hidden card-breathe" style={CARD_STYLE}>

            {/* Input method dropdown */}
            <div className="px-4 pt-3 pb-2 flex items-center gap-2">
              <div className="relative flex-1">
                <select
                  value={inputTab}
                  onChange={(e) => setInputTab(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-xs font-medium outline-none appearance-none cursor-pointer pr-7"
                  style={{ background: 'rgba(14,165,233,0.1)', border: '1px solid rgba(14,165,233,0.25)', color: '#7dd3fc' }}>
                  <option value="paste">Paste Transcript</option>
                  {micSupported && <option value="record">Record Audio</option>}
                  <option value="upload">Upload Audio</option>
                  <option value="join">Join Meeting</option>
                </select>
                <svg className="w-3 h-3 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              {inputTab !== 'join' && (
                <button onClick={() => setTranscript(SAMPLE_TRANSCRIPT)}
                  className="text-[11px] px-2.5 py-2 rounded-lg transition-colors flex-shrink-0"
                  style={{ background: 'rgba(14,165,233,0.08)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.15)' }}>
                  Load sample
                </button>
              )}
            </div>

            {/* Paste Transcript */}
            {inputTab === 'paste' && (
              <div className="px-4 pb-4">
                <textarea
                  value={transcript}
                  onChange={(e) => setTranscript(e.target.value)}
                  placeholder="Paste your meeting transcript here..."
                  rows={8}
                  className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed placeholder-gray-700"
                  style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }}
                />
                <div className="flex items-center justify-between mt-3">
                  <span className="text-[11px] text-gray-600">
                    {transcript.length > 0 ? `${transcript.split(/\s+/).filter(Boolean).length} words` : 'No transcript'}
                  </span>
                  <button onClick={handleAnalyzeClick} disabled={!transcript.trim() || loading}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
                    style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.35)' }}>
                    {loading ? (<><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Analyzing...</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
                  </button>
                </div>
              </div>
            )}

            {/* Record Audio */}
            {inputTab === 'record' && (
              <div className="px-4 pb-4">
                <p className="text-[11px] text-gray-500 mb-3">Speak and your words will appear in the transcript below. Hit Analyze when done.</p>
                <button onClick={recording ? stopRecording : startRecording}
                  className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-semibold transition-all mb-3 ${recording ? 'animate-pulse' : ''}`}
                  style={recording
                    ? { background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)', color: '#fca5a5' }
                    : { background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.3)', color: '#fff' }}>
                  <svg className="w-4 h-4" fill={recording ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  {recording ? <><span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />Stop Recording</> : 'Start Recording'}
                </button>
                {transcript ? (
                  <>
                    <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} rows={5}
                      className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed"
                      style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }} />
                    <div className="flex justify-between items-center mt-3">
                      <span className="text-[11px] text-gray-600">{transcript.split(/\s+/).filter(Boolean).length} words</span>
                      <button onClick={handleAnalyzeClick} disabled={!transcript.trim() || loading}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 hover:scale-[1.02] active:scale-[0.98]"
                        style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.35)' }}>
                        {loading ? (<><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Analyzing...</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="text-[11px] text-gray-700 text-center py-4">Transcript will appear here as you speak</p>
                )}
              </div>
            )}

            {/* Upload Audio */}
            {inputTab === 'upload' && (
              <div className="px-4 pb-4">
                <p className="text-[11px] text-gray-500 mb-3">Upload an audio file and Whisper will transcribe it automatically. Supports mp3, wav, m4a, ogg, webm — max 25MB.</p>
                <button onClick={() => fileInputRef.current?.click()} disabled={transcribing}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 mb-3 hover:scale-[1.02] active:scale-[0.98]"
                  style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.3)' }}>
                  {transcribing ? (
                    <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Transcribing with Whisper...</>
                  ) : (
                    <><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>Choose Audio File</>
                  )}
                </button>
                <input ref={fileInputRef} type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm" className="hidden" onChange={handleAudioUpload} />
                {transcript ? (
                  <>
                    <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} rows={5}
                      className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed"
                      style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }} />
                    <div className="flex justify-between items-center mt-3">
                      <span className="text-[11px] text-gray-600">{transcript.split(/\s+/).filter(Boolean).length} words</span>
                      <button onClick={handleAnalyzeClick} disabled={!transcript.trim() || loading}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 hover:scale-[1.02] active:scale-[0.98]"
                        style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.35)' }}>
                        {loading ? (<><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Analyzing...</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="text-[11px] text-gray-700 text-center py-4">Transcript will appear here after upload</p>
                )}
              </div>
            )}

            {/* Join Meeting — was previously inline below */}
            {inputTab === 'join' && (
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
                  <button
                    onClick={() => document.getElementById('mobile-results')?.scrollIntoView({ behavior: 'smooth' })}
                    className="mt-3 w-full px-3 py-2.5 rounded-xl text-[11px] text-emerald-300 flex items-center gap-2 animate-fade-in-up cursor-pointer hover:bg-emerald-500/10 transition-colors"
                    style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)' }}>
                    <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    Analysis complete — tap to see results
                    <svg className="w-3 h-3 ml-auto flex-shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
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
            <ChatPanel key={sessionId} meetingId={meetingId} initialMessages={initialMessages} transcript={transcript} result={result} onResultUpdate={(updated) => setResult(r => ({ ...r, ...updated }))} />
          </div>
        </div>

        {/* RIGHT PANEL — Results */}
        <div className="hidden lg:flex flex-1 flex-col overflow-y-auto">
          {loading ? (
            <div className="p-6 space-y-4">
              <AgentPipelineLoader />
              {/* Skeleton cards while streaming */}
              <div className="space-y-4 opacity-40">
                <SkeletonCard lines={2} />
                <div className="grid grid-cols-2 gap-4">
                  <SkeletonCard lines={3} />
                  <SkeletonCard lines={3} />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <SkeletonCard lines={4} />
                  <SkeletonCard lines={3} />
                </div>
              </div>
            </div>
          ) : result ? (
            <div className="p-6 space-y-4">
              {/* Results header strip */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <AgentTags agents={result.agents_run || []} />
                  {analysisTime && (
                    <span className="text-[11px] text-gray-600">
                      {analysisTime}s · ~{Math.round(analysisTime * 1.8 + 20)} min saved
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                  {shareToken && (
                    <button onClick={() => {
                      const url = `${window.location.origin}${window.location.pathname}#share/${shareToken}`
                      navigator.clipboard.writeText(url).then(() => { setShareCopied(true); setTimeout(() => setShareCopied(false), 2000) })
                    }}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                      style={{ background: shareCopied ? 'rgba(14,165,233,0.15)' : 'rgba(255,255,255,0.05)', border: `1px solid ${shareCopied ? 'rgba(14,165,233,0.4)' : 'rgba(255,255,255,0.1)'}`, color: shareCopied ? '#7dd3fc' : '#9ca3af' }}>
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                      </svg>
                      {shareCopied ? 'Copied!' : 'Share'}
                    </button>
                  )}
                  <button onClick={exportMarkdown}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#9ca3af' }}>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Export .md
                  </button>
                </div>
              </div>

              {/* Health score — full width, prominent */}
              <div className="animate-fade-in-up card-delay-0">
                <HealthScoreCard healthScore={result.health_score} />
              </div>

              {/* Summary + Sentiment */}
              <div className="grid grid-cols-2 gap-4">
                <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
                <div className="animate-fade-in-up card-delay-2"><SentimentCard sentiment={result.sentiment} /></div>
              </div>

              {/* Action items + Decisions */}
              <div className="grid grid-cols-2 gap-4">
                <div className="animate-fade-in-up card-delay-3"><ActionItemsCard actionItems={result.action_items} onToggle={toggleActionItem} /></div>
                <div className="animate-fade-in-up card-delay-3"><DecisionsCard decisions={result.decisions} /></div>
              </div>

              {/* Email + Calendar */}
              <div className="grid grid-cols-2 gap-4">
                <div className="animate-fade-in-up card-delay-4"><EmailCard email={result.follow_up_email} /></div>
                <div className="animate-fade-in-up card-delay-5"><CalendarCard suggestion={result.calendar_suggestion} /></div>
              </div>
            </div>
          ) : (
            <EmptyState onDemo={() => { setIsDemoMode(true); setTranscript(SAMPLE_TRANSCRIPT); runAnalysis([], SAMPLE_TRANSCRIPT) }} />
          )}
        </div>

        {/* Mobile tab bar */}
        <div className="lg:hidden fixed bottom-0 left-0 right-0 z-40 flex"
          style={{ background: 'rgba(7,4,15,0.95)', borderTop: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(20px)' }}>
          <button
            onClick={() => setMobileTab('input')}
            className={`flex-1 py-3 text-xs font-medium transition-colors ${mobileTab === 'input' ? 'text-sky-400' : 'text-gray-600'}`}>
            Input
          </button>
          <button
            onClick={() => setMobileTab('results')}
            className={`flex-1 py-3 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${mobileTab === 'results' ? 'text-sky-400' : 'text-gray-600'}`}>
            Results
            {(loading || result) && (
              <span className={`w-1.5 h-1.5 rounded-full ${loading ? 'bg-sky-400 animate-pulse' : 'bg-emerald-400'}`} />
            )}
          </button>
        </div>

        {/* Mobile results panel */}
        <div className={`lg:hidden w-full overflow-y-auto pb-16 ${mobileTab === 'results' ? 'block' : 'hidden'}`}>
          {loading ? (
            <div className="px-4 pt-4 space-y-4">
              <AgentPipelineLoader />
              <div className="space-y-4 opacity-40">
                <SkeletonCard lines={2} />
                <SkeletonCard lines={3} />
                <SkeletonCard lines={4} />
              </div>
            </div>
          ) : result ? (
            <div className="px-4 pb-4 space-y-4">
              <div className="flex items-center justify-between pt-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <AgentTags agents={result.agents_run || []} />
                  {analysisTime && (
                    <span className="text-[11px] text-gray-600">{analysisTime}s · ~{Math.round(analysisTime * 1.8 + 20)} min saved</span>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-2 flex-shrink-0">
                  {shareToken && (
                    <button onClick={() => {
                      const url = `${window.location.origin}${window.location.pathname}#share/${shareToken}`
                      navigator.clipboard.writeText(url).then(() => { setShareCopied(true); setTimeout(() => setShareCopied(false), 2000) })
                    }}
                      className="text-xs px-3 py-1.5 rounded-lg transition-all"
                      style={{ background: shareCopied ? 'rgba(14,165,233,0.15)' : 'rgba(255,255,255,0.05)', border: `1px solid ${shareCopied ? 'rgba(14,165,233,0.4)' : 'rgba(255,255,255,0.1)'}`, color: shareCopied ? '#7dd3fc' : '#9ca3af' }}>
                      {shareCopied ? 'Copied!' : 'Share'}
                    </button>
                  )}
                  <button onClick={exportMarkdown} className="text-xs px-3 py-1.5 rounded-lg text-gray-400"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                    Export
                  </button>
                </div>
              </div>
              <div className="animate-fade-in-up card-delay-0"><HealthScoreCard healthScore={result.health_score} /></div>
              <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
              <div className="animate-fade-in-up card-delay-2"><ActionItemsCard actionItems={result.action_items} onToggle={toggleActionItem} /></div>
              <div className="animate-fade-in-up card-delay-3"><DecisionsCard decisions={result.decisions} /></div>
              <div className="animate-fade-in-up card-delay-4"><SentimentCard sentiment={result.sentiment} /></div>
              <div className="animate-fade-in-up card-delay-4"><EmailCard email={result.follow_up_email} /></div>
              <div className="animate-fade-in-up card-delay-5"><CalendarCard suggestion={result.calendar_suggestion} /></div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-600 text-sm">
              Analyze a meeting to see results
            </div>
          )}
        </div>

        {/* Mobile input panel — hide when on results tab */}
        <div className={`lg:hidden ${mobileTab === 'input' ? 'block' : 'hidden'}`} />

      </div>
    </div>
  )
}

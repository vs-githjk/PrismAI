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

const AGENT_NODES = [
  { id: 'summarizer', label: 'Summarizer', icon: '📝', color: 'indigo' },
  { id: 'action_items', label: 'Action Items', icon: '✅', color: 'purple' },
  { id: 'sentiment', label: 'Sentiment', icon: '💬', color: 'yellow' },
  { id: 'email_drafter', label: 'Email Draft', icon: '✉️', color: 'emerald' },
  { id: 'calendar_suggester', label: 'Calendar', icon: '📅', color: 'pink' },
  { id: 'health_score', label: 'Health Score', icon: '📊', color: 'cyan' },
]

const COLOR_MAP = {
  indigo: { bg: 'bg-indigo-500/15', border: 'border-indigo-500/40', text: 'text-indigo-300' },
  purple: { bg: 'bg-purple-500/15', border: 'border-purple-500/40', text: 'text-purple-300' },
  yellow: { bg: 'bg-yellow-500/15', border: 'border-yellow-500/40', text: 'text-yellow-300' },
  emerald: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/40', text: 'text-emerald-300' },
  pink: { bg: 'bg-pink-500/15', border: 'border-pink-500/40', text: 'text-pink-300' },
  cyan: { bg: 'bg-cyan-500/15', border: 'border-cyan-500/40', text: 'text-cyan-300' },
}

function AgentPipelineLoader() {
  return (
    <div className="flex flex-col items-center gap-6 py-10">
      <div className="flex flex-col items-center gap-2 animate-fade-in-up card-delay-0">
        <div className="relative">
          <div className="w-16 h-16 rounded-2xl bg-indigo-500/20 border border-indigo-500/50 flex items-center justify-center animate-glow-pulse">
            <svg className="w-8 h-8 text-indigo-400 animate-spin-slow" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <div className="absolute -top-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-[#070711] animate-pulse"></div>
        </div>
        <div className="text-center">
          <p className="text-sm font-semibold text-indigo-300">Orchestrator</p>
          <p className="text-xs text-gray-500 mt-0.5">LLaMA 3.3-70b · routing</p>
        </div>
      </div>
      <div className="flex flex-col items-center gap-1 animate-fade-in-up card-delay-1">
        <div className="w-px h-6 bg-gradient-to-b from-indigo-500/60 to-purple-500/30"></div>
        <div className="text-xs text-gray-500 px-3 py-1 rounded-full bg-white/5 border border-white/10">
          dispatching 6 agents in parallel
        </div>
        <div className="w-px h-6 bg-gradient-to-b from-purple-500/30 to-transparent"></div>
      </div>
      <div className="flex flex-wrap justify-center gap-3 max-w-lg animate-fade-in-up card-delay-2">
        {AGENT_NODES.map((agent, i) => {
          const c = COLOR_MAP[agent.color]
          return (
            <div
              key={agent.id}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${c.bg} ${c.border} animate-pulse`}
              style={{ animationDelay: `${i * 0.15}s` }}
            >
              <span className="text-sm">{agent.icon}</span>
              <span className={`text-xs font-medium ${c.text}`}>{agent.label}</span>
              <div className={`w-1.5 h-1.5 rounded-full bg-current ${c.text} animate-pulse`}></div>
            </div>
          )
        })}
      </div>
      <p className="text-xs text-gray-600 animate-fade-in-up card-delay-3">Analyzing your meeting transcript...</p>
    </div>
  )
}

// Generate markdown export
function buildMarkdown(transcript, result) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const h = result.health_score
  let md = `# Meeting Summary — ${date}\n\n`

  if (h && h.score) {
    md += `## Meeting Health: ${h.score}/100 — ${h.verdict}\n`
    if (h.badges?.length) md += h.badges.map(b => `\`${b}\``).join(' ') + '\n'
    md += '\n'
  }

  if (result.summary) {
    md += `## Summary\n\n${result.summary}\n\n`
  }

  if (result.action_items?.length) {
    md += `## Action Items\n\n`
    result.action_items.forEach(item => {
      md += `- [ ] ${item.task}`
      if (item.owner && item.owner !== 'Unassigned') md += ` *(${item.owner})*`
      if (item.due && item.due !== 'TBD') md += ` — due ${item.due}`
      md += '\n'
    })
    md += '\n'
  }

  if (result.sentiment) {
    md += `## Sentiment: ${result.sentiment.overall} (${result.sentiment.score}/100)\n\n`
    if (result.sentiment.notes) md += `${result.sentiment.notes}\n\n`
  }

  if (result.follow_up_email?.subject) {
    md += `## Follow-up Email Draft\n\n**Subject:** ${result.follow_up_email.subject}\n\n${result.follow_up_email.body}\n\n`
  }

  if (result.calendar_suggestion?.recommended) {
    md += `## Calendar Suggestion\n\n${result.calendar_suggestion.reason}`
    if (result.calendar_suggestion.suggested_timeframe) md += ` — ${result.calendar_suggestion.suggested_timeframe}`
    md += '\n\n'
  }

  return md
}

export default function App() {
  const [transcript, setTranscript] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // Mic recording
  const [recording, setRecording] = useState(false)
  const recognitionRef = useRef(null)
  const micSupported = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  // Audio upload / transcription
  const [transcribing, setTranscribing] = useState(false)
  const fileInputRef = useRef(null)

  // History
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('meeting-history') || '[]') }
    catch { return [] }
  })
  const [showHistory, setShowHistory] = useState(false)

  const saveToHistory = (t, r) => {
    const entry = {
      id: Date.now(),
      date: new Date().toISOString(),
      transcript: t,
      result: r,
      title: r.summary?.slice(0, 65) || 'Meeting ' + new Date().toLocaleDateString(),
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

  const clearHistory = () => {
    setHistory([])
    localStorage.removeItem('meeting-history')
    setShowHistory(false)
  }

  // Mic recording
  const startRecording = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    const recognition = new SR()
    recognition.continuous = true
    recognition.interimResults = false
    recognition.lang = 'en-US'
    recognition.onresult = (e) => {
      const text = Array.from(e.results).map(r => r[0].transcript).join(' ')
      setTranscript(prev => prev ? prev + '\n' + text : text)
    }
    recognition.onerror = () => setRecording(false)
    recognition.onend = () => setRecording(false)
    recognition.start()
    recognitionRef.current = recognition
    setRecording(true)
  }

  const stopRecording = () => {
    recognitionRef.current?.stop()
    setRecording(false)
  }

  // Audio file upload
  const handleAudioUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setTranscribing(true)
    setError(null)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${API}/transcribe`, { method: 'POST', body: formData })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Transcription failed')
      }
      const data = await res.json()
      setTranscript(data.transcript)
    } catch (e) {
      setError(e.message)
    } finally {
      setTranscribing(false)
      e.target.value = ''
    }
  }

  // Analyze
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
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Server error: ${res.status}`)
      }
      const data = await res.json()
      setResult(data)
      saveToHistory(transcript, data)
    } catch (e) {
      setError(e.message || 'Failed to analyze. Check that the backend is running.')
    } finally {
      setLoading(false)
    }
  }

  // Export
  const exportMarkdown = () => {
    if (!result) return
    const md = buildMarkdown(transcript, result)
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `meeting-summary-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // Close history on outside click
  useEffect(() => {
    if (!showHistory) return
    const handler = (e) => {
      if (!e.target.closest('[data-history-panel]')) setShowHistory(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showHistory])

  return (
    <div className="min-h-screen text-gray-100" style={{ background: '#070711' }}>

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-white/5 backdrop-blur-xl" style={{ background: 'rgba(7,7,17,0.85)' }}>
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold gradient-text">Agentic Meeting Copilot</h1>
              <p className="text-[10px] text-gray-500 leading-none mt-0.5">multi-agent AI pipeline</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* History button */}
            {history.length > 0 && (
              <div className="relative" data-history-panel>
                <button
                  onClick={() => setShowHistory(v => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 hover:bg-white/8 transition-colors text-xs text-gray-400 hover:text-gray-200"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  History
                  <span className="w-4 h-4 rounded-full bg-indigo-500/30 text-indigo-300 text-[10px] flex items-center justify-center font-bold">{history.length}</span>
                </button>

                {showHistory && (
                  <div className="absolute right-0 top-10 w-80 rounded-2xl border border-white/10 shadow-2xl z-30 overflow-hidden animate-fade-in-up"
                    style={{ background: '#0f0f20' }}>
                    <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-300">Recent Meetings</span>
                      <button onClick={clearHistory} className="text-[11px] text-gray-600 hover:text-red-400 transition-colors">Clear all</button>
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      {history.map((entry) => (
                        <button
                          key={entry.id}
                          onClick={() => loadFromHistory(entry)}
                          className="w-full text-left px-4 py-3 hover:bg-white/5 border-b border-white/5 last:border-0 transition-colors group"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-xs text-gray-300 group-hover:text-white transition-colors line-clamp-2 flex-1">{entry.title}</p>
                            {entry.score !== undefined && (
                              <span className={`text-[11px] font-bold flex-shrink-0 ${entry.score >= 80 ? 'text-emerald-400' : entry.score >= 60 ? 'text-indigo-400' : entry.score >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
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
            <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
              <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></div>
              <span className="text-[11px] text-gray-400 font-medium">llama-3.3-70b</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20">
              <span className="text-[11px] text-indigo-400 font-medium">6 agents</span>
            </div>
          </div>
        </div>
      </header>

      {/* Hero strip */}
      <div className="border-b border-white/5" style={{ background: 'linear-gradient(to bottom, rgba(99,102,241,0.06), transparent)' }}>
        <div className="max-w-4xl mx-auto px-4 py-8">
          <div className="flex flex-col sm:flex-row sm:items-end gap-4">
            <div className="flex-1">
              <h2 className="text-2xl sm:text-3xl font-bold text-white leading-tight">
                Turn any meeting into<br />
                <span className="gradient-text">structured intelligence.</span>
              </h2>
              <p className="text-sm text-gray-400 mt-2 max-w-md">
                An orchestrator LLM reads your transcript and dynamically routes it to 6 specialized agents — summaries, action items, health score, sentiment, emails, and calendar suggestions.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 sm:max-w-[220px]">
              {AGENT_NODES.map((a) => {
                const c = COLOR_MAP[a.color]
                return (
                  <div key={a.id} className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-medium border ${c.bg} ${c.border} ${c.text}`}>
                    <span>{a.icon}</span> {a.label}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">

        {/* Error */}
        {error && (
          <div className="animate-fade-in-up bg-red-500/10 border border-red-500/30 text-red-300 px-4 py-3 rounded-xl text-sm flex items-start gap-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {/* Transcript input */}
        <section className="animate-fade-in-up card-delay-0 rounded-2xl border border-white/8 overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
          <div className="px-5 pt-5 pb-3 flex items-center justify-between border-b border-white/5">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <h2 className="text-sm font-semibold text-gray-200">Meeting Transcript</h2>
            </div>
            <button
              onClick={() => setTranscript(SAMPLE_TRANSCRIPT)}
              className="text-xs text-indigo-400 hover:text-indigo-300 px-3 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-colors"
            >
              Load sample →
            </button>
          </div>

          {/* Toolbar: mic + upload */}
          <div className="px-5 pt-3 pb-1 flex items-center gap-2">
            {micSupported && (
              <button
                onClick={recording ? stopRecording : startRecording}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                  recording
                    ? 'bg-red-500/20 border-red-500/40 text-red-300 animate-pulse'
                    : 'bg-white/5 border-white/10 text-gray-400 hover:text-gray-200 hover:bg-white/8'
                }`}
              >
                <svg className="w-3.5 h-3.5" fill={recording ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
                {recording ? 'Stop Recording' : 'Record'}
              </button>
            )}

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={transcribing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/10 bg-white/5 text-gray-400 hover:text-gray-200 hover:bg-white/8 transition-all disabled:opacity-40"
            >
              {transcribing ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Transcribing...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072M12 6v6m0 0v6m0-6h.01M9.172 16.172a4 4 0 015.656 0M6.343 9.343a8 8 0 0111.314 0" />
                  </svg>
                  Upload Audio
                </>
              )}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*,.mp3,.wav,.m4a,.ogg,.webm"
              className="hidden"
              onChange={handleAudioUpload}
            />

            {recording && (
              <span className="text-xs text-red-400 flex items-center gap-1.5 ml-2">
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"></span>
                Listening...
              </span>
            )}
            {transcribing && (
              <span className="text-xs text-indigo-400 ml-2">Running Whisper large-v3...</span>
            )}
          </div>

          <div className="px-4 pb-4 pt-2">
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Paste your meeting transcript here, or use Record / Upload Audio above..."
              rows={10}
              className="w-full text-gray-200 rounded-xl px-4 py-3 text-sm resize-none outline-none focus:ring-1 focus:ring-indigo-500/50 placeholder-gray-600 font-mono leading-relaxed border border-white/5 transition-colors"
              style={{ background: 'rgba(0,0,0,0.3)' }}
            />
            <div className="flex items-center justify-between mt-3">
              <span className="text-xs text-gray-600">
                {transcript.length > 0
                  ? `${transcript.split(/\s+/).filter(Boolean).length} words · ${transcript.length} chars`
                  : 'Paste, record, or upload an audio file'}
              </span>
              <button
                onClick={analyze}
                disabled={!transcript.trim() || loading}
                className="relative px-6 py-2.5 font-semibold rounded-xl text-sm text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed overflow-hidden group"
                style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}
              >
                <span className="relative z-10 flex items-center gap-2">
                  {loading ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                      </svg>
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                      Analyze Meeting
                    </>
                  )}
                </span>
                <div className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"></div>
              </button>
            </div>
          </div>
        </section>

        {/* Loading pipeline */}
        {loading && (
          <section className="rounded-2xl border border-white/8 p-6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <AgentPipelineLoader />
          </section>
        )}

        {/* Results */}
        {result && !loading && (
          <section className="space-y-4">
            {/* Results header with export */}
            <div className="flex items-center justify-between">
              <AgentTags agents={result.agents_run || []} />
            </div>
            <div className="flex justify-end -mt-2">
              <button
                onClick={exportMarkdown}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-gray-400 hover:text-gray-200 hover:bg-white/8 transition-all"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Export .md
              </button>
            </div>

            <div className="animate-fade-in-up card-delay-0"><HealthScoreCard healthScore={result.health_score} /></div>
            <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
            <div className="animate-fade-in-up card-delay-2"><ActionItemsCard actionItems={result.action_items} /></div>
            <div className="animate-fade-in-up card-delay-3"><SentimentCard sentiment={result.sentiment} /></div>
            <div className="animate-fade-in-up card-delay-4"><EmailCard email={result.follow_up_email} /></div>
            <div className="animate-fade-in-up card-delay-5"><CalendarCard suggestion={result.calendar_suggestion} /></div>
          </section>
        )}

        {/* Chat panel */}
        <section className="animate-fade-in-up card-delay-1">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-6 h-6 rounded-lg bg-violet-500/20 border border-violet-500/30 flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <h2 className="text-sm font-semibold text-gray-200">Chat with your meeting</h2>
          </div>
          <ChatPanel transcript={transcript} />
        </section>

      </main>

      <footer className="border-t border-white/5 mt-16 py-8">
        <div className="max-w-4xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-gray-600 text-xs">Agentic Meeting Copilot · Built with LLaMA 3.3-70b via Groq</p>
          <div className="flex items-center gap-1.5">
            {AGENT_NODES.map((a) => {
              const c = COLOR_MAP[a.color]
              return <span key={a.id} className={`w-2 h-2 rounded-full ${c.bg.replace('/15', '/60')}`}></span>
            })}
          </div>
        </div>
      </footer>

    </div>
  )
}

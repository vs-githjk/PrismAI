import { useState } from 'react'
import AgentTags from './components/AgentTags'
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
]

const COLOR_MAP = {
  indigo: { bg: 'bg-indigo-500/15', border: 'border-indigo-500/40', text: 'text-indigo-300', glow: 'shadow-indigo-500/30' },
  purple: { bg: 'bg-purple-500/15', border: 'border-purple-500/40', text: 'text-purple-300', glow: 'shadow-purple-500/30' },
  yellow: { bg: 'bg-yellow-500/15', border: 'border-yellow-500/40', text: 'text-yellow-300', glow: 'shadow-yellow-500/30' },
  emerald: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/40', text: 'text-emerald-300', glow: 'shadow-emerald-500/30' },
  pink: { bg: 'bg-pink-500/15', border: 'border-pink-500/40', text: 'text-pink-300', glow: 'shadow-pink-500/30' },
}

function AgentPipelineLoader() {
  return (
    <div className="flex flex-col items-center gap-6 py-10">
      {/* Orchestrator node */}
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

      {/* Connector */}
      <div className="flex flex-col items-center gap-1 animate-fade-in-up card-delay-1">
        <div className="w-px h-6 bg-gradient-to-b from-indigo-500/60 to-purple-500/30"></div>
        <div className="text-xs text-gray-500 px-3 py-1 rounded-full bg-white/5 border border-white/10">
          dispatching agents in parallel
        </div>
        <div className="w-px h-6 bg-gradient-to-b from-purple-500/30 to-transparent"></div>
      </div>

      {/* Agent nodes */}
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
              <div className={`w-1.5 h-1.5 rounded-full ${c.text.replace('text', 'bg')} animate-pulse`}></div>
            </div>
          )
        })}
      </div>

      <p className="text-xs text-gray-600 animate-fade-in-up card-delay-3">Analyzing your meeting transcript...</p>
    </div>
  )
}

export default function App() {
  const [transcript, setTranscript] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

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
    } catch (e) {
      setError(e.message || 'Failed to analyze. Check that the backend is running.')
    } finally {
      setLoading(false)
    }
  }

  const loadSample = () => setTranscript(SAMPLE_TRANSCRIPT)

  return (
    <div className="min-h-screen text-gray-100" style={{ background: '#070711' }}>

      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-white/5 backdrop-blur-xl"
        style={{ background: 'rgba(7,7,17,0.85)' }}>
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
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
          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
              <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"></div>
              <span className="text-[11px] text-gray-400 font-medium">llama-3.3-70b</span>
            </div>
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20">
              <span className="text-[11px] text-indigo-400 font-medium">5 agents</span>
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
                An orchestrator LLM reads your transcript and dynamically routes it to specialized agents — summaries, action items, sentiment, follow-up emails, and calendar suggestions.
              </p>
            </div>
            {/* Pipeline preview badges */}
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
        <section className="animate-fade-in-up card-delay-0 rounded-2xl border border-white/8 overflow-hidden"
          style={{ background: 'rgba(255,255,255,0.03)' }}>
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
              onClick={loadSample}
              className="text-xs text-indigo-400 hover:text-indigo-300 px-3 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 transition-colors"
            >
              Load sample →
            </button>
          </div>
          <div className="p-4">
            <textarea
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder="Paste your meeting transcript here..."
              rows={10}
              className="w-full text-gray-200 rounded-xl px-4 py-3 text-sm resize-none outline-none focus:ring-1 focus:ring-indigo-500/50 placeholder-gray-600 font-mono leading-relaxed border border-white/5 transition-colors"
              style={{ background: 'rgba(0,0,0,0.3)' }}
            />
            <div className="flex items-center justify-between mt-3">
              <span className="text-xs text-gray-600">
                {transcript.length > 0
                  ? `${transcript.split(/\s+/).filter(Boolean).length} words · ${transcript.length} chars`
                  : 'Paste any meeting transcript'}
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
            <AgentTags agents={result.agents_run || []} />
            <div className="animate-fade-in-up card-delay-0"><SummaryCard summary={result.summary} /></div>
            <div className="animate-fade-in-up card-delay-1"><ActionItemsCard actionItems={result.action_items} /></div>
            <div className="animate-fade-in-up card-delay-2"><SentimentCard sentiment={result.sentiment} /></div>
            <div className="animate-fade-in-up card-delay-3"><EmailCard email={result.follow_up_email} /></div>
            <div className="animate-fade-in-up card-delay-4"><CalendarCard suggestion={result.calendar_suggestion} /></div>
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

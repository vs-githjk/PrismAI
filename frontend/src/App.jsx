import { useState } from 'react'
import AgentTags from './components/AgentTags'
import SummaryCard from './components/SummaryCard'
import ActionItemsCard from './components/ActionItemsCard'
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
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">
              Agentic Meeting Copilot
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">Powered by multi-agent AI</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            <span className="text-xs text-gray-400">llama-3.3-70b</span>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-8">
        {/* Error toast */}
        {error && (
          <div className="bg-red-900/50 border border-red-500/50 text-red-300 px-4 py-3 rounded-xl text-sm flex items-start gap-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {/* Transcript Input */}
        <section className="bg-gray-900 rounded-2xl p-6 border border-gray-800">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-semibold text-gray-200">Meeting Transcript</h2>
            <button
              onClick={loadSample}
              className="text-xs text-blue-400 hover:text-blue-300 underline-offset-2 hover:underline"
            >
              Load sample
            </button>
          </div>
          <textarea
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="Paste your meeting transcript here..."
            rows={10}
            className="w-full bg-gray-800 text-gray-200 rounded-xl px-4 py-3 text-sm resize-none outline-none focus:ring-1 focus:ring-blue-500 placeholder-gray-600 font-mono leading-relaxed"
          />
          <div className="flex items-center justify-between mt-3">
            <span className="text-xs text-gray-500">
              {transcript.length > 0 ? `${transcript.split(/\s+/).filter(Boolean).length} words` : 'No transcript yet'}
            </span>
            <button
              onClick={analyze}
              disabled={!transcript.trim() || loading}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-medium rounded-xl transition-colors text-sm"
            >
              {loading ? 'Analyzing...' : 'Analyze Meeting'}
            </button>
          </div>
        </section>

        {/* Loading skeletons */}
        {loading && (
          <section className="space-y-4">
            <div className="flex gap-2 mb-2">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-6 w-20 bg-gray-800 rounded-full animate-pulse"></div>
              ))}
            </div>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </section>
        )}

        {/* Results */}
        {result && !loading && (
          <section className="space-y-4">
            <AgentTags agents={result.agents_run || []} />
            <SummaryCard summary={result.summary} />
            <ActionItemsCard actionItems={result.action_items} />
            <SentimentCard sentiment={result.sentiment} />
            <EmailCard email={result.follow_up_email} />
            <CalendarCard suggestion={result.calendar_suggestion} />
          </section>
        )}

        {/* Chat Panel */}
        <section>
          <h2 className="text-base font-semibold text-gray-200 mb-3">Chat with your meeting</h2>
          <ChatPanel transcript={transcript} />
        </section>
      </main>

      <footer className="border-t border-gray-800 mt-12 py-6 text-center">
        <p className="text-gray-600 text-xs">Agentic Meeting Copilot — Hackathon Demo</p>
      </footer>
    </div>
  )
}

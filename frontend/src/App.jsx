import { useState, useRef, useEffect, useCallback, Component, Suspense, lazy } from 'react'
import { UI_SCREEN_KEY, VISITED_KEY, TEST_RUN_SESSION_KEY } from './lib/sessionKeys'
import Prism from './components/Prism'
import LogoIcon from './components/LogoIcon'
import LandingNav from './components/LandingNav'
import { TextRotate } from '@/components/ui/text-rotate'
import HowItWorks from './components/HowItWorks'
import AgentShowcase from './components/AgentShowcase'
import PricingSection from './components/PricingSection'
import TeamSection from './components/TeamSection'
import SignupDialog from './components/SignupDialog'
import AgentTags from './components/AgentTags'
import HealthScoreCard from './components/HealthScoreCard'
import SummaryCard from './components/SummaryCard'
import ActionItemsCard from './components/ActionItemsCard'
import DecisionsCard from './components/DecisionsCard'
import SentimentCard from './components/SentimentCard'
import EmailCard from './components/EmailCard'
import CalendarCard from './components/CalendarCard'
import SpeakerCoachCard from './components/SpeakerCoachCard'
import SkeletonCard from './components/SkeletonCard'
import ErrorCard from './components/ErrorCard'
import DashboardMcpPage from './components/DashboardMcpPage'
import { supabase } from './lib/supabase'
import { apiFetch } from './lib/api'

const ChatPanel = lazy(() => import('./components/ChatPanel'))
const ProactiveSuggestions = lazy(() => import('./components/ProactiveSuggestions'))
const ScoreTrendChart = lazy(() => import('./components/ScoreTrendChart'))
const CrossMeetingInsights = lazy(() => import('./components/CrossMeetingInsights'))
const IntegrationsModal = lazy(() => import('./components/IntegrationsModal'))
const UpcomingMeetings = lazy(() => import('./components/UpcomingMeetings'))
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-2xl px-5 py-6 text-center animate-fade-in-up"
          style={{ background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)' }}>
          <p className="text-sm font-semibold text-red-300 mb-1">Something went wrong rendering results</p>
          <p className="text-xs text-gray-500 mb-4">{this.state.error?.message || 'An unexpected error occurred.'}</p>
          <button onClick={() => this.setState({ hasError: false, error: null })}
            className="text-[11px] px-4 py-2 rounded-lg font-medium transition-all hover:scale-105"
            style={{ background: 'rgba(239,68,68,0.15)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.3)' }}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

const APP_URL = typeof window !== 'undefined' ? `${window.location.origin}${window.location.pathname}` : ''
const TEST_RUN_QUERY_PARAM = 'testRun'
const isDashboardTestRunRequest =
  typeof window !== 'undefined' &&
  window.location.pathname === '/dashboard-mcp' &&
  new URLSearchParams(window.location.search).get(TEST_RUN_QUERY_PARAM) === '1'

if (isDashboardTestRunRequest) {
  sessionStorage.setItem(TEST_RUN_SESSION_KEY, '1')
}

const isTestRunSession = () =>
  typeof window !== 'undefined' &&
  window.location.pathname === '/dashboard-mcp' &&
  sessionStorage.getItem(TEST_RUN_SESSION_KEY) === '1'
const TEST_AUTH_SESSION = {
  access_token: 'local-test-session',
  user: {
    id: 'test-account',
    email: 'test@prismai.local',
    user_metadata: { name: 'Prism Test' },
    app_metadata: { provider: 'test' },
  },
}

function DeferredCardFallback({ lines = 2 }) {
  return (
    <div className="animate-fade-in-up">
      <SkeletonCard lines={lines} />
    </div>
  )
}

const DEMO_TRANSCRIPTS = [
  // Q2 roadmap planning
  `Sarah: Alright everyone, let's get started. Today we need to finalize the Q2 roadmap and discuss the upcoming product launch.

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

Sarah: Excellent. I think we're in good shape. Thanks everyone.`,

  // Engineering incident postmortem
  `Alex: Let's get through this postmortem on the payment outage from Tuesday. We had roughly 40 minutes of degraded checkout.

Jordan: So the root cause was a Redis connection pool exhaustion. We had a config change go out Monday night that lowered the max connections from 100 to 10. That's it.

Priya: Who approved that config change? I don't see it in the deploy log.

Jordan: It was bundled into the infra cost-optimization PR. It was reviewed but nobody caught the connection pool value change.

Alex: Okay. So we need a couple things here. First, we need to restore the connection pool config — Jordan, is that already done?

Jordan: Done Tuesday afternoon. We're back to 100 and I added a 20% headroom buffer.

Alex: Good. Priya, can you set up an alert that fires if connection pool utilization exceeds 70 percent?

Priya: Yes, I'll have that in by end of week.

Alex: We also need to add connection pool values to our change review checklist. Marcus, can you own that doc update?

Marcus: I'll update the checklist and send it to the eng channel by Thursday.

Alex: And we need a runbook for this class of failure. Priya, can you draft that?

Priya: Sure. I'll model it after the database failover runbook, should be done by next Monday.

Alex: This one stings because it was totally preventable. Going forward, any infra config change touching connection limits needs a second reviewer from the on-call rotation. Agreed?

Jordan: Agreed.

Marcus: Makes sense.

Priya: Yes, I'll add that to the on-call policy doc as well.

Alex: Good. I think we have clear owners on everything. Let's do a quick check-in Friday to make sure the alert is in and the checklist is updated.`,

  // Sales strategy and pipeline review
  `Diana: Okay team, Q1 closed yesterday. Let's look at where we landed and what we're doing differently in Q2.

Carlos: We hit 87% of target. The mid-market segment was strong — 112% — but enterprise dragged us down. We lost three deals in the final stage that we thought were locked.

Diana: What happened on those enterprise deals?

Carlos: Two of them went to a competitor on pricing. We were 20% higher with no compelling differentiation in the demo. The third ghosted us after legal review took six weeks.

Rachel: The legal review time is a real problem. I've flagged this before. We need a pre-approved contract template for deals under $50k ARR.

Diana: I agree. Rachel, can you work with legal to get a standard template ready before end of April?

Rachel: I'll get on their calendar this week. Should be doable.

Diana: On the pricing issue — Carlos, I want you to build a competitive battle card for our top two competitors. Focus on where we win and where we need to match.

Carlos: I can have a first draft by next Friday.

Diana: Good. Also we're piloting a new discovery call framework in Q2. Everyone should complete the MEDDIC certification on the learning portal by April 30th.

Carlos: I'll block time this week.

Rachel: Same.

Diana: Last thing — we're targeting 15 net-new enterprise logos in Q2. That means we need pipeline coverage of at least 3x, so 45 active enterprise opportunities. Let's review pipeline health every Monday at 9am. I'll send a recurring invite.

Carlos: Works for me.

Rachel: Sounds good.`,

  // Dysfunctional budget meeting — low health, tense sentiment
  `Greg: Okay so I called this meeting because we need to talk about the Q3 budget. I sent around a spreadsheet last week. Did everyone look at it?

Kevin: I glanced at it yeah.

Tara: I didn't get it.

Greg: I sent it to the whole team.

Tara: I'm not on that distribution list. This keeps happening.

Greg: Okay well, the point is we're over budget. Marketing is 40% over and I need to understand why.

Kevin: That's not entirely fair. We ran two campaigns that weren't in the original plan because leadership asked us to.

Greg: Leadership asked for the campaigns, not for 40% overspend.

Kevin: The budget wasn't adjusted when the scope changed. I flagged this in June.

Greg: I don't have any record of that.

Kevin: I sent an email. I can forward it to you.

Greg: Fine, forward it. But we still need to figure out how to get back on track.

Tara: Can someone explain what the actual number is? The spreadsheet Greg mentioned had three different totals on different tabs and I don't know which one is right.

Greg: The one on the summary tab.

Tara: The summary tab has a formula error. It says REF.

Greg: What? That can't be right. I just updated it.

Kevin: Yeah it does say REF. I noticed that too but I assumed it was intentional for some reason.

Greg: It's not intentional. Okay. I'll fix the spreadsheet. Can we just... can we move on?

Tara: Move on to what? We don't know what the actual number is.

Greg: We're roughly 40% over on marketing, maybe 15% over overall. I'm estimating.

Kevin: And what do you want us to do about it?

Greg: I want us to come up with a plan.

Kevin: Okay what kind of plan? Cut spend? Move budget from another team?

Greg: I don't know, that's why I called the meeting.

Tara: So there's no agenda?

Greg: The agenda is figuring out the budget.

Tara: Right, but like, do you want ideas? Do you want someone to own a proposal? I'm not clear on what we're deciding today.

Greg: I just want to get aligned.

Kevin: I have a hard stop at 3. Are we going to actually decide anything?

Greg: Let's just say everyone reviews their team spend this week and we reconvene.

Tara: Reconvene when?

Greg: I'll send something.

Kevin: Okay. I have to drop.

Greg: Fine, we'll figure it out async.`,

  // Design review and user research readout
  `Morgan: Alright, let's go through the user research findings from the onboarding study and figure out what we're changing.

Tyler: We ran 12 sessions. The biggest drop-off point is step 3 — connecting the first integration. 8 out of 12 users either abandoned or needed help. The instructions assume you have admin access, but most users doing onboarding are not admins.

Morgan: That's a real problem. What's the fix?

Tyler: Two things. One, we add an explicit check at that step — if the user doesn't have admin access, we show them a flow to invite their admin via email with a magic link. Two, we rewrite the copy to explain why admin access is needed.

Sam: The magic link idea is good but that's at least two sprints of work. Can we do a short-term fix?

Tyler: Short-term we can just surface a 'get help from your admin' tooltip with a pre-written email template they can copy. That's a one-day frontend change.

Morgan: Let's do both. Sam, can you scope the magic link flow for the sprint after next?

Sam: Yes, I'll have a spec ready by next Wednesday.

Morgan: Tyler, can you write the tooltip copy and updated step 3 instructions by end of this week?

Tyler: Done by Friday.

Morgan: We also saw confusion around pricing during onboarding — 5 users asked when they'd be charged. We should add a one-line reassurance at the start: 'Free for 14 days, no credit card required.' Casey, can you add that to the hero text?

Casey: Already have a mockup, I'll share it in Figma today.

Morgan: Perfect. Let's retest with 5 users after the tooltip change goes live. I'll schedule that for two weeks out.`,
]

function getRandomDemoTranscript() {
  return DEMO_TRANSCRIPTS[Math.floor(Math.random() * DEMO_TRANSCRIPTS.length)]
}

// ROYGBIV — white = transcript/orchestrator input, then splits into 7 agent colors
const AGENTS_META = [
  { id: 'summarizer',         label: 'Summarizer',    icon: '📝', grad: 'from-red-500 to-red-400',         desc: 'Condenses the entire meeting into a clear summary of key topics and outcomes.' },
  { id: 'action_items',       label: 'Action Items',  icon: '✅', grad: 'from-orange-500 to-amber-400',    desc: 'Extracts every task, assigns owners, and flags due dates so nothing falls through the cracks.' },
  { id: 'decisions',          label: 'Decisions',     icon: '⚖️', grad: 'from-yellow-400 to-yellow-300',   desc: 'Logs every decision made in the meeting, ranked by importance, with the accountable owner.' },
  { id: 'sentiment',          label: 'Sentiment',     icon: '💬', grad: 'from-emerald-500 to-green-400',   desc: 'Reads the emotional tone — per speaker, mood arc, and moments where tension spiked.' },
  { id: 'email_drafter',      label: 'Email Draft',   icon: '✉️', grad: 'from-blue-500 to-blue-400',       desc: 'Writes a polished follow-up email ready to send to all attendees.' },
  { id: 'calendar_suggester', label: 'Calendar',      icon: '📅', grad: 'from-indigo-500 to-indigo-400',   desc: 'Detects if a follow-up meeting is needed and suggests the best timeframe.' },
  { id: 'health_score',       label: 'Health Score',  icon: '📊', grad: 'from-violet-500 to-purple-400',   desc: 'Scores the meeting out of 100 across clarity, engagement, and action-orientation.' },
  { id: 'speaker_coach',      label: 'Speaker Coach', icon: '🎤', grad: 'from-rose-500 to-pink-400',         desc: 'Shows each speaker\'s talk share, decisions and actions owned, and a one-line coaching note.' },
]

const INPUT_MODE_META = {
  paste: {
    label: 'Paste Transcript',
    eyebrow: 'Transcript workspace',
    description: 'Best for pasted notes, copied transcripts, and quick edits before analysis.',
    accent: 'rgba(56,189,248,0.16)',
    border: 'rgba(56,189,248,0.24)',
    text: '#7dd3fc',
  },
  record: {
    label: 'Record Audio',
    eyebrow: 'Live capture',
    description: 'Use your microphone to turn a live conversation into a transcript draft in real time.',
    accent: 'rgba(16,185,129,0.14)',
    border: 'rgba(16,185,129,0.22)',
    text: '#6ee7b7',
  },
  upload: {
    label: 'Upload Audio',
    eyebrow: 'File transcription',
    description: 'Drop in recorded audio and let PrismAI transcribe it before the agent pipeline runs.',
    accent: 'rgba(168,85,247,0.14)',
    border: 'rgba(168,85,247,0.22)',
    text: '#d8b4fe',
  },
  join: {
    label: 'Join Meeting',
    eyebrow: 'Live meeting bot',
    description: 'PrismAI joins the call, captures the conversation, and returns with structured outputs.',
    accent: 'rgba(249,115,22,0.14)',
    border: 'rgba(249,115,22,0.22)',
    text: '#fdba74',
  },
}

const DEFAULT_RESULT = {
  summary: '',
  action_items: [],
  decisions: [],
  sentiment: { overall: 'neutral', score: 50, arc: 'stable', notes: '', speakers: [], tension_moments: [] },
  follow_up_email: { subject: '', body: '' },
  calendar_suggestion: { recommended: false, reason: '', suggested_timeframe: '', resolved_date: '', resolved_day: '' },
  health_score: { score: 0, verdict: '', badges: [], breakdown: { clarity: 0, action_orientation: 0, engagement: 0 } },
  speaker_coach: { speakers: [], balance_score: 100 },
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
  background: 'linear-gradient(180deg, rgba(3,7,18,0.15) 0%, rgba(3,7,18,0.42) 100%)',
}

const PANEL_STYLE = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.045) 0%, rgba(255,255,255,0.02) 100%)',
  borderRight: '1px solid rgba(125,211,252,0.1)',
  backdropFilter: 'blur(22px)',
}

const CARD_STYLE = {
  background: 'linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.025) 100%)',
  border: '1px solid rgba(125,211,252,0.1)',
  boxShadow: '0 22px 60px rgba(2,132,199,0.08)',
}

function getTranscriptStats(text = '') {
  const words = text.trim() ? text.trim().split(/\s+/).filter(Boolean).length : 0
  const lines = text.trim() ? text.trim().split('\n').filter(Boolean).length : 0
  return { words, lines }
}

function countNamedSpeakers(text = '') {
  const matches = text.match(/^([A-Z][a-zA-Z\s]{1,30}?):/gm) || []
  return [...new Set(matches.map((m) => m.replace(/:$/, '').trim()))].length
}

function hasMeaningfulResult(result) {
  if (!result || typeof result !== 'object') return false
  if (typeof result.summary === 'string' && result.summary.trim()) return true
  if (Array.isArray(result.action_items) && result.action_items.length > 0) return true
  if (Array.isArray(result.decisions) && result.decisions.length > 0) return true
  if (result.health_score?.verdict) return true
  if ((result.health_score?.score ?? 0) > 0) return true
  if (result.sentiment?.notes) return true
  if (result.follow_up_email?.subject || result.follow_up_email?.body) return true
  if (result.calendar_suggestion?.recommended || result.calendar_suggestion?.reason) return true
  return false
}

function formatRelativeMeetingDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const diffMs = now - date
  const diffHours = Math.round(diffMs / (1000 * 60 * 60))
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24))

  if (Math.abs(diffHours) < 24) {
    return diffHours <= 0 ? 'Just now' : `${diffHours}h ago`
  }

  if (Math.abs(diffDays) < 7) {
    return diffDays <= 0 ? 'Today' : `${diffDays}d ago`
  }

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatMinutesUntil(start, end) {
  if (!start) return ''
  const now = new Date()
  const startDate = new Date(start)
  if (Number.isNaN(startDate.getTime())) return ''
  const mins = Math.round((startDate - now) / 60000)
  // Meeting has started
  if (mins <= 0) {
    if (end) {
      const endDate = new Date(end)
      const minsLeft = Math.round((endDate - now) / 60000)
      if (minsLeft <= 0) return 'ended'
      return `in progress · ${minsLeft}m left`
    }
    return 'in progress'
  }
  if (mins < 60) return `in ${mins}m`
  const hours = Math.floor(mins / 60)
  const rem = mins % 60
  return rem ? `in ${hours}h ${rem}m` : `in ${hours}h`
}

function PrismStoryPanel({ transcript, result, loading, analysisTime }) {
  const stats = getTranscriptStats(transcript)
  const speakers = countNamedSpeakers(transcript)
  const score = result?.health_score?.score
  const decisionCount = result?.decisions?.length || 0
  const actionCount = result?.action_items?.length || 0
  const ranAgents = result?.agents_run?.length || 0

  return (
    <div className="rounded-[28px] overflow-hidden animate-fade-in-up"
      style={{
        background: 'linear-gradient(135deg, rgba(8,15,33,0.92) 0%, rgba(10,25,38,0.78) 55%, rgba(20,19,48,0.82) 100%)',
        border: '1px solid rgba(125,211,252,0.14)',
        boxShadow: '0 28px 80px rgba(2,132,199,0.14)',
      }}>
      <div className="h-[2px] w-full prism-spectrum-bar" />
      <div className="p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] font-semibold text-cyan-200 mb-3"
              style={{ background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.18)' }}>
              <span className={`w-2 h-2 rounded-full ${loading ? 'bg-cyan-400 animate-pulse' : 'bg-emerald-400'}`} />
              {loading ? 'Prism is splitting your meeting into structured intelligence' : 'Structured intelligence extracted from the transcript'}
            </div>

            <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight leading-tight">
              {loading ? 'Raw conversation is becoming a complete operational picture.' : 'Your meeting is no longer just notes. It is a system of record.'}
            </h2>

            <p className="text-sm text-slate-300/85 leading-relaxed mt-2 max-w-xl">
              {loading
                ? 'The orchestrator is routing the transcript to specialized agents for clarity, decisions, ownership, follow-up, and meeting quality.'
                : 'PrismAI turned the transcript into accountable outputs you can review, share, and act on. AI-generated fields should be verified before sending externally.'}
            </p>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 lg:w-[360px]">
            {[
              { label: 'Words', value: stats.words || '0' },
              { label: 'Speakers', value: speakers || '1' },
              { label: loading ? 'Agents' : 'Agents Ran', value: ranAgents || (loading ? '7' : '0') },
              { label: loading ? 'Status' : 'Health', value: loading ? 'Live' : (score ?? '—') },
            ].map((item) => (
              <div key={item.label} className="rounded-2xl px-3 py-3"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{item.label}</p>
                <p className="text-lg font-semibold text-white mt-1">{item.value}</p>
              </div>
            ))}
          </div>
        </div>

        {!loading && result && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mt-4">
            <div className="rounded-2xl px-4 py-3" style={{ background: 'rgba(16,185,129,0.07)', border: '1px solid rgba(16,185,129,0.18)' }}>
              <p className="text-[10px] uppercase tracking-[0.18em] text-emerald-300/70">Actionable</p>
              <p className="text-sm text-white mt-1">{actionCount} action item{actionCount !== 1 ? 's' : ''} with tracked ownership and completion state.</p>
            </div>
            <div className="rounded-2xl px-4 py-3" style={{ background: 'rgba(56,189,248,0.07)', border: '1px solid rgba(56,189,248,0.18)' }}>
              <p className="text-[10px] uppercase tracking-[0.18em] text-sky-300/70">Decisions</p>
              <p className="text-sm text-white mt-1">{decisionCount} decision{decisionCount !== 1 ? 's' : ''} surfaced from the transcript and ranked by importance.</p>
            </div>
            <div className="rounded-2xl px-4 py-3" style={{ background: 'rgba(168,85,247,0.07)', border: '1px solid rgba(168,85,247,0.18)' }}>
              <p className="text-[10px] uppercase tracking-[0.18em] text-violet-300/70">Reviewable</p>
              <p className="text-sm text-white mt-1">{analysisTime ? `Generated in ${analysisTime}s.` : 'Generated live.'} Use this as a high-trust draft, then verify sensitive details.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PrismSignatureScene({ transcript, result, loading }) {
  const stats = getTranscriptStats(transcript)
  const speakerCount = countNamedSpeakers(transcript)
  const outputs = [
    { label: 'Summary', value: result?.summary ? 'Ready' : loading ? 'Streaming' : 'Pending', color: '#f87171' },
    { label: 'Actions', value: result?.action_items?.length ? `${result.action_items.length}` : loading ? '...' : '0', color: '#fb923c' },
    { label: 'Decisions', value: result?.decisions?.length ? `${result.decisions.length}` : loading ? '...' : '0', color: '#facc15' },
    { label: 'Health', value: result?.health_score?.score ?? (loading ? '...' : '—'), color: '#a78bfa' },
  ]

  return (
    <div className="rounded-[30px] overflow-hidden animate-fade-in-up"
      style={{
        background: 'linear-gradient(135deg, rgba(8,10,24,0.92) 0%, rgba(5,18,34,0.86) 45%, rgba(24,16,44,0.82) 100%)',
        border: '1px solid rgba(125,211,252,0.14)',
        boxShadow: '0 30px 90px rgba(2,132,199,0.12)',
      }}>
      <div className="h-[2px] w-full prism-spectrum-bar" />
      <div className="px-5 py-5 sm:px-6 sm:py-6">
        <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_80px_1.3fr] gap-4 items-center">
          <div className="rounded-[24px] p-4 prism-scene-panel">
            <div className="flex items-center justify-between gap-3 mb-3">
              <div>
                <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Input</p>
                <h3 className="text-sm font-semibold text-white mt-1">Meeting transcript</h3>
              </div>
              <span className="text-[11px] px-2.5 py-1 rounded-full border border-white/10 bg-white/5 text-slate-400">
                {speakerCount} speaker{speakerCount !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="rounded-2xl px-3.5 py-3.5 border border-white/8 bg-black/20 max-h-36 overflow-y-auto">
              <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
                {transcript?.trim()
                  ? transcript.trim()
                  : 'Paste, upload, record, or capture a live meeting to begin.'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-slate-400">{stats.words} words</span>
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-slate-400">{stats.lines} lines</span>
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-slate-400">{loading ? 'Live analysis' : 'Stored intelligence'}</span>
            </div>
          </div>

          <div className="hidden lg:flex items-center justify-center h-full relative">
            <div className={`prism-beam-shell ${loading ? 'is-active' : 'is-resting'}`}>
              <div className="prism-beam-core" />
              <div className="prism-beam-spectrum" />
            </div>
          </div>

          <div className="rounded-[24px] p-4 prism-scene-panel relative overflow-hidden">
            <div className="absolute inset-0 pointer-events-none opacity-80">
              <div className={`prism-output-glow ${loading ? 'is-active' : ''}`} />
            </div>
            <div className="relative">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div>
                  <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Prism Output</p>
                  <h3 className="text-sm font-semibold text-white mt-1">Structured meeting intelligence</h3>
                </div>
                <span className={`text-[11px] px-2.5 py-1 rounded-full border ${
                  loading
                    ? 'border-cyan-400/25 bg-cyan-400/10 text-cyan-200'
                    : 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200'
                }`}>
                  {loading ? 'Transforming' : 'Ready to use'}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2.5">
                {outputs.map((item, i) => (
                  <div
                    key={item.label}
                    className="rounded-2xl px-3.5 py-3 border border-white/8 bg-white/[0.03] animate-fade-in-up"
                    style={{ animationDelay: `${i * 0.05}s` }}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: item.color, boxShadow: `0 0 12px ${item.color}` }} />
                      <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">{item.label}</p>
                    </div>
                    <p className="text-base font-semibold text-white">{item.value}</p>
                  </div>
                ))}
              </div>

              <div className="mt-3 rounded-2xl px-3.5 py-3 border border-white/8 bg-black/20">
                <p className="text-xs text-slate-300 leading-relaxed">
                  {loading
                    ? 'The prism is extracting operational clarity from conversational ambiguity in real time.'
                    : 'This layer is built for daily use: review, share, export, and act without digging back through the transcript.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
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
    md += `## Calendar\n\n${result.calendar_suggestion.reason}`
    if (result.calendar_suggestion.suggested_timeframe) md += ` — ${result.calendar_suggestion.suggested_timeframe}`
    if (result.calendar_suggestion.resolved_day || result.calendar_suggestion.resolved_date) {
      md += ` (${[result.calendar_suggestion.resolved_day, result.calendar_suggestion.resolved_date].filter(Boolean).join(', ')})`
    }
    md += `\n`
  }
  return md
}

function buildPrintHTML(result) {
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  const h = result.health_score
  let body = `<h1>Meeting Summary — ${date}</h1>`
  if (h?.score) {
    body += `<h2>Meeting Health: ${h.score}/100 — ${h.verdict}</h2>`
    if (h.badges?.length) body += `<p>${h.badges.map(b => `<code>${b}</code>`).join(' ')}</p>`
    if (h.breakdown) body += `<ul><li>Clarity: ${h.breakdown.clarity}/100</li><li>Action Orientation: ${h.breakdown.action_orientation}/100</li><li>Engagement: ${h.breakdown.engagement}/100</li></ul>`
  }
  if (result.summary) body += `<h2>Summary</h2><p>${result.summary}</p>`
  if (result.action_items?.length) {
    body += `<h2>Action Items</h2><ul>`
    result.action_items.forEach(i => {
      body += `<li>${i.task}${i.owner && i.owner !== 'Unassigned' ? ` <em>(${i.owner})</em>` : ''}${i.due && i.due !== 'TBD' ? ` — due ${i.due}` : ''}</li>`
    })
    body += `</ul>`
  }
  if (result.decisions?.length) {
    body += `<h2>Decisions</h2><ul>`
    result.decisions.forEach(d => {
      const imp = d.importance === 1 ? 'Critical' : d.importance === 2 ? 'Significant' : 'Minor'
      body += `<li><strong>${d.decision}</strong>${d.owner && d.owner !== 'Team' ? ` <em>(${d.owner})</em>` : ''} — ${imp}</li>`
    })
    body += `</ul>`
  }
  if (result.sentiment?.overall) {
    body += `<h2>Sentiment: ${result.sentiment.overall} (${result.sentiment.score ?? 50}/100)</h2>`
    if (result.sentiment.notes) body += `<p>${result.sentiment.notes}</p>`
  }
  if (result.follow_up_email?.subject) {
    body += `<h2>Follow-up Email</h2><p><strong>Subject:</strong> ${result.follow_up_email.subject}</p><p style="white-space:pre-wrap">${result.follow_up_email.body}</p>`
  }
  if (result.calendar_suggestion?.recommended) {
    const resolvedCalendar = [result.calendar_suggestion.resolved_day, result.calendar_suggestion.resolved_date].filter(Boolean).join(', ')
    body += `<h2>Calendar</h2><p>${result.calendar_suggestion.reason}${result.calendar_suggestion.suggested_timeframe ? ` — ${result.calendar_suggestion.suggested_timeframe}` : ''}${resolvedCalendar ? ` (${resolvedCalendar})` : ''}</p>`
  }
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Meeting Summary — ${date}</title><style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;margin:40px auto;color:#111;line-height:1.6}
    h1{font-size:1.5rem;margin-bottom:.5rem}
    h2{font-size:1.1rem;margin-top:1.5rem;margin-bottom:.5rem;border-bottom:1px solid #eee;padding-bottom:.25rem}
    ul{padding-left:1.25rem}li{margin-bottom:.25rem}
    code{background:#f0f0f0;padding:2px 6px;border-radius:3px;font-size:.85em}
    p{margin:.5rem 0}
  </style></head><body>${body}</body></html>`
}

// ── Prism background ─────────────────────────────────────────────
// ── Agent pipeline loader ────────────────────────────────────────
function AgentPipelineLoader() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 py-16 px-8 rounded-[28px] prism-loader-shell">
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
          Refracting the meeting into 7 live intelligence streams
        </div>
        <div className="w-px h-8" style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.15), transparent)' }}></div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 animate-fade-in-up card-delay-2">
        {AGENTS_META.map((a, i) => (
          <div key={a.id} className="flex flex-col items-center gap-2 px-4 py-3 rounded-2xl animate-pulse"
            style={{ animationDelay: `${i * 0.18}s`, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div className={`w-8 h-8 rounded-xl bg-gradient-to-br ${a.grad} flex items-center justify-center text-sm shadow-lg`}>{a.icon}</div>
            <span className="text-[11px] text-gray-400 font-medium text-center leading-tight">{a.label}</span>
            <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" style={{ animationDelay: `${i * 0.2}s` }}></div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 w-full max-w-3xl animate-fade-in-up card-delay-3">
        {[
          'Capturing decisions, ownership, and follow-up',
          'Scoring meeting quality and emotional temperature',
          'Streaming structured cards as soon as each agent finishes',
        ].map((line) => (
          <div key={line} className="rounded-2xl px-4 py-3 text-[11px] text-gray-400 text-center"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            {line}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Empty state for right panel ──────────────────────────────────
function EmptyState({ onDemo, isDemoMode, onUseOwnTranscript, inputModeLabel }) {
  const [active, setActive] = useState(null)
  const gridRef = useRef(null)

  useEffect(() => {
    if (!active) return
    const handler = (e) => { if (!gridRef.current?.contains(e.target)) setActive(null) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [active])

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 px-8 py-10">
      <div className="w-full max-w-4xl rounded-[30px] overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, rgba(8,15,33,0.9) 0%, rgba(9,23,36,0.78) 52%, rgba(22,16,42,0.82) 100%)',
          border: '1px solid rgba(125,211,252,0.14)',
          boxShadow: '0 30px 90px rgba(2,132,199,0.12)',
        }}>
        <div className="h-[2px] w-full prism-spectrum-bar" />
        <div className="grid lg:grid-cols-[1.2fr_0.8fr] gap-4 px-6 py-5">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] font-semibold text-cyan-200 mb-3"
              style={{ background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.18)' }}>
              <span className={`w-2 h-2 rounded-full ${isDemoMode ? 'bg-emerald-400' : 'bg-cyan-400 animate-pulse'}`} />
              {isDemoMode ? 'Demo workspace active' : `${inputModeLabel || 'Transcript'} workspace ready`}
            </div>
            <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight leading-tight">
              {isDemoMode ? 'You are looking at a polished sample run.' : 'The workspace is ready for a real meeting.'}
            </h2>
            <p className="text-sm text-slate-300/85 leading-relaxed mt-2 max-w-xl">
              {isDemoMode
                ? 'Use the sample to understand how PrismAI thinks, then switch into your own transcript workspace when you want to run a real meeting.'
                : 'Paste a transcript, record live audio, upload a file, or send the meeting bot in. The right side becomes a live intelligence briefing once analysis starts.'}
            </p>
            <div className="flex flex-wrap gap-3 mt-4">
              <button onClick={onDemo}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold text-sky-300 transition-all hover:text-sky-200 hover:scale-[1.02]"
                style={{ background: 'rgba(14,165,233,0.09)', border: '1px solid rgba(14,165,233,0.2)' }}>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                See it in action
              </button>
              {isDemoMode && onUseOwnTranscript && (
                <button onClick={onUseOwnTranscript}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-medium text-gray-200 transition-all hover:text-white hover:scale-[1.02]"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                  Use my own transcript
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Input modes', value: '4', note: 'Paste, record, upload, or join live' },
              { label: 'Agent outputs', value: '7', note: 'Structured cards stream back live' },
              { label: 'Workflow', value: isDemoMode ? 'Sample' : 'Ready', note: isDemoMode ? 'Swap to your own transcript any time' : 'Analyze as soon as your draft is ready' },
              { label: 'Trust model', value: 'Review', note: 'Verify owners, decisions, and send-ready drafts' },
            ].map((item) => (
              <div key={item.label} className="rounded-2xl px-4 py-3"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{item.label}</p>
                <p className="text-lg font-semibold text-white mt-1">{item.value}</p>
                <p className="text-[11px] text-slate-400 mt-1.5 leading-relaxed">{item.note}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div ref={gridRef} className="grid grid-cols-2 sm:grid-cols-4 gap-3 w-full max-w-2xl">
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

// ── Pre-Meeting Brief ────────────────────────────────────────────
function PreMeetingBrief({ brief }) {
  const [expanded, setExpanded] = useState(false)
  if (!brief) return null
  const totalCount = (brief.open_items?.length || 0) + (brief.recent_decisions?.length || 0) + (brief.blockers?.length || 0)
  if (totalCount === 0) return null
  return (
    <div className="rounded-2xl overflow-hidden cursor-pointer"
      style={{ background: 'rgba(14,165,233,0.06)', border: '1px solid rgba(14,165,233,0.2)' }}
      onClick={() => setExpanded(e => !e)}>
      <div className="px-4 py-3 flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        <span className="text-xs font-semibold text-sky-300">Pre-Meeting Brief</span>
        <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded-full text-sky-200" style={{ background: 'rgba(14,165,233,0.15)' }}>
          {totalCount} item{totalCount !== 1 ? 's' : ''}
        </span>
        <svg className={`w-3 h-3 text-sky-500 ml-auto transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      {expanded && (
        <div className="px-4 pb-4 space-y-3" style={{ borderTop: '1px solid rgba(14,165,233,0.12)' }}>
          {brief.open_items?.length > 0 && (
            <div className="pt-3">
              <p className="text-[10px] font-semibold text-orange-400 mb-1.5">○ Open Action Items</p>
              {brief.open_items.map((item, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-orange-500 text-[10px] mt-0.5 flex-shrink-0">○</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{item.task}</p>
                    {(item.owner || item.due || item.meeting_date) && (
                      <p className="text-[10px] text-gray-600">{[item.owner, item.due, item.meeting_date].filter(Boolean).join(' · ')}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {brief.recent_decisions?.length > 0 && (
            <div className={brief.open_items?.length > 0 ? '' : 'pt-3'}>
              <p className="text-[10px] font-semibold text-yellow-400 mb-1.5">⚖ Recent Decisions</p>
              {brief.recent_decisions.map((d, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-yellow-500 text-[10px] mt-0.5 flex-shrink-0">⚖</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{d.decision}</p>
                    {(d.owner || d.meeting_date) && (
                      <p className="text-[10px] text-gray-600">{[d.owner, d.meeting_date].filter(Boolean).join(' · ')}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {brief.blockers?.length > 0 && (
            <div className={(!brief.open_items?.length && !brief.recent_decisions?.length) ? 'pt-3' : ''}>
              <p className="text-[10px] font-semibold text-red-400 mb-1.5">⚠ Recurring Blockers</p>
              {brief.blockers.map((b, i) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <span className="text-red-500 text-[10px] mt-0.5 flex-shrink-0">⚠</span>
                  <div>
                    <p className="text-[11px] text-gray-300">{b.snippet}</p>
                    {b.meeting_date && <p className="text-[10px] text-gray-600">{b.meeting_date}</p>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Live Meeting View ────────────────────────────────────────────
function LiveMeetingView({ token }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [session, setSession] = useState(null)
  const [saveState, setSaveState] = useState('idle')
  const intervalRef = useRef(null)

  useEffect(() => {
    supabase?.auth.getSession().then(({ data: s }) => setSession(s?.session ?? null))
  }, [])

  const handleSave = async () => {
    if (saveState !== 'idle') return
    setSaveState('saving')
    const result = data?.result || {}
    try {
      await apiFetch('/meetings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: Date.now(),
          date: new Date().toISOString().slice(0, 10),
          title: result.summary?.slice(0, 80).split('.')[0] || 'Meeting',
          score: result.health_score?.score || null,
          transcript: data?.transcript || '',
          result,
          share_token: '',
        }),
      })
      setSaveState('saved')
    } catch {
      setSaveState('error')
    }
  }

  const poll = useCallback(async () => {
    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/live/${token}`)
      if (res.status === 404) { setError('Live session not found or has expired.'); clearInterval(intervalRef.current); return }
      if (!res.ok) return
      const json = await res.json()
      setData(json)
      if (['done', 'error'].includes(json.status)) clearInterval(intervalRef.current)
    } catch { /* network blip — keep polling */ }
  }, [token])

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, 3000)
    return () => clearInterval(intervalRef.current)
  }, [poll])

  const appUrl = window.location.origin + window.location.pathname
  const status = data?.status
  const commands = data?.commands || []
  const lines = data?.transcript_lines || []
  const result = data?.result || {}

  if (error) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#07040f' }}>
      <p className="text-sm text-gray-500">{error}</p>
    </div>
  )

  if (!data) return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#07040f' }}>
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 rounded-xl flex items-center justify-center animate-pulse" style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
        </div>
        <p className="text-xs text-gray-500">Connecting to live meeting…</p>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen" style={{ background: '#07040f' }}>
      {/* Header */}
      <div className="sticky top-0 z-10 px-4 py-3 flex items-center justify-between"
        style={{ background: 'rgba(7,4,15,0.92)', borderBottom: '1px solid rgba(255,255,255,0.07)', backdropFilter: 'blur(16px)' }}>
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 16px rgba(2,132,199,0.4)' }}>
            <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
          </div>
          <span className="text-sm font-bold gradient-text">PrismAI</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full flex items-center gap-1"
            style={{ background: status === 'recording' ? 'rgba(239,68,68,0.1)' : 'rgba(255,255,255,0.05)', border: `1px solid ${status === 'recording' ? 'rgba(239,68,68,0.3)' : 'rgba(255,255,255,0.08)'}`, color: status === 'recording' ? '#fca5a5' : '#6b7280' }}>
            {status === 'recording' && <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />}
            {status === 'joining' && 'Joining…'}
            {status === 'recording' && 'Live'}
            {status === 'processing' && 'Analyzing…'}
            {status === 'done' && 'Meeting ended'}
            {status === 'error' && 'Error'}
          </span>
        </div>
        <a href={appUrl} className="text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:scale-105"
          style={{ background: 'linear-gradient(135deg, rgba(2,132,199,0.2), rgba(13,148,136,0.15))', border: '1px solid rgba(14,165,233,0.3)', color: '#7dd3fc' }}>
          Analyze your own →
        </a>
      </div>

      <div className="px-4 py-6 max-w-2xl mx-auto space-y-4">
        {status !== 'done' && <PreMeetingBrief brief={data?.brief} />}
        {/* Prism commands log */}
        {commands.length > 0 && (
          <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <svg className="w-3.5 h-3.5 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
              <span className="text-xs font-semibold text-violet-300">Prism Commands</span>
              <span className="ml-auto text-[10px] text-gray-600">{commands.length}</span>
            </div>
            <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
              {commands.map((cmd, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="flex items-start gap-2">
                    <svg className="w-3 h-3 text-emerald-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs text-gray-200">"{cmd.command}"</p>
                      {cmd.speaker && <p className="text-[10px] text-gray-600 mt-0.5">{cmd.speaker}{cmd.tools?.length ? ` · ${cmd.tools.join(', ')}` : ''}</p>}
                      {cmd.reply && <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">{cmd.reply}</p>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Live transcript */}
        {lines.length > 0 && status !== 'done' && (
          <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className="px-4 py-2.5 flex items-center gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-xs font-semibold text-gray-400">Live Transcript</span>
            </div>
            <div className="px-4 py-3 max-h-64 overflow-y-auto space-y-1">
              {lines.slice(-30).map((line, i) => (
                <p key={i} className="text-[11px] text-gray-400 leading-relaxed">{line}</p>
              ))}
            </div>
          </div>
        )}

        {/* Full results when done */}
        {status === 'done' && result && (
          <>
            {result.agents_run?.length > 0 && <AgentTags agents={result.agents_run} />}
            <HealthScoreCard healthScore={result.health_score} />
            <SummaryCard summary={result.summary} />
            <ActionItemsCard actionItems={result.action_items} readOnly />
            <DecisionsCard decisions={result.decisions} />
            {result.sentiment && <SentimentCard sentiment={result.sentiment} />}
            <EmailCard email={result.follow_up_email} readOnly />
            <CalendarCard calendar={result.calendar_suggestion} />
            <SpeakerCoachCard speakerCoach={result.speaker_coach} />
            {session && (
              <button
                onClick={handleSave}
                disabled={saveState !== 'idle'}
                className="w-full py-2.5 rounded-xl text-sm font-semibold transition-all hover:scale-[1.02] disabled:opacity-60 disabled:cursor-not-allowed"
                style={{ background: 'linear-gradient(135deg, rgba(2,132,199,0.25), rgba(13,148,136,0.2))', border: '1px solid rgba(14,165,233,0.35)', color: '#7dd3fc' }}>
                {saveState === 'idle' && 'Save to my history'}
                {saveState === 'saving' && 'Saving…'}
                {saveState === 'saved' && '✓ Saved'}
                {saveState === 'error' && 'Save failed — try again'}
              </button>
            )}
          </>
        )}

        {status === 'processing' && (
          <div className="flex items-center gap-3 px-4 py-4 rounded-2xl" style={{ background: 'rgba(14,165,233,0.06)', border: '1px solid rgba(14,165,233,0.15)' }}>
            <svg className="w-4 h-4 text-sky-400 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <p className="text-xs text-sky-300">Meeting ended — running analysis across 7 agents…</p>
          </div>
        )}

        {status === 'error' && data.error && (
          <div className="px-4 py-3 rounded-2xl" style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)' }}>
            <p className="text-xs text-red-400">{data.error}</p>
          </div>
        )}

        {!commands.length && !lines.length && ['joining', 'recording'].includes(status) && (
          <div className="text-center py-12">
            <div className="w-10 h-10 rounded-2xl mx-auto mb-3 flex items-center justify-center animate-pulse" style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.15)' }}>
              <svg className="w-5 h-5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
            </div>
            <p className="text-xs text-gray-600">Waiting for conversation…</p>
            <p className="text-[10px] text-gray-700 mt-1">Commands and transcript will appear here as the meeting progresses.</p>
          </div>
        )}
      </div>
    </div>
  )
}

// Detect share token synchronously so first render already knows we're in share mode
const INITIAL_SHARE_TOKEN = (() => {
  const match = window.location.hash.match(/^#share\/([a-f0-9]+)$/)
  return match ? match[1] : null
})()

// Detect live-share token synchronously
const INITIAL_LIVE_TOKEN = (() => {
  const match = window.location.hash.match(/^#live\/([a-f0-9]+)$/)
  return match ? match[1] : null
})()

const HERO_SENTENCES = [
  "Your cleanup always outlasts the meeting itself.",
  "Everyone left the call with different action items.",
  "Nobody owns that decision from Tuesday anymore.",
  "Back-to-backs all day. Notes happen at midnight.",
  "Twelve open tabs, zero decisions documented.",
  "The follow-up never made it out of your drafts.",
]

// ── Landing / Hero screen ────────────────────────────────────────
function LandingScreen({ onDemo, onSkip, onViewDashboard, exiting }) {
  const [signupOpen, setSignupOpen] = useState(false)
  const [signupMode, setSignupMode] = useState('signup')
  const [scrollCueVisible, setScrollCueVisible] = useState(true)
  const scrollContainerRef = useRef(null)
  const heroRef = useRef(null)

  const openSignup = () => {
    setSignupMode('signup')
    setSignupOpen(true)
  }

  const openLogin = () => {
    setSignupMode('login')
    setSignupOpen(true)
  }

  useEffect(() => {
    const container = scrollContainerRef.current
    const hero = heroRef.current
    if (!container || !hero) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        const r = entry.intersectionRatio
        setScrollCueVisible(r >= 0.7)
      },
      { threshold: [0, 0.1, 0.5, 0.7, 1], root: container }
    )
    obs.observe(hero)
    return () => obs.disconnect()
  }, [])

  return (
    <div
      className="landing-page-shell"
      style={{
        opacity: exiting ? 0 : 1,
        transform: exiting ? 'scale(0.97)' : 'scale(1)',
        transition: 'opacity 0.35s ease, transform 0.35s ease',
      }}
    >
      {/* Fixed prism — persists behind all sections */}
      <div className="landing-bg-prism" aria-hidden="true">
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -48%)', width: 'max(1080px, 100vw)', height: 'max(1080px, 100vh)' }}>
          <Prism
            height={2}
            baseWidth={3}
            animationType="rotate3d"
            glow={1.1}
            noise={0.1}
            transparent
            scale={2.9}
            hueShift={5.6}
            colorFrequency={1}
            hoverStrength={0}
            inertia={0.04}
            bloom={0.9}
            timeScale={0.3}
          />
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        className="landing-page"
      >
        {/* Sticky nav — sits above all sections while scrolling */}
        <div className="landing-nav-sticky">
          <LandingNav onSignup={openSignup} onLogin={openLogin} />
        </div>

        <section ref={heroRef} id="prism" className="landing-hero scroll-section">
        {/* SVG filter defs — hidden, used by .prism-logo-text hover */}
        <svg style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }} aria-hidden="true">
          <defs>
            <filter id="prism-text-noise" x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
              <feTurbulence type="fractalNoise" baseFrequency="0.72" numOctaves="4" seed="8" stitchTiles="stitch" result="noise"/>
              <feColorMatrix type="saturate" values="0" in="noise" result="grayNoise"/>
              <feComposite operator="in" in="grayNoise" in2="SourceGraphic" result="maskedNoise"/>
              <feBlend in="SourceGraphic" in2="maskedNoise" mode="overlay" result="blended"/>
              <feComponentTransfer in="blended">
                <feFuncA type="linear" slope="1"/>
              </feComponentTransfer>
            </filter>
          </defs>
        </svg>

        {/* Hero content */}
        <div className="relative z-10 flex flex-col items-center text-center px-6 pt-16 pb-20 gap-14 w-full" style={{ marginTop: '14vh' }}>
          {/* Rotating pain-point text */}
          <div className="w-full flex translate-y-[5vh] items-center justify-center animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
            <TextRotate
              texts={HERO_SENTENCES}
              rotationInterval={3600}
              staggerFrom="first"
              staggerDuration={0.012}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ type: 'spring', damping: 30, stiffness: 400 }}
              splitBy="words"
              mainClassName="min-h-[6.75rem] w-full max-w-[min(100%,84rem)] justify-center text-center text-[clamp(1.25rem,4.8vw,3.75rem)] font-medium leading-tight tracking-tight text-white/85 sm:min-h-[7.5rem] lg:min-h-[8.75rem]"
              splitLevelClassName="overflow-hidden pb-1"
              elementLevelClassName="font-medium"
              style={{ fontFamily: "'Rubik', 'General Sans', sans-serif", fontWeight: 500 }}
            />
          </div>

          {/* Tagline */}
          <div className="animate-fade-in-up mt-24" style={{ animationDelay: '0.45s' }}>
            <p
              className="text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-semibold tracking-tight text-white"
            >
              Let <span className="font-light">prism</span> handle it.
            </p>
          </div>

          {/* CTA buttons */}
          <div className="cta-row animate-fade-in-up" style={{ animationDelay: '0.65s', marginTop: '9rem' }}>
            <button type="button" className="btn-primary landing-button-primary" onClick={openSignup}>Get started</button>
            <span className="cta-or">or</span>
            <button type="button" className="btn-ghost landing-button-secondary" onClick={onDemo}>Try it out</button>
            <span className="cta-or">or</span>
            <button type="button" className="btn-ghost landing-button-secondary" onClick={onViewDashboard}>View dashboard</button>
          </div>
        </div>

        {/* Scroll cue */}
        <div className={`scroll-cue${scrollCueVisible ? '' : ' hidden'}`} aria-hidden="true">
          <span>see more below</span>
          <svg className="scroll-cue-chevron" width="14" height="10" viewBox="0 0 14 10" fill="none" aria-hidden="true">
            <polyline points="1,2 7,8 13,2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        </section>

        <div className="landing-post-hero">
          <HowItWorks />
          <AgentShowcase />
          <PricingSection onGetStarted={openSignup} />
          <TeamSection />
        </div>
        {signupOpen && (
          <SignupDialog
            mode={signupMode}
            onModeChange={setSignupMode}
            onClose={() => setSignupOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

// ── Google Calendar PKCE helpers ─────────────────────────────────
async function generateCodeVerifier() {
  const arr = new Uint8Array(32)
  crypto.getRandomValues(arr)
  return btoa(String.fromCharCode(...arr)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

async function generateCodeChallenge(verifier) {
  const data = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

// ── Main App ─────────────────────────────────────────────────────
export default function App() {
  const [authReady, setAuthReady] = useState(() => !supabase)
  const [authSession, setAuthSession] = useState(null)
  const [crossMeetingInsights, setCrossMeetingInsights] = useState(null)
  const [insightsCollapsed, setInsightsCollapsed] = useState(() => {
    try { return localStorage.getItem('prism_insights_collapsed') !== 'false' } catch { return true }
  })
  const [transcript, setTranscript] = useState('')
  const [transcriptDrafts, setTranscriptDrafts] = useState({ paste: '', record: '', upload: '' })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [analysisTime, setAnalysisTime] = useState(null) // seconds elapsed
  const [showTimeSaved, setShowTimeSaved] = useState(false)
  const [timeSavedShared, setTimeSavedShared] = useState(false)
  const analysisStartRef = useRef(null)
  const analysisAbortRef = useRef(null)
  const analysisRunIdRef = useRef(0)
  const [mobileTab, setMobileTab] = useState('input') // 'input' | 'results'
  const hasResultsView = loading || Boolean(result)
  const isMcpDashboard = typeof window !== 'undefined' && window.location.pathname === '/dashboard-mcp'

  // Show landing only to first-time visitors (not returning users, not share links)
  const [showLanding, setShowLanding] = useState(
    () => {
      if (typeof window !== 'undefined' && window.location.pathname === '/dashboard-mcp') return false
      if (INITIAL_SHARE_TOKEN) return false
      const persistedScreen = sessionStorage.getItem(UI_SCREEN_KEY)
      if (persistedScreen === 'landing') return true
      if (persistedScreen === 'app') return false
      return !sessionStorage.getItem(VISITED_KEY)
    }
  )
  const [landingExiting, setLandingExiting] = useState(false)
  const [isDemoMode, setIsDemoMode] = useState(false)
  const [demoChatOpen, setDemoChatOpen] = useState(false)

  const exitLanding = (demo = false) => {
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    setLandingExiting(true)
    setTimeout(() => {
      setShowLanding(false)
      if (demo) startDemo()
    }, 370)
  }

  const enterDashboardTestRun = () => {
    sessionStorage.setItem(TEST_RUN_SESSION_KEY, '1')
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    sessionStorage.removeItem('prism_active_bot_id')
    sessionStorage.removeItem('prism_active_live_token')
    sessionStorage.removeItem('prism_new_meeting')
    window.location.href = `/dashboard-mcp?${TEST_RUN_QUERY_PARAM}=1`
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
  const [inputTab, setInputTab] = useState('join') // 'paste' | 'join'
  const [meetingUrl, setMeetingUrl] = useState('')
  const [botStatus, setBotStatus] = useState(null) // joining | recording | processing | done | error
  const [botError, setBotError] = useState(null)
  const [activeBotId, setActiveBotId] = useState(() => sessionStorage.getItem('prism_active_bot_id') || null)
  const [activeLiveToken, setActiveLiveToken] = useState(() => sessionStorage.getItem('prism_active_live_token') || null)
  const [liveShareCopied, setLiveShareCopied] = useState(false)
  const [liveCommands, setLiveCommands] = useState([]) // commands executed during live meeting
  const pollRef = useRef(null)

  const [history, setHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [historySearch, setHistorySearch] = useState('')
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [mdCopied, setMdCopied] = useState(false)
  const [calendarConnected, setCalendarConnected] = useState(false)
  const [nextUpcomingMeeting, setNextUpcomingMeeting] = useState(null)
  const historySearchDebounceRef = useRef(null)
  const previousUserRef = useRef(null)
  const user = authSession?.user || null
  const isTestAccount = user?.id === 'test-account'

  useEffect(() => {
    if (INITIAL_SHARE_TOKEN || !authReady) return // skip auto-load for shared links
    const previousUser = previousUserRef.current
    previousUserRef.current = user

    if (!user) {
      setHistory([])
      setCrossMeetingInsights(null)
      setInitialMessages([])
      setMeetingId(null)
      setShareToken(null)
      setShowHistory(false)
      setShareCopied(false)
      return
    }

    if (isTestAccount) {
      setHistory([])
      setCrossMeetingInsights(null)
      setInitialMessages([])
      setMeetingId(null)
      setShareToken(null)
      setShowHistory(false)
      setShareCopied(false)
      return
    }

    const shouldPreserveLocalWorkspace =
      !previousUser &&
      !loading &&
      Boolean(transcript.trim()) &&
      hasMeaningfulResult(result) &&
      !meetingId &&
      !INITIAL_SHARE_TOKEN

    ;(async () => {
      if (shouldPreserveLocalWorkspace) {
        const preserved = saveToHistory(transcript, result)
        setInitialMessages([])
        setSessionId((s) => s + 1)
        setWorkspaceToast('Local workspace saved to your account.')
        setTimeout(() => setWorkspaceToast(null), 3500)
        const res = await apiFetch('/meetings').catch(() => null)
        const data = res?.ok ? await res.json() : []
        if (Array.isArray(data)) {
          setHistory(mergeHistoryEntries([preserved, ...data]))
        }
        return
      }

      apiFetch('/meetings')
      .then(r => (r.ok ? r.json() : []))
      .then(async data => {
        if (!Array.isArray(data)) return
        const validHistory = data.filter((entry) => hasMeaningfulResult(entry?.result))
        setHistory(validHistory)
      })
      .catch(() => {})
    })()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, user?.id, isTestAccount])

  useEffect(() => {
    if (!user || isTestAccount || history.length < 2) {
      setCrossMeetingInsights(null)
      return
    }

    apiFetch('/insights')
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data && typeof data === 'object') setCrossMeetingInsights(data)
      })
      .catch(() => {})
  }, [user?.id, isTestAccount, history])

  useEffect(() => {
    if (!user) { setCalendarConnected(false); return }
    if (isTestAccount) { setCalendarConnected(false); return }
    apiFetch('/calendar/status')
      .then(r => r.ok ? r.json() : { connected: false })
      .then(d => setCalendarConnected(Boolean(d.connected)))
      .catch(() => {})
  }, [user?.id, isTestAccount])


  // pendingAutoJoinUrl: set by polling effect, consumed by an effect after joinMeeting is defined
  const pendingAutoJoinRef = useRef(null)

  const [showSpeakerModal, setShowSpeakerModal] = useState(false)
  const [speakers, setSpeakers] = useState([])
  const [shareToken, setShareToken] = useState(null)
  const [shareMode, setShareMode] = useState(INITIAL_SHARE_TOKEN ? 'loading' : null)
  const [shareCopied, setShareCopied] = useState(false)

  // Integrations
  const [showIntegrations, setShowIntegrations] = useState(false)
  const [integrations, setIntegrations] = useState(() => ({
    slack_webhook: localStorage.getItem('prism_slack_webhook') || '',
    notion_token: localStorage.getItem('prism_notion_token') || '',
    notion_page_id: localStorage.getItem('prism_notion_page_id') || '',
    auto_send_slack: localStorage.getItem('prism_auto_send_slack') === '1',
    auto_send_notion: localStorage.getItem('prism_auto_send_notion') === '1',
  }))
  // Load tool settings from backend when signed in
  useEffect(() => {
    if (!user || isTestAccount) return
    apiFetch('/user-settings').then(async (res) => {
      if (!res.ok) return
      const data = await res.json()
      setIntegrations(prev => ({
        ...prev,
        linear_api_key: data.linear_api_key || '',
        slack_bot_token: data.slack_bot_token || '',
      }))
    }).catch(() => {})
  }, [user?.id, isTestAccount])

  const [exportingSlack, setExportingSlack] = useState(false)
  const [exportingNotion, setExportingNotion] = useState(false)
  const [integrationToast, setIntegrationToast] = useState(null) // { type: 'ok'|'err', msg }
  const [autoJoinSetting, setAutoJoinSetting] = useState(
    () => localStorage.getItem('prism_autojoin') || 'off'
  )
  const [autoJoinPrompt, setAutoJoinPrompt] = useState(null) // { title, url, minsUntil }
  const autoJoinFiredRef = useRef(new Set()) // event IDs already acted on this session
  const savedMeetingRef = useRef(null) // tracks ID of the meeting already saved for the current workspace
  const [workspaceToast, setWorkspaceToast] = useState(null)
  const [botTranscriptReady, setBotTranscriptReady] = useState(false)
  const transcriptStats = getTranscriptStats(transcript)
  const transcriptSpeakerCount = countNamedSpeakers(transcript)
  const inputModeMeta = INPUT_MODE_META[inputTab] || INPUT_MODE_META.paste
  const recentMeetings = user ? history.slice(0, 3) : []

  useEffect(() => {
    if (!supabase) {
      if (isTestRunSession()) {
        setAuthSession(TEST_AUTH_SESSION)
      }
      setAuthReady(true)
      return
    }

    supabase.auth.getSession().then(({ data }) => {
      if (data.session) {
        sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
        setAuthSession(data.session)
      } else if (isTestRunSession()) {
        setAuthSession(TEST_AUTH_SESSION)
      } else {
        setAuthSession(null)
      }
      setAuthReady(true)
    })

    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
      setAuthSession(session || (isTestRunSession() ? TEST_AUTH_SESSION : null))
      setAuthReady(true)
    })

    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!authReady || INITIAL_SHARE_TOKEN || isMcpDashboard) return
    if (user && !isTestAccount) {
      sessionStorage.setItem(VISITED_KEY, '1')
      sessionStorage.setItem(UI_SCREEN_KEY, 'app')
      window.location.replace('/dashboard-mcp')
    }
  }, [authReady, user?.id, isTestAccount, isMcpDashboard])

  useEffect(() => {
    if (!authReady || !isMcpDashboard || !isTestAccount) return
    if (new URLSearchParams(window.location.search).get(TEST_RUN_QUERY_PARAM) === '1') {
      window.history.replaceState({}, '', '/dashboard-mcp')
    }
    setWorkspaceToast('Test account loaded.')
    const timeoutId = setTimeout(() => setWorkspaceToast(null), 2500)
    return () => clearTimeout(timeoutId)
  }, [authReady, isMcpDashboard, isTestAccount])

  // Detect Google Calendar OAuth callback (?code=...&state=calendar_connect)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const state = params.get('state')
    if (!code || state !== 'calendar_connect') return

    const verifier = sessionStorage.getItem('cal_pkce_verifier')
    sessionStorage.removeItem('cal_pkce_verifier')
    // Clean URL before doing anything else
    window.history.replaceState({}, '', window.location.pathname)

    if (!verifier) {
      console.warn('[calendar] No PKCE verifier found for calendar callback')
      return
    }

    apiFetch('/calendar/exchange-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code,
        code_verifier: verifier,
        redirect_uri: window.location.origin,
      }),
    }).then(res => {
      if (res.ok) setCalendarConnected(true)
      else console.warn('[calendar] exchange-code failed:', res.status)
    }).catch(err => console.warn('[calendar] exchange-code error:', err))
  }, [])

  const signInWithGoogle = async () => {
    if (!supabase) {
      setError('Supabase auth is not configured yet.')
      return
    }
    const { error: authError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${window.location.origin}/dashboard-mcp`,
      },
    })
    if (authError) setError(authError.message)
  }

  const signInWithTestAccount = () => {
    setError(null)
    setAuthReady(true)
    setAuthSession(TEST_AUTH_SESSION)
    setCalendarConnected(false)
    setWorkspaceToast('Loaded test account.')
    setTimeout(() => setWorkspaceToast(null), 2500)
  }

  // Direct Google OAuth PKCE flow for calendar (bypasses Supabase session)
  const connectGoogleCalendar = async () => {
    if (isTestAccount) {
      setIntegrationToast({ type: 'err', msg: 'Connect a real account to enable Google integrations.' })
      setTimeout(() => setIntegrationToast(null), 3000)
      return
    }
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
    if (!clientId) {
      setError('Google Client ID is not configured (VITE_GOOGLE_CLIENT_ID missing).')
      return
    }
    const verifier = await generateCodeVerifier()
    const challenge = await generateCodeChallenge(verifier)
    sessionStorage.setItem('cal_pkce_verifier', verifier)
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: window.location.origin,
      response_type: 'code',
      scope: 'https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly',
      code_challenge: challenge,
      code_challenge_method: 'S256',
      access_type: 'offline',
      prompt: 'consent',
      state: 'calendar_connect',
    })
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params}`
  }

  const disconnectCalendar = async () => {
    try {
      await apiFetch('/calendar/disconnect', { method: 'DELETE' })
    } catch {}
    setCalendarConnected(false)
  }

  const saveAutoJoinSetting = (val) => {
    if (isTestAccount) return
    setAutoJoinSetting(val)
    localStorage.setItem('prism_autojoin', val)
  }

  const setTranscriptForTab = (value, tab = inputTab) => {
    setTranscript(value)
    if (['paste', 'record', 'upload'].includes(tab)) {
      setTranscriptDrafts((prev) => ({ ...prev, [tab]: value }))
    }
  }

  const resetTranscriptWorkspaces = () => {
    setTranscript('')
    setTranscriptDrafts({ paste: '', record: '', upload: '' })
  }

  useEffect(() => {
    if (inputTab !== 'record' && recording) {
      stopRecording()
    }
    if (['paste', 'record', 'upload'].includes(inputTab)) {
      setTranscript(transcriptDrafts[inputTab] || '')
    }
  }, [inputTab, transcriptDrafts])

  async function exportToSlack() {
    if (isTestAccount) {
      setIntegrationToast({ type: 'err', msg: 'Connect a real account to export to Slack.' })
      setTimeout(() => setIntegrationToast(null), 3000)
      return
    }
    if (!integrations.slack_webhook) { setShowIntegrations(true); return }
    setExportingSlack(true)
    try {
      const res = await apiFetch('/export/slack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          webhook_url: integrations.slack_webhook,
          title: history.find(h => h.id === meetingId)?.title || 'Meeting',
          result,
        }),
      })
      if (!res.ok) throw new Error('Failed')
      setIntegrationToast({ type: 'ok', msg: 'Sent to Slack!' })
    } catch {
      setIntegrationToast({ type: 'err', msg: 'Slack export failed' })
    } finally {
      setExportingSlack(false)
      setTimeout(() => setIntegrationToast(null), 3000)
    }
  }

  const autoDeliveryRef = useRef(new Set())

  async function deliverMeetingRecap(meetingTitle, meetingResult, meetingId) {
    if (isTestAccount) return
    if (!meetingResult) return
    const deliveryKey = meetingId ? String(meetingId) : `${meetingTitle}-${meetingResult.health_score?.score ?? 'na'}`
    if (autoDeliveryRef.current.has(deliveryKey)) return
    autoDeliveryRef.current.add(deliveryKey)

    const delivered = []
    const failed = []

    if (integrations.auto_send_slack && integrations.slack_webhook) {
      try {
        const res = await apiFetch('/export/slack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            webhook_url: integrations.slack_webhook,
            title: meetingTitle,
            result: meetingResult,
          }),
        })
        if (!res.ok) throw new Error('Slack failed')
        delivered.push('Slack')
      } catch {
        failed.push('Slack')
      }
    }

    if (integrations.auto_send_notion && integrations.notion_token && integrations.notion_page_id) {
      try {
        const res = await apiFetch('/export/notion', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: integrations.notion_token,
            parent_page_id: integrations.notion_page_id,
            title: meetingTitle,
            result: meetingResult,
          }),
        })
        if (!res.ok) throw new Error('Notion failed')
        delivered.push('Notion')
      } catch {
        failed.push('Notion')
      }
    }

    if (delivered.length > 0) {
      setIntegrationToast({
        type: failed.length ? 'err' : 'ok',
        msg: failed.length
          ? `Auto-sent to ${delivered.join(' + ')}. ${failed.join(' + ')} failed.`
          : `Auto-sent recap to ${delivered.join(' + ')}.`,
      })
      setTimeout(() => setIntegrationToast(null), 5000)
    } else if (failed.length > 0) {
      setIntegrationToast({
        type: 'err',
        msg: `Auto-send failed for ${failed.join(' + ')}.`,
      })
      setTimeout(() => setIntegrationToast(null), 5000)
    }
  }

  async function exportToNotion() {
    if (isTestAccount) {
      setIntegrationToast({ type: 'err', msg: 'Connect a real account to export to Notion.' })
      setTimeout(() => setIntegrationToast(null), 3000)
      return
    }
    if (!integrations.notion_token || !integrations.notion_page_id) { setShowIntegrations(true); return }
    setExportingNotion(true)
    try {
      const res = await apiFetch('/export/notion', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: integrations.notion_token,
          parent_page_id: integrations.notion_page_id,
          title: history.find(h => h.id === meetingId)?.title || 'Meeting Analysis',
          result,
        }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || 'Failed')
      }
      const data = await res.json()
      setIntegrationToast({ type: 'ok', msg: 'Exported to Notion!', url: data.url })
    } catch (e) {
      setIntegrationToast({ type: 'err', msg: e.message || 'Notion export failed' })
    } finally {
      setExportingNotion(false)
      setTimeout(() => setIntegrationToast(null), 5000)
    }
  }

  // Handle #share/{token} on load
  useEffect(() => {
    if (!INITIAL_SHARE_TOKEN) return
    apiFetch(`/share/${INITIAL_SHARE_TOKEN}`, { skipAuth: true })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        setShareMode(data || null)
        if (data) {
          const title = `${data.title || 'Meeting'} — PrismAI`
          const desc = data.result?.summary
            ? data.result.summary.slice(0, 150) + '…'
            : 'Meeting analysis shared via PrismAI — 7 AI agents in parallel.'
          document.title = title
          const setMeta = (prop, val, attr = 'name') => {
            let el = document.querySelector(`meta[${attr}="${prop}"]`)
            if (!el) { el = document.createElement('meta'); el.setAttribute(attr, prop); document.head.appendChild(el) }
            el.setAttribute('content', val)
          }
          setMeta('description', desc)
          setMeta('og:title', title, 'property')
          setMeta('og:description', desc, 'property')
          setMeta('og:type', 'website', 'property')
          setMeta('twitter:card', 'summary')
          setMeta('twitter:title', title)
          setMeta('twitter:description', desc)
        }
      })
      .catch(() => { setShareMode(null) })
  }, [])

  const joinMeeting = async () => {
    if (isTestAccount) {
      setBotError('Meeting bot join is disabled in test run.')
      return
    }
    if (!meetingUrl.trim()) return
    setBotError(null)
    setBotTranscriptReady(false)
    setLiveCommands([])
    setBotStatus('joining')
    try {
      const res = await apiFetch('/join-meeting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meeting_url: meetingUrl }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to join meeting')
      const data = await res.json()
      setBotStatus(data.status)
      setActiveBotId(data.bot_id)
      sessionStorage.setItem('prism_active_bot_id', data.bot_id)
      if (data.live_token) {
        setActiveLiveToken(data.live_token)
        sessionStorage.setItem('prism_active_live_token', data.live_token)
      }
      startPolling(data.bot_id)
    } catch (e) {
      setBotStatus('error')
      setBotError(e.message)
    }
  }

  const startPolling = (id) => {
    clearInterval(pollRef.current)
    let networkFailCount = 0
    let processingStartTime = null
    pollRef.current = setInterval(async () => {
      try {
        const res = await apiFetch(`/bot-status/${id}`)
        if (!res.ok) {
          networkFailCount++
          if (networkFailCount > 15) {
            clearInterval(pollRef.current)
            setBotStatus('error')
            setBotError('Lost connection to server. Click Retry to try again.')
          }
          return
        }
        networkFailCount = 0
        const data = await res.json()
        setBotStatus(data.status)
        if (data.commands?.length) setLiveCommands(data.commands)
        if (data.status === 'processing' && !processingStartTime) {
          processingStartTime = Date.now()
        }
        // If processing has taken more than 3 minutes, show error
        if (data.status === 'processing' && processingStartTime && Date.now() - processingStartTime > 180_000) {
          clearInterval(pollRef.current)
          setBotStatus('error')
          setBotError('Transcript processing timed out. The server may have restarted. Click Retry to try again.')
          return
        }
        if (data.status === 'done') {
          clearInterval(pollRef.current)
          sessionStorage.removeItem('prism_active_bot_id')
          if (data.result) {
            savedMeetingRef.current = null
            sessionStorage.setItem('prism_new_meeting', '1')
            setTranscriptForTab(data.transcript || '', 'paste')
            setSessionId(s => s + 1)
            setResult(data.result)
            const entry = saveToHistory(data.transcript || '', data.result)
            const meetingTitle = entry?.title || data.result.summary?.slice(0, 65) || 'Meeting Analysis'
            void deliverMeetingRecap(meetingTitle, data.result, entry?.id)
            setBotTranscriptReady(false)
            setMobileTab('results')
          } else if (data.transcript) {
            setTranscriptForTab(data.transcript, 'paste')
            setSessionId(s => s + 1)
            setBotTranscriptReady(true)
          } else {
            setBotStatus('error')
            setBotError('Meeting ended but no transcript was returned. Check the Recall.ai dashboard or try again.')
          }
        } else if (data.status === 'error') {
          clearInterval(pollRef.current)
          sessionStorage.removeItem('prism_active_bot_id')
          setBotError(data.error || 'Bot encountered an error')
        }
      } catch (err) {
        console.warn('[poll] network error, will retry:', err?.message)
        networkFailCount++
        if (networkFailCount > 15) {
          clearInterval(pollRef.current)
          setBotStatus('error')
          setBotError('Cannot reach the server. Check your connection or try again.')
        }
      }
    }, 4000)
  }

  const cancelBot = async () => {
    clearInterval(pollRef.current)
    if (activeBotId) {
      apiFetch(`/remove-bot/${activeBotId}`, { method: 'DELETE' }).catch(() => {})
    }
    setBotStatus(null)
    setBotError(null)
    setActiveBotId(null)
    sessionStorage.removeItem('prism_active_bot_id')
    sessionStorage.removeItem('prism_active_live_token')
  }

  // Clean up poll on unmount
  useEffect(() => () => clearInterval(pollRef.current), [])

  // Resume polling if a bot was active before a page refresh
  useEffect(() => {
    const savedBotId = sessionStorage.getItem('prism_active_bot_id')
    if (savedBotId && !pollRef.current) {
      setBotStatus('joining')
      startPolling(savedBotId)
    }
  }, [])

  // Consume pendingAutoJoinRef — fires joinMeeting once URL + flag are set
  useEffect(() => {
    if (!pendingAutoJoinRef.current) return
    const url = pendingAutoJoinRef.current
    pendingAutoJoinRef.current = null
    setInputTab('join')
    setMeetingUrl(url)
    setTimeout(() => joinMeeting(), 100)
  })

  // Auto-join: directly join when polling detects an imminent meeting
  const autoJoinDirect = (url) => {
    setInputTab('join')
    setMeetingUrl(url)
    // joinMeeting reads meetingUrl state, so we need to call the API directly
    setBotError(null)
    setBotTranscriptReady(false)
    setBotStatus('joining')
    apiFetch('/join-meeting', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ meeting_url: url }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Failed to join meeting')
        return res.json()
      })
      .then((data) => {
        setBotStatus(data.status)
        setActiveBotId(data.bot_id)
        sessionStorage.setItem('prism_active_bot_id', data.bot_id)
        startPolling(data.bot_id)
      })
      .catch((e) => {
        setBotStatus('error')
        setBotError(e.message)
      })
  }

  // Calendar polling — next-up banner + auto-join check, one fetch per 60s
  useEffect(() => {
    if (!calendarConnected || !user) {
      setNextUpcomingMeeting(null)
      return
    }

    let cancelled = false

    async function pollCalendarEvents() {
      try {
        const res = await apiFetch('/calendar/events?days_ahead=1')
        if (!res.ok) throw new Error()
        const data = await res.json()
        if (cancelled) return
        const events = data?.events || []

        setNextUpcomingMeeting(events.find((e) => e?.start) || null)

        if (autoJoinSetting !== 'off') {
          const markedIds = JSON.parse(localStorage.getItem('prism_marked_events') || '[]')
          const now = new Date()
          for (const ev of events) {
            if (!ev.has_meeting_link || !ev.start) continue
            if (autoJoinFiredRef.current.has(ev.id)) continue
            const minsUntil = Math.round((new Date(ev.start) - now) / 60000)
            if (minsUntil < -5 || minsUntil > 5) continue
            if (autoJoinSetting === 'marked' && !markedIds.includes(ev.id)) continue
            autoJoinFiredRef.current.add(ev.id)
            if (autoJoinSetting === 'auto' || autoJoinSetting === 'marked') {
              autoJoinDirect(ev.meeting_link)
            } else if (autoJoinSetting === 'ask') {
              setAutoJoinPrompt({ title: ev.title, url: ev.meeting_link, minsUntil })
            }
            break
          }
        }
      } catch {
        if (!cancelled) setNextUpcomingMeeting(null)
      }
    }

    pollCalendarEvents()
    const interval = setInterval(pollCalendarEvents, 60_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [calendarConnected, user?.id, autoJoinSetting])

  const mergeHistoryEntries = (entries) => {
    const seen = new Set()
    return entries.filter((entry) => {
      if (!entry?.id || seen.has(entry.id)) return false
      seen.add(entry.id)
      return true
    }).sort((a, b) => b.id - a.id)
  }

  const saveToHistory = (t, r) => {
    if (!user) {
      setMeetingId(null)
      setShareToken(null)
      return null
    }
    if (!hasMeaningfulResult(r)) return null
    if (savedMeetingRef.current) return null  // already saved this workspace — prevent double-save
    sessionStorage.removeItem('prism_new_meeting')
    const id = (Date.now() * 1000) + Math.floor(Math.random() * 1000)
    savedMeetingRef.current = id
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
    setHistory(prev => mergeHistoryEntries([entry, ...prev]))
    setMeetingId(id)
    setShareToken(share_token)
    if (isTestAccount) {
      return entry
    }
    apiFetch('/meetings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    }).catch(() => {
      savedMeetingRef.current = null
      setMeetingId(null)
    })
    return entry
  }

  const loadFromHistory = async (entry) => {
    cancelActiveAnalysis()
    sessionStorage.removeItem('prism_new_meeting')
    savedMeetingRef.current = entry.id
    setTranscript(entry.transcript)
    setTranscriptDrafts((prev) => ({ ...prev, paste: entry.transcript || '' }))
    setResult(entry.result)
    setMobileTab('results')
    setMeetingId(entry.id)
    // Generate share token on the fly if missing (older meetings)
    let token = entry.share_token || null
    if (!token && user && !isTestAccount) {
      token = crypto.randomUUID().replace(/-/g, '').slice(0, 16)
      apiFetch(`/meetings/${entry.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ share_token: token }),
      }).catch(() => {})
    }
    setShareToken(token)
    setSessionId(s => s + 1)
    setShowHistory(false)
    if (isTestAccount) {
      setInitialMessages([])
      return
    }
    try {
      const res = await apiFetch(`/chats/${entry.id}`)
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
      setTranscriptDrafts((prev) => {
        const next = prev.record ? `${prev.record}\n${text}` : text
        setTranscript(next)
        return { ...prev, record: next }
      })
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
      const res = await apiFetch('/transcribe', { method: 'POST', body: formData })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Transcription failed')
      const data = await res.json()
      setTranscriptForTab(data.transcript, 'upload')
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

  const startDemo = () => {
    const t = getRandomDemoTranscript()
    setIsDemoMode(true)
    setDemoChatOpen(false)
    setInputTab('paste')
    setTranscriptForTab(t, 'paste')
    setMobileTab('input')
    runAnalysis([], t, true)
  }

  const loadDashboardSample = () => {
    const now = Date.now()
    const sampleResults = [
      {
        title: 'Q2 roadmap planning',
        transcript: DEMO_TRANSCRIPTS[0],
        result: {
          summary: 'The team narrowed Q2 priorities to checkout improvements and mobile redesign, moving analytics to Q3. Follow-up ownership is clear across roadmap, client messaging, and feature specs.',
          action_items: [
            { task: 'Update the roadmap with analytics moved to Q3', owner: 'Mike', due: 'Thursday EOD' },
            { task: 'Draft enterprise client message about mobile redesign timing', owner: 'Lisa', due: 'Wednesday' },
            { task: 'Finalize feature specs for marketing launch campaign', owner: 'Mike', due: 'Next Friday' },
          ],
          decisions: [
            { decision: 'Prioritize checkout improvements and mobile redesign for Q2', owner: 'Sarah', importance: 1 },
            { decision: 'Move analytics dashboard to Q3', owner: 'Mike', importance: 2 },
          ],
          sentiment: { overall: 'positive', score: 78, arc: 'aligned', notes: 'Constructive disagreement resolved into clear tradeoffs.' },
          health_score: { score: 84, verdict: 'Strong prioritization with clear owners and near-term follow-ups.', badges: ['Clear Decisions', 'Action-Oriented'], breakdown: { clarity: 88, action_orientation: 86, engagement: 78 } },
        },
      },
      {
        title: 'Payment outage postmortem',
        transcript: DEMO_TRANSCRIPTS[1],
        result: {
          summary: 'The outage was traced to Redis connection pool exhaustion after an infra config change. The team agreed on alerting, review checklist updates, and a runbook.',
          action_items: [
            { task: 'Set alert for connection pool utilization above 70 percent', owner: 'Priya', due: 'End of week' },
            { task: 'Update infra change review checklist', owner: 'Marcus', due: 'Thursday' },
            { task: 'Draft runbook for connection pool exhaustion', owner: 'Priya', due: 'Next Monday' },
          ],
          decisions: [
            { decision: 'Connection limit config changes require a second on-call reviewer', owner: 'Alex', importance: 1 },
          ],
          sentiment: { overall: 'tense', score: 58, arc: 'recovered', notes: 'The incident was preventable, but the group landed concrete safeguards.' },
          health_score: { score: 72, verdict: 'Useful postmortem with specific safeguards, though tension was present.', badges: ['Clear Owners', 'Risk Surfaced'], breakdown: { clarity: 76, action_orientation: 82, engagement: 62 } },
        },
      },
      {
        title: 'Sales strategy pipeline review',
        transcript: DEMO_TRANSCRIPTS[2],
        result: {
          summary: 'The team reviewed Q1 miss drivers and set Q2 sales improvements around legal templates, competitor battle cards, MEDDIC certification, and weekly pipeline reviews.',
          action_items: [
            { task: 'Work with legal on standard contract template', owner: 'Rachel', due: 'End of April' },
            { task: 'Build competitive battle card for top two competitors', owner: 'Carlos', due: 'Next Friday' },
            { task: 'Complete MEDDIC certification', owner: 'Carlos', due: 'April 30' },
            { task: 'Complete MEDDIC certification', owner: 'Rachel', due: 'April 30' },
          ],
          decisions: [
            { decision: 'Target 15 net-new enterprise logos in Q2', owner: 'Diana', importance: 1 },
            { decision: 'Review pipeline health every Monday at 9am', owner: 'Diana', importance: 2 },
          ],
          sentiment: { overall: 'neutral', score: 66, arc: 'focused', notes: 'Clear pipeline pressure with pragmatic next steps.' },
          health_score: { score: 78, verdict: 'Focused operational review with measurable goals and owners.', badges: ['Measurable Goals', 'Action-Oriented'], breakdown: { clarity: 80, action_orientation: 84, engagement: 70 } },
        },
      },
      {
        title: 'Q3 budget alignment',
        transcript: DEMO_TRANSCRIPTS[3],
        result: {
          summary: 'The budget conversation exposed unclear data, a broken spreadsheet, missing distribution lists, and no concrete decision beyond reconvening later.',
          action_items: [
            { task: 'Fix the spreadsheet formula error', owner: 'Greg', due: '' },
            { task: 'Forward prior budget scope-change email', owner: 'Kevin', due: '' },
            { task: 'Review team spend before reconvening', owner: '', due: 'This week' },
          ],
          decisions: [],
          sentiment: { overall: 'tense', score: 34, arc: 'frustrated', notes: 'Confusion and unclear ownership blocked useful alignment.' },
          health_score: { score: 29, verdict: 'Low-clarity meeting with unresolved numbers, unclear agenda, and weak ownership.', badges: ['Needs Follow-Up', 'Unclear Decisions'], breakdown: { clarity: 22, action_orientation: 34, engagement: 38 } },
        },
      },
      {
        title: 'Onboarding research readout',
        transcript: DEMO_TRANSCRIPTS[4],
        result: {
          summary: 'Research found onboarding drop-off around integration admin access. The team split immediate tooltip/email-template fixes from a later magic-link flow.',
          action_items: [
            { task: 'Scope magic link flow for admin invitations', owner: 'Sam', due: 'Next Wednesday' },
            { task: 'Write tooltip copy and updated step 3 instructions', owner: 'Tyler', due: 'Friday' },
            { task: 'Share pricing reassurance mockup in Figma', owner: 'Casey', due: 'Today' },
          ],
          decisions: [
            { decision: 'Ship short-term admin help tooltip and email template', owner: 'Morgan', importance: 1 },
            { decision: 'Retest with five users after tooltip change goes live', owner: 'Morgan', importance: 2 },
          ],
          sentiment: { overall: 'positive', score: 82, arc: 'collaborative', notes: 'Research translated into both quick wins and strategic follow-up.' },
          health_score: { score: 88, verdict: 'Excellent research readout with clear evidence, sequencing, and owners.', badges: ['Evidence-Based', 'Clear Owners'], breakdown: { clarity: 90, action_orientation: 88, engagement: 86 } },
        },
      },
    ]

    const entries = sampleResults.map((item, index) => ({
      id: now - index * 86400000,
      date: new Date(now - index * 86400000).toISOString(),
      transcript: item.transcript,
      result: item.result,
      title: item.title,
      score: item.result.health_score.score,
      share_token: `sample${index}`,
    }))

    setIsDemoMode(false)
    setDemoChatOpen(false)
    setInputTab('paste')
    setMobileTab('results')
    setLoading(false)
    setError(null)
    setAnalysisTime(null)
    setShowTimeSaved(false)
    setCrossMeetingInsights(null)
    setShowHistory(false)
    clearTimeout(historySearchDebounceRef.current)
    setHistorySearch('')
    setHistory(entries)
    setTranscript(entries[0].transcript)
    setTranscriptDrafts((prev) => ({ ...prev, paste: entries[0].transcript }))
    setResult(entries[0].result)
    setMeetingId(entries[0].id)
    savedMeetingRef.current = entries[0].id
    setShareToken(entries[0].share_token)
    setInitialMessages([])
    setSessionId((s) => s + 1)
    setWorkspaceToast('Loaded sample dashboard.')
    setTimeout(() => setWorkspaceToast(null), 2500)
  }

  const cancelActiveAnalysis = () => {
    analysisRunIdRef.current += 1
    analysisAbortRef.current?.abort()
    analysisAbortRef.current = null
    setLoading(false)
  }

  const clearWorkspaceState = () => {
    cancelActiveAnalysis()
    resetTranscriptWorkspaces()
    setResult(null)
    setError(null)
    setShowTimeSaved(false)
    setAnalysisTime(null)
    setMeetingId(null)
    setShareToken(null)
    setInitialMessages([])
    setMobileTab('input')
    setSessionId(s => s + 1)
    savedMeetingRef.current = null
  }

  const signOut = async () => {
    clearWorkspaceState()
    clearInterval(pollRef.current)
    setBotStatus(null)
    setBotError(null)
    setActiveBotId(null)
    sessionStorage.removeItem('prism_active_bot_id')
    setDemoChatOpen(false)
    setIsDemoMode(false)
    setHistory([])
    if (isTestAccount) {
      sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
      sessionStorage.setItem(UI_SCREEN_KEY, 'landing')
      setAuthSession(null)
      setAuthReady(true)
      window.location.href = '/'
    } else if (supabase) {
      await supabase.auth.signOut()
    }
  }

  const exitDemoMode = () => {
    setIsDemoMode(false)
    setDemoChatOpen(false)
    setInputTab('paste')
    setShowHistory(false)
    if (user && history.length > 0) {
      // Restore the most recent real meeting instead of leaving workspace blank
      loadFromHistory(history[0])
    } else {
      clearWorkspaceState()
    }
  }

  const runAnalysis = async (speakersParam, transcriptOverride, isDemo = false) => {
    cancelActiveAnalysis()
    setShowSpeakerModal(false)
    setLoading(true)
    setMobileTab('results')
    setError(null)
    setResult(null)
    setAnalysisTime(null)
    setShowTimeSaved(false)
    savedMeetingRef.current = null
    if (!isDemo) sessionStorage.setItem('prism_new_meeting', '1')
    analysisStartRef.current = Date.now()
    const runId = analysisRunIdRef.current
    const t = transcriptOverride ?? transcript
    const validSpeakers = speakersParam.filter(s => s.name.trim())
    const controller = new AbortController()
    analysisAbortRef.current = controller
    const timeoutId = setTimeout(() => controller.abort(), 120_000)
    try {
      const res = await apiFetch('/analyze-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transcript: t,
          speakers: validSpeakers,
          owner_name: authSession?.user?.user_metadata?.full_name || null,
        }),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Server error ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = { ...DEFAULT_RESULT }
      let buffer = ''
      let successfulPayloads = 0

      let streamDone = false
      while (!streamDone) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (runId !== analysisRunIdRef.current) {
            streamDone = true
            break
          }
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (raw === '[DONE]') {
            if (runId !== analysisRunIdRef.current) {
              streamDone = true
              break
            }
            if (!hasMeaningfulResult(accumulated) || successfulPayloads === 0) {
              throw new Error('Analysis did not return usable results. Please try again.')
            }
            const elapsed = ((Date.now() - analysisStartRef.current) / 1000).toFixed(1)
            setAnalysisTime(parseFloat(elapsed))
            setShowTimeSaved(true)
            setMobileTab('results')
            if (!isDemo) {
              const entry = saveToHistory(t, accumulated)
              const meetingTitle = entry?.title || accumulated.summary?.slice(0, 65) || 'Meeting Analysis'
              void deliverMeetingRecap(meetingTitle, accumulated, entry?.id)
            }
            streamDone = true
            break
          }
          try {
            const chunk = JSON.parse(raw)
            accumulated = { ...accumulated, ...chunk }
            if (Object.keys(chunk).some((key) => key !== 'agents_run')) {
              successfulPayloads += 1
            }
            if (runId === analysisRunIdRef.current) {
              setResult({ ...accumulated })
            }
          } catch { /* malformed chunk, skip */ }
        }
      }
    } catch (e) {
      if (runId !== analysisRunIdRef.current) {
        return
      }
      if (e.name === 'AbortError') {
        setError('Analysis timed out. The server may be starting up — please try again.')
      } else {
        setError(e.message || 'Failed to analyze.')
      }
    } finally {
      clearTimeout(timeoutId)
      if (analysisAbortRef.current === controller) {
        analysisAbortRef.current = null
      }
      if (runId === analysisRunIdRef.current) {
        setLoading(false)
      }
    }
  }

  const toggleActionItem = (index) => {
    const snapshot = result
    if (!snapshot?.action_items) return
    const updated = snapshot.action_items.map((item, i) =>
      i === index ? { ...item, completed: !item.completed } : item
    )
    const updatedResult = { ...snapshot, action_items: updated }
    setResult(updatedResult)
    if (meetingId) {
      apiFetch(`/meetings/${meetingId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: updatedResult }),
      }).catch(() => {
        // Revert optimistic update if persist fails
        setResult(snapshot)
      })
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

  const copyMarkdown = () => {
    if (!result) return
    navigator.clipboard.writeText(buildMarkdown(result)).then(() => {
      setMdCopied(true)
      setTimeout(() => setMdCopied(false), 2000)
    })
  }

  const exportPDF = () => {
    if (!result) return
    const html = buildPrintHTML(result)
    const blob = new Blob([html], { type: 'text/html' })
    const url = URL.createObjectURL(blob)
    const w = window.open(url, '_blank')
    w?.focus()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  useEffect(() => {
    if (!showHistory) return
    const h = (e) => { if (!e.target.closest('[data-history-panel]')) setShowHistory(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [showHistory])

  useEffect(() => {
    if (!showExportMenu) return
    const h = (e) => { if (!e.target.closest('[data-export-menu]')) setShowExportMenu(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [showExportMenu])

  // Landing screen — shown to first-time visitors
  if (showLanding) {
    return <LandingScreen onDemo={() => exitLanding(true)} onSkip={() => exitLanding(false)} onViewDashboard={enterDashboardTestRun} exiting={landingExiting} />
  }

  // Live meeting view — shown when URL is #live/{token}
  if (INITIAL_LIVE_TOKEN) {
    return <LiveMeetingView token={INITIAL_LIVE_TOKEN} />
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
    const appUrl = window.location.origin + window.location.pathname
    return (
      <div className="min-h-screen" style={{ background: '#07040f' }}>
        {/* Header bar */}
        <div className="sticky top-0 z-10 px-4 py-3 flex items-center justify-between"
          style={{ background: 'rgba(7,4,15,0.92)', borderBottom: '1px solid rgba(255,255,255,0.07)', backdropFilter: 'blur(16px)' }}>
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 16px rgba(2,132,199,0.4)' }}>
              <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
              </svg>
            </div>
            <span className="text-sm font-bold gradient-text">PrismAI</span>
            <span className="text-[10px] text-gray-600 px-2 py-0.5 rounded-full"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
              shared
            </span>
          </div>
          <a href={appUrl}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:scale-105"
            style={{ background: 'linear-gradient(135deg, rgba(2,132,199,0.2), rgba(13,148,136,0.15))', border: '1px solid rgba(14,165,233,0.3)', color: '#7dd3fc' }}>
            Analyze your own →
          </a>
        </div>

        {/* Meeting title + date */}
        <div className="px-4 pt-6 pb-4 max-w-2xl mx-auto">
          <h1 className="text-xl font-bold text-white leading-tight">{shareMode.title || 'Meeting'}</h1>
          {shareMode.date && (
            <p className="text-xs text-gray-500 mt-1">
              {new Date(shareMode.date).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
            </p>
          )}
          {r.agents_run?.length > 0 && (
            <div className="mt-3"><AgentTags agents={r.agents_run} /></div>
          )}
        </div>

        {/* Cards */}
        <div className="px-4 pb-8 max-w-2xl mx-auto space-y-4">
          <HealthScoreCard healthScore={r.health_score} />
          <SummaryCard summary={r.summary} />
          <ActionItemsCard actionItems={r.action_items} />
          <DecisionsCard decisions={r.decisions} />
          <SentimentCard sentiment={r.sentiment} />
          <CalendarCard suggestion={r.calendar_suggestion} />
          <SpeakerCoachCard speakerCoach={r.speaker_coach} />
        </div>

        {/* Bottom CTA */}
        <div className="px-4 pb-12 max-w-2xl mx-auto text-center">
          <div className="rounded-2xl p-6"
            style={{ background: 'rgba(14,165,233,0.06)', border: '1px solid rgba(14,165,233,0.15)' }}>
            <p className="text-sm font-semibold text-white mb-1">Analyze your own meetings</p>
            <p className="text-xs text-gray-400 mb-4">Paste any transcript — 7 AI agents produce a full analysis in seconds.</p>
            <a href={appUrl}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold text-white transition-all hover:scale-[1.02]"
              style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: '0 4px 20px rgba(2,132,199,0.35)' }}>
              Try PrismAI free →
            </a>
          </div>
        </div>
      </div>
    )
  }

  if (isMcpDashboard) {
    if (authReady && !user && !isTestAccount) {
      window.location.replace('/')
      return null
    }

    return (
      <>
        <DashboardMcpPage
          authReady={authReady}
          user={user}
          isTestAccount={isTestAccount}
          signOut={signOut}
          loadDashboardSample={loadDashboardSample}
          canLoadSample={isTestAccount}
          selectedMeetingId={meetingId ?? history?.[0]?.id}
          isDemoMode={isDemoMode}
          exitDemoMode={exitDemoMode}
          inputTab={inputTab}
          setInputTab={setInputTab}
          inputModeMeta={inputModeMeta}
          transcript={transcript}
          setTranscriptForTab={setTranscriptForTab}
          transcriptStats={transcriptStats}
          transcriptSpeakerCount={transcriptSpeakerCount}
          loading={loading}
          result={result}
          setResult={setResult}
          error={error}
          analysisTime={analysisTime}
          showTimeSaved={showTimeSaved}
          handleAnalyzeClick={handleAnalyzeClick}
          cancelActiveAnalysis={cancelActiveAnalysis}
          startDemo={startDemo}
          clearWorkspaceState={clearWorkspaceState}
          toggleActionItem={toggleActionItem}
          history={history}
          showHistory={showHistory}
          setShowHistory={setShowHistory}
          historySearch={historySearch}
          setHistorySearch={setHistorySearch}
          historySearchDebounceRef={historySearchDebounceRef}
          setHistory={setHistory}
          loadFromHistory={loadFromHistory}
          apiFetch={apiFetch}
          hasMeaningfulResult={hasMeaningfulResult}
          crossMeetingInsights={crossMeetingInsights}
          sessionId={sessionId}
          meetingId={meetingId}
          initialMessages={initialMessages}
          meetingUrl={meetingUrl}
          setMeetingUrl={setMeetingUrl}
          joinMeeting={joinMeeting}
          cancelBot={cancelBot}
          botStatus={botStatus}
          botError={botError}
          botTranscriptReady={botTranscriptReady}
          liveCommands={liveCommands}
          calendarConnected={calendarConnected}
          nextUpcomingMeeting={nextUpcomingMeeting}
          recording={recording}
          startRecording={startRecording}
          stopRecording={stopRecording}
          micSupported={micSupported}
          transcribing={transcribing}
          fileInputRef={fileInputRef}
          handleAudioUpload={handleAudioUpload}
          shareToken={shareToken}
          shareCopied={shareCopied}
          setShareCopied={setShareCopied}
          showExportMenu={showExportMenu}
          setShowExportMenu={setShowExportMenu}
          copyMarkdown={copyMarkdown}
          mdCopied={mdCopied}
          exportMarkdown={exportMarkdown}
          exportPDF={exportPDF}
          exportToSlack={exportToSlack}
          exportToNotion={exportToNotion}
          exportingSlack={exportingSlack}
          exportingNotion={exportingNotion}
          integrations={integrations}
          setShowIntegrations={setShowIntegrations}
        />

        {showSpeakerModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-xl border border-black bg-white shadow-2xl">
              <div className="border-b border-black/10 px-5 py-4">
                <h3 className="text-sm font-bold text-[#191c1e]">Who was in this meeting?</h3>
                <p className="mt-1 text-xs text-[#6b7280]">Add roles for stronger ownership and attribution.</p>
              </div>
              <div className="max-h-64 space-y-2 overflow-y-auto px-5 py-4">
                {speakers.map((speaker, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <input
                      value={speaker.name}
                      onChange={(event) => setSpeakers((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))}
                      placeholder="Name"
                      className="w-32 rounded-lg border border-black px-3 py-2 text-xs outline-none focus:ring-2 focus:ring-black/20"
                    />
                    <input
                      value={speaker.role}
                      onChange={(event) => setSpeakers((prev) => prev.map((item, itemIndex) => itemIndex === index ? { ...item, role: event.target.value } : item))}
                      placeholder="Role"
                      className="flex-1 rounded-lg border border-black px-3 py-2 text-xs outline-none focus:ring-2 focus:ring-black/20"
                    />
                    <button type="button" onClick={() => setSpeakers((prev) => prev.filter((_, itemIndex) => itemIndex !== index))} className="min-h-9 rounded-lg border border-black px-2 text-xs">
                      Remove
                    </button>
                  </div>
                ))}
                <button type="button" onClick={() => setSpeakers((prev) => [...prev, { name: '', role: '' }])} className="text-xs font-semibold text-[#191c1e]">
                  Add person
                </button>
              </div>
              <div className="flex items-center justify-end gap-2 border-t border-black/10 px-5 py-3">
                <button type="button" onClick={() => runAnalysis([])} className="min-h-10 rounded-lg border border-black px-4 text-xs font-semibold">
                  Skip
                </button>
                <button type="button" onClick={() => runAnalysis(speakers)} className="min-h-10 rounded-lg border border-black bg-black px-4 text-xs font-semibold text-white">
                  Analyze
                </button>
              </div>
            </div>
          </div>
        )}

        {showIntegrations && (
          <Suspense fallback={null}>
            <IntegrationsModal
              integrations={integrations}
              onSave={setIntegrations}
              onClose={() => setShowIntegrations(false)}
              calendarConnected={calendarConnected}
              onConnectCalendar={connectGoogleCalendar}
              onDisconnectCalendar={disconnectCalendar}
              autoJoinSetting={autoJoinSetting}
              onAutoJoinChange={saveAutoJoinSetting}
              isSignedIn={!!user}
              isTestAccount={isTestAccount}
            />
          </Suspense>
        )}

        {workspaceToast && (
          <div className="fixed right-6 top-20 z-50 rounded-xl border border-black bg-white px-4 py-3 text-xs font-semibold text-[#191c1e] shadow-xl">
            {workspaceToast}
          </div>
        )}

        {integrationToast && (
          <div className="fixed bottom-28 left-1/2 z-50 -translate-x-1/2 rounded-xl border border-black bg-white px-4 py-3 text-xs font-semibold text-[#191c1e] shadow-xl">
            {integrationToast.msg}
          </div>
        )}
      </>
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
                    aria-label="Remove speaker"
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
      <header className="app-content flex-shrink-0 px-4 sm:px-6 py-3"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.07)', background: 'rgba(7,4,15,0.7)', backdropFilter: 'blur(20px)', position: 'relative', zIndex: 40 }}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center justify-between gap-3">
            <button className="flex items-center gap-3 hover:opacity-80 transition-opacity min-w-0"
              onClick={() => {
                sessionStorage.setItem(UI_SCREEN_KEY, 'landing')
                setShowLanding(true)
                setLandingExiting(false)
              }}>
              <div className="w-8 h-8 rounded-xl flex items-center justify-center shadow-lg shadow-sky-500/30 flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                </svg>
              </div>
              <div className="min-w-0">
                <span className="text-sm font-bold gradient-text">PrismAI</span>
                <span className="hidden sm:inline text-[10px] text-gray-600 ml-2">meeting intelligence</span>
              </div>
            </button>

            {authReady && (
              user ? (
                <button
                  onClick={signOut}
                  className="sm:hidden flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] text-gray-300 hover:text-white transition-colors flex-shrink-0"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                  Sign out
                </button>
              ) : (
                <button
                  onClick={signInWithGoogle}
                  className="sm:hidden flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] text-sky-300 hover:text-white transition-colors flex-shrink-0"
                  style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.18)' }}>
                  Sign in
                </button>
              )
            )}
          </div>

          <div className="flex items-center gap-2 overflow-x-auto sm:overflow-visible pb-1 sm:pb-0 no-scrollbar">
            {authReady && !user && (
              <button
                onClick={signInWithGoogle}
                className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] text-sky-300 hover:text-white transition-colors flex-shrink-0"
                style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.18)' }}>
                Sign in
              </button>
            )}

            {authReady && user && (
              <button
                onClick={signOut}
                className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] text-gray-300 hover:text-white transition-colors flex-shrink-0"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                <span className="hidden sm:inline max-w-[160px] truncate">{user.email}</span>
                <span>Sign out</span>
              </button>
            )}

            {/* History */}
            {user && history.length > 0 && (
              <div className="relative flex-shrink-0" data-history-panel>
                <button onClick={() => setShowHistory(v => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-gray-200 transition-colors whitespace-nowrap"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  History
                  <span className="w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center"
                    style={{ background: 'rgba(14,165,233,0.25)', color: '#7dd3fc' }}>{history.length}</span>
                </button>

                {showHistory && (
                  <div className="absolute right-0 top-[calc(100%+6px)] w-[min(20rem,calc(100vw-2rem))] rounded-2xl shadow-2xl z-50 overflow-hidden animate-fade-in-up"
                    style={{ background: '#100c1e', border: '1px solid rgba(255,255,255,0.1)' }}>
                    <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                      <span className="text-xs font-semibold text-gray-300">Recent Meetings</span>
                      <button onClick={async () => {
                        cancelActiveAnalysis()
                        await Promise.all(history.map(h => apiFetch(`/meetings/${h.id}`, { method: 'DELETE' }).catch(() => {})))
                        setHistory([])
                        setShowHistory(false)
                        clearWorkspaceState()
                      }} className="text-[11px] text-gray-600 hover:text-red-400 transition-colors">Clear all</button>
                    </div>
                    <div className="px-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
                      <input
                        value={historySearch}
                        onChange={e => {
                          const q = e.target.value
                          setHistorySearch(q)
                          clearTimeout(historySearchDebounceRef.current)
                          historySearchDebounceRef.current = setTimeout(async () => {
                            const res = await apiFetch(`/meetings?q=${encodeURIComponent(q)}`).catch(() => null)
                            if (res?.ok) {
                              const d = await res.json()
                              setHistory(Array.isArray(d) ? d.filter((entry) => hasMeaningfulResult(entry?.result)) : [])
                            }
                          }, 300)
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
                              apiFetch(`/meetings/${entry.id}`, { method: 'DELETE' }).catch(() => {})
                              if (entry.id === meetingId) {
                                sessionStorage.setItem('prism_new_meeting', '1')
                                clearWorkspaceState()
                              }
                            }}
                            aria-label="Delete meeting"
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
                onClick={() => { sessionStorage.setItem('prism_new_meeting', '1'); clearWorkspaceState() }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white transition-colors flex-shrink-0 whitespace-nowrap"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                New Meeting
              </button>
            )}

            <button
              onClick={() => startDemo()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] text-sky-400 transition-colors hover:text-sky-300 flex-shrink-0 whitespace-nowrap"
              style={{ background: 'rgba(14,165,233,0.07)', border: '1px solid rgba(14,165,233,0.15)' }}>
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Demo
            </button>

            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] text-gray-400 flex-shrink-0 whitespace-nowrap"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              llama-3.3-70b
            </div>
            <div className="flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-semibold flex-shrink-0 whitespace-nowrap"
              style={{ background: 'linear-gradient(135deg, rgba(14,165,233,0.2), rgba(6,182,212,0.15))', border: '1px solid rgba(14,165,233,0.3)', color: '#7dd3fc' }}>
              7 agents
            </div>

            {/* Integrations button */}
            <button
              onClick={() => setShowIntegrations(true)}
              title="Integrations"
              aria-label="Integrations"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] text-gray-400 hover:text-white transition-colors flex-shrink-0 whitespace-nowrap"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              <span>Integrations</span>
            </button>
          </div>
        </div>
      </header>

      {/* ── Demo banner ── */}
      {isDemoMode && (
        <div className="flex-shrink-0 px-6 py-2.5"
          style={{ background: 'linear-gradient(90deg, rgba(2,132,199,0.12), rgba(13,148,136,0.08))', borderBottom: '1px solid rgba(14,165,233,0.16)' }}>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between rounded-2xl px-4 py-2.5"
            style={{ background: 'rgba(255,255,255,0.035)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.24)' }}>
                <svg className="w-4 h-4 text-sky-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-sky-400/80">Demo mode</p>
                <p className="text-sm text-slate-200 mt-1">
                  Explore the sample run, then switch into your own transcript workspace when you are ready.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <button
                onClick={exitDemoMode}
                className="text-[11px] px-3.5 py-2 rounded-xl text-sky-300 hover:text-sky-200 transition-colors flex-shrink-0"
                style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.2)' }}>
                Use my own transcript
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Main two-pane layout ── */}
      <div className="app-content flex flex-1 overflow-hidden">

        {/* LEFT PANEL — Input */}
        <div className={`flex flex-col w-full lg:w-[420px] xl:w-[460px] flex-shrink-0 overflow-y-auto pb-32 lg:pb-0 ${mobileTab === 'results' ? 'hidden lg:flex' : 'flex'}`} style={PANEL_STYLE}>

          {/* Workspace header */}
          <div className="px-6 pt-4 pb-2">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-semibold text-white">
                  {isDemoMode ? 'Demo workspace' : 'Meeting workspace'}
                </h1>
                {isDemoMode && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                    style={{ background: 'rgba(14,165,233,0.1)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                    Demo
                  </span>
                )}
              </div>
              {!user && !isDemoMode && (
                <button
                  onClick={signInWithGoogle}
                  className="text-[11px] px-2.5 py-1 rounded-lg transition-all flex-shrink-0"
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)', color: '#94a3b8' }}>
                  Sign in to save this workspace
                </button>
              )}
            </div>
            <p className="mt-2 text-[12px] text-slate-400 leading-relaxed">
              {isDemoMode
                ? 'Inspect the sample flow, then switch into your own meeting when you are ready.'
                : 'Paste, record, upload, or join live · 7 agents stream results back.'}
            </p>

            {recentMeetings.length > 0 && !isDemoMode && result && (
              <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide">
                {recentMeetings.map((entry) => (
                  <button
                    key={entry.id}
                    onClick={() => loadFromHistory(entry)}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl text-left flex-shrink-0 transition-all hover:scale-[1.01]"
                    style={{
                      background: entry.id === meetingId ? 'rgba(14,165,233,0.12)' : 'rgba(255,255,255,0.04)',
                      border: entry.id === meetingId ? '1px solid rgba(14,165,233,0.28)' : '1px solid rgba(255,255,255,0.08)',
                    }}>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
                      style={{
                        background: 'rgba(255,255,255,0.06)',
                        color: (entry.score ?? 0) > 0 ? '#99f6e4' : '#cbd5e1',
                      }}>
                      {entry.score ? `${entry.score}` : 'Saved'}
                    </span>
                    <span className="text-[11px] text-slate-200 max-w-[120px] truncate">
                      {entry.title || 'Meeting'}
                    </span>
                    <span className="text-[10px] text-slate-500">
                      {formatRelativeMeetingDate(entry.date)}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {calendarConnected && user && nextUpcomingMeeting && !isDemoMode && (
              <div className="mt-3 flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-2xl"
                style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.16)' }}>
                <div className="min-w-0">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-sky-300/80">
                    {(() => {
                      const status = formatMinutesUntil(nextUpcomingMeeting.start, nextUpcomingMeeting.end)
                      return status.startsWith('in progress') ? 'In progress' : status === 'ended' ? 'Ended' : 'Next up'
                    })()}
                  </p>
                  <p className="text-[12px] text-slate-100 truncate">
                    {nextUpcomingMeeting.title || 'Upcoming meeting'} · {formatMinutesUntil(nextUpcomingMeeting.start, nextUpcomingMeeting.end)}
                  </p>
                </div>
                {nextUpcomingMeeting.meeting_link && (
                  <button
                    onClick={() => {
                      setInputTab('join')
                      setMeetingUrl(nextUpcomingMeeting.meeting_link)
                    }}
                    className="text-[11px] px-3 py-1.5 rounded-xl flex-shrink-0 transition-colors"
                    style={{ background: 'rgba(14,165,233,0.12)', border: '1px solid rgba(14,165,233,0.2)', color: '#7dd3fc' }}>
                    Join
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Error */}
          {error && <ErrorCard message={error} onRetry={() => runAnalysis([])} />}

          {/* Transcript card */}
          <div className="mx-6 mb-3 rounded-2xl overflow-hidden card-breathe" style={CARD_STYLE}>

            {/* Input method tabs */}
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
                <button onClick={() => setTranscriptForTab(getRandomDemoTranscript())}
                  className="text-[11px] px-2.5 py-2 rounded-lg transition-colors flex-shrink-0"
                  style={{ background: 'rgba(14,165,233,0.08)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.15)' }}>
                  Load sample
                </button>
              )}
              {inputTab !== 'join' && transcript.trim() && (
                <button
                  onClick={() => setTranscriptForTab('')}
                  className="text-[11px] px-2.5 py-2 rounded-lg transition-colors flex-shrink-0"
                  style={{ background: 'rgba(255,255,255,0.05)', color: '#cbd5e1', border: '1px solid rgba(255,255,255,0.1)' }}>
                  Clear
                </button>
              )}
            </div>


            {/* Paste Transcript */}
            {inputTab === 'paste' && (
              <div className="px-4 pb-3">
                <div className="relative">
                  <textarea
                    value={transcript}
                    onChange={(e) => setTranscriptForTab(e.target.value, 'paste')}
                    placeholder=""
                    rows={6}
                    className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed min-h-[120px] max-h-[28vh] lg:max-h-[32vh] overflow-y-auto"
                    style={{
                      background: 'rgba(0,0,0,0.35)',
                      border: transcript.trim() ? '1px solid rgba(255,255,255,0.06)' : '1px dashed rgba(125,211,252,0.22)',
                    }}
                  />
                  {!transcript.trim() && (
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-5 text-center">
                      <div className="max-w-xs">
                        <div className="w-10 h-10 rounded-2xl mx-auto mb-3 flex items-center justify-center"
                          style={{ background: 'rgba(14,165,233,0.09)', border: '1px solid rgba(14,165,233,0.18)' }}>
                          <svg className="w-5 h-5 text-sky-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16h8M8 12h8m-8-4h5M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H9l-3 3v11a2 2 0 002 2z" />
                          </svg>
                        </div>
                        <p className="text-sm font-medium text-slate-200">Paste your meeting transcript here</p>
                        <p className="text-[11px] text-slate-500 mt-1">
                          Use speaker labels like <span className="text-slate-400">Sarah:</span> and <span className="text-slate-400">Mike:</span> for stronger decisions, ownership, and sentiment output.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between gap-3 mt-2.5 sticky bottom-0 pt-2.5"
                  style={{ background: 'linear-gradient(180deg, rgba(7,4,15,0), rgba(7,4,15,0.88) 28%, rgba(7,4,15,0.96) 100%)' }}>
                  <span className="text-[11px] text-gray-600">
                    {transcript.length > 0 ? `${transcriptStats.words} words · ${transcriptSpeakerCount || 0} named speakers` : 'No transcript'}
                  </span>
                  <button onClick={loading ? cancelActiveAnalysis : handleAnalyzeClick} disabled={!transcript.trim() && !loading}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98] flex-shrink-0"
                    style={{ background: loading ? 'linear-gradient(135deg, #dc2626, #b91c1c)' : 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: loading ? '0 4px 20px rgba(220,38,38,0.35)' : '0 4px 20px rgba(2,132,199,0.35)' }}>
                    {loading ? (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>Cancel</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
                  </button>
                </div>
              </div>
            )}

            {/* Record Audio */}
            {inputTab === 'record' && (
              <div className="px-4 pb-3">
                <p className="text-[11px] text-gray-500 mb-3">Speak — your words will appear below. Hit Analyze when done.</p>
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
                    <textarea value={transcript} onChange={(e) => setTranscriptForTab(e.target.value, 'record')} rows={5}
                      className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed min-h-[120px] max-h-[28vh] lg:max-h-[32vh] overflow-y-auto"
                      style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }} />
                    <div className="flex justify-between items-center gap-3 mt-2.5">
                      <span className="text-[11px] text-gray-600">{transcriptStats.words} words · {transcriptSpeakerCount || 0} named speakers</span>
                      <button onClick={loading ? cancelActiveAnalysis : handleAnalyzeClick} disabled={!transcript.trim() && !loading}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 hover:scale-[1.02] active:scale-[0.98] flex-shrink-0"
                        style={{ background: loading ? 'linear-gradient(135deg, #dc2626, #b91c1c)' : 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: loading ? '0 4px 20px rgba(220,38,38,0.35)' : '0 4px 20px rgba(2,132,199,0.35)' }}>
                        {loading ? (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>Cancel</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
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
              <div className="px-4 pb-3">
                <p className="text-[11px] text-gray-500 mb-3">Upload audio — Whisper will transcribe it. Supports mp3, wav, m4a, ogg, webm (max 25MB).</p>
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
                    <textarea value={transcript} onChange={(e) => setTranscriptForTab(e.target.value, 'upload')} rows={5}
                      className="w-full rounded-xl px-3 py-3 text-xs font-mono text-gray-300 resize-none outline-none leading-relaxed min-h-[120px] max-h-[28vh] lg:max-h-[32vh] overflow-y-auto"
                      style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.06)' }} />
                    <div className="flex justify-between items-center gap-3 mt-2.5">
                      <span className="text-[11px] text-gray-600">{transcriptStats.words} words · {transcriptSpeakerCount || 0} named speakers</span>
                      <button onClick={loading ? cancelActiveAnalysis : handleAnalyzeClick} disabled={!transcript.trim() && !loading}
                        className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all disabled:opacity-40 hover:scale-[1.02] active:scale-[0.98] flex-shrink-0"
                        style={{ background: loading ? 'linear-gradient(135deg, #dc2626, #b91c1c)' : 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: loading ? '0 4px 20px rgba(220,38,38,0.35)' : '0 4px 20px rgba(2,132,199,0.35)' }}>
                        {loading ? (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>Cancel</>) : (<><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>Analyze Meeting</>)}
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
                {/* Upcoming meetings from Google Calendar */}
                {calendarConnected && user && (
                  <div className="mb-3">
                    <Suspense fallback={null}>
                      <UpcomingMeetings onJoin={(url) => setMeetingUrl(url)} />
                    </Suspense>
                  </div>
                )}

                <p className="text-[11px] text-gray-500 mb-3 leading-relaxed">
                  {calendarConnected
                    ? 'Or paste a link manually:'
                    : 'Paste a Zoom, Google Meet, or Teams link. PrismAI will join the meeting, record, and automatically analyze it when it ends.'}
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
                        <p className="text-[10px] text-gray-600 mt-0.5">Listening for "Prism, ..." commands · Results when meeting ends</p>
                      )}
                      {botStatus === 'recording' && activeLiveToken && (
                        <button
                          onClick={() => {
                            const url = `${window.location.origin}${window.location.pathname}#live/${activeLiveToken}`
                            navigator.clipboard.writeText(url).then(() => {
                              setLiveShareCopied(true)
                              setTimeout(() => setLiveShareCopied(false), 2000)
                            })
                          }}
                          className="mt-1 text-[10px] px-2 py-0.5 rounded-md transition-colors"
                          style={{ background: liveShareCopied ? 'rgba(14,165,233,0.15)' : 'rgba(255,255,255,0.05)', color: liveShareCopied ? '#7dd3fc' : '#6b7280', border: '1px solid rgba(255,255,255,0.08)' }}>
                          {liveShareCopied ? '✓ Copied!' : '⬡ Copy live link'}
                        </button>
                      )}
                    </div>
                    {botStatus === 'recording'
                      ? <span className="ml-auto w-2 h-2 rounded-full bg-red-500 animate-pulse flex-shrink-0"></span>
                      : <button onClick={cancelBot} className="ml-auto text-[10px] px-2 py-1 rounded-lg flex-shrink-0 text-slate-400 hover:text-white transition-colors" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}>Cancel</button>
                    }
                  </div>
                )}

                {/* Live command log */}
                {botStatus === 'recording' && liveCommands.length > 0 && (
                  <div className="mt-2 rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div className="px-3 py-1.5 flex items-center gap-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <svg className="w-3 h-3 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                      <span className="text-[10px] font-medium text-violet-300">Live commands</span>
                      <span className="ml-auto text-[9px] text-gray-600">{liveCommands.length}</span>
                    </div>
                    <div className="max-h-28 overflow-y-auto">
                      {liveCommands.slice(-5).map((cmd, i) => (
                        <div key={i} className="px-3 py-1.5 flex items-start gap-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                          <svg className="w-2.5 h-2.5 text-emerald-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                          </svg>
                          <div className="min-w-0">
                            <p className="text-[10px] text-gray-300 truncate">"{cmd.command}"</p>
                            <p className="text-[9px] text-gray-600 truncate">
                              {cmd.speaker && <span>{cmd.speaker} · </span>}
                              {cmd.tools?.length ? cmd.tools.join(', ') : 'responded'}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {botStatus === 'error' && botError && (
                  <div className="mt-3">
                    <ErrorCard message={botError} onRetry={joinMeeting} />
                  </div>
                )}

                {botStatus === 'done' && (
                  <div className="mt-3 space-y-2">
                    {result ? (
                      <button
                        onClick={() => setMobileTab('results')}
                        className="w-full px-3 py-2.5 rounded-xl text-[11px] text-emerald-300 flex items-center gap-2 animate-fade-in-up cursor-pointer hover:bg-emerald-500/10 transition-colors"
                        style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)' }}>
                        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        Analysis complete — view results
                        <svg className="w-3 h-3 ml-auto flex-shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                    ) : botTranscriptReady ? (
                      <button
                        onClick={() => { setInputTab('paste'); handleAnalyzeClick() }}
                        className="w-full px-3 py-2.5 rounded-xl text-[11px] text-emerald-300 flex items-center gap-2 animate-fade-in-up cursor-pointer hover:bg-emerald-500/10 transition-colors"
                        style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)' }}>
                        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        Transcript ready — analyze now
                      </button>
                    ) : (
                      <div className="w-full px-3 py-2.5 rounded-xl text-[11px] text-emerald-300 flex items-center gap-2 animate-fade-in-up"
                        style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)' }}>
                        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                        Meeting finished successfully
                      </div>
                    )}
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

          {/* Historical intelligence — between transcript and chat */}
          {user && history.length > 1 && (
            <div className="mt-1 mb-1">
              <button
                className="w-full flex items-center justify-between px-6 py-1.5 hover:opacity-70 transition-opacity"
                onClick={() => {
                  const next = !insightsCollapsed
                  setInsightsCollapsed(next)
                  try { localStorage.setItem('prism_insights_collapsed', String(next)) } catch {}
                }}
              >
                <div className="flex items-center gap-1.5">
                  <svg className="w-3 h-3 text-gray-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                  </svg>
                  <span className="text-[11px] text-gray-600">Historical data · {history.length} meetings</span>
                </div>
                <svg className={`w-3 h-3 text-gray-700 transition-transform mr-6 ${insightsCollapsed ? '' : 'rotate-180'}`}
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="18 15 12 9 6 15"/>
                </svg>
              </button>
              {!insightsCollapsed && (
                <div className="flex flex-col gap-3 mt-1 mb-2">
                  <Suspense fallback={null}>
                    <ScoreTrendChart history={history} onSelect={loadFromHistory} />
                  </Suspense>
                  <Suspense fallback={null}>
                    <CrossMeetingInsights history={history} insights={crossMeetingInsights} onSelect={loadFromHistory} />
                  </Suspense>
                </div>
              )}
            </div>
          )}

          {/* Chat panel */}
          <div className="mx-6 mb-4 flex-1 min-h-0">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center"
                style={{ background: 'rgba(14,165,233,0.15)', border: '1px solid rgba(14,165,233,0.25)' }}>
                <svg className="w-3 h-3 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <span className="text-xs font-semibold text-gray-400">Chat with meeting</span>
              {isDemoMode && (
                <button
                  onClick={() => setDemoChatOpen((v) => !v)}
                  className="ml-auto text-[11px] px-3 py-1.5 rounded-lg transition-colors"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', color: '#cbd5e1' }}>
                  {demoChatOpen ? 'Hide chat' : 'Open chat'}
                </button>
              )}
            </div>
            {isDemoMode && !demoChatOpen ? (
              <button
                onClick={() => setDemoChatOpen(true)}
                className="w-full rounded-[22px] px-4 py-4 text-left transition-all hover:scale-[1.005] active:scale-[0.995]"
                style={{
                  background: 'linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.02) 100%)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  boxShadow: '0 16px 34px rgba(2,132,199,0.05)',
                }}>
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(14,165,233,0.12)', border: '1px solid rgba(14,165,233,0.22)' }}>
                    <svg className="w-4 h-4 text-sky-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-white">Open demo chat</p>
                    <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">
                      Ask follow-up questions about the sample run only when you want to inspect the outputs more deeply.
                    </p>
                  </div>
                  <svg className="w-4 h-4 text-gray-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </button>
            ) : result ? (
              <Suspense fallback={<DeferredCardFallback lines={4} />}>
                <ChatPanel key={sessionId} meetingId={meetingId} initialMessages={initialMessages} transcript={transcript} result={result} onResultUpdate={(updated) => setResult(r => ({ ...r, ...updated }))} isSignedIn={Boolean(user)} compact />
              </Suspense>
            ) : (
              <div className="rounded-[24px] px-5 py-5"
                style={{
                  background: 'linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.02) 100%)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  boxShadow: '0 16px 34px rgba(2,132,199,0.05)',
                }}>
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(14,165,233,0.12)', border: '1px solid rgba(14,165,233,0.22)' }}>
                    <svg className="w-4 h-4 text-sky-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-white">Chat unlocks after analysis</p>
                    <p className="text-[11px] text-gray-400 mt-1 max-w-sm leading-relaxed">
                      Analyze the meeting first, then ask follow-up questions about decisions, owners, blockers, and timing.
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 mt-4">
                  {['What were the key decisions?', 'Who owns what?', 'What is the timeline?'].map((prompt) => (
                    <span key={prompt}
                      className="text-[11px] px-3 py-1.5 rounded-full text-gray-500"
                      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                      {prompt}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT PANEL — Results */}
        <div className="hidden lg:flex flex-1 flex-col overflow-y-auto">
          {loading ? (
            <div className="p-6 space-y-4">
              <PrismStoryPanel transcript={transcript} loading={true} result={result} analysisTime={analysisTime} />
              <PrismSignatureScene transcript={transcript} result={result} loading={true} />
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
              <PrismStoryPanel transcript={transcript} result={result} loading={false} analysisTime={analysisTime} />
              <PrismSignatureScene transcript={transcript} result={result} loading={false} />
              {/* Results header strip */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 flex-wrap">
                  <AgentTags agents={result.agents_run || []} />
                  {analysisTime && (
                    <span className="text-[11px] text-gray-600">
                      {analysisTime}s · ~{Math.round(analysisTime * 1.8 + 20)} min saved
                    </span>
                  )}
                  {!user && (
                    <>
                      <span
                        className="text-[11px] px-2.5 py-1 rounded-full"
                        style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.18)', color: '#fcd34d' }}>
                        Local only
                      </span>
                      <button
                        onClick={signInWithGoogle}
                        className="text-[11px] px-2.5 py-1 rounded-full font-medium transition-all hover:scale-[1.02]"
                        style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.18)', color: '#7dd3fc' }}>
                        Sign in to save
                      </button>
                    </>
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
                  <div className="relative" data-export-menu>
                    <button onClick={() => setShowExportMenu(v => !v)}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all"
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#9ca3af' }}>
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      Export
                    </button>
                    {showExportMenu && (
                      <div className="absolute right-0 top-9 w-44 rounded-xl shadow-2xl z-50 overflow-hidden animate-fade-in-up"
                        style={{ background: '#100c1e', border: '1px solid rgba(255,255,255,0.1)' }}>
                        <button onClick={() => { copyMarkdown(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                          {mdCopied ? 'Copied!' : 'Copy Markdown'}
                        </button>
                        <button onClick={() => { exportMarkdown(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                          Download .md
                        </button>
                        <button onClick={() => { exportPDF(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                          Download PDF
                        </button>
                        <button onClick={() => { exportToSlack(); setShowExportMenu(false) }}
                          disabled={exportingSlack}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>
                          {exportingSlack ? 'Sending...' : integrations.slack_webhook ? 'Send to Slack' : 'Connect Slack →'}
                        </button>
                        <button onClick={() => { exportToNotion(); setShowExportMenu(false) }}
                          disabled={exportingNotion}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.14c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z"/></svg>
                          {exportingNotion ? 'Exporting...' : integrations.notion_token ? 'Export to Notion' : 'Connect Notion →'}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Time saved banner */}
              {showTimeSaved && analysisTime && (() => {
                const mins = Math.round(analysisTime * 1.8 + 20)
                const tweetText = `Just analyzed my meeting in ${analysisTime}s with PrismAI — saved ~${mins} minutes of manual work. Try it: ${APP_URL}`
                return (
                  <div className="rounded-2xl px-4 py-3 flex items-center gap-3 animate-fade-in-up"
                    style={{ background: 'rgba(52,211,153,0.07)', border: '1px solid rgba(52,211,153,0.2)' }}>
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: 'rgba(52,211,153,0.15)', border: '1px solid rgba(52,211,153,0.25)' }}>
                      <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <p className="flex-1 text-xs text-emerald-300">
                      <span className="font-semibold">~{mins} minutes saved</span>
                      <span className="text-emerald-500 ml-1">— analyzed in {analysisTime}s</span>
                    </p>
                    <button
                      onClick={async () => {
                        try {
                          if (navigator.share) {
                            await navigator.share({
                              title: 'PrismAI',
                              text: tweetText,
                            })
                          } else {
                            await navigator.clipboard.writeText(tweetText)
                          }
                          setTimeSavedShared(true)
                          setTimeout(() => setTimeSavedShared(false), 2000)
                        } catch {
                          // user canceled or browser blocked share; no-op
                        }
                      }}
                      className="text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all hover:scale-105 flex-shrink-0"
                      style={{ background: 'rgba(52,211,153,0.12)', color: '#6ee7b7', border: '1px solid rgba(52,211,153,0.25)' }}>
                      {timeSavedShared ? 'Shared!' : 'Share'}
                    </button>
                    <button onClick={() => setShowTimeSaved(false)}
                      aria-label="Dismiss"
                      className="text-gray-700 hover:text-gray-400 transition-colors flex-shrink-0 p-0.5">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                )
              })()}

              <ErrorBoundary>
                {/* Proactive suggestions */}
                <Suspense fallback={<DeferredCardFallback lines={2} />}>
                  <ProactiveSuggestions result={result} transcript={transcript} />
                </Suspense>

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
                  <div className="animate-fade-in-up card-delay-4"><DecisionsCard decisions={result.decisions} /></div>
                </div>

                {/* Email + Calendar */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="animate-fade-in-up card-delay-5"><EmailCard email={result.follow_up_email} gmailConnected={calendarConnected} /></div>
                  <div className="animate-fade-in-up card-delay-6"><CalendarCard suggestion={result.calendar_suggestion} /></div>
                </div>

                {/* Speaker Coaching — full width */}
                <div className="animate-fade-in-up card-delay-6"><SpeakerCoachCard speakerCoach={result.speaker_coach} /></div>
              </ErrorBoundary>
            </div>
          ) : (
            <EmptyState
              onDemo={() => startDemo()}
              isDemoMode={isDemoMode}
              onUseOwnTranscript={isDemoMode ? exitDemoMode : undefined}
              inputModeLabel={inputModeMeta.label}
            />
          )}
        </div>

      {/* Mobile tab bar */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 z-40 flex"
          style={{ background: 'rgba(7,4,15,0.95)', borderTop: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(20px)', paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}>
          <button
            onClick={() => setMobileTab('input')}
            className={`flex-1 py-3 text-xs font-medium transition-colors ${mobileTab === 'input' ? 'text-sky-400' : 'text-gray-600'}`}>
            Input
          </button>
          <button
            onClick={() => hasResultsView && setMobileTab('results')}
            disabled={!hasResultsView}
            className={`flex-1 py-3 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${mobileTab === 'results' ? 'text-sky-400' : 'text-gray-600'}`}>
            Results
            {hasResultsView && (
              <span className={`w-1.5 h-1.5 rounded-full ${loading ? 'bg-sky-400 animate-pulse' : 'bg-emerald-400'}`} />
            )}
          </button>
        </div>

        {mobileTab === 'input' && inputTab !== 'join' && (
          <div className="lg:hidden fixed left-4 right-4 z-30" style={{ bottom: 'calc(3.25rem + env(safe-area-inset-bottom, 0px))' }}>
            <button
              onClick={loading ? cancelActiveAnalysis : handleAnalyzeClick}
              disabled={!transcript.trim() && !loading}
              className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-2xl text-sm font-semibold text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-2xl"
              style={{ background: loading ? 'linear-gradient(135deg, #dc2626, #b91c1c)' : 'linear-gradient(135deg, #0284c7, #0d9488)', boxShadow: loading ? '0 8px 30px rgba(220,38,38,0.35)' : '0 8px 30px rgba(2,132,199,0.35)' }}
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                  Cancel
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Analyze Meeting
                </>
              )}
            </button>
          </div>
        )}

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
              <div className="pt-4">
                <PrismStoryPanel transcript={transcript} result={result} loading={false} analysisTime={analysisTime} />
                <div className="mt-4">
                  <PrismSignatureScene transcript={transcript} result={result} loading={false} />
                </div>
              </div>
              <div className="flex items-center justify-between pt-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <AgentTags agents={result.agents_run || []} />
                  {analysisTime && (
                    <span className="text-[11px] text-gray-600">{analysisTime}s · ~{Math.round(analysisTime * 1.8 + 20)} min saved</span>
                  )}
                  {!user && (
                    <>
                      <span
                        className="text-[11px] px-2.5 py-1 rounded-full"
                        style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.18)', color: '#fcd34d' }}>
                        Local only
                      </span>
                      <button
                        onClick={signInWithGoogle}
                        className="text-[11px] px-2.5 py-1 rounded-full font-medium transition-all hover:scale-[1.02]"
                        style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.18)', color: '#7dd3fc' }}>
                        Sign in to save
                      </button>
                    </>
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
                  <div className="relative" data-export-menu>
                    <button onClick={() => setShowExportMenu(v => !v)}
                      className="text-xs px-3 py-1.5 rounded-lg text-gray-400"
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
                      Export
                    </button>
                    {showExportMenu && (
                      <div className="absolute right-0 top-9 w-44 rounded-xl shadow-2xl z-50 overflow-hidden animate-fade-in-up"
                        style={{ background: '#100c1e', border: '1px solid rgba(255,255,255,0.1)' }}>
                        <button onClick={() => { copyMarkdown(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                          {mdCopied ? 'Copied!' : 'Copy Markdown'}
                        </button>
                        <button onClick={() => { exportMarkdown(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                          Download .md
                        </button>
                        <button onClick={() => { exportPDF(); setShowExportMenu(false) }}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                          Download PDF
                        </button>
                        <button onClick={() => { exportToSlack(); setShowExportMenu(false) }}
                          disabled={exportingSlack}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>
                          {exportingSlack ? 'Sending...' : integrations.slack_webhook ? 'Send to Slack' : 'Connect Slack →'}
                        </button>
                        <button onClick={() => { exportToNotion(); setShowExportMenu(false) }}
                          disabled={exportingNotion}
                          className="w-full text-left px-4 py-2.5 text-xs text-gray-300 hover:bg-white/5 transition-colors flex items-center gap-2 disabled:opacity-50"
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.14c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z"/></svg>
                          {exportingNotion ? 'Exporting...' : integrations.notion_token ? 'Export to Notion' : 'Connect Notion →'}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {showTimeSaved && analysisTime && (() => {
                const mins = Math.round(analysisTime * 1.8 + 20)
                const tweetText = `Just analyzed my meeting in ${analysisTime}s with PrismAI — saved ~${mins} minutes of manual work. Try it: ${APP_URL}`
                return (
                  <div className="rounded-2xl px-4 py-3 flex items-center gap-3 animate-fade-in-up"
                    style={{ background: 'rgba(52,211,153,0.07)', border: '1px solid rgba(52,211,153,0.2)' }}>
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: 'rgba(52,211,153,0.15)', border: '1px solid rgba(52,211,153,0.25)' }}>
                      <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </div>
                    <p className="flex-1 text-xs text-emerald-300">
                      <span className="font-semibold">~{mins} minutes saved</span>
                      <span className="text-emerald-500 ml-1">· analyzed in {analysisTime}s</span>
                    </p>
                    <button
                      onClick={async () => {
                        try {
                          if (navigator.share) {
                            await navigator.share({
                              title: 'PrismAI',
                              text: tweetText,
                            })
                          } else {
                            await navigator.clipboard.writeText(tweetText)
                          }
                          setTimeSavedShared(true)
                          setTimeout(() => setTimeSavedShared(false), 2000)
                        } catch {
                          // user canceled or browser blocked share; no-op
                        }
                      }}
                      className="text-[11px] px-2.5 py-1.5 rounded-lg font-medium flex-shrink-0"
                      style={{ background: 'rgba(52,211,153,0.12)', color: '#6ee7b7', border: '1px solid rgba(52,211,153,0.25)' }}>
                      {timeSavedShared ? 'Shared!' : 'Share'}
                    </button>
                    <button onClick={() => setShowTimeSaved(false)} aria-label="Dismiss" className="text-gray-700 hover:text-gray-400 transition-colors flex-shrink-0 p-0.5">
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                )
              })()}
              <ErrorBoundary>
                <Suspense fallback={<DeferredCardFallback lines={2} />}>
                  <ProactiveSuggestions result={result} transcript={transcript} />
                </Suspense>
                <div className="animate-fade-in-up card-delay-0"><HealthScoreCard healthScore={result.health_score} /></div>
                <div className="animate-fade-in-up card-delay-1"><SummaryCard summary={result.summary} /></div>
                <div className="animate-fade-in-up card-delay-2"><ActionItemsCard actionItems={result.action_items} onToggle={toggleActionItem} /></div>
                <div className="animate-fade-in-up card-delay-3"><DecisionsCard decisions={result.decisions} /></div>
                <div className="animate-fade-in-up card-delay-4"><SentimentCard sentiment={result.sentiment} /></div>
                <div className="animate-fade-in-up card-delay-5"><EmailCard email={result.follow_up_email} gmailConnected={calendarConnected} /></div>
                <div className="animate-fade-in-up card-delay-6"><CalendarCard suggestion={result.calendar_suggestion} /></div>
                <div className="animate-fade-in-up card-delay-6"><SpeakerCoachCard speakerCoach={result.speaker_coach} /></div>
              </ErrorBoundary>
            </div>
          ) : (
            <EmptyState
              onDemo={() => startDemo()}
              isDemoMode={isDemoMode}
              onUseOwnTranscript={isDemoMode ? exitDemoMode : undefined}
              inputModeLabel={inputModeMeta.label}
            />
          )}
        </div>

      </div>

      {/* Integrations modal */}
      {showIntegrations && (
        <Suspense fallback={null}>
          <IntegrationsModal
            integrations={integrations}
            onSave={setIntegrations}
            onClose={() => setShowIntegrations(false)}
            calendarConnected={calendarConnected}
            onConnectCalendar={connectGoogleCalendar}
            onDisconnectCalendar={disconnectCalendar}
            autoJoinSetting={autoJoinSetting}
            onAutoJoinChange={saveAutoJoinSetting}
            isSignedIn={!!user}
            isTestAccount={isTestAccount}
          />
        </Suspense>
      )}

      {/* Auto-join prompt toast */}
      {autoJoinPrompt && (
        <div className="fixed top-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-2xl shadow-2xl animate-fade-in-up"
          style={{ background: 'rgba(7,12,28,0.96)', border: '1px solid rgba(14,165,233,0.35)', backdropFilter: 'blur(20px)', maxWidth: '90vw' }}>
          <svg className="w-4 h-4 text-sky-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-white truncate">{autoJoinPrompt.title}</p>
            <p className="text-[10px] text-gray-400">
              {autoJoinPrompt.minsUntil <= 0 ? 'Starting now' : `Starts in ${autoJoinPrompt.minsUntil}m`}
            </p>
          </div>
          <button
            onClick={() => {
              setAutoJoinPrompt(null)
              setInputTab('join')
              setMeetingUrl(autoJoinPrompt.url)
            }}
            className="text-[11px] font-semibold px-3 py-1.5 rounded-lg flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)', color: '#fff' }}>
            Join
          </button>
          <button
            onClick={() => setAutoJoinPrompt(null)}
            aria-label="Dismiss"
            className="text-gray-600 hover:text-gray-300 transition-colors flex-shrink-0 p-1">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {workspaceToast && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-2xl shadow-2xl animate-fade-in-up"
          style={{
            background: 'rgba(14,165,233,0.14)',
            border: '1px solid rgba(14,165,233,0.28)',
            backdropFilter: 'blur(16px)',
          }}>
          <svg className="w-4 h-4 text-sky-300 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <span className="text-xs font-medium text-sky-100">{workspaceToast}</span>
        </div>
      )}

      {/* Integration export toast */}
      {integrationToast && (
        <div className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 px-4 py-3 rounded-2xl shadow-2xl animate-fade-in-up"
          style={{
            background: integrationToast.type === 'ok' ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
            border: `1px solid ${integrationToast.type === 'ok' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            backdropFilter: 'blur(16px)',
          }}>
          {integrationToast.type === 'ok' ? (
            <svg className="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-red-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          )}
          <span className={`text-xs font-medium ${integrationToast.type === 'ok' ? 'text-emerald-300' : 'text-red-300'}`}>
            {integrationToast.msg}
          </span>
          {integrationToast.url && (
            <a href={integrationToast.url} target="_blank" rel="noopener noreferrer"
              className="text-xs text-sky-400 hover:text-sky-300 underline ml-1">
              Open →
            </a>
          )}
        </div>
      )}
    </div>
  )
}

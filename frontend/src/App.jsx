import { useState, useRef, useEffect, useCallback, Component, Suspense, lazy } from 'react'
import { UI_SCREEN_KEY, VISITED_KEY, TEST_RUN_SESSION_KEY } from './lib/sessionKeys'
import { deriveDisplayTitle } from './lib/insights'
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
import EmailCard from './components/dashboard/EmailCard'
import CalendarCard from './components/dashboard/CalendarCard'
import SpeakerCoachCard from './components/dashboard/SpeakerCoachCard'
import SkeletonCard from './components/SkeletonCard'
import ErrorCard from './components/ErrorCard'
import DashboardPage from './components/DashboardPage'
import MeetingView from './components/dashboard/MeetingView'
import { supabase } from './lib/supabase'
import { apiFetch } from './lib/api'

const ChatPanel = lazy(() => import('./components/ChatPanel'))
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
  window.location.pathname === '/dashboard' &&
  new URLSearchParams(window.location.search).get(TEST_RUN_QUERY_PARAM) === '1'

if (isDashboardTestRunRequest) {
  sessionStorage.setItem(TEST_RUN_SESSION_KEY, '1')
}

const isTestRunSession = () =>
  typeof window !== 'undefined' &&
  window.location.pathname === '/dashboard' &&
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

// ── Empty state for right panel ──────────────────────────────────

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
          title: result.title || result.summary?.slice(0, 80).split('.')[0] || 'Meeting',
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
function LandingScreen({ onViewDashboard }) {
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
    <div className="landing-page-shell">
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
        <div className="relative z-10 w-full" style={{ height: '100vh' }}>
          {/* Rotating pain-point text — top edge at 17% */}
          <div className="absolute w-full flex justify-center px-6 animate-fade-in-up" style={{ top: '17%', animationDelay: '0.2s' }}>
            <div className="w-full max-w-[min(100%,67rem)] h-[5rem] sm:h-[7rem] lg:h-[12rem] flex items-center justify-center">
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
                mainClassName="w-full justify-center text-center text-[clamp(1.5rem,5.5vw,4.5rem)] font-medium leading-tight tracking-tight text-white/85"
                splitLevelClassName="overflow-hidden pb-1"
                elementLevelClassName="font-medium"
                style={{ fontFamily: "'Rubik', 'General Sans', sans-serif", fontWeight: 500 }}
              />
            </div>
          </div>

          {/* Tagline — centerline at 50% */}
          <div style={{ position: 'absolute', top: '55%', left: 0, right: 0, transform: 'translateY(-50%)', display: 'flex', justifyContent: 'center', padding: '0 1.5rem' }}>
            <div className="animate-fade-in-up" style={{ animationDelay: '0.45s' }}>
              <p className="text-4xl sm:text-5xl lg:text-6xl xl:text-7xl font-semibold tracking-tight text-white text-center">
                Let <span className="font-light">prism</span> handle it.
              </p>
            </div>
          </div>

          {/* CTA buttons — centerline at 69% */}
          <div style={{ position: 'absolute', top: '69%', left: 0, right: 0, transform: 'translateY(-50%)', display: 'flex', justifyContent: 'center', padding: '0 1.5rem' }}>
            <div className="cta-row animate-fade-in-up" style={{ animationDelay: '0.65s' }}>
              <button type="button" className="btn-primary landing-button-primary" onClick={openSignup}>Get started</button>
              <span className="cta-or">or</span>
              <button type="button" className="btn-ghost landing-button-secondary" onClick={onViewDashboard}>View dashboard</button>
            </div>
          </div>
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
  const [transcript, setTranscript] = useState('')
  const [transcriptDrafts, setTranscriptDrafts] = useState({ paste: '', record: '', upload: '' })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [analysisTime, setAnalysisTime] = useState(null) // seconds elapsed
  const [showTimeSaved, setShowTimeSaved] = useState(false)
  const analysisStartRef = useRef(null)
  const analysisAbortRef = useRef(null)
  const analysisRunIdRef = useRef(0)
  const hasResultsView = loading || Boolean(result)
  const isDashboard = typeof window !== 'undefined' && window.location.pathname === '/dashboard'

  // Show landing only to first-time visitors (not returning users, not share links)
  const showLanding =
    typeof window !== 'undefined' &&
    window.location.pathname !== '/dashboard' &&
    !INITIAL_SHARE_TOKEN &&
    !INITIAL_LIVE_TOKEN
  const [isDemoMode, setIsDemoMode] = useState(false)
  const [demoChatOpen, setDemoChatOpen] = useState(false)

  const enterDashboardTestRun = () => {
    sessionStorage.setItem(TEST_RUN_SESSION_KEY, '1')
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    sessionStorage.removeItem('prism_active_bot_id')
    sessionStorage.removeItem('prism_active_live_token')
    sessionStorage.removeItem('prism_new_meeting')
    window.location.href = `/dashboard?${TEST_RUN_QUERY_PARAM}=1`
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

  const titleBackfillDone = useRef(false)
  useEffect(() => {
    if (!user || isTestAccount || history.length === 0 || titleBackfillDone.current) return
    const stale = history.filter((e) => /^the meeting\b/i.test(e.title || ''))
    if (stale.length === 0) { titleBackfillDone.current = true; return }
    titleBackfillDone.current = true
    const updates = stale
      .map((e) => ({ id: e.id, title: deriveDisplayTitle(e) }))
      .filter((u) => u.title && u.title !== stale.find((e) => e.id === u.id)?.title)
    if (updates.length === 0) return
    setHistory((prev) => prev.map((e) => {
      const u = updates.find((x) => x.id === e.id)
      return u ? { ...e, title: u.title } : e
    }))
    updates.forEach(({ id, title }) => {
      apiFetch(`/meetings/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      }).catch(() => {})
    })
  }, [history, user, isTestAccount])

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
      if (_event === 'SIGNED_IN') {
        if (window.location.pathname !== '/dashboard' && sessionStorage.getItem(UI_SCREEN_KEY) !== 'landing') {
          sessionStorage.setItem(VISITED_KEY, '1')
          sessionStorage.setItem(UI_SCREEN_KEY, 'app')
          window.location.replace('/dashboard')
        }
      }
    })

    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (!authReady || INITIAL_SHARE_TOKEN || isDashboard) return
    if (sessionStorage.getItem(UI_SCREEN_KEY) === 'landing') return
    if (user && !isTestAccount) {
      sessionStorage.setItem(VISITED_KEY, '1')
      sessionStorage.setItem(UI_SCREEN_KEY, 'app')
      window.location.replace('/dashboard')
    }
  }, [authReady, user?.id, isTestAccount, isDashboard])

  useEffect(() => {
    if (!authReady || !isDashboard || !isTestAccount) return
    if (new URLSearchParams(window.location.search).get(TEST_RUN_QUERY_PARAM) === '1') {
      window.history.replaceState({}, '', '/dashboard')
    }
    setWorkspaceToast('Test account loaded.')
    const timeoutId = setTimeout(() => setWorkspaceToast(null), 2500)
    return () => clearTimeout(timeoutId)
  }, [authReady, isDashboard, isTestAccount])

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
        redirectTo: `${window.location.origin}/dashboard`,
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
    // Prevent duplicate bot creation if one is already active
    if (activeBotId && botStatus && !['done', 'error'].includes(botStatus)) return
    setBotError(null)
    setBotTranscriptReady(false)
    setLiveCommands([])
    setBotStatus('joining')
    try {
      const res = await apiFetch('/join-meeting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          meeting_url: meetingUrl,
          owner_name: user?.user_metadata?.full_name || user?.email?.split('@')[0] || null,
        }),
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
      body: JSON.stringify({
        meeting_url: url,
        owner_name: user?.user_metadata?.full_name || user?.email?.split('@')[0] || null,
      }),
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
      title: r.title || r.summary?.slice(0, 65) || 'Meeting',
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
    // Active chat is ephemeral per visit — always start blank. Past sessions are surfaced
    // via the chat panel's per-meeting history dropdown (fetched in DashboardPage).
    setInitialMessages([])
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
          follow_up_email: { subject: 'Q2 Roadmap — follow-up & next steps', body: 'Hi team,\n\nThanks for a productive planning session. Quick recap of what we landed on:\n\n• Checkout improvements and mobile redesign are locked for Q2.\n• Analytics dashboard moves to Q3 — Mike will update the roadmap by Thursday EOD.\n• Lisa will draft the enterprise client message by Wednesday.\n• Mike to finalize feature specs for the marketing launch by next Friday.\n\nLet me know if anything needs revisiting before then.\n\nBest,\nSarah' },
          calendar_suggestion: { recommended: true, reason: 'A short check-in next week will confirm roadmap updates are complete before sprint planning.', suggested_timeframe: 'Next Thursday', resolved_date: '', resolved_day: 'Thursday' },
          speaker_coach: { speakers: [{ name: 'Sarah', talk_percent: 38, decisions_owned: 2, action_items_owned: 0, coaching_note: 'Strong facilitation — consider inviting quieter voices earlier to surface blockers faster.' }, { name: 'Mike', talk_percent: 32, decisions_owned: 1, action_items_owned: 2, coaching_note: 'Good ownership of follow-ups; watch for over-qualifying estimates when time is short.' }, { name: 'Lisa', talk_percent: 30, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Solid contributions — bringing client context earlier would strengthen prioritisation decisions.' }], balance_score: 96 },
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
          follow_up_email: { subject: 'Payment outage postmortem — action items & safeguards', body: 'Hi everyone,\n\nThank you for a thorough postmortem. Here is what we committed to:\n\n• Priya: alert on connection pool utilization above 70% by end of week.\n• Marcus: update the infra change review checklist by Thursday.\n• Priya: draft runbook for connection pool exhaustion by next Monday.\n\nGoing forward, all connection limit config changes require a second on-call reviewer sign-off.\n\nLet me know if I missed anything.\n\nBest,\nAlex' },
          calendar_suggestion: { recommended: false, reason: 'All action items have owners and due dates — no follow-up meeting is needed at this stage.', suggested_timeframe: '', resolved_date: '', resolved_day: '' },
          speaker_coach: { speakers: [{ name: 'Alex', talk_percent: 42, decisions_owned: 1, action_items_owned: 0, coaching_note: 'Effective at driving conclusions — allow more space after tense moments before pressing for decisions.' }, { name: 'Priya', talk_percent: 35, decisions_owned: 0, action_items_owned: 2, coaching_note: 'High ownership and strong technical depth; summarising findings upfront would save time.' }, { name: 'Marcus', talk_percent: 23, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Concise and direct — adding more context around the checklist gap would strengthen accountability.' }], balance_score: 78 },
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
          follow_up_email: { subject: 'Q2 Sales strategy — commitments and targets', body: 'Hi team,\n\nGreat session today. Here is what we are driving toward in Q2:\n\n• Target: 15 net-new enterprise logos.\n• Weekly pipeline review every Monday at 9am starting next week.\n• Rachel: standard contract template with legal by end of April.\n• Carlos & Rachel: MEDDIC certification by April 30.\n• Carlos: competitive battle cards for top two competitors by next Friday.\n\nLet\'s make Q2 the turnaround quarter.\n\nBest,\nDiana' },
          calendar_suggestion: { recommended: true, reason: 'A pipeline review cadence was agreed — the first session should be confirmed on the calendar.', suggested_timeframe: 'Next Monday at 9am', resolved_date: '', resolved_day: 'Monday' },
          speaker_coach: { speakers: [{ name: 'Diana', talk_percent: 44, decisions_owned: 2, action_items_owned: 0, coaching_note: 'Strong direction-setting — leaving more room for Rachel and Carlos to problem-solve would increase buy-in.' }, { name: 'Rachel', talk_percent: 30, decisions_owned: 0, action_items_owned: 2, coaching_note: 'Good on execution detail; raising risks earlier in the discussion would improve planning.' }, { name: 'Carlos', talk_percent: 26, decisions_owned: 0, action_items_owned: 2, coaching_note: 'Practical and accountable — sharing competitive intelligence proactively would add more value.' }], balance_score: 82 },
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
          follow_up_email: { subject: 'Q3 Budget — next steps before we reconvene', body: 'Hi Greg, Kevin, and Tara,\n\nFollowing up on today\'s session. We did not reach a budget decision, but here is what needs to happen before we meet again:\n\n• Greg: fix the spreadsheet formula error.\n• Kevin: forward the prior budget scope-change email.\n• Everyone: review team spend before we reconvene this week.\n\nOnce those are done we should be in a better position to align. I will send a calendar invite for a follow-up.\n\nBest,\nAbhinav' },
          calendar_suggestion: { recommended: true, reason: 'No decisions were made and the spreadsheet data was incorrect — a follow-up is essential before the quarter closes.', suggested_timeframe: 'Later this week', resolved_date: '', resolved_day: '' },
          speaker_coach: { speakers: [{ name: 'Greg', talk_percent: 36, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Brought technical clarity on the spreadsheet — leading with the data issue earlier would have saved time.' }, { name: 'Kevin', talk_percent: 34, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Good at surfacing context; follow up on the email distribution gap more assertively.' }, { name: 'Tara', talk_percent: 30, decisions_owned: 0, action_items_owned: 0, coaching_note: 'Flagged a real access gap early — pushing for a resolution or clear owner in the moment would help move things forward.' }], balance_score: 95 },
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
          follow_up_email: { subject: 'Onboarding research readout — next steps', body: 'Hi team,\n\nThanks for a great session. The research surfaced a clear drop-off point and we have a solid plan to address it:\n\nShort term:\n• Tyler: tooltip copy and updated step 3 instructions by Friday.\n• Casey: pricing reassurance mockup in Figma today.\n\nLonger term:\n• Sam: scope the magic link flow for admin invitations by next Wednesday.\n\nDecision: ship the tooltip and email template fix as the immediate win, then revisit the magic link flow once scoped.\n\nExcited about this one.\n\nBest,\nMorgan' },
          calendar_suggestion: { recommended: true, reason: 'A retest with five users was agreed after the tooltip change ships — that session should be scheduled now.', suggested_timeframe: 'Two weeks out', resolved_date: '', resolved_day: '' },
          speaker_coach: { speakers: [{ name: 'Morgan', talk_percent: 40, decisions_owned: 2, action_items_owned: 0, coaching_note: 'Clear decision-maker and good at sequencing — giving the team more space to debate tradeoffs would strengthen alignment.' }, { name: 'Sam', talk_percent: 25, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Solid on the technical scope; sharing complexity estimates earlier helps the group prioritise.' }, { name: 'Tyler', talk_percent: 20, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Concise and reliable — proactively flagging copy dependencies would prevent last-minute bottlenecks.' }, { name: 'Casey', talk_percent: 15, decisions_owned: 0, action_items_owned: 1, coaching_note: 'Strong visual contributions — narrating design decisions as you share mockups helps non-designers follow the reasoning.' }], balance_score: 68 },
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

  // Landing screen — shown to first-time visitors
  if (showLanding) {
    return <LandingScreen onViewDashboard={enterDashboardTestRun} />
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
        <div className="px-4 pb-8 max-w-5xl mx-auto">
          <MeetingView result={r} readOnly />
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

  if (isDashboard) {
    const hasPendingOAuthCode = typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('code')
    if (authReady && !user && !isTestAccount && !hasPendingOAuthCode) {
      sessionStorage.setItem(UI_SCREEN_KEY, 'landing')
      window.location.replace('/')
      return null
    }

    return (
      <>
        <DashboardPage
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

  return null
}

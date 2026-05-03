// Single source of truth for all 8 ROYGBIV agents.
// App.jsx, AgentTags, and AgentShowcase all import from here.
export const AGENTS = [
  {
    id: 'summarizer',
    label: 'Summarizer',
    icon: '📝',
    grad: 'from-red-500 to-red-400',
    desc: 'Condenses the entire meeting into a clear summary of key topics and outcomes.',
    bg: 'bg-red-500/20', border: 'border-red-500/40', text: 'text-red-300', dot: 'bg-red-400',
  },
  {
    id: 'action_items',
    label: 'Action Items',
    icon: '✅',
    grad: 'from-orange-500 to-amber-400',
    desc: 'Extracts every task, assigns owners, and flags due dates so nothing falls through the cracks.',
    bg: 'bg-orange-500/20', border: 'border-orange-500/40', text: 'text-orange-300', dot: 'bg-orange-400',
  },
  {
    id: 'decisions',
    label: 'Decisions',
    icon: '⚖️',
    grad: 'from-yellow-400 to-yellow-300',
    desc: 'Logs every decision made in the meeting, ranked by importance, with the accountable owner.',
    bg: 'bg-yellow-500/20', border: 'border-yellow-500/40', text: 'text-yellow-200', dot: 'bg-yellow-400',
  },
  {
    id: 'sentiment',
    label: 'Sentiment',
    icon: '💬',
    grad: 'from-emerald-500 to-green-400',
    desc: 'Reads the emotional tone — per speaker, mood arc, and moments where tension spiked.',
    bg: 'bg-emerald-500/20', border: 'border-emerald-500/40', text: 'text-emerald-300', dot: 'bg-emerald-400',
  },
  {
    id: 'email_drafter',
    label: 'Email Draft',
    icon: '✉️',
    grad: 'from-blue-500 to-blue-400',
    desc: 'Writes a polished follow-up email ready to send to all attendees.',
    bg: 'bg-blue-500/20', border: 'border-blue-500/40', text: 'text-blue-300', dot: 'bg-blue-400',
  },
  {
    id: 'calendar_suggester',
    label: 'Calendar',
    icon: '📅',
    grad: 'from-indigo-500 to-indigo-400',
    desc: 'Detects if a follow-up meeting is needed and suggests the best timeframe.',
    bg: 'bg-indigo-500/20', border: 'border-indigo-500/40', text: 'text-indigo-300', dot: 'bg-indigo-400',
  },
  {
    id: 'health_score',
    label: 'Health Score',
    icon: '📊',
    grad: 'from-violet-500 to-purple-400',
    desc: 'Scores the meeting out of 100 across clarity, engagement, and action-orientation.',
    bg: 'bg-violet-500/20', border: 'border-violet-500/40', text: 'text-violet-300', dot: 'bg-violet-400',
  },
  {
    id: 'speaker_coach',
    label: 'Speaker Coach',
    icon: '🎤',
    grad: 'from-rose-500 to-pink-400',
    desc: "Shows each speaker's talk share, decisions and actions owned, and a one-line coaching note.",
    bg: 'bg-rose-500/20', border: 'border-rose-500/40', text: 'text-rose-300', dot: 'bg-rose-400',
  },
]

export const AGENTS_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a]))

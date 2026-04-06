import { useState } from 'react'

const STOP_WORDS = new Set([
  'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'will', 'into', 'your',
  'their', 'about', 'after', 'before', 'need', 'needs', 'next', 'then', 'than', 'just',
  'more', 'less', 'team', 'meeting', 'meetings', 'owner', 'owners', 'task', 'tasks',
  'action', 'actions', 'decision', 'decisions', 'update', 'draft', 'send', 'review',
  'schedule', 'timeline', 'launch', 'project', 'follow', 'email', 'calendar', 'high',
  'low', 'ready', 'work', 'works', 'done', 'doing', 'look', 'looks', 'through',
  'across', 'still', 'again', 'there', 'where', 'what', 'when', 'been', 'being',
  'they', 'them', 'were', 'make', 'made', 'gets', 'getting', 'into', 'onto', 'over',
  'under', 'today', 'tomorrow', 'yesterday', 'week', 'weeks', 'month', 'months',
])

const BLOCKER_KEYWORDS = [
  'blocked', 'blocker', 'delay', 'delayed', 'risk', 'risky', 'concern', 'concerns',
  'worried', 'worry', 'issue', 'issues', 'stuck', 'slip', 'slipping', 'outage',
  'degraded', 'preventable', 'missed', 'overcommit', 'overcommitting', 'dependency',
]

function formatMeetingDate(value) {
  if (!value) return 'Unknown date'
  return new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function normalizeWord(word) {
  return word
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '')
    .trim()
}

function extractSignificantTerms(text, minimumLength = 4) {
  return (text || '')
    .split(/\s+/)
    .map(normalizeWord)
    .filter((word) => word.length >= minimumLength && !STOP_WORDS.has(word))
}

function looksLikeBlocker(text) {
  const value = (text || '').toLowerCase()
  return BLOCKER_KEYWORDS.some((keyword) => value.includes(keyword))
}

function buildBlockerSnippet(text) {
  const clean = (text || '').replace(/\s+/g, ' ').trim()
  if (!clean) return ''
  return clean.length > 88 ? `${clean.slice(0, 85).trim()}...` : clean
}

function deriveInsights(history) {
  const meetings = [...history]
    .filter((entry) => entry?.result)
    .sort((a, b) => new Date(b.date) - new Date(a.date))

  const scoredMeetings = meetings.filter((entry) => entry.result?.health_score?.score !== undefined && entry.result?.health_score?.score !== null)
  const latestScore = scoredMeetings[0]?.result?.health_score?.score ?? null
  const oldestScore = scoredMeetings.at(-1)?.result?.health_score?.score ?? null
  const avgScore = scoredMeetings.length
    ? Math.round(scoredMeetings.reduce((sum, entry) => sum + (entry.result.health_score?.score ?? 0), 0) / scoredMeetings.length)
    : null
  const scoreDelta = latestScore !== null && oldestScore !== null ? latestScore - oldestScore : null

  const ownerCounts = new Map()
  const themeCounts = new Map()
  const decisionThemeCounts = new Map()
  const decisionMemory = []
  const blockerCounts = new Map()
  let tenseMeetings = 0

  meetings.forEach((entry) => {
    const result = entry.result || {}
    const items = result.action_items || []
    const decisions = result.decisions || []
    const sentiment = result.sentiment || {}

    if (['tense', 'unresolved', 'conflicted'].includes((sentiment.overall || '').toLowerCase())) {
      tenseMeetings += 1
    }

    items.forEach((item) => {
      const owner = (item.owner || '').trim()
      if (owner) ownerCounts.set(owner, (ownerCounts.get(owner) || 0) + 1)

      const text = `${item.task || ''} ${item.owner || ''} ${item.due || ''}`
      extractSignificantTerms(text).forEach((word) => {
        themeCounts.set(word, (themeCounts.get(word) || 0) + 1)
      })

      if (looksLikeBlocker(item.task || '')) {
        const snippet = buildBlockerSnippet(item.task || '')
        if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
      }
    })

    decisions.forEach((decision) => {
      const text = decision.decision || ''
      const decisionTerms = extractSignificantTerms(text)
      decisionTerms.forEach((word) => {
        themeCounts.set(word, (themeCounts.get(word) || 0) + 1)
        decisionThemeCounts.set(word, (decisionThemeCounts.get(word) || 0) + 1)
      })

      decisionMemory.push({
        id: `${entry.id}-${decision.decision}`,
        meeting: entry,
        title: decision.decision || 'Decision recorded',
        owner: decision.owner || '',
        importance: Number(decision.importance ?? 3),
        date: entry.date,
      })
    })

    const summaryText = result.summary || ''
    extractSignificantTerms(summaryText, 5).forEach((word) => {
      themeCounts.set(word, (themeCounts.get(word) || 0) + 1)
    })

    if (looksLikeBlocker(summaryText)) {
      const snippet = buildBlockerSnippet(summaryText)
      if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
    }

    if (looksLikeBlocker(sentiment.notes || '')) {
      const snippet = buildBlockerSnippet(sentiment.notes || '')
      if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
    }
  })

  const topOwners = [...ownerCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([owner, count]) => ({ owner, count }))

  const recurringThemes = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([theme, count]) => ({ theme, count }))

  const recurringBlockers = [...blockerCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([snippet, count]) => ({ snippet, count }))

  const resurfacingDecisionThemes = [...decisionThemeCounts.entries()]
    .filter(([, count]) => count > 1)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([theme, count]) => ({ theme, count }))

  const recentDecisions = decisionMemory
    .sort((a, b) => {
      if (a.importance !== b.importance) return a.importance - b.importance
      return new Date(b.date) - new Date(a.date)
    })
    .slice(0, 4)

  return {
    meetingCount: meetings.length,
    avgScore,
    latestScore,
    scoreDelta,
    tenseMeetings,
    topOwners,
    recurringThemes,
    recurringBlockers,
    resurfacingDecisionThemes,
    recentDecisions,
  }
}

export default function CrossMeetingInsights({ history, onSelect }) {
  const [expanded, setExpanded] = useState(false)
  const insights = deriveInsights(history)

  if (insights.meetingCount < 2) return null

  const deltaLabel = insights.scoreDelta === null
    ? 'stable'
    : insights.scoreDelta > 0
      ? `+${insights.scoreDelta}`
      : `${insights.scoreDelta}`

  const deltaColor = insights.scoreDelta === null
    ? '#94a3b8'
    : insights.scoreDelta > 0
      ? '#34d399'
      : insights.scoreDelta < 0
        ? '#f87171'
        : '#94a3b8'

  return (
    <div
      className="mx-6 mb-4 rounded-2xl overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(34,197,94,0.12)' }}
    >
      <button
        onClick={() => setExpanded((value) => !value)}
        className="w-full px-4 py-3 text-left"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-6m3 6V7m3 10v-4m5 8H4a1 1 0 01-1-1V4a1 1 0 011-1h16a1 1 0 011 1v16a1 1 0 01-1 1z" />
              </svg>
              <span className="text-xs font-semibold text-gray-400">Cross-Meeting Intelligence</span>
            </div>
            <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">
              PrismAI is spotting patterns across {insights.meetingCount} saved meetings, not just this one.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {insights.avgScore !== null && (
              <span className="text-[11px] px-2.5 py-1 rounded-full"
                style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.18)', color: '#86efac' }}>
                avg {insights.avgScore}/100
              </span>
            )}
            <span className="text-[11px] font-semibold" style={{ color: deltaColor }}>{deltaLabel}</span>
            <svg
              className={`w-3.5 h-3.5 text-gray-600 transition-transform ${expanded ? 'rotate-180' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {insights.topOwners[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
              Most active owner: {insights.topOwners[0].owner}
            </span>
          )}
          {insights.recurringThemes[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
              Recurring theme: {insights.recurringThemes[0].theme}
            </span>
          )}
          {insights.tenseMeetings > 0 && (
            <span className="text-[10px] px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.18)', color: '#fca5a5' }}>
              {insights.tenseMeetings} tense meeting{insights.tenseMeetings === 1 ? '' : 's'} in history
            </span>
          )}
          {insights.recurringBlockers[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.18)', color: '#fca5a5' }}>
              Recurring blocker signal detected
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          <div className="grid grid-cols-1 gap-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl px-3 py-3"
                style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.12)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-emerald-400/75">Momentum</p>
                <p className="text-lg font-semibold text-white mt-1">{insights.latestScore ?? '—'}</p>
                <p className="text-[11px] text-gray-500 mt-1">latest health score</p>
              </div>
              <div className="rounded-xl px-3 py-3"
                style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.12)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-sky-400/75">Owners</p>
                <p className="text-lg font-semibold text-white mt-1">{insights.topOwners.length || '—'}</p>
                <p className="text-[11px] text-gray-500 mt-1">repeat owners surfacing</p>
              </div>
              <div className="rounded-xl px-3 py-3"
                style={{ background: 'rgba(168,85,247,0.06)', border: '1px solid rgba(168,85,247,0.12)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-violet-400/75">Memory</p>
                <p className="text-lg font-semibold text-white mt-1">{insights.recentDecisions.length}</p>
                <p className="text-[11px] text-gray-500 mt-1">recent decisions tracked</p>
              </div>
            </div>

            {(insights.recurringBlockers.length > 0 || insights.resurfacingDecisionThemes.length > 0) && (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(248,113,113,0.05)', border: '1px solid rgba(248,113,113,0.12)' }}>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-rose-300/80">Recurring Blockers</p>
                  {insights.recurringBlockers.length > 0 ? (
                    <div className="space-y-2 mt-2">
                      {insights.recurringBlockers.map(({ snippet, count }) => (
                        <div key={snippet} className="rounded-lg px-3 py-2" style={{ background: 'rgba(255,255,255,0.025)' }}>
                          <p className="text-sm text-white leading-snug">{snippet}</p>
                          <p className="text-[11px] text-rose-300/80 mt-1">surfaced {count} time{count === 1 ? '' : 's'}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">No repeated blockers are surfacing yet.</p>
                  )}
                </div>

                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(250,204,21,0.05)', border: '1px solid rgba(250,204,21,0.12)' }}>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-amber-300/80">Decision Resurfacing</p>
                  {insights.resurfacingDecisionThemes.length > 0 ? (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {insights.resurfacingDecisionThemes.map(({ theme, count }) => (
                        <span
                          key={theme}
                          className="text-[11px] px-2.5 py-1 rounded-full"
                          style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.16)', color: '#fde68a' }}
                        >
                          {theme} · {count} mentions
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">Recent decisions are not repeating in a concerning way.</p>
                  )}
                </div>
              </div>
            )}

            {insights.topOwners.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Ownership Pattern</p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {insights.topOwners.map(({ owner, count }) => (
                    <span
                      key={owner}
                      className="text-[11px] px-2.5 py-1 rounded-full"
                      style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.16)', color: '#7dd3fc' }}
                    >
                      {owner} · {count} items
                    </span>
                  ))}
                </div>
              </div>
            )}

            {insights.recurringThemes.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Recurring Themes</p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {insights.recurringThemes.map(({ theme, count }) => (
                    <span
                      key={theme}
                      className="text-[11px] px-2.5 py-1 rounded-full"
                      style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.16)', color: '#fde047' }}
                    >
                      {theme} · {count}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {insights.recentDecisions.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Decision Memory</p>
                  <span className="text-[10px] text-gray-600">tap to load meeting</span>
                </div>
                <div className="space-y-2 mt-2">
                  {insights.recentDecisions.map((decision) => (
                    <button
                      key={decision.id}
                      onClick={() => onSelect?.(decision.meeting)}
                      className="w-full text-left rounded-xl px-3 py-2 transition-colors hover:bg-white/5"
                      style={{ border: '1px solid rgba(255,255,255,0.06)' }}
                    >
                      <p className="text-sm font-medium text-white leading-snug">{decision.title}</p>
                      <p className="text-[11px] text-gray-500 mt-1">
                        {formatMeetingDate(decision.date)}
                        {decision.owner ? ` · ${decision.owner}` : ''}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

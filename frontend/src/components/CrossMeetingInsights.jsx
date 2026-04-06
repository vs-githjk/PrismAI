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

function buildDecisionKey(text) {
  const terms = extractSignificantTerms(text, 4).slice(0, 3)
  return terms.join(' ')
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
  const ownerMeetingCounts = new Map()
  const themeCounts = new Map()
  const decisionThemeCounts = new Map()
  const decisionGroups = new Map()
  const decisionMemory = []
  const blockerCounts = new Map()
  const hygieneMeetings = []
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
      if (owner) {
        ownerCounts.set(owner, (ownerCounts.get(owner) || 0) + 1)
        if (!ownerMeetingCounts.has(owner)) ownerMeetingCounts.set(owner, new Set())
        ownerMeetingCounts.get(owner).add(entry.id)
      }

      const text = `${item.task || ''} ${item.owner || ''} ${item.due || ''}`
      extractSignificantTerms(text).forEach((word) => {
        themeCounts.set(word, (themeCounts.get(word) || 0) + 1)
      })

      if (looksLikeBlocker(item.task || '')) {
        const snippet = buildBlockerSnippet(item.task || '')
        if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
      }
    })

    const missingOwnerItems = items.filter((item) => !(item.owner || '').trim())
    const missingDueItems = items.filter((item) => !(item.due || '').trim())
    if (missingOwnerItems.length > 0 || missingDueItems.length > 0) {
      hygieneMeetings.push({
        meeting: entry,
        missingOwners: missingOwnerItems.length,
        missingDueDates: missingDueItems.length,
      })
    }

    decisions.forEach((decision) => {
      const text = decision.decision || ''
      const decisionTerms = extractSignificantTerms(text)
      const decisionKey = buildDecisionKey(text)
      decisionTerms.forEach((word) => {
        themeCounts.set(word, (themeCounts.get(word) || 0) + 1)
        decisionThemeCounts.set(word, (decisionThemeCounts.get(word) || 0) + 1)
      })

      const decisionEntry = {
        id: `${entry.id}-${decision.decision}`,
        meeting: entry,
        title: decision.decision || 'Decision recorded',
        owner: decision.owner || '',
        importance: Number(decision.importance ?? 3),
        date: entry.date,
      }
      decisionMemory.push(decisionEntry)

      if (decisionKey) {
        if (!decisionGroups.has(decisionKey)) decisionGroups.set(decisionKey, [])
        decisionGroups.get(decisionKey).push(decisionEntry)
      }
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

  const ownershipDrift = [...ownerCounts.entries()]
    .map(([owner, count]) => ({
      owner,
      count,
      meetings: ownerMeetingCounts.get(owner)?.size || 0,
    }))
    .filter(({ count, meetings }) => count >= 3 || meetings >= 2)
    .sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count
      return b.meetings - a.meetings
    })
    .slice(0, 3)

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

  const unresolvedDecisions = [...decisionGroups.entries()]
    .filter(([, group]) => {
      const uniqueMeetings = new Set(group.map((item) => item.meeting.id))
      return uniqueMeetings.size > 1
    })
    .map(([key, group]) => {
      const sorted = [...group].sort((a, b) => new Date(b.date) - new Date(a.date))
      const uniqueMeetings = [...new Set(group.map((item) => item.meeting.id))]
      return {
        key,
        count: uniqueMeetings.length,
        latestTitle: sorted[0]?.title || 'Decision thread',
        latestOwner: sorted[0]?.owner || '',
        meetings: sorted.map((item) => item.meeting).filter((meeting, index, all) => all.findIndex((value) => value.id === meeting.id) === index).slice(0, 5),
      }
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 3)

  const recurringHygieneIssues = hygieneMeetings
    .sort((a, b) => (b.missingOwners + b.missingDueDates) - (a.missingOwners + a.missingDueDates))
    .slice(0, 4)

  return {
    meetingCount: meetings.length,
    avgScore,
    latestScore,
    scoreDelta,
    tenseMeetings,
    topOwners,
    ownershipDrift,
    recurringThemes,
    recurringBlockers,
    recurringHygieneIssues,
    resurfacingDecisionThemes,
    unresolvedDecisions,
    recentDecisions,
  }
}

export default function CrossMeetingInsights({ history, insights: insightsProp, onSelect }) {
  const [expanded, setExpanded] = useState(false)
  const [focusCluster, setFocusCluster] = useState(null)
  const insights = insightsProp || deriveInsights(history)
  const meetingMap = new Map(history.map((meeting) => [meeting.id, meeting]))

  const openCluster = (title, subtitle, meetingIds = []) => {
    const meetings = meetingIds.map((id) => meetingMap.get(id)).filter(Boolean)
    setFocusCluster({ title, subtitle, meetings })
  }

  if ((insights.meeting_count ?? insights.meetingCount) < 2) return null

  const avgScore = insights.avg_score ?? insights.avgScore
  const latestScore = insights.latest_score ?? insights.latestScore
  const scoreDelta = insights.score_delta ?? insights.scoreDelta
  const tenseMeetings = insights.tense_meetings ?? insights.tenseMeetings ?? 0
  const topOwners = insights.top_owners ?? insights.topOwners ?? []
  const ownershipDrift = insights.ownership_drift ?? insights.ownershipDrift ?? []
  const recurringThemes = insights.recurring_themes ?? insights.recurringThemes ?? []
  const recurringBlockers = insights.recurring_blockers ?? insights.recurringBlockers ?? []
  const recurringHygieneIssues = insights.recurring_hygiene_issues ?? insights.recurringHygieneIssues ?? []
  const resurfacingDecisionThemes = insights.resurfacing_decision_themes ?? insights.resurfacingDecisionThemes ?? []
  const unresolvedDecisions = insights.unresolved_decisions ?? insights.unresolvedDecisions ?? []
  const recentDecisions = insights.recent_decisions ?? insights.recentDecisions ?? []
  const recommendedActions = insights.recommended_actions ?? insights.recommendedActions ?? []
  const meetingCount = insights.meeting_count ?? insights.meetingCount ?? 0

  const deltaLabel = scoreDelta === null
    ? 'stable'
    : scoreDelta > 0
      ? `+${scoreDelta}`
      : `${scoreDelta}`

  const deltaColor = scoreDelta === null
    ? '#94a3b8'
    : scoreDelta > 0
      ? '#34d399'
      : scoreDelta < 0
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
              PrismAI is spotting patterns across {meetingCount} saved meetings, not just this one.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {avgScore !== null && (
              <span className="text-[11px] px-2.5 py-1 rounded-full"
                style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.18)', color: '#86efac' }}>
                avg {avgScore}/100
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
          {topOwners[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
              Most active owner: {topOwners[0].owner}
            </span>
          )}
          {recurringThemes[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full bg-white/5 border border-white/8 text-gray-400">
              Recurring theme: {recurringThemes[0].theme}
            </span>
          )}
          {tenseMeetings > 0 && (
            <span className="text-[10px] px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.18)', color: '#fca5a5' }}>
              {tenseMeetings} tense meeting{tenseMeetings === 1 ? '' : 's'} in history
            </span>
          )}
          {recurringBlockers[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.18)', color: '#fca5a5' }}>
              Recurring blocker signal detected
            </span>
          )}
          {ownershipDrift[0] && (
            <span className="text-[10px] px-2.5 py-1 rounded-full"
              style={{ background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.18)', color: '#7dd3fc' }}>
              Ownership drift detected
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          <div className="grid grid-cols-1 gap-3">
            {recommendedActions.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(14,165,233,0.04)', border: '1px solid rgba(14,165,233,0.12)' }}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-sky-300/80">Recommended Next Actions</p>
                  <span className="text-[10px] text-gray-600">tap to inspect</span>
                </div>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {recommendedActions.map((action) => (
                    <button
                      key={action.id}
                      onClick={() => openCluster(action.title, action.description, action.meeting_ids || action.meetingIds || [])}
                      className="text-left rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
                      style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.04)' }}
                    >
                      <p className="text-sm font-medium text-white leading-snug">{action.title}</p>
                      <p className="text-[11px] text-gray-500 mt-1 leading-relaxed">{action.description}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl px-3 py-3"
                style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.12)' }}>
                <p className="text-[10px] uppercase tracking-[0.18em] text-emerald-400/75">Momentum</p>
                <p className="text-lg font-semibold text-white mt-1">{latestScore ?? '—'}</p>
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

            {(ownershipDrift.length > 0 || recurringHygieneIssues.length > 0 || unresolvedDecisions.length > 0) && (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(14,165,233,0.05)', border: '1px solid rgba(14,165,233,0.12)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-sky-300/80">Ownership Drift</p>
                    <span className="text-[10px] text-gray-600">tap to inspect</span>
                  </div>
                  {ownershipDrift.length > 0 ? (
                    <div className="space-y-2 mt-2">
                      {ownershipDrift.map(({ owner, count, meetings, meeting_ids: meetingIds, meetingIds: legacyMeetingIds }) => (
                        <button
                          key={owner}
                          onClick={() => openCluster('Meetings loading this owner repeatedly', `${owner} appears on ${count} action items across ${meetings} meetings`, meetingIds || legacyMeetingIds || [])}
                          className="w-full text-left rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
                          style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.04)' }}
                        >
                          <p className="text-sm text-white">{owner}</p>
                          <p className="text-[11px] text-sky-300/80 mt-1">{count} items · {meetings} meetings</p>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">Ownership looks balanced across recent meetings.</p>
                  )}
                </div>

                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(251,191,36,0.05)', border: '1px solid rgba(251,191,36,0.12)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-amber-300/80">Action Hygiene</p>
                    <span className="text-[10px] text-gray-600">tap to inspect</span>
                  </div>
                  {recurringHygieneIssues.length > 0 ? (
                    <div className="space-y-2 mt-2">
                      {recurringHygieneIssues.map(({ meeting, meeting_id: meetingId, missingOwners, missingDueDates, missing_owners: missingOwnersSnake, missing_due_dates: missingDueDatesSnake }) => (
                        <button
                          key={meeting?.id || meetingId}
                          onClick={() => onSelect?.(meeting || meetingMap.get(meetingId))}
                          className="w-full text-left rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
                          style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.04)' }}
                        >
                          <p className="text-sm text-white leading-snug">{meeting?.title || meetingMap.get(meetingId)?.title || 'Meeting'}</p>
                          <p className="text-[11px] text-amber-300/80 mt-1">
                            {(missingOwners ?? missingOwnersSnake) > 0 ? `${missingOwners ?? missingOwnersSnake} unowned` : '0 unowned'}
                            {' · '}
                            {(missingDueDates ?? missingDueDatesSnake) > 0 ? `${missingDueDates ?? missingDueDatesSnake} undated` : '0 undated'}
                          </p>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">Recent action items are consistently assigned and dated.</p>
                  )}
                </div>

                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(168,85,247,0.05)', border: '1px solid rgba(168,85,247,0.12)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-violet-300/80">Unresolved Decisions</p>
                    <span className="text-[10px] text-gray-600">tap to inspect</span>
                  </div>
                  {unresolvedDecisions.length > 0 ? (
                    <div className="space-y-2 mt-2">
                      {unresolvedDecisions.map((decision) => (
                        <button
                          key={decision.key}
                          onClick={() => openCluster('Meetings revisiting this unresolved decision', decision.latestTitle || decision.latest_title, decision.meeting_ids || decision.meetingIds || [])}
                          className="w-full text-left rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
                          style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.04)' }}
                        >
                          <p className="text-sm text-white leading-snug">{decision.latestTitle || decision.latest_title}</p>
                          <p className="text-[11px] text-violet-300/80 mt-1">
                            {decision.count} meetings
                            {(decision.latestOwner || decision.latest_owner) ? ` · latest owner: ${decision.latestOwner || decision.latest_owner}` : ''}
                          </p>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">Recent decisions do not appear to be looping back unresolved.</p>
                  )}
                </div>
              </div>
            )}

            {(recurringBlockers.length > 0 || resurfacingDecisionThemes.length > 0) && (
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(248,113,113,0.05)', border: '1px solid rgba(248,113,113,0.12)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-rose-300/80">Recurring Blockers</p>
                    <span className="text-[10px] text-gray-600">tap to inspect</span>
                  </div>
                  {recurringBlockers.length > 0 ? (
                    <div className="space-y-2 mt-2">
                      {recurringBlockers.map(({ snippet, count, meeting_ids: meetingIds, meetingIds: legacyMeetingIds }) => (
                        <button
                          key={snippet}
                          onClick={() => openCluster('Meetings behind this blocker', snippet, meetingIds || legacyMeetingIds || [])}
                          className="w-full text-left rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
                          style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.04)' }}
                        >
                          <p className="text-sm text-white leading-snug">{snippet}</p>
                          <p className="text-[11px] text-rose-300/80 mt-1">surfaced {count} time{count === 1 ? '' : 's'}</p>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">No repeated blockers are surfacing yet.</p>
                  )}
                </div>

                <div className="rounded-xl px-3.5 py-3"
                  style={{ background: 'rgba(250,204,21,0.05)', border: '1px solid rgba(250,204,21,0.12)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-amber-300/80">Decision Resurfacing</p>
                    <span className="text-[10px] text-gray-600">tap to inspect</span>
                  </div>
                  {resurfacingDecisionThemes.length > 0 ? (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {resurfacingDecisionThemes.map(({ theme, count, meeting_ids: meetingIds, meetingIds: legacyMeetingIds }) => (
                        <button
                          key={theme}
                          onClick={() => openCluster('Meetings revisiting this decision theme', theme, meetingIds || legacyMeetingIds || [])}
                          className="text-[11px] px-2.5 py-1 rounded-full"
                          style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.16)', color: '#fde68a' }}
                        >
                          {theme} · {count} mentions
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-gray-500 mt-2">Recent decisions are not repeating in a concerning way.</p>
                  )}
                </div>
              </div>
            )}

            {focusCluster && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">{focusCluster.title}</p>
                    <p className="text-sm text-white mt-1 leading-snug">{focusCluster.subtitle}</p>
                  </div>
                  <button
                    onClick={() => setFocusCluster(null)}
                    className="text-[10px] px-2 py-1 rounded-lg text-gray-500 hover:text-gray-300 transition-colors"
                    style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
                  >
                    Close
                  </button>
                </div>
                {focusCluster.meetings.length > 0 ? (
                  <div className="space-y-2 mt-3">
                    {focusCluster.meetings.map((meeting) => (
                      <button
                        key={meeting.id}
                        onClick={() => onSelect?.(meeting)}
                        className="w-full text-left rounded-xl px-3 py-2 transition-colors hover:bg-white/5"
                        style={{ border: '1px solid rgba(255,255,255,0.06)' }}
                      >
                        <p className="text-sm font-medium text-white leading-snug">{meeting.title || 'Meeting'}</p>
                        <p className="text-[11px] text-gray-500 mt-1">
                          {formatMeetingDate(meeting.date)}
                          {meeting.result?.health_score?.score !== undefined && meeting.result?.health_score?.score !== null
                            ? ` · ${meeting.result.health_score.score}/100`
                            : ''}
                        </p>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-[11px] text-gray-500 mt-3">No matching meetings were found in the current saved history.</p>
                )}
              </div>
            )}

            {topOwners.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Ownership Pattern</p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {topOwners.map(({ owner, count }) => (
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

            {recurringThemes.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Recurring Themes</p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {recurringThemes.map(({ theme, count }) => (
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

            {recentDecisions.length > 0 && (
              <div className="rounded-xl px-3.5 py-3"
                style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] uppercase tracking-[0.18em] text-gray-500">Decision Memory</p>
                  <span className="text-[10px] text-gray-600">tap to load meeting</span>
                </div>
                <div className="space-y-2 mt-2">
                  {recentDecisions.map((decision) => (
                    <button
                      key={decision.id}
                      onClick={() => onSelect?.(decision.meeting || meetingMap.get(decision.meeting_id || decision.meetingId))}
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

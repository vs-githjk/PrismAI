const STOP_WORDS = new Set([
  'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'will', 'into', 'your',
  'their', 'about', 'after', 'before', 'need', 'needs', 'next', 'then', 'than', 'just',
  'more', 'less', 'team', 'meeting', 'meetings', 'owner', 'owners', 'task', 'tasks',
  'action', 'actions', 'decision', 'decisions', 'update', 'draft', 'send', 'review',
  'schedule', 'timeline', 'launch', 'project', 'follow', 'email', 'calendar', 'high',
  'low', 'ready', 'work', 'works', 'done', 'doing', 'look', 'looks', 'through',
  'across', 'still', 'again', 'there', 'where', 'what', 'when', 'been', 'being',
  'they', 'them', 'were', 'make', 'made', 'gets', 'getting', 'onto', 'over',
  'under', 'today', 'tomorrow', 'yesterday', 'week', 'weeks', 'month', 'months',
  'january', 'february', 'march', 'april', 'june', 'july', 'august',
  'september', 'october', 'november', 'december',
  'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
  'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
])

const BLOCKER_KEYWORDS = [
  'blocked', 'blocker', 'delay', 'delayed', 'risk', 'risky', 'concern', 'concerns',
  'worried', 'worry', 'issue', 'issues', 'stuck', 'slip', 'slipping', 'outage',
  'degraded', 'preventable', 'missed', 'overcommit', 'overcommitting', 'dependency',
]

export function formatMeetingDate(value) {
  if (!value) return 'Unknown date'
  return new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function normalizeWord(word) {
  return word.toLowerCase().replace(/[^a-z0-9-]/g, '').trim()
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
  return extractSignificantTerms(text, 4).slice(0, 3).join(' ')
}

export function deriveInsights(history = []) {
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
      extractSignificantTerms(text).forEach((word) => themeCounts.set(word, (themeCounts.get(word) || 0) + 1))

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

    extractSignificantTerms(result.summary || '', 5).forEach((word) => themeCounts.set(word, (themeCounts.get(word) || 0) + 1))

    if (looksLikeBlocker(result.summary || '')) {
      const snippet = buildBlockerSnippet(result.summary)
      if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
    }

    if (looksLikeBlocker(sentiment.notes || '')) {
      const snippet = buildBlockerSnippet(sentiment.notes)
      if (snippet) blockerCounts.set(snippet, (blockerCounts.get(snippet) || 0) + 1)
    }
  })

  const topOwners = [...ownerCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([owner, count]) => ({ owner, count }))

  const ownershipDrift = [...ownerCounts.entries()]
    .map(([owner, count]) => ({ owner, count, meetings: ownerMeetingCounts.get(owner)?.size || 0 }))
    .filter(({ count, meetings }) => count >= 3 || meetings >= 2)
    .sort((a, b) => (b.count !== a.count ? b.count - a.count : b.meetings - a.meetings))
    .slice(0, 4)

  const recurringThemes = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([theme, count]) => ({ theme, count }))

  const recurringBlockers = [...blockerCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([snippet, count]) => ({ snippet, count }))

  const resurfacingDecisionThemes = [...decisionThemeCounts.entries()]
    .filter(([, count]) => count > 1)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([theme, count]) => ({ theme, count }))

  const recentDecisions = decisionMemory
    .sort((a, b) => (a.importance !== b.importance ? a.importance - b.importance : new Date(b.date) - new Date(a.date)))
    .slice(0, 5)

  const unresolvedDecisions = [...decisionGroups.entries()]
    .filter(([, group]) => new Set(group.map((item) => item.meeting.id)).size > 1)
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
    .slice(0, 4)

  const recurringHygieneIssues = hygieneMeetings
    .sort((a, b) => (b.missingOwners + b.missingDueDates) - (a.missingOwners + a.missingDueDates))
    .slice(0, 5)

  const recommendedActions = []
  if (recurringBlockers[0]) {
    recommendedActions.push({
      id: 'blockers',
      title: 'Resolve repeated blockers',
      description: recurringBlockers[0].snippet,
    })
  }
  if (ownershipDrift[0]) {
    recommendedActions.push({
      id: 'owners',
      title: `Rebalance ${ownershipDrift[0].owner}'s load`,
      description: `${ownershipDrift[0].owner} owns ${ownershipDrift[0].count} recent action items.`,
    })
  }
  if (recurringHygieneIssues[0]) {
    recommendedActions.push({
      id: 'hygiene',
      title: 'Tighten action hygiene',
      description: 'Add owners and due dates before the next follow-up.',
    })
  }

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
    recommendedActions,
  }
}

export function normalizeInsights(insights = {}, history = []) {
  const derived = deriveInsights(history)
  const source = insights || {}
  return {
    meetingCount: source.meeting_count ?? source.meetingCount ?? derived.meetingCount,
    avgScore: source.avg_score ?? source.avgScore ?? derived.avgScore,
    latestScore: source.latest_score ?? source.latestScore ?? derived.latestScore,
    scoreDelta: source.score_delta ?? source.scoreDelta ?? derived.scoreDelta,
    tenseMeetings: source.tense_meetings ?? source.tenseMeetings ?? derived.tenseMeetings,
    topOwners: source.top_owners ?? source.topOwners ?? derived.topOwners,
    ownershipDrift: source.ownership_drift ?? source.ownershipDrift ?? derived.ownershipDrift,
    recurringThemes: source.recurring_themes ?? source.recurringThemes ?? derived.recurringThemes,
    recurringBlockers: source.recurring_blockers ?? source.recurringBlockers ?? derived.recurringBlockers,
    recurringHygieneIssues: source.recurring_hygiene_issues ?? source.recurringHygieneIssues ?? derived.recurringHygieneIssues,
    resurfacingDecisionThemes: source.resurfacing_decision_themes ?? source.resurfacingDecisionThemes ?? derived.resurfacingDecisionThemes,
    unresolvedDecisions: source.unresolved_decisions ?? source.unresolvedDecisions ?? derived.unresolvedDecisions,
    recentDecisions: source.recent_decisions ?? source.recentDecisions ?? derived.recentDecisions,
    recommendedActions: source.recommended_actions ?? source.recommendedActions ?? derived.recommendedActions,
  }
}

export function deriveDisplayTitle(entry) {
  const resultTitle = entry?.result?.title
  if (resultTitle) return resultTitle
  const stored = entry?.title || ''
  // Skip stored titles that look like summary excerpts (> 45 chars or start with "The meeting")
  if (stored && !/^the meeting\b/i.test(stored) && stored.length <= 45) return stored
  const summary = entry?.result?.summary || ''
  if (summary) {
    const stripped = summary
      .replace(/^the meeting[^,]*(?:,[^,]*)?,\s*/i, '')
      .replace(/^(?:appeared to be|was|seemed to be|is|seemed)\s+/i, '')
      .replace(/^(?:discussed|covered|focused on|reviewed|addressed|explored|examined|centered on)\s+/i, '')
      .trim()
    const text = stripped || summary
    const atComma = text.split(',')[0].trim()
    const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1)
    // Strip trailing preposition phrases for a cleaner noun-phrase title
    const corePhrase = atComma.replace(/\s+(?:from|with|for|about|regarding|in|at|by)\s+.*/i, '').trim()
    if (corePhrase.length >= 8 && corePhrase.length <= 60) return cap(corePhrase)
    if (atComma.length >= 8 && atComma.length <= 60) return cap(atComma)
    const words = text.split(/\s+/)
    let title = ''
    for (const word of words) {
      if ((title + ' ' + word).trim().length > 55) break
      title = (title + ' ' + word).trim()
    }
    if (title.length >= 8) return cap(title)
  }
  return stored || 'Meeting'
}

export function scoreBand(score) {
  const value = Number(score)
  if (!Number.isFinite(value)) return { color: '#94a3b8', label: 'No score', tone: 'slate' }
  if (value < 30) return { color: '#f59e0b', label: 'At risk', tone: 'amber' }
  if (value < 60) return { color: '#22d3ee', label: 'Building', tone: 'cyan' }
  return { color: '#8b5cf6', label: 'Strong', tone: 'violet' }
}

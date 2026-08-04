import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiFetch } from '../../lib/api'
import { normalizeInsights } from '../../lib/insights'
import SkeletonCard from '../SkeletonCard'
import {
  DecisionEvolutionCard,
  NarrativeBar,
  OpenThreadsCard,
  SemanticLockedBanner,
} from './CrossMeetingSemantic'
import { ActionModal } from './SuggestedActions'
import HealthTrend from './HealthTrend'
import StatsHero from './StatsHero'
import TaskHub from './TaskHub'
import Vitals from './Vitals'
import CollapsibleSection from './CollapsibleSection'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

const DecisionMemory = lazy(() => import('./DecisionMemory'))

// (Ownership drift, Owner load, Topics, and Members leaderboard were pruned in
// the Aug 2026 redesign — the Task hub replaced them as the page's second focus.)

export default function IntelligenceView({
  history,
  crossMeetingInsights,
  onSelectMeeting,
  workspaceId = null,
  workspaceName = null,
  actionConnections = {},
  suggestedEmails = [],
  teamsWebhook = '',
  user = null,
  onToggleAction,
}) {
  const safeHistory = history || []
  const insights = useMemo(
    () => normalizeInsights(crossMeetingInsights, safeHistory),
    [crossMeetingInsights, safeHistory],
  )
  const latestMeeting = safeHistory[0] || null

  const byId = useMemo(() => new Map(safeHistory.map((entry) => [entry.id, entry])), [safeHistory])
  const resolveMeeting = useCallback((id) => byId.get(id) || null, [byId])

  // B2 semantic block — fetched separately from /insights so the cheap deterministic
  // cards above render instantly and only these wait on the (cached) LLM synthesis.
  const [semantic, setSemantic] = useState(null)
  const [semanticLoading, setSemanticLoading] = useState(false)
  const historyCount = safeHistory.length

  useEffect(() => {
    let cancelled = false
    if (!historyCount) {
      setSemantic(null)
      return
    }
    setSemanticLoading(true)
    const url = workspaceId ? `/insights/semantic?workspace_id=${workspaceId}` : '/insights/semantic'
    apiFetch(url)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (!cancelled) setSemantic(data && typeof data === 'object' ? data : null) })
      .catch(() => { if (!cancelled) setSemantic(null) })
      .finally(() => { if (!cancelled) setSemanticLoading(false) })
    return () => { cancelled = true }
  }, [workspaceId, historyCount])

  const locked = Boolean(semantic?.locked)
  const semanticReady = Boolean(semantic) && !locked && semantic.enabled !== false
  const showSemantic = semanticLoading || semanticReady
  const cardsLoading = semanticLoading && !semanticReady

  // "Act on a thread" — turn an open thread's next-step into a real tracked task,
  // reusing the meeting-view action surface. Type adapts to what's connected so the
  // button is never a dead end; the concrete destination is shown in the modal.
  const threadActionType = actionConnections.jira || actionConnections.linear
    ? 'task'
    : actionConnections.calendar ? 'calendar'
    : actionConnections.email ? 'email'
    : 'task'
  const threadActLabel = { task: 'Add as task', calendar: 'Add to calendar', email: 'Email reminder' }[threadActionType]

  // Remember threads already turned into a task so the button flips to "Filed" and can't
  // double-file. Keyed by thread text within the scope (personal / workspace); best-effort
  // — a reworded thread on the next synthesis loses its mark, which is fine.
  const actedStoreKey = `prism_acted_threads_${workspaceId || 'personal'}`
  const [actedThreads, setActedThreads] = useState({})
  useEffect(() => {
    try { setActedThreads(JSON.parse(localStorage.getItem(actedStoreKey) || '{}') || {}) } catch { setActedThreads({}) }
  }, [actedStoreKey])
  const threadKey = (thread) => (thread?.thread || '').slice(0, 200)
  const isThreadActed = useCallback((thread) => actedThreads[threadKey(thread)] || null, [actedThreads])

  const [threadAction, setThreadAction] = useState(null)
  const actOnThread = useCallback((thread) => {
    setThreadAction({
      _key: threadKey(thread),
      action_type: threadActionType,
      title: (thread.suggested_next_step || thread.thread || '').slice(0, 200),
      body: [
        thread.suggested_next_step,
        thread.why_open && `Why it's open: ${thread.why_open}`,
        `Open thread: ${thread.thread}`,
      ].filter(Boolean).join('\n\n'),
      task: thread.thread,
    })
  }, [threadActionType])
  const markThreadActed = useCallback((url) => {
    const key = threadAction?._key
    if (!key) return
    setActedThreads((prev) => {
      const next = { ...prev, [key]: { url: url || null, at: Date.now() } }
      try { localStorage.setItem(actedStoreKey, JSON.stringify(next)) } catch { /* storage unavailable */ }
      return next
    })
  }, [threadAction, actedStoreKey])

  return (
    <div className="space-y-3">
      <StatsHero insights={insights} workspaceName={workspaceName} />

      {locked ? (
        <SemanticLockedBanner minMeetings={semantic?.min_meetings || 3} />
      ) : showSemantic ? (
        <NarrativeBar narrative={semantic?.narrative} loading={cardsLoading} />
      ) : null}

      {/* Co-headline row (ADR 0002): the health graph and the Task hub share the
          top of the page — tasks as prominent as the graph, no tabs. */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
        <div className="min-w-0 space-y-3">
          <HealthTrend history={safeHistory} onSelect={onSelectMeeting} />
          <Vitals insights={insights} latestMeeting={latestMeeting} />
        </div>
        <div className="min-w-0 lg:max-h-[42rem]">
          <TaskHub
            history={safeHistory}
            user={user}
            onToggle={onToggleAction}
            onOpenMeeting={onSelectMeeting}
          />
        </div>
      </div>

      {/* Demoted, not deleted (standard prune, Aug 2026): threads / evolution /
          decision memory live behind one collapsed row. The aggressive-prune
          follow-up is deleting this block. */}
      <CollapsibleSection
        title="Threads & decisions"
        hint="open threads · decision evolution · decision memory"
      >
        <div className="space-y-3 pt-1">
          {!locked && showSemantic && (
            <div className="grid gap-3 lg:grid-cols-2">
              <OpenThreadsCard
                threads={semantic?.open_threads || []}
                loading={cardsLoading}
                resolveMeeting={resolveMeeting}
                onSelect={onSelectMeeting}
                onAct={actOnThread}
                actLabel={threadActLabel}
                isActed={isThreadActed}
              />
              <DecisionEvolutionCard
                items={semantic?.decision_evolution || []}
                loading={cardsLoading}
                resolveMeeting={resolveMeeting}
                onSelect={onSelectMeeting}
              />
            </div>
          )}
          <Suspense fallback={<SkeletonCard lines={3} />}>
            <DecisionMemory insights={insights} onSelect={onSelectMeeting} />
          </Suspense>
        </div>
      </CollapsibleSection>

      {threadAction && createPortal(
        <ActionModal
          action={threadAction}
          connections={actionConnections}
          suggestedEmails={suggestedEmails}
          meetingId={null}
          teamsWebhook={teamsWebhook}
          workspaceId={workspaceId}
          onExecuted={markThreadActed}
          onClose={() => setThreadAction(null)}
        />, document.body)}
    </div>
  )
}

import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight } from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { normalizeInsights } from '../../lib/insights'
import { collectOpenActions, byPriority, dueBand } from '../../lib/actionItems'
import SkeletonCard from '../SkeletonCard'
import {
  DecisionEvolutionCard,
  NarrativeBar,
  OpenThreadsCard,
  SemanticLockedBanner,
} from './CrossMeetingSemantic'
import { ActionModal } from './SuggestedActions'
import ActionItemRow from './ActionItemRow'
import HealthTrend from './HealthTrend'
import StatsHero from './StatsHero'
import Vitals from './Vitals'
import CollapsibleSection from './CollapsibleSection'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

const DecisionMemory = lazy(() => import('./DecisionMemory'))

// (Ownership drift, Owner load, Topics, and Members leaderboard were pruned in
// the Aug 2026 redesign; the Task hub that replaced them has since moved to the
// standalone Actions page — Trend keeps only a compact open-task summary.)

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
  onOpenActions,
}) {
  const safeHistory = history || []
  const insights = useMemo(
    () => normalizeInsights(crossMeetingInsights, safeHistory),
    [crossMeetingInsights, safeHistory],
  )
  const latestMeeting = safeHistory[0] || null

  // Compact open-task summary (ADR 0002 amendment, Aug 2026): the full queue
  // now lives on the standalone Actions page; Trend keeps top-3 by the one
  // true priority order plus overdue/due-soon counts, with a link across.
  const openTasks = useMemo(() => {
    const all = collectOpenActions(safeHistory, user)
    return {
      total: all.length,
      overdue: all.filter((r) => dueBand(r) === 'overdue').length,
      soon: all.filter((r) => dueBand(r) === 'soon').length,
      top: [...all].sort(byPriority).slice(0, 3),
    }
  }, [safeHistory, user])

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

      {/* Co-headline row (ADR 0002, amended Aug 2026): the health graph keeps
          top billing; the full task queue moved to the standalone Actions
          page, so this column is a compact summary that links across. */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(300px,4fr)]">
        <div className="min-w-0 space-y-3">
          <HealthTrend history={safeHistory} onSelect={onSelectMeeting} />
          <Vitals insights={insights} latestMeeting={latestMeeting} />
        </div>
        <section className={`${glassCard} p-4`} style={cardGlowStyle} aria-label="Open tasks">
          <div className="flex items-center justify-between">
            <h3 className={cardTitle}>Open tasks</h3>
            <span className="text-2xl font-semibold text-[color:var(--db-text)]">{openTasks.total}</span>
          </div>
          <p className={`${subtleText} mt-1`}>{openTasks.overdue} overdue · {openTasks.soon} due soon</p>
          <ul className="mt-3 space-y-1">
            {openTasks.top.map((row) => (
              <ActionItemRow key={`${row.entry.id}-${row.index}`} row={row} onToggle={onToggleAction} onOpenMeeting={onSelectMeeting} showMeeting />
            ))}
          </ul>
          <button onClick={onOpenActions} className="mt-3 inline-flex min-h-[36px] items-center gap-1 text-sm text-[color:var(--db-accent-text)]">
            View all in Actions <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </section>
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

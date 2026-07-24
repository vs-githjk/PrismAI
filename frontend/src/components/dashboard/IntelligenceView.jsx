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
  TopicsCard,
} from './CrossMeetingSemantic'
import { ActionModal } from './SuggestedActions'
import HealthTrend from './HealthTrend'
import StatsHero from './StatsHero'
import Vitals from './Vitals'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

const OwnerLoad = lazy(() => import('./OwnerLoad'))
const DecisionMemory = lazy(() => import('./DecisionMemory'))

function OwnershipDriftCard({ insights }) {
  const drift = insights.ownershipDrift || []
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Ownership drift</p>
        <h2 className={cardTitle}>Overloaded contributors</h2>
      </div>
      {drift.length ? (
        <div className="space-y-2">
          {drift.map(({ owner, count, meetings }) => (
            <div key={owner} className="rounded-lg border border-sky-200/[0.14] bg-sky-300/[0.06] px-3 py-2.5">
              <p className="text-sm font-semibold text-white">{owner}</p>
              <p className={subtleText}>
                {count} action item{count !== 1 ? 's' : ''} · {meetings} meeting{meetings !== 1 ? 's' : ''}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className={subtleText}>Ownership looks balanced across recent meetings.</p>
      )}
    </section>
  )
}

function MembersLeaderboard({ insights }) {
  const load = insights.openOwnerLoad || []
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Members leaderboard</p>
        <h2 className={cardTitle}>Open action items by owner</h2>
      </div>
      {load.length ? (
        <div className="space-y-2">
          {load.map(({ owner, open, total }) => (
            <div key={owner} className="rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-white">{owner}</p>
                <span className="text-[11px] font-semibold text-amber-300/90">{open} open</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className="h-full rounded-full bg-amber-400/60"
                  style={{ width: total > 0 ? `${Math.round((open / total) * 100)}%` : '0%' }}
                />
              </div>
              <p className="mt-1 text-[10px] text-white/38">{total} total assigned</p>
            </div>
          ))}
        </div>
      ) : (
        <p className={subtleText}>No action items assigned yet.</p>
      )}
    </section>
  )
}

export default function IntelligenceView({
  history,
  crossMeetingInsights,
  onSelectMeeting,
  workspaceId = null,
  workspaceName = null,
  actionConnections = {},
  suggestedEmails = [],
  teamsWebhook = '',
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

      <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <HealthTrend history={safeHistory} onSelect={onSelectMeeting} />
        <Vitals insights={insights} latestMeeting={latestMeeting} />
      </div>

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

      <div className="grid gap-3 lg:grid-cols-2">
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <OwnerLoad insights={insights} />
        </Suspense>
        <OwnershipDriftCard insights={insights} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <DecisionMemory insights={insights} onSelect={onSelectMeeting} />
        </Suspense>
        {!locked && showSemantic && (
          <TopicsCard
            topics={semantic?.topics || []}
            loading={cardsLoading}
            resolveMeeting={resolveMeeting}
            onSelect={onSelectMeeting}
          />
        )}
      </div>

      {workspaceName && <MembersLeaderboard insights={insights} />}

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

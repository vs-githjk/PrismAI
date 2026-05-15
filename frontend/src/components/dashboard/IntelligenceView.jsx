import { lazy, Suspense, useMemo } from 'react'
import { formatMeetingDate, normalizeInsights } from '../../lib/insights'
import SkeletonCard from '../SkeletonCard'
import ActionBoard from './ActionBoard'
import HealthTrend from './HealthTrend'
import StatsHero from './StatsHero'
import Vitals from './Vitals'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

const OwnerLoad = lazy(() => import('./OwnerLoad'))
const DecisionMemory = lazy(() => import('./DecisionMemory'))
const ThemeChips = lazy(() => import('./ThemeChips'))
const MeetingsRail = lazy(() => import('./MeetingsRail'))

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

function ActionHygieneCard({ insights, onSelect }) {
  const issues = insights.recurringHygieneIssues || []
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Action hygiene</p>
        <h2 className={cardTitle}>Incomplete assignments</h2>
      </div>
      {issues.length ? (
        <div className="space-y-2">
          {issues.map(({ meeting, missingOwners, missingDueDates }) => (
            <button
              type="button"
              key={meeting?.id}
              onClick={() => onSelect?.(meeting)}
              className="w-full rounded-lg border border-amber-200/[0.14] bg-amber-300/[0.06] px-3 py-2.5 text-left transition hover:border-amber-200/[0.28] hover:bg-amber-300/[0.10]"
            >
              <p className="text-sm font-semibold text-white">{meeting?.title || 'Meeting'}</p>
              <p className="mt-0.5 text-[11px] leading-4 text-amber-200/70">
                {missingOwners > 0 ? `${missingOwners} unowned` : '0 unowned'} · {missingDueDates > 0 ? `${missingDueDates} undated` : '0 undated'}
              </p>
            </button>
          ))}
        </div>
      ) : (
        <p className={subtleText}>Action items are consistently assigned and dated.</p>
      )}
    </section>
  )
}

function UnresolvedDecisionsCard({ insights, onSelect }) {
  const unresolved = insights.unresolvedDecisions || []
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Unresolved decisions</p>
        <h2 className={cardTitle}>Decision loops</h2>
      </div>
      {unresolved.length ? (
        <div className="space-y-2">
          {unresolved.map((decision) => (
            <div key={decision.key} className="rounded-lg border border-violet-200/[0.14] bg-violet-300/[0.06] p-3">
              <p className="text-sm font-semibold leading-snug text-white">{decision.latestTitle}</p>
              <p className={`mt-0.5 ${subtleText}`}>
                Resurfaced in {decision.count} meeting{decision.count !== 1 ? 's' : ''}
                {decision.latestOwner ? ` · ${decision.latestOwner}` : ''}
              </p>
              {decision.meetings?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {decision.meetings.slice(0, 3).map((meeting) => (
                    <button
                      type="button"
                      key={meeting.id}
                      onClick={() => onSelect?.(meeting)}
                      className="rounded border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10.5px] text-white/56 transition hover:border-cyan-200/24 hover:text-cyan-100"
                    >
                      {meeting.title || formatMeetingDate(meeting.date)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className={subtleText}>No decision loops detected across recent meetings.</p>
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

export default function IntelligenceView({ history, crossMeetingInsights, onSelectMeeting, workspaceName = null }) {
  const safeHistory = history || []
  const insights = useMemo(
    () => normalizeInsights(crossMeetingInsights, safeHistory),
    [crossMeetingInsights, safeHistory],
  )
  const latestMeeting = safeHistory[0] || null
  const latestResult = latestMeeting?.result || null

  return (
    <div className="space-y-3">
      <StatsHero insights={insights} workspaceName={workspaceName} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <HealthTrend history={safeHistory} onSelect={onSelectMeeting} />
        <Vitals insights={insights} latestMeeting={latestMeeting} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <ActionBoard result={latestResult} insights={insights} hideOpen />
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <OwnerLoad insights={insights} />
        </Suspense>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <DecisionMemory insights={insights} onSelect={onSelectMeeting} />
        </Suspense>
        <Suspense fallback={<SkeletonCard lines={2} />}>
          <ThemeChips insights={insights} />
        </Suspense>
      </div>

      {workspaceName && (
        <div className="grid gap-3 lg:grid-cols-2">
          <MembersLeaderboard insights={insights} />
          <section className={`${glassCard} p-4`} style={cardGlowStyle}>
            <div className="mb-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Unresolved topics</p>
              <h2 className={cardTitle}>Topics without a decision</h2>
            </div>
            {insights.unresolvedThemes?.length ? (
              <div className="flex flex-wrap gap-2">
                {insights.unresolvedThemes.map(({ theme, count }) => (
                  <span
                    key={theme}
                    className="rounded-full border border-amber-200/20 bg-amber-300/[0.08] px-3 py-1 text-[11px] font-medium text-amber-200/80"
                  >
                    {theme}
                    <span className="ml-1.5 text-amber-200/45">×{count}</span>
                  </span>
                ))}
              </div>
            ) : (
              <p className={subtleText}>All recurring topics have landed in decisions.</p>
            )}
          </section>
        </div>
      )}

      <Suspense fallback={<SkeletonCard lines={2} />}>
        <MeetingsRail history={safeHistory} onSelect={onSelectMeeting} />
      </Suspense>

      <div>
        <p className="mb-3 px-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/34">Deep patterns</p>
        <div className="grid gap-3 lg:grid-cols-3">
          <OwnershipDriftCard insights={insights} />
          <ActionHygieneCard insights={insights} onSelect={onSelectMeeting} />
          <UnresolvedDecisionsCard insights={insights} onSelect={onSelectMeeting} />
        </div>
      </div>
    </div>
  )
}

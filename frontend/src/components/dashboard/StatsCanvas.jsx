import { lazy, Suspense, useMemo } from 'react'
import { normalizeInsights } from '../../lib/insights'
import SkeletonCard from '../SkeletonCard'
import ActionBoard from './ActionBoard'
import HealthTrend from './HealthTrend'
import StatsHero from './StatsHero'
import Vitals from './Vitals'
import { cardGlowStyle, glassCard, subtleText } from './dashboardStyles'

const OwnerLoad = lazy(() => import('./OwnerLoad'))
const DecisionMemory = lazy(() => import('./DecisionMemory'))
const ThemeChips = lazy(() => import('./ThemeChips'))
const MeetingsRail = lazy(() => import('./MeetingsRail'))

function FirstMeetingPlaceholder({ onLoadSample }) {
  return (
    <section className="flex min-h-[420px] flex-col items-center justify-center px-6 py-12 text-center">
      <h1 className="w-full max-w-6xl text-[clamp(2.35rem,5.6vw,4.75rem)] font-semibold leading-[1.02] text-white">
        Turn your next meeting
        <br />
        into momentum.
      </h1>
      <p className="mt-5 max-w-2xl text-lg leading-8 text-white/62 sm:text-xl">Start a new meeting or upload a transcript.</p>
      <button
        type="button"
        onClick={onLoadSample}
        className="mt-12 inline-flex h-12 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-full border border-[#2f2f2f] bg-[#18181b] px-7 py-3 text-base font-medium text-[#f2f2f2] shadow-xs transition-all hover:bg-[#27272a] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40"
      >
        Load sample dashboard
      </button>
    </section>
  )
}

function SingleMeetingState({ history, onSelect }) {
  const entry = history[0]
  return (
    <div className="space-y-3">
      <StatsHero insights={normalizeInsights(null, history)} />
      <section className={`${glassCard} p-4`} style={cardGlowStyle}>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">One meeting saved</p>
        <h2 className="mt-1 text-xl font-semibold tracking-[-0.02em] text-white">More meetings unlock trends</h2>
        <p className={`mt-2 ${subtleText}`}>Health trends, owner load, recurring decisions, and themes appear after at least two saved meetings.</p>
        {entry && (
          <button
            type="button"
            onClick={() => onSelect?.(entry)}
            className="mt-4 w-full rounded-2xl border border-white/[0.1] bg-white/[0.035] p-3 text-left transition hover:border-cyan-200/30 hover:bg-white/[0.06]"
          >
            <p className="text-sm font-semibold text-white">{entry.title || 'Meeting'}</p>
            <p className="mt-2 text-xs leading-5 text-white/58">{entry.result?.health_score?.verdict || entry.result?.summary || 'Meeting saved.'}</p>
          </button>
        )}
      </section>
    </div>
  )
}

export default function StatsCanvas({ history, result, crossMeetingInsights, loadFromHistory, loadSample }) {
  const safeHistory = history || []
  const insights = useMemo(() => normalizeInsights(crossMeetingInsights, safeHistory), [crossMeetingInsights, safeHistory])
  const latestMeeting = safeHistory[0] || null

  if (safeHistory.length === 0) {
    return <FirstMeetingPlaceholder onLoadSample={loadSample} />
  }

  if (safeHistory.length === 1) {
    return <SingleMeetingState history={safeHistory} onSelect={loadFromHistory} />
  }

  return (
    <div className="space-y-3">
      <StatsHero insights={insights} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <HealthTrend history={safeHistory} onSelect={loadFromHistory} />
        <Vitals insights={insights} latestMeeting={latestMeeting} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <ActionBoard result={result || latestMeeting?.result} insights={insights} />
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <OwnerLoad insights={insights} />
        </Suspense>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Suspense fallback={<SkeletonCard lines={3} />}>
          <DecisionMemory insights={insights} onSelect={loadFromHistory} />
        </Suspense>
        <Suspense fallback={<SkeletonCard lines={2} />}>
          <ThemeChips insights={insights} />
        </Suspense>
      </div>

      <Suspense fallback={<SkeletonCard lines={2} />}>
        <MeetingsRail history={safeHistory} onSelect={loadFromHistory} />
      </Suspense>
    </div>
  )
}

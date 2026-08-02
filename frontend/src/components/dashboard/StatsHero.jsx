import MetricTile from './MetricTile'
import { cardGlowStyle, glassCard } from './dashboardStyles'

export default function StatsHero({ insights, workspaceName = null }) {
  const delta = insights.scoreDelta
  const deltaTone = delta < 0 ? 'amber' : delta > 0 ? 'emerald' : 'cyan'
  // A null delta means there is no previous meeting to compare against — that is
  // not "Stable", which would assert a comparison we never made.
  const status = delta === null || delta === undefined
    ? 'Not enough history'
    : delta > 0 ? 'Improving' : delta < 0 ? 'Needs attention' : 'Stable'
  const avgCount = insights.avgScoreCount
  const completionRate = insights.completionRate?.rate ?? null
  const avgDecisions = insights.decisionVelocity?.avg ?? null

  return (
    <section className={`${glassCard} overflow-hidden`} style={cardGlowStyle}>
      <div className="flex flex-col gap-3 border-b border-[color:var(--db-border)] px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200/76">
            {workspaceName ? `Team · ${workspaceName}` : 'Personal overview'}
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-[color:var(--db-text)] sm:text-3xl">
            {workspaceName ? 'Team intelligence' : 'Meeting intelligence'}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill)] px-2.5 py-1 text-[color:var(--db-text-muted)]">
            {insights.meetingCount || 0} meetings indexed
          </span>
          <span className={`rounded-full border px-2.5 py-1 ${delta < 0 ? 'border-amber-200/24 bg-amber-300/10 text-amber-100' : 'border-cyan-200/24 bg-cyan-300/10 text-cyan-100'}`}>
            {status}
          </span>
        </div>
      </div>
      {/* Tone is deliberately uniform: six tiles in five hues read as decoration,
          not severity. Severity lives in the score band + the header pill. Each
          tile carries a plain-English definition so the figure is self-explaining. */}
      <div className="grid grid-cols-2 lg:grid-cols-3">
        <MetricTile label="Latest score" value={insights.latestScore} suffix="/100" isScore bar delay={0}
          hint="health of your most recent meeting" />
        <MetricTile label="30-day average" value={insights.avgScore} suffix="/100" isScore bar delay={60}
          hint={avgCount ? `mean health across ${avgCount} meeting${avgCount === 1 ? '' : 's'} in the last 30 days` : 'no scored meetings in the last 30 days'} />
        <MetricTile label="Delta vs prior" value={delta} tone={deltaTone} delta delay={120}
          hint="change from the meeting before this one" />
        <MetricTile label="Meetings analyzed" value={insights.meetingCount} delay={180}
          hint="meetings in this view" />
        <MetricTile label="Completion rate" value={completionRate} suffix="% done" bar delay={240}
          hint="share of action items ticked off" />
        <MetricTile label="Avg decisions" value={avgDecisions !== null ? Math.round(avgDecisions) : null} suffix="/meeting" delay={300}
          hint="decisions logged per meeting" />
      </div>
    </section>
  )
}

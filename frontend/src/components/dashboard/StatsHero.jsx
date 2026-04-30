import MetricTile from './MetricTile'
import { cardGlowStyle, glassCard } from './dashboardStyles'

export default function StatsHero({ insights }) {
  const delta = insights.scoreDelta
  const deltaTone = delta < 0 ? 'amber' : delta > 0 ? 'emerald' : 'cyan'
  const status = delta > 0 ? 'Improving' : delta < 0 ? 'Needs attention' : 'Stable'

  return (
    <section className={`${glassCard} animate-fade-in-up overflow-hidden`} style={cardGlowStyle}>
      <div className="flex flex-col gap-3 border-b border-white/[0.08] px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200/76">Workspace overview</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-white sm:text-3xl">Meeting intelligence</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-white/[0.1] bg-white/[0.035] px-2.5 py-1 text-white/64">
            {insights.meetingCount || 0} meetings indexed
          </span>
          <span className={`rounded-full border px-2.5 py-1 ${delta < 0 ? 'border-amber-200/24 bg-amber-300/10 text-amber-100' : 'border-cyan-200/24 bg-cyan-300/10 text-cyan-100'}`}>
            {status}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4">
        <MetricTile label="Latest score" value={insights.latestScore} suffix="/100" isScore delay={0} />
        <MetricTile label="30-day average" value={insights.avgScore} suffix="/100" tone="cyan" delay={60} />
        <MetricTile label="Delta vs prior" value={delta ?? 0} tone={deltaTone} delta delay={120} />
        <MetricTile label="Meetings analyzed" value={insights.meetingCount} tone="violet" delay={180} />
      </div>
    </section>
  )
}

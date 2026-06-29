import { Activity, AlertTriangle, ClipboardCheck } from 'lucide-react'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

export default function Vitals({ insights, latestMeeting }) {
  const latestResult = latestMeeting?.result
  const verdict = latestResult?.health_score?.verdict || 'No verdict recorded yet.'
  const sentiment = latestResult?.sentiment?.overall || 'neutral'
  const hygieneCount = insights.recurringHygieneIssues?.length || 0

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Vitals</p>
          <h2 className={cardTitle}>Meeting health signals</h2>
        </div>
        <div className="relative flex h-9 w-9 items-center justify-center rounded-full border border-cyan-200/20 bg-cyan-300/10">
          <span className="absolute h-2.5 w-2.5 rounded-full bg-cyan-300 animate-glow-pulse" />
          <Activity className="h-4 w-4 text-cyan-50" aria-hidden="true" />
        </div>
      </div>

      <div className="space-y-2">
        <div className="rounded-lg border border-white/[0.08] bg-black/25 px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-white/42">Sentiment</p>
            <span className="h-2 w-2 rounded-full bg-cyan-300 animate-glow-pulse" />
          </div>
          <p className="mt-1 text-lg font-semibold capitalize text-white">{sentiment}</p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-amber-200/18 bg-amber-300/8 px-3 py-2">
            <div className="flex items-center justify-between">
              <p className="text-xl font-semibold text-amber-50">{insights.tenseMeetings || 0}</p>
              <AlertTriangle className="h-4 w-4 text-amber-200/72" aria-hidden="true" />
            </div>
            <p className={subtleText}>tense meetings</p>
          </div>
          <div className="rounded-lg border border-cyan-200/18 bg-cyan-300/8 px-3 py-2">
            <div className="flex items-center justify-between">
              <p className="text-xl font-semibold text-cyan-50">{hygieneCount}</p>
              <ClipboardCheck className="h-4 w-4 text-cyan-200/72" aria-hidden="true" />
            </div>
            <p className={subtleText}>hygiene issues</p>
          </div>
        </div>
        <blockquote className="line-clamp-3 rounded-lg border-l-2 border-violet-300 bg-violet-300/8 px-3 py-2 text-sm leading-5 text-white/78">
          “{verdict}”
        </blockquote>
      </div>
    </section>
  )
}

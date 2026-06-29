import { TrendingDown, TrendingUp } from 'lucide-react'
import { scoreBand } from '../../lib/insights'
import useCountUp from './useCountUp'

function toneClasses(tone) {
  if (tone === 'emerald') return 'text-emerald-200'
  if (tone === 'amber') return 'text-amber-200'
  if (tone === 'violet') return 'text-violet-200'
  return 'text-cyan-200'
}

export default function MetricTile({ label, value, suffix = '', tone = 'cyan', isScore = false, delta = false, delay = 0 }) {
  const numeric = Number(value)
  const hasValue = Number.isFinite(numeric)
  const display = useCountUp(hasValue ? Math.abs(numeric) : 0)
  const band = isScore ? scoreBand(value) : null
  const resolvedTone = band?.tone || tone
  const isPositive = numeric > 0
  const isNegative = numeric < 0

  return (
    <div className={`animate-fade-in-up border-r border-white/[0.08] p-3 last:border-r-0 ${toneClasses(resolvedTone)}`} style={{ animationDelay: `${delay}ms` }} aria-live="off">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-white/48">{label}</p>
        {delta && hasValue && (
          <span className={`transition-transform duration-300 ${isNegative ? 'rotate-0 text-amber-200' : 'text-emerald-200'}`}>
            {isNegative ? <TrendingDown className="h-4 w-4" aria-hidden="true" /> : <TrendingUp className="h-4 w-4" aria-hidden="true" />}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1 border-b border-white/[0.06] pb-2">
        <span className="text-2xl font-semibold tracking-[-0.04em] text-white">
          {hasValue ? `${delta && isPositive ? '+' : delta && isNegative ? '-' : ''}${display}` : '—'}
        </span>
        {suffix && hasValue && <span className="text-sm text-white/52">{suffix}</span>}
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full" style={{ width: hasValue ? `${Math.min(Math.abs(numeric), 100)}%` : '0%', background: band?.color || 'currentColor' }} />
      </div>
      {band && <p className="mt-1 text-[11px] font-medium" style={{ color: band.color }}>{band.label}</p>}
    </div>
  )
}

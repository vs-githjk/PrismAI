import { TrendingDown, TrendingUp } from 'lucide-react'
import { scoreBand } from '../../lib/insights'
import useCountUp from './useCountUp'

function toneClasses(tone) {
  if (tone === 'emerald') return 'text-emerald-200'
  if (tone === 'lime') return 'text-lime-200'
  if (tone === 'amber') return 'text-amber-200'
  if (tone === 'orange') return 'text-orange-200'
  if (tone === 'rose') return 'text-rose-200'
  if (tone === 'violet') return 'text-violet-200'
  return 'text-cyan-200'
}

export default function MetricTile({ label, value, suffix = '', tone = 'cyan', isScore = false, delta = false, delay = 0, hint = '', bar = false }) {
  const numeric = Number(value)
  // null/undefined must NOT become a confident "0" — Number(null) is 0 and 0 is
  // finite, which is how "Completion rate 0 %" shipped on a page that was
  // simultaneously listing five decisions. Missing data renders the dash below.
  const hasValue = value !== null && value !== undefined && value !== '' && Number.isFinite(numeric)
  const display = useCountUp(hasValue ? Math.abs(numeric) : 0)
  const band = isScore ? scoreBand(value) : null
  const resolvedTone = band?.tone || tone
  const isPositive = numeric > 0
  const isNegative = numeric < 0

  return (
    <div className={`animate-fade-in-up border-r border-[color:var(--db-border)] p-3 last:border-r-0 ${toneClasses(resolvedTone)}`} style={{ animationDelay: `${delay}ms` }} aria-live="off">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--db-text-faint)]">{label}</p>
        {delta && hasValue && (
          <span className={`transition-transform duration-300 ${isNegative ? 'rotate-0 text-amber-200' : 'text-emerald-200'}`}>
            {isNegative ? <TrendingDown className="h-4 w-4" aria-hidden="true" /> : <TrendingUp className="h-4 w-4" aria-hidden="true" />}
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1 border-b border-[color:var(--db-border)] pb-2">
        <span className="text-2xl font-semibold tracking-[-0.04em] text-[color:var(--db-text)]">
          {hasValue ? `${delta && isPositive ? '+' : delta && isNegative ? '-' : ''}${display}` : '—'}
        </span>
        {suffix && hasValue && <span className="text-sm text-[color:var(--db-text-faint)]">{suffix}</span>}
      </div>
      {/* A 0-100 bar only means something when the value IS a proportion. It used
          to render for every tile, so "avg decisions 2 /meeting" drew a 2%-full
          bar — decoration reading as data. Opt in via `bar`. */}
      {bar && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--db-fill-strong)]">
          <div className="h-full rounded-full" style={{ width: hasValue ? `${Math.min(Math.abs(numeric), 100)}%` : '0%', background: band?.color || 'currentColor' }} />
        </div>
      )}
      {band && hasValue && <p className="mt-1 text-[11px] font-medium" style={{ color: band.color }}>{band.label}</p>}
      {hint && <p className="mt-1 text-[11px] leading-snug text-[color:var(--db-text-faint)]">{hint}</p>}
    </div>
  )
}

import { Users } from 'lucide-react'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '—'
}

export default function OwnerLoad({ insights }) {
  const owners = insights.topOwners || []
  const flagged = new Set((insights.ownershipDrift || []).map((item) => item.owner))
  const max = Math.max(...owners.map((owner) => owner.count), 1)

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Owners</p>
          <h2 className={cardTitle}>Owner load</h2>
        </div>
        <Users className="h-5 w-5 text-cyan-200/80" aria-hidden="true" />
      </div>

      {owners.length ? (
        <div className="overflow-hidden rounded-lg border border-white/[0.08]">
          {owners.map((owner) => {
            const isFlagged = flagged.has(owner.owner)
            return (
              <div
                key={owner.owner}
                className={`border-b border-white/[0.07] px-3 py-2 last:border-b-0 ${isFlagged ? 'bg-amber-300/8' : 'bg-black/18'}`}
              >
                <div className="mb-1.5 flex items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border border-cyan-200/16 bg-cyan-300/10 text-[11px] font-semibold text-cyan-50">
                    {initials(owner.owner)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-white">{owner.owner}</p>
                    <p className={subtleText}>{owner.count} action item{owner.count === 1 ? '' : 's'}</p>
                  </div>
                  {isFlagged && <span className="rounded-full border border-amber-200/24 bg-amber-300/10 px-2 py-0.5 text-[10px] font-semibold text-amber-100">drift</span>}
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="h-full rounded-full bg-cyan-300 animate-bar-grow" style={{ width: `${Math.max((owner.count / max) * 100, 8)}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <p className={subtleText}>Owner patterns appear once action items have assigned owners.</p>
      )}
    </section>
  )
}

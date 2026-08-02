import { Users } from 'lucide-react'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '—'
}

export default function OwnerLoad({ insights }) {
  const owners = insights.topOwners || []
  const flagged = new Set((insights.ownershipDrift || []).map((item) => item.owner))

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
        <div className="overflow-hidden rounded-lg border border-[color:var(--db-border)]">
          {owners.map((owner) => {
            const isFlagged = flagged.has(owner.owner)
            return (
              <div
                key={owner.owner}
                className={`border-b border-[color:var(--db-border)] px-3 py-2 last:border-b-0 ${isFlagged ? 'bg-amber-300/8' : 'bg-black/18'}`}
              >
                {/* The list is already sorted descending and each count is printed,
                    so the old per-owner bar added nothing — with counts of 2/2/1/1
                    it drew two full and two half brand-cyan stripes, reading as a
                    field of decoration. Count right-aligned instead. */}
                <div className="flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill-strong)] text-[11px] font-semibold text-[color:var(--db-text-soft)]">
                    {initials(owner.owner)}
                  </span>
                  <p className="min-w-0 flex-1 truncate text-sm font-semibold text-[color:var(--db-text)]">{owner.owner}</p>
                  {isFlagged && <span className="shrink-0 rounded-full border border-amber-200/24 bg-amber-300/10 px-2 py-0.5 text-[10px] font-semibold text-amber-100">drift</span>}
                  <span className={`shrink-0 ${subtleText}`}>
                    <span className="font-semibold text-[color:var(--db-text-soft)]">{owner.count}</span> open
                  </span>
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

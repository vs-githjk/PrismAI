import { formatMeetingDate, scoreBand } from '../../lib/insights'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

export default function MeetingsRail({ history, onSelect, selectedMeetingId = null }) {
  const meetings = history.slice(0, 12)

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Meetings</p>
        <h2 className={cardTitle}>Recent meeting memory</h2>
      </div>

      {meetings.length ? (
        <div className="no-scrollbar flex snap-x gap-2 overflow-x-auto pb-1">
          {meetings.map((entry, index) => {
            const score = entry.result?.health_score?.score
            const band = scoreBand(score)
            const badges = entry.result?.health_score?.badges || []
            const isSelected = entry.id === selectedMeetingId
            return (
              <button
                type="button"
                key={entry.id}
                onClick={() => onSelect?.(entry)}
                className={`min-h-[122px] w-[240px] flex-shrink-0 snap-start rounded-xl border bg-black/22 p-3 text-left transition hover:-translate-y-0.5 hover:border-cyan-200/30 hover:bg-white/[0.055] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/16 ${isSelected ? 'border-cyan-200/55 ring-2 ring-cyan-300/18' : 'border-white/[0.1]'}`}
                style={{ animationDelay: `${index * 45}ms` }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex rounded-md border px-2 py-0.5 text-[10px] font-semibold" style={{ borderColor: `${band.color}55`, color: band.color, background: `${band.color}16` }}>
                    {Number.isFinite(Number(score)) ? `${score} / ${band.label}` : band.label}
                  </span>
                  {isSelected && (
                    <span className="rounded-md border border-cyan-200/30 bg-cyan-300/10 px-2 py-0.5 text-[10px] font-semibold text-cyan-100">
                      Latest
                    </span>
                  )}
                </div>
                <p className="mt-2 line-clamp-1 text-sm font-semibold leading-5 text-white">{entry.title || 'Meeting'}</p>
                <p className="mt-1 text-[11px] text-white/45">{formatMeetingDate(entry.date)}</p>
                <p className="mt-2 line-clamp-1 text-xs leading-5 text-white/58">{entry.result?.health_score?.verdict || entry.result?.summary || 'No verdict recorded.'}</p>
                {badges.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {badges.slice(0, 2).map((badge) => (
                      <span key={badge} className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/56">{badge}</span>
                    ))}
                  </div>
                )}
              </button>
            )
          })}
        </div>
      ) : (
        <p className={subtleText}>Saved meetings will appear here.</p>
      )}
    </section>
  )
}

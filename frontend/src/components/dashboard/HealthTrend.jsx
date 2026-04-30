import { useMemo, useState } from 'react'
import { scoreBand, formatMeetingDate } from '../../lib/insights'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

function buildPath(points, width, height, pad) {
  if (points.length === 0) return ''
  return points.map((point, index) => {
    const x = pad + (index / Math.max(points.length - 1, 1)) * (width - pad * 2)
    const y = pad + ((100 - point.score) / 100) * (height - pad * 2)
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
  }).join(' ')
}

export default function HealthTrend({ history, onSelect }) {
  const [hovered, setHovered] = useState(null)
  const data = useMemo(() => [...history]
    .filter((entry) => entry?.result?.health_score?.score !== undefined && entry?.result?.health_score?.score !== null)
    .slice(0, 10)
    .reverse()
    .map((entry) => ({
      id: entry.id,
      title: entry.title || 'Meeting',
      date: formatMeetingDate(entry.date),
      score: Number(entry.result.health_score.score),
      badges: entry.result.health_score.badges || [],
      raw: entry,
    })), [history])

  const width = 720
  const height = 180
  const pad = 22
  const linePath = buildPath(data, width, height, pad)
  const areaPath = linePath ? `${linePath} L ${width - pad} ${height - pad} L ${pad} ${height - pad} Z` : ''
  const active = hovered ?? data.at(-1)

  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Health pulse</p>
          <h2 className={cardTitle}>Recent score movement</h2>
        </div>
        {active && (
          <div className="rounded-lg border border-white/[0.1] bg-black/30 px-3 py-1.5 text-right">
            <p className="max-w-[220px] truncate text-xs font-semibold text-white">{active.title}</p>
            <p className="mt-1 text-[11px]" style={{ color: scoreBand(active.score).color }}>{active.score}/100 · {active.date}</p>
          </div>
        )}
      </div>

      {data.length < 2 ? (
        <div className="flex min-h-[150px] items-center justify-center rounded-2xl border border-dashed border-white/[0.14] bg-white/[0.025]">
          <p className={subtleText}>More meetings unlock a trend line.</p>
        </div>
      ) : (
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[180px] w-full overflow-visible" role="img" aria-label="Meeting health score trend">
          <defs>
            <linearGradient id="healthArea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.24" />
              <stop offset="55%" stopColor="#8b5cf6" stopOpacity="0.12" />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 25, 50, 75, 100].map((tick) => {
            const y = pad + ((100 - tick) / 100) * (height - pad * 2)
            return (
              <g key={tick}>
                <line x1={pad} x2={width - pad} y1={y} y2={y} stroke="rgba(255,255,255,0.055)" />
                <text x="4" y={y + 3} fill="rgba(255,255,255,0.32)" fontSize="10">{tick}</text>
              </g>
            )
          })}
          <rect x={pad} y={pad} width={width - pad * 2} height={height - pad * 2} fill="none" stroke="rgba(255,255,255,0.04)" />
          <path d={areaPath} fill="url(#healthArea)" />
          <path d={linePath} fill="none" stroke="#22d3ee" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="path-draw" />
          {data.map((point, index) => {
            const x = pad + (index / Math.max(data.length - 1, 1)) * (width - pad * 2)
            const y = pad + ((100 - point.score) / 100) * (height - pad * 2)
            const band = scoreBand(point.score)
            return (
              <g
                key={point.id}
                role="button"
                tabIndex="0"
                onMouseEnter={() => setHovered(point)}
                onFocus={() => setHovered(point)}
                onClick={() => onSelect?.(point.raw)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') onSelect?.(point.raw)
                }}
                className="cursor-pointer focus:outline-none"
              >
                <circle cx={x} cy={y} r={hovered?.id === point.id ? 7 : 5} fill={band.color} stroke="#050505" strokeWidth="2" />
              </g>
            )
          })}
          <g>
            <text x={pad} y={height - 4} fill="rgba(255,255,255,0.38)" fontSize="10">{data[0]?.date}</text>
            <text x={width - pad - 48} y={height - 4} fill="rgba(255,255,255,0.38)" fontSize="10">{data.at(-1)?.date}</text>
          </g>
        </svg>
      )}
    </section>
  )
}

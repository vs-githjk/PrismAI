import { useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

function scoreColor(s) {
  if (s >= 80) return '#10b981'
  if (s >= 60) return '#6366f1'
  if (s >= 40) return '#f59e0b'
  return '#ef4444'
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  const color = scoreColor(d.score)
  return (
    <div className="rounded-xl px-3 py-2 text-xs shadow-xl"
      style={{ background: 'rgba(7,4,15,0.97)', border: '1px solid rgba(255,255,255,0.1)' }}>
      <p className="text-gray-200 font-medium leading-snug max-w-[140px] truncate">{d.title}</p>
      <p className="font-bold mt-0.5" style={{ color }}>{d.score}/100</p>
      <p className="text-gray-600 mt-0.5">{d.date}</p>
    </div>
  )
}

export default function ScoreTrendChart({ history, onSelect }) {
  const [expanded, setExpanded] = useState(false)

  const data = [...history]
    .filter(h => h.score !== undefined && h.score !== null)
    .reverse()
    .map(h => ({
      date: new Date(h.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      score: h.score,
      title: h.title || 'Untitled',
      id: h.id,
      raw: h,
    }))

  if (data.length < 2) return null

  const avg = Math.round(data.reduce((s, d) => s + d.score, 0) / data.length)
  const trend = data[data.length - 1].score - data[0].score
  const trendColor = trend > 0 ? '#10b981' : trend < 0 ? '#ef4444' : '#6b7280'
  const trendLabel = trend > 0 ? `+${trend}` : trend < 0 ? `${trend}` : '→'

  return (
    <div className="mx-6 mb-4 rounded-2xl overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(14,165,233,0.1)' }}>
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-sky-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          <span className="text-xs font-semibold text-gray-400">Meeting Health Trend</span>
          <span className="text-[10px] text-gray-600 ml-1">avg {avg}/100</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold" style={{ color: trendColor }}>{trendLabel}</span>
          <svg className={`w-3.5 h-3.5 text-gray-600 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4">
          <ResponsiveContainer width="100%" height={90}>
            <AreaChart
              data={data}
              onClick={(e) => {
                const p = e?.activePayload?.[0]?.payload
                if (p && onSelect) onSelect(p.raw)
              }}
              style={{ cursor: 'pointer' }}
            >
              <defs>
                <linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                tick={{ fill: '#4b5563', fontSize: 9 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis domain={[0, 100]} hide />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="score"
                stroke="#06b6d4"
                strokeWidth={1.5}
                fill="url(#trendGrad)"
                dot={{ fill: '#06b6d4', r: 3, strokeWidth: 0 }}
                activeDot={{ r: 5, fill: '#38bdf8', strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-gray-700 text-center mt-1">Click a point to load that meeting</p>
        </div>
      )}
    </div>
  )
}

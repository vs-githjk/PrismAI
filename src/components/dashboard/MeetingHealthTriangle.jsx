import { useCountUp, overallHealth } from '../../lib/healthScore'

// Balance triangle (3-axis radar) for the meeting health sub-scores.
// Clarity / Action / Engagement each score 0-100 and contribute one third of
// the overall. Overall = round(average). Semantic traffic-light coloring lives
// in TRI_THRESHOLDS below — change it in one place.

const TRI_THRESHOLDS = [
  { min: 80, color: '#22c55e' }, // green  — healthy
  { min: 60, color: '#f59e0b' }, // amber  — fair
  { min: 0, color: '#ef4444' },  // red    — needs work
]
const triColor = (score) =>
  (TRI_THRESHOLDS.find((t) => score >= t.min) ?? TRI_THRESHOLDS[TRI_THRESHOLDS.length - 1]).color

const META = {
  clarity: { label: 'Clarity' },
  action: { label: 'Action' },
  engagement: { label: 'Engagement' },
}
// Axis angles in degrees (SVG: -90 = straight up).
const ANGLE = { clarity: -90, action: 30, engagement: 150 }
const ORDER = ['clarity', 'action', 'engagement']

// viewBox geometry
const C = 80        // center
const MAX_R = 52    // radius at score = 100
const VB = 160      // viewBox extent
const LABEL_R = MAX_R + 16

const polar = (r, deg) => {
  const a = (deg * Math.PI) / 180
  return [C + r * Math.cos(a), C + r * Math.sin(a)]
}
const ptStr = ([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`

export default function MeetingHealthTriangle({ scores, size = 248 }) {
  // Animate each axis + the overall number so the shape grows in, matching the
  // app's gauge/bar count-up feel.
  const clarity = useCountUp(scores.clarity, 1000)
  const action = useCountUp(scores.action, 1000)
  const engagement = useCountUp(scores.engagement, 1000)
  const animated = { clarity, action, engagement }

  // Mean of the 3 axes via the shared helper so this never drifts from the
  // home card. (The helper keys on action_orientation; map our local `action`.)
  const overall = overallHealth({
    breakdown: {
      clarity: scores.clarity,
      action_orientation: scores.action,
      engagement: scores.engagement,
    },
  })
  const displayedOverall = useCountUp(overall, 1000)
  const overallColor = triColor(displayedOverall)

  // Grid rings at 33 / 66 / 100% and the data polygon.
  const ring = (f) => ORDER.map((k) => ptStr(polar(MAX_R * f, ANGLE[k]))).join(' ')
  const dataPoly = ORDER.map((k) => ptStr(polar((MAX_R * animated[k]) / 100, ANGLE[k]))).join(' ')

  return (
    <div style={{ width: size }}>
      <svg
        viewBox={`0 -10 ${VB} 138`}
        width={size}
        height={(size * 138) / VB}
        className="block"
        role="img"
        aria-label={`Meeting health ${overall} of 100 — clarity ${scores.clarity}, action-oriented ${scores.action}, engagement ${scores.engagement}`}
      >
        {/* grid rings */}
        {[1, 0.66, 0.33].map((f, i) => (
          <polygon key={i} points={ring(f)} fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth={1.25} />
        ))}
        {/* axis spokes */}
        {ORDER.map((k) => {
          const [x, y] = polar(MAX_R, ANGLE[k])
          return <line key={k} x1={C} y1={C} x2={x} y2={y} stroke="rgba(255,255,255,0.16)" strokeWidth={1.25} />
        })}
        {/* data shape */}
        <polygon points={dataPoly} fill="rgba(255,255,255,0.12)" stroke="rgba(255,255,255,0.65)" strokeWidth={2.5} strokeLinejoin="round" />
        {/* vertices + always-on labels */}
        {ORDER.map((k) => {
          const [cx, cy] = polar((MAX_R * animated[k]) / 100, ANGLE[k])
          const [lx, ly] = polar(LABEL_R, ANGLE[k])
          const color = triColor(scores[k])
          const top = ANGLE[k] === -90
          const anchor = top ? 'middle' : lx > C ? 'end' : 'start'
          // Push the two bottom labels further apart horizontally.
          const dx = top ? 0 : lx > C ? 12 : -12
          return (
            <g key={k}>
              <circle cx={cx} cy={cy} r={5} fill={color} />
              <text
                x={lx + dx}
                y={ly + (top ? -3 : 4)}
                textAnchor={anchor}
                style={{ fontSize: 9, fontWeight: 600 }}
              >
                <tspan fill="rgba(255,255,255,0.55)">{META[k].label} </tspan>
                <tspan fill={color} fontWeight={700}>{scores[k]}</tspan>
              </text>
            </g>
          )
        })}
      </svg>
      <div className="mt-1 text-center font-semibold leading-none" style={{ fontSize: '1.5rem' }}>
        <span className="text-white">Overall: </span>
        <span style={{ color: overallColor }}>{displayedOverall}</span>
      </div>
    </div>
  )
}

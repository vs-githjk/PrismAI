import { useCountUp, overallHealth } from '../../lib/healthScore'
import { healthColor } from '../../lib/insights'

// Balance triangle (3-axis radar) for the meeting health sub-scores.
// Clarity / Action / Engagement each score 0-100 and contribute one third of
// the overall. Overall = round(average).
//
// Colour comes from lib/insights healthColor — the app's ONE health scale. This
// file used to declare its own traffic light, so the same score rendered green
// here and violet on Home. Don't reintroduce a local scale.
const triColor = healthColor

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

// `ungraded`: the same triangle as the app's visual anchor, but empty — wireframe,
// axis labels without numbers, "Overall: —". Shown for recordings the calibrated
// agent declined to score (solo bot sessions etc.) so the meeting page keeps its
// identity without inventing a number.
export default function MeetingHealthTriangle({ scores = {}, size = 248, ungraded = false }) {
  // Animate each axis + the overall number so the shape grows in, matching the
  // app's gauge/bar count-up feel.
  const clarity = useCountUp(scores.clarity, 1000)
  const action = useCountUp(scores.action, 1000)
  const engagement = useCountUp(scores.engagement, 1000)
  const animated = { clarity, action, engagement }

  // Mean of the 3 axes via the shared helper so this never drifts from the
  // home card. (The helper keys on action_orientation; map our local `action`.)
  const overall = ungraded ? null : overallHealth({
    breakdown: {
      clarity: scores.clarity,
      action_orientation: scores.action,
      engagement: scores.engagement,
    },
  })
  // Colour from the TRUE score, never the animating value: seeding the count-up
  // at 0 made a healthy 84 spend its first second as a red "needs work" verdict
  // that then silently corrected itself. The number is printed directly for the
  // same reason — the polygon growing in (vertices below) carries the animation.
  const overallColor = triColor(overall)

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
        aria-label={ungraded
          ? 'Meeting health not graded'
          : `Meeting health ${overall} of 100 — clarity ${scores.clarity}, action-oriented ${scores.action}, engagement ${scores.engagement}`}
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
        {!ungraded && (
          <polygon points={dataPoly} fill="rgba(255,255,255,0.12)" stroke="rgba(255,255,255,0.65)" strokeWidth={2.5} strokeLinejoin="round" />
        )}
        {/* vertices + always-on labels */}
        {ORDER.map((k) => {
          const [cx, cy] = polar((MAX_R * animated[k]) / 100, ANGLE[k])
          const [lx, ly] = polar(LABEL_R, ANGLE[k])
          const color = ungraded ? 'rgba(148,163,184,0.6)' : triColor(scores[k])
          const top = ANGLE[k] === -90
          const anchor = top ? 'middle' : lx > C ? 'end' : 'start'
          // Push the two bottom labels further apart horizontally.
          const dx = top ? 0 : lx > C ? 12 : -12
          return (
            <g key={k}>
              {!ungraded && <circle cx={cx} cy={cy} r={5} fill={color} />}
              <text
                x={lx + dx}
                y={ly + (top ? -3 : 4)}
                textAnchor={anchor}
                style={{ fontSize: 9, fontWeight: 600 }}
              >
                <tspan fill="rgba(255,255,255,0.55)">{META[k].label} </tspan>
                {!ungraded && <tspan fill={color} fontWeight={700}>{scores[k]}</tspan>}
              </text>
            </g>
          )
        })}
      </svg>
      <div className="mt-1 text-center font-semibold leading-none" style={{ fontSize: '1.5rem' }}>
        <span className="text-[color:var(--db-text)]">Overall: </span>
        <span style={{ color: overallColor }}>{ungraded ? '—' : overall}</span>
      </div>
    </div>
  )
}

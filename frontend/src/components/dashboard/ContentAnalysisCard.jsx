import { Quote, ThumbsDown, ThumbsUp, Sparkles } from 'lucide-react'
import { cardGlowStyle, glassCard } from './dashboardStyles'

function scoreColor(s) {
  const n = Number(s)
  if (!Number.isFinite(n)) return '#94a3b8'
  if (n >= 75) return '#22c55e'
  if (n >= 55) return '#84cc16'
  if (n >= 35) return '#f59e0b'
  return '#ef4444'
}

// The deep-dive card for pitch / interview meetings. Renders the type-specific
// rubric, strengths/weaknesses, and key moments produced by the content_analyst
// agent. The headline score lives in the top health slot (swapped in MeetingView);
// here we lead with the verdict + per-dimension breakdown.
export default function ContentAnalysisCard({ analysis }) {
  if (!analysis) return null
  const { type_label, score_label, headline_score, verdict, rubric = [], strengths = [], weaknesses = [], key_moments = [] } = analysis

  return (
    <section className={`${glassCard} p-5`} style={cardGlowStyle}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          <h2 className="text-xl font-bold tracking-[-0.01em] text-white">
            {type_label || 'Content analysis'}
          </h2>
        </div>
        {Number.isFinite(Number(headline_score)) && (
          <span className="flex items-baseline gap-1.5">
            <span className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-white/40">
              {score_label || 'Score'}
            </span>
            <span className="text-2xl font-bold leading-none" style={{ color: scoreColor(headline_score) }}>
              {headline_score}
            </span>
          </span>
        )}
      </div>

      {verdict && (
        <blockquote className="mb-5 border-l-2 border-cyan-400/40 pl-3.5 text-[14px] italic leading-6 text-white/80">
          {verdict}
        </blockquote>
      )}

      {rubric.length > 0 && (
        <div className="mb-5 space-y-3.5">
          {rubric.map((row, i) => (
            <div key={i}>
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-white/90">{row.dimension}</span>
                <span className="text-[12px] font-bold" style={{ color: scoreColor(row.score) }}>
                  {Number.isFinite(Number(row.score)) ? row.score : '—'}
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.max(0, Math.min(100, Number(row.score) || 0))}%`, backgroundColor: scoreColor(row.score) }}
                />
              </div>
              {row.notes && <p className="mt-1.5 text-[12.5px] leading-5 text-white/62">{row.notes}</p>}
              {row.evidence && (
                <p className="mt-1 flex items-start gap-1.5 text-[11.5px] italic leading-5 text-white/45">
                  <Quote className="mt-0.5 h-3 w-3 shrink-0 -scale-x-100 text-white/30" aria-hidden="true" />
                  <span>{row.evidence}</span>
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          {strengths.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-300/80">
                <ThumbsUp className="h-3 w-3" aria-hidden="true" /> Strengths
              </p>
              <ul className="space-y-1">
                {strengths.map((s, i) => (
                  <li key={i} className="flex gap-1.5 text-[12.5px] leading-5 text-white/72">
                    <span className="text-emerald-300/70">·</span><span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {weaknesses.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">
                <ThumbsDown className="h-3 w-3" aria-hidden="true" /> To improve
              </p>
              <ul className="space-y-1">
                {weaknesses.map((w, i) => (
                  <li key={i} className="flex gap-1.5 text-[12.5px] leading-5 text-white/72">
                    <span className="text-amber-300/70">·</span><span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {key_moments.length > 0 && (
        <div className="border-t border-white/[0.07] pt-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-white/40">Key moments</p>
          <div className="space-y-2.5">
            {key_moments.map((m, i) => (
              <div key={i} className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2">
                {m.label && <p className="text-[12.5px] font-semibold text-white/85">{m.label}</p>}
                {m.quote && <p className="mt-0.5 text-[12px] italic leading-5 text-white/55">“{m.quote}”</p>}
                {m.note && <p className="mt-1 text-[12px] leading-5 text-white/70">{m.note}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

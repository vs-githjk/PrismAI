import { useState } from 'react'
import { ChevronDown, Quote, ThumbsDown, ThumbsUp, Sparkles, ShieldQuestion } from 'lucide-react'
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
// agent. The headline score lives ONLY in the top health slot (swapped in
// MeetingView) — repeating it in this card's corner put two loud copies of the
// same number on one screen. Here we lead with the verdict, and the rubric is
// progressive-disclosure: label + bar + number always (the shape of the analysis
// in one glance), the explanation + evidence quote on demand. The weakest
// dimension starts open — it's the one you came to understand.
export default function ContentAnalysisCard({ analysis }) {
  const rubric = analysis?.rubric || []
  const [openRows, setOpenRows] = useState(() => {
    let weakest = null
    let min = Infinity
    rubric.forEach((row, i) => {
      const n = Number(row.score)
      if (Number.isFinite(n) && n < min) { min = n; weakest = i }
    })
    return new Set(weakest === null ? [] : [weakest])
  })
  if (!analysis) return null
  const { type_label, verdict, strengths = [], weaknesses = [], key_moments = [], authenticity_signals = [], authenticity_note } = analysis
  const toggleRow = (i) => setOpenRows((prev) => {
    const next = new Set(prev)
    next.has(i) ? next.delete(i) : next.add(i)
    return next
  })

  return (
    <section className={`${glassCard} p-5`} style={cardGlowStyle}>
      <div className="mb-4 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-cyan-300" aria-hidden="true" />
        <h2 className="text-xl font-bold tracking-[-0.01em] text-[color:var(--db-text)]">
          {type_label || 'Content analysis'}
        </h2>
      </div>

      {verdict && (
        <blockquote className="mb-5 border-l-2 border-cyan-400/40 pl-3.5 text-[14px] italic leading-6 text-[color:var(--db-text-soft)]">
          {verdict}
        </blockquote>
      )}

      {rubric.length > 0 && (
        <div className="mb-5 space-y-1">
          {rubric.map((row, i) => {
            const expandable = !!(row.notes || row.evidence)
            const open = openRows.has(i)
            return (
              <div key={i} className={`rounded-lg px-2 py-1.5 transition ${expandable ? 'hover:bg-[var(--db-fill)]' : ''}`}>
                <button
                  type="button"
                  onClick={expandable ? () => toggleRow(i) : undefined}
                  aria-expanded={expandable ? open : undefined}
                  disabled={!expandable}
                  className="block w-full text-left disabled:cursor-default"
                >
                  <div className="mb-1 flex items-baseline justify-between gap-3">
                    <span className="flex items-center gap-1.5 text-[13px] font-semibold text-[color:var(--db-text)]">
                      {row.dimension}
                      {expandable && (
                        <ChevronDown
                          className={`h-3 w-3 text-[color:var(--db-text-faint)] transition-transform ${open ? 'rotate-180' : ''}`}
                          aria-hidden="true"
                        />
                      )}
                    </span>
                    <span className="text-[12px] font-bold" style={{ color: scoreColor(row.score) }}>
                      {Number.isFinite(Number(row.score)) ? row.score : '—'}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--db-fill-strong)]">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${Math.max(0, Math.min(100, Number(row.score) || 0))}%`, backgroundColor: scoreColor(row.score) }}
                    />
                  </div>
                </button>
                {open && row.notes && <p className="mt-1.5 text-[12.5px] leading-5 text-[color:var(--db-text-muted)]">{row.notes}</p>}
                {open && row.evidence && (
                  <p className="mt-1 flex items-start gap-1.5 text-[11.5px] italic leading-5 text-[color:var(--db-text-muted)]">
                    <Quote className="mt-0.5 h-3 w-3 shrink-0 -scale-x-100 text-[color:var(--db-text-faint)]" aria-hidden="true" />
                    <span>{row.evidence}</span>
                  </p>
                )}
              </div>
            )
          })}
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
                  <li key={i} className="flex gap-1.5 text-[12.5px] leading-5 text-[color:var(--db-text-soft)]">
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
                  <li key={i} className="flex gap-1.5 text-[12.5px] leading-5 text-[color:var(--db-text-soft)]">
                    <span className="text-amber-300/70">·</span><span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {key_moments.length > 0 && (
        <div className="border-t border-[color:var(--db-border)] pt-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[color:var(--db-text-faint)]">Key moments</p>
          <div className="space-y-2.5">
            {key_moments.map((m, i) => (
              <div key={i} className="rounded-lg border border-[color:var(--db-border)] bg-[var(--db-fill)] px-3 py-2">
                {m.label && <p className="text-[12.5px] font-semibold text-[color:var(--db-text)]">{m.label}</p>}
                {m.quote && <p className="mt-0.5 text-[12px] italic leading-5 text-[color:var(--db-text-muted)]">“{m.quote}”</p>}
                {m.note && <p className="mt-1 text-[12px] leading-5 text-[color:var(--db-text-soft)]">{m.note}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {authenticity_signals.length > 0 && (
        <div className="mt-4 border-t border-[color:var(--db-border)] pt-4">
          <div className="mb-2 flex items-center gap-1.5">
            <ShieldQuestion className="h-3.5 w-3.5 text-amber-300/80" aria-hidden="true" />
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-300/80">Authenticity signals</p>
          </div>
          {/* Heuristic only — reliable AI detection does not exist. Never a verdict. */}
          <p className="mb-2.5 rounded-lg border border-amber-400/20 bg-amber-400/[0.05] px-3 py-2 text-[11.5px] leading-5 text-amber-100/70">
            Heuristic writing patterns, <span className="font-semibold">not proof</span> of AI use — automated AI detection is unreliable. Read these as observations, not a judgment.
          </p>
          <ul className="space-y-1">
            {authenticity_signals.map((s, i) => (
              <li key={i} className="flex gap-1.5 text-[12.5px] leading-5 text-[color:var(--db-text-soft)]">
                <span className="text-amber-300/60">·</span><span>{s}</span>
              </li>
            ))}
          </ul>
          {authenticity_note && (
            <p className="mt-2 text-[12px] italic leading-5 text-[color:var(--db-text-muted)]">{authenticity_note}</p>
          )}
        </div>
      )}
    </section>
  )
}

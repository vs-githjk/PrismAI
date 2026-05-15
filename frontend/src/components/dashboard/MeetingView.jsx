import { useState } from 'react'
import { ArrowLeft, CheckCircle2, ChevronDown, FileText } from 'lucide-react'
import CalendarCard from './CalendarCard'
import EmailCard from './EmailCard'
import SpeakerCoachCard from './SpeakerCoachCard'
import { deriveDisplayTitle, formatMeetingDate, scoreBand } from '../../lib/insights'
import { BADGE_POSITIVE, useCountUp } from '../../lib/healthScore'
import { cardGlowStyle, cardTitle, eyebrow, glassCard, subtleText } from './dashboardStyles'

const GAUGE_RADIUS = 46
const GAUGE_STROKE = 8
// Half-circumference for a 180° arc (we draw only the top half)
const GAUGE_ARC_LEN = Math.PI * GAUGE_RADIUS

function SemicircularGauge({ score, color }) {
  const displayed = useCountUp(score, 1000)
  const offset = GAUGE_ARC_LEN - (displayed / 100) * GAUGE_ARC_LEN
  // Box: width = diameter + stroke padding, height = radius + stroke padding (semicircle only).
  const width = GAUGE_RADIUS * 2 + GAUGE_STROKE * 2
  const height = GAUGE_RADIUS + GAUGE_STROKE * 2
  const cx = width / 2
  const cy = GAUGE_RADIUS + GAUGE_STROKE

  return (
    <div className="relative shrink-0" style={{ width, height: height + 8 }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {/* Track — top semicircle only (sweep from left to right across the top) */}
        <path
          d={`M ${cx - GAUGE_RADIUS} ${cy} A ${GAUGE_RADIUS} ${GAUGE_RADIUS} 0 0 1 ${cx + GAUGE_RADIUS} ${cy}`}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={GAUGE_STROKE}
          strokeLinecap="round"
        />
        {/* Progress */}
        <path
          d={`M ${cx - GAUGE_RADIUS} ${cy} A ${GAUGE_RADIUS} ${GAUGE_RADIUS} 0 0 1 ${cx + GAUGE_RADIUS} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={GAUGE_STROKE}
          strokeLinecap="round"
          strokeDasharray={GAUGE_ARC_LEN}
          strokeDashoffset={offset}
          style={{ filter: `drop-shadow(0 0 6px ${color}80)` }}
        />
      </svg>
      {/* Number sits just under the arc's apex */}
      <div
        className="absolute inset-x-0 flex flex-col items-center"
        style={{ top: GAUGE_RADIUS * 0.55 + GAUGE_STROKE }}
      >
        <span className="text-3xl font-semibold leading-none" style={{ color }}>
          {displayed}
        </span>
        <span className="mt-0.5 text-[10px] font-medium text-white/40">/100</span>
      </div>
    </div>
  )
}

function BreakdownBar({ label, value, color }) {
  const displayed = useCountUp(value, 1000)
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[11.5px] font-medium text-white/68">{label}</span>
        <span className="text-[11.5px] font-semibold text-white/86">{displayed}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div
          className="h-full rounded-full"
          style={{ width: `${displayed}%`, background: color, transition: 'width 16ms linear' }}
        />
      </div>
    </div>
  )
}

export default function MeetingView({ result, meeting, gmailConnected = false, onToggleActionItem, readOnly = false, transcript = '', onBack, recordedByEmail = null }) {
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  if (!result) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 text-center">
        <p className="text-lg font-semibold text-white/54">No meeting loaded</p>
        <p className={subtleText}>Select a meeting from history or analyze a new one below.</p>
      </div>
    )
  }

  const healthScore = result.health_score
  const band = scoreBand(healthScore?.score)
  const breakdown = healthScore?.breakdown || {}
  const hasBreakdown =
    breakdown.clarity !== undefined ||
    breakdown.action_orientation !== undefined ||
    breakdown.engagement !== undefined

  const actionItems = result.action_items || []
  const openCount = actionItems.filter((item) => !item.completed).length
  const decisions = result.decisions || []
  const sentiment = result.sentiment
  const displayTitle = deriveDisplayTitle({ title: meeting?.title, result })

  return (
    <div className="space-y-3">
      {meeting && (
        <div className="px-0.5">
          <div className="flex items-center gap-2">
            {onBack && (
              <button
                type="button"
                onClick={onBack}
                aria-label="Back to dashboard"
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-cyan-200/70 transition-colors hover:text-cyan-200"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            )}
            <p className={eyebrow}>Current meeting</p>
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-white">{displayTitle}</h1>
          {meeting.date && <p className={`mt-0.5 ${subtleText}`}>{formatMeetingDate(meeting.date)}</p>}
          {recordedByEmail && (
            <p className="mt-1 text-[11px] text-white/38">Recorded by {recordedByEmail}</p>
          )}
        </div>
      )}

      {transcript && (
        <section className={`${glassCard}`} style={cardGlowStyle}>
          <button
            type="button"
            onClick={() => setTranscriptOpen(o => !o)}
            className="flex w-full items-center justify-between gap-3 p-4"
          >
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 shrink-0 text-cyan-300/80" aria-hidden="true" />
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-200">Transcript</p>
            </div>
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-white/70 transition-transform duration-200 ${transcriptOpen ? 'rotate-180' : ''}`}
              aria-hidden="true"
            />
          </button>
          {transcriptOpen && (
            <div className="border-t border-white/[0.07] px-4 pb-4 pt-3">
              <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap text-[13px] leading-6 text-white/90">
                {transcript}
              </pre>
            </div>
          )}
        </section>
      )}

      <div className="grid gap-3 lg:grid-cols-[minmax(340px,1fr)_minmax(0,1.3fr)]">
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <p className={`${eyebrow} mb-3`}>Health score</p>
          {healthScore?.score !== undefined ? (
            <>
              <div className="flex items-center gap-4">
                <div className="flex flex-col items-center">
                  <SemicircularGauge score={healthScore.score} color={band.color} />
                  <span
                    className="mt-2 inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-semibold"
                    style={{ borderColor: `${band.color}44`, color: band.color, background: `${band.color}18` }}
                  >
                    {band.label}
                  </span>
                </div>
                {hasBreakdown && (
                  <div className="min-w-0 flex-1 space-y-2">
                    {breakdown.clarity !== undefined && (
                      <BreakdownBar label="Clarity" value={breakdown.clarity} color={band.color} />
                    )}
                    {breakdown.action_orientation !== undefined && (
                      <BreakdownBar label="Action-Oriented" value={breakdown.action_orientation} color={band.color} />
                    )}
                    {breakdown.engagement !== undefined && (
                      <BreakdownBar label="Engagement" value={breakdown.engagement} color={band.color} />
                    )}
                  </div>
                )}
              </div>
              {healthScore.badges?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {healthScore.badges.map((badge) => {
                    const isPositive = BADGE_POSITIVE.has(badge)
                    return (
                      <span
                        key={badge}
                        className={`rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${
                          isPositive
                            ? 'border-emerald-400/30 bg-emerald-400/[0.10] text-emerald-300'
                            : 'border-red-400/30 bg-red-400/[0.10] text-red-300'
                        }`}
                      >
                        {isPositive ? '✓' : '!'} {badge}
                      </span>
                    )
                  })}
                </div>
              )}
            </>
          ) : (
            <p className={subtleText}>No health score recorded.</p>
          )}
        </section>

        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <p className={`${eyebrow} mb-2`}>Summary</p>
          {result.summary ? (
            <p className="text-sm leading-6 text-white">{result.summary}</p>
          ) : (
            <p className={subtleText}>No summary generated.</p>
          )}
          {healthScore?.verdict && (
            <blockquote
              className="mt-3 border-l-2 pl-3 text-sm leading-5 text-white/62"
              style={{ borderColor: `${band.color}88` }}
            >
              {healthScore.verdict}
            </blockquote>
          )}
        </section>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className={eyebrow}>Action items</p>
              <h2 className={cardTitle}>
                {openCount} open · {actionItems.length} total
              </h2>
            </div>
            <CheckCircle2 className="h-5 w-5 shrink-0 text-cyan-200/70" aria-hidden="true" />
          </div>
          {actionItems.length ? (
            <div className="overflow-hidden rounded-lg border border-white/[0.08]">
              {actionItems.map((item, i) => (
                <div
                  key={`${item.task}-${i}`}
                  className="flex items-start gap-2.5 border-b border-white/[0.07] px-3 py-2.5 last:border-b-0"
                >
                  {readOnly ? (
                    <span
                      aria-hidden="true"
                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border-2 ${
                        item.completed ? 'border-cyan-400 bg-cyan-400' : 'border-white/30'
                      }`}
                    >
                      {item.completed && (
                        <svg className="h-2.5 w-2.5 text-[#07040f]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onToggleActionItem?.(i)}
                      aria-label={item.completed ? 'Mark as not done' : 'Mark as done'}
                      aria-pressed={!!item.completed}
                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border-2 transition-colors ${
                        item.completed
                          ? 'border-cyan-400 bg-cyan-400'
                          : 'border-white/30 hover:border-cyan-300'
                      }`}
                    >
                      {item.completed && (
                        <svg className="h-2.5 w-2.5 text-[#07040f]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </button>
                  )}
                  <div className={`min-w-0 flex-1 ${item.completed ? 'opacity-50' : ''}`}>
                    <p className={`text-sm font-medium text-white ${item.completed ? 'line-through' : ''}`}>
                      {item.task}
                    </p>
                    <p className={subtleText}>
                      {item.owner || 'Unowned'}
                      {item.due ? ` · ${item.due}` : ''}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className={subtleText}>No action items in this meeting.</p>
          )}
        </section>

        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className={eyebrow}>Decisions</p>
              <h2 className={cardTitle}>{decisions.length} decision{decisions.length !== 1 ? 's' : ''} recorded</h2>
            </div>
            <FileText className="h-5 w-5 shrink-0 text-cyan-200/70" aria-hidden="true" />
          </div>
          {decisions.length ? (
            <div className="overflow-hidden rounded-lg border border-white/[0.08]">
              {decisions.map((d, i) => (
                <div key={i} className="border-b border-l-2 border-white/[0.07] border-l-violet-300/70 bg-black/18 px-3 py-2.5 last:border-b-0">
                  <p className="text-sm font-medium text-white">{d.decision}</p>
                  {d.owner && <p className={subtleText}>{d.owner}</p>}
                </div>
              ))}
            </div>
          ) : (
            <p className={subtleText}>No decisions recorded in this meeting.</p>
          )}
        </section>
      </div>

      {sentiment?.overall && !readOnly && (
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <p className={`${eyebrow} mb-2`}>Sentiment</p>
          <div className="flex flex-wrap items-start gap-3">
            <span className="rounded-full border border-white/[0.12] bg-white/[0.06] px-3 py-1 text-sm font-semibold capitalize text-white">
              {sentiment.overall}
            </span>
            {sentiment.notes && <p className="text-sm leading-5 text-white/62">{sentiment.notes}</p>}
          </div>
        </section>
      )}

      {!readOnly && <EmailCard email={result.follow_up_email} gmailConnected={gmailConnected} />}
      <CalendarCard suggestion={result.calendar_suggestion} />
      {!readOnly && <SpeakerCoachCard speakerCoach={result.speaker_coach} />}

    </div>
  )
}

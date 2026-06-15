import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, CornerDownRight, FileText, Lightbulb, Paperclip, Plus } from 'lucide-react'
import CalendarCard from './CalendarCard'
import EmailCard from './EmailCard'
import KnowledgeDocCard from '../KnowledgeDocCard'
import MeetingHealthTriangle from './MeetingHealthTriangle'
import RecordingPlayer from './RecordingPlayer'
import SentimentCard from './SentimentCard'
import SpeakerCoachCard from './SpeakerCoachCard'
import KnowledgeUploadModal from '../KnowledgeUploadModal'
import { listDocs } from '../../lib/knowledge'
import { useCountUp } from '../../lib/healthScore'
import { dueInfo, dueLabel, compareDue } from '../../lib/dueStatus'
import { cardGlowStyle, glassCard, subtleText } from './dashboardStyles'

const GAUGE_RADIUS = 46
const GAUGE_STROKE = 9
// Half-circumference for a 180° arc (we draw only the top half)
const GAUGE_ARC_LEN = Math.PI * GAUGE_RADIUS

// Semantic health color: low = danger (red), mid = warning (amber), high = success (green).
function healthColor(score) {
  const value = Number(score)
  if (!Number.isFinite(value)) return '#94a3b8'
  if (value < 30) return '#ef4444'
  if (value < 60) return '#f59e0b'
  return '#22c55e'
}

// Padding baked into the viewBox so the progress arc's glow isn't clipped.
const GAUGE_PAD = 12

// Decision importance → label + accent. 1=critical, 2=significant, 3=minor.
const DECISION_PRIORITY = {
  1: { label: 'Critical', color: '#f87171', border: 'rgba(248,113,113,0.30)', tint: 'rgba(248,113,113,0.10)' },
  2: { label: 'Significant', color: '#fbbf24', border: 'rgba(251,191,36,0.30)', tint: 'rgba(251,191,36,0.10)' },
  3: { label: 'Minor', color: '#94a3b8', border: 'rgba(148,163,184,0.28)', tint: 'rgba(148,163,184,0.10)' },
}

function SemicircularGauge({ score }) {
  const displayed = useCountUp(score, 1000)
  const color = healthColor(displayed)
  const offset = GAUGE_ARC_LEN - (displayed / 100) * GAUGE_ARC_LEN
  // Geometry box: diameter wide, radius tall (top semicircle only) + padding for the glow.
  const width = GAUGE_RADIUS * 2 + GAUGE_PAD * 2
  // Top padding for the glow; minimal bottom padding so the number sits close to the arc.
  const height = GAUGE_RADIUS + GAUGE_PAD + 3
  const cx = width / 2
  const cy = GAUGE_RADIUS + GAUGE_PAD

  return (
    <div className="relative w-[200px]">
      <svg
        width="100%"
        viewBox={`0 0 ${width} ${height}`}
        className="block overflow-visible"
        aria-hidden="true"
      >
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
          style={{ filter: `drop-shadow(0 0 7px ${color}99)` }}
        />
      </svg>
      {/* Number nests inside the arc's hollow, just under its apex. */}
      <span
        className="absolute inset-x-0 bottom-1 text-center font-semibold leading-none"
        style={{ color, fontSize: '2.75rem' }}
      >
        {displayed}
      </span>
    </div>
  )
}

export default function MeetingView({ result, meeting, gmailConnected = false, onToggleActionItem, readOnly = false, transcript = '', recordedByEmail = null, workspaceId = null, suggestedEmails = [], onResultUpdate }) {
  const meetingId = meeting?.id ? String(meeting.id) : undefined
  const [pinnedDocs, setPinnedDocs] = useState([])
  const [uploadOpen, setUploadOpen] = useState(false)
  const [transcriptOpen, setTranscriptOpen] = useState(false)

  const refreshDocs = useCallback(async () => {
    if (!meetingId) return
    try {
      const list = await listDocs({ meetingId })
      setPinnedDocs(list)
    } catch {
      // non-critical — silently ignore errors in the pinned docs panel
    }
  }, [meetingId])

  useEffect(() => { refreshDocs() }, [refreshDocs])

  useEffect(() => {
    if (!pinnedDocs.some(d => d.status === 'processing')) return
    const id = setInterval(refreshDocs, 5000)
    return () => clearInterval(id)
  }, [pinnedDocs, refreshDocs])
  if (!result) {
    return (
      <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 text-center">
        <p className="text-lg font-semibold text-white/54">No meeting loaded</p>
        <p className={subtleText}>Select a meeting from history or analyze a new one below.</p>
      </div>
    )
  }

  const healthScore = result.health_score
  const sentiment = result.sentiment

  // Show the balance triangle only when all three sub-scores are present & finite;
  // otherwise fall back to the single-arc gauge (seed/old meetings, mid-analysis).
  const bd = healthScore?.breakdown
  const breakdown = bd && {
    clarity: Number(bd.clarity),
    action: Number(bd.action_orientation),
    engagement: Number(bd.engagement),
  }
  const hasBreakdown = !!breakdown &&
    [breakdown.clarity, breakdown.action, breakdown.engagement].every(Number.isFinite)

  const actionItems = result.action_items || []
  const openCount = actionItems.filter((item) => !item.completed).length
  // Sort open-first, then by deadline (overdue/soonest first, undated last) —
  // while preserving each item's original index for the completion PATCH.
  const sortedActionItems = actionItems
    .map((item, originalIndex) => ({ item, originalIndex, due: dueInfo(item) }))
    .sort((a, b) => {
      if (!!a.item.completed !== !!b.item.completed) return a.item.completed ? 1 : -1
      return compareDue(a.due, b.due)
    })

  const DUE_STYLE = {
    overdue: 'border-red-400/30 bg-red-400/[0.10] text-red-300',
    soon: 'border-amber-400/30 bg-amber-400/[0.10] text-amber-300',
    later: 'border-white/[0.12] bg-white/[0.04] text-white/55',
  }
  // Surface the importance the agent assigns: sort critical-first and badge each.
  // Keep each decision's original index so it can be matched to linked actions.
  const decisions = (result.decisions || [])
    .map((d, _i) => ({ ...d, _i }))
    .sort((a, b) => (a.importance || 3) - (b.importance || 3))

  // Decision ↔ action links (indices reference the original arrays).
  const decisionLinks = result.decision_links || []
  const actionsByDecision = {} // decision index -> [action indices]
  const decisionByAction = {}  // action index -> decision index
  const linkedDecisions = new Set() // decisions the linker returned an entry for
  for (const link of decisionLinks) {
    linkedDecisions.add(link.decision)
    actionsByDecision[link.decision] = link.actions || []
    for (const a of (link.actions || [])) decisionByAction[a] = link.decision
  }
  const showPinned = !readOnly && !!meetingId

  const pinnedSection = showPinned ? (
    <section className={`${glassCard} flex max-h-[30vh] flex-col p-4`} style={cardGlowStyle}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Paperclip className="h-4 w-4 text-cyan-300" />
          <h3 className="text-sm font-semibold text-white">Pinned Documents</h3>
        </div>
        <button onClick={() => setUploadOpen(true)}
                className="flex items-center gap-1 rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/80 hover:bg-white/10">
          <Plus className="h-3 w-3" /> Add
        </button>
      </div>
      <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
        {pinnedDocs.length === 0 ? (
          <p className="text-[11px] text-white/40">No documents pinned to this meeting.</p>
        ) : (
          <div className="space-y-2">
            {pinnedDocs.map(d => <KnowledgeDocCard key={d.id} doc={d} onChange={refreshDocs} />)}
          </div>
        )}
      </div>
      <KnowledgeUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)}
                            meetingId={meetingId} workspaceId={workspaceId} onUploaded={refreshDocs} />
    </section>
  ) : null

  return (
    <div className="space-y-5">
      <div
        className={`grid gap-5 ${
          showPinned
            ? 'lg:grid-cols-[max-content_minmax(0,1.5fr)_minmax(0,1fr)]'
            : 'lg:grid-cols-[max-content_minmax(0,1fr)]'
        }`}
      >
        <section className="flex max-h-[30vh] flex-col items-center justify-center px-2 py-4">
          {hasBreakdown ? (
            <MeetingHealthTriangle scores={breakdown} />
          ) : healthScore?.score !== undefined ? (
            <>
              <SemicircularGauge score={healthScore.score} />
              <p className="mt-1.5 text-sm font-medium text-white/55">Health score</p>
            </>
          ) : (
            <p className={subtleText}>No health score recorded.</p>
          )}
        </section>

        <section className="flex max-h-[30vh] flex-col justify-center p-4">
          <p className="mb-2.5 text-xl font-bold tracking-[-0.01em] text-white">Summary</p>
          <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
            {result.tldr && (
              <p className="mb-3 text-[15px] font-semibold leading-6 text-white">{result.tldr}</p>
            )}
            {result.summary ? (
              <p className={`${result.tldr ? 'text-[13.5px] text-white/65' : 'text-[15px] text-white/90'} leading-7`}>{result.summary}</p>
            ) : (
              <p className={subtleText}>No summary generated.</p>
            )}
            {result.topics?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {result.topics.map((topic, i) => (
                  <span key={i} className="rounded-full border border-white/[0.10] bg-white/[0.04] px-2.5 py-0.5 text-[11px] font-medium text-white/70">
                    {topic}
                  </span>
                ))}
              </div>
            )}
            {healthScore?.verdict && (
              <figure
                className="mt-3.5 border-l-2 pl-3.5"
                style={{ borderColor: healthColor(healthScore.score) }}
              >
                <figcaption
                  className="text-[9.5px] font-semibold uppercase tracking-[0.18em]"
                  style={{ color: healthColor(healthScore.score) }}
                >
                  Verdict
                </figcaption>
                <blockquote className="mt-1 text-[13px] italic leading-6 text-white/75">
                  {healthScore.verdict}
                </blockquote>
              </figure>
            )}
            {healthScore?.improvement_tip && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.05] px-3 py-2">
                <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-300" aria-hidden="true" />
                <div>
                  <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-cyan-300/80">To improve next time</p>
                  <p className="mt-0.5 text-[13px] leading-5 text-white/80">{healthScore.improvement_tip}</p>
                </div>
              </div>
            )}
          </div>
        </section>

        {pinnedSection}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className={`${glassCard} flex max-h-[40vh] flex-col p-5`} style={cardGlowStyle}>
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <h2 className="text-xl font-bold tracking-[-0.01em] text-white">Action items</h2>
            {actionItems.length > 0 && (
              <span
                className="text-sm font-semibold"
                style={{ color: openCount > 0 ? '#f59e0b' : '#22c55e' }}
              >
                {openCount > 0 ? `${openCount} open` : 'All done'}
              </span>
            )}
          </div>
          <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
          {actionItems.length ? (
            <div>
              {sortedActionItems.map(({ item, originalIndex: i, due }) => {
                const check = (
                  <span
                    aria-hidden="true"
                    className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-md border-2 transition-colors ${
                      item.completed
                        ? 'border-emerald-400 bg-emerald-400'
                        : `border-white/30${readOnly ? '' : ' group-hover:border-emerald-300'}`
                    }`}
                  >
                    {item.completed && (
                      <svg className="h-3 w-3 text-[#07040f]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                )
                return (
                  <div
                    key={`${item.task}-${i}`}
                    className="flex items-start gap-3 border-t border-white/[0.06] py-3 first:border-t-0 first:pt-0"
                  >
                    {readOnly ? (
                      check
                    ) : (
                      <button
                        type="button"
                        onClick={() => onToggleActionItem?.(i)}
                        aria-label={item.completed ? 'Mark as not done' : 'Mark as done'}
                        aria-pressed={!!item.completed}
                        className="group shrink-0"
                      >
                        {check}
                      </button>
                    )}
                    <div className={`min-w-0 flex-1 ${item.completed ? 'opacity-45' : ''}`}>
                      <p className={`text-[15px] font-medium leading-snug text-white ${item.completed ? 'line-through' : ''}`}>
                        {item.task}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <p className="text-xs font-medium text-white/45">
                          {item.owner || 'Unowned'}
                          {item.due && item.due !== 'TBD' ? ` · ${item.due}` : ''}
                        </p>
                        {!item.completed && (due.status === 'overdue' || due.status === 'soon') && (
                          <span className={`rounded-full border px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide ${DUE_STYLE[due.status]}`}>
                            {dueLabel(due)}
                          </span>
                        )}
                      </div>
                      {item.external_ref && (
                        <span className="mt-1.5 inline-flex items-center gap-1 rounded-full border border-cyan-400/25 bg-cyan-400/[0.08] px-2 py-0.5 text-[10.5px] font-medium text-cyan-200">
                          {item.external_ref.tool === 'linear_create_issue' ? '⬡' : '📅'} {item.external_ref.external_id}
                        </span>
                      )}
                      {decisionByAction[i] !== undefined && result.decisions?.[decisionByAction[i]] && (
                        <p className="mt-1 flex items-start gap-1 text-[10.5px] text-violet-300/70">
                          <CornerDownRight className="mt-0.5 h-3 w-3 shrink-0 rotate-180" aria-hidden="true" />
                          <span className="line-clamp-1">From decision: {result.decisions[decisionByAction[i]].decision}</span>
                        </p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className={subtleText}>No action items in this meeting.</p>
          )}
          </div>
        </section>

        <section className={`${glassCard} flex max-h-[40vh] flex-col p-5`} style={cardGlowStyle}>
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <h2 className="text-xl font-bold tracking-[-0.01em] text-white">Decisions</h2>
            {decisions.length > 0 && (
              <span className="text-sm font-semibold text-violet-300">{decisions.length}</span>
            )}
          </div>
          <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
          {decisions.length ? (
            <div className="space-y-3">
              {decisions.map((d, i) => {
                const prio = DECISION_PRIORITY[d.importance] || DECISION_PRIORITY[3]
                return (
                  <div key={i} className="border-l-2 pl-3.5" style={{ borderColor: prio.border }}>
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[15px] font-medium leading-snug text-white">{d.decision}</p>
                      <span
                        className="mt-0.5 shrink-0 rounded-full border px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                        style={{ borderColor: prio.border, color: prio.color, background: prio.tint }}
                      >
                        {prio.label}
                      </span>
                    </div>
                    {d.rationale && (
                      <p className="mt-1 text-[12.5px] leading-5 text-white/55">{d.rationale}</p>
                    )}
                    {d.owner && <p className="mt-1 text-xs font-medium text-white/45">{d.owner}</p>}
                    {actionsByDecision[d._i]?.length > 0 && (
                      <div className="mt-1.5 space-y-0.5">
                        {actionsByDecision[d._i].map((ai) => (
                          <p key={ai} className="flex items-start gap-1 text-[11px] text-cyan-300/70">
                            <CornerDownRight className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
                            <span className="line-clamp-1">{result.action_items?.[ai]?.task}</span>
                          </p>
                        ))}
                      </div>
                    )}
                    {linkedDecisions.has(d._i) && !(actionsByDecision[d._i]?.length) && (
                      <span className="mt-1.5 inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/[0.10] px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-amber-300">
                        ⚠ No action item
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <p className={subtleText}>No decisions recorded in this meeting.</p>
          )}
          </div>
        </section>
      </div>

      {!readOnly && <SentimentCard sentiment={sentiment} />}

      {!readOnly && (
        <EmailCard
          email={result.follow_up_email}
          gmailConnected={gmailConnected}
          suggestedEmails={suggestedEmails}
          onSave={(updated) => onResultUpdate?.({ follow_up_email: updated })}
        />
      )}

      <CalendarCard
        suggestion={result.calendar_suggestion}
        meetingDate={meeting?.date}
        meetingTitle={meeting?.title || result?.title || ''}
        readOnly={readOnly}
        suggestedEmails={suggestedEmails}
      />

      {/* Secondary insight — kept low, just above the recording/transcript. */}
      {!readOnly && <SpeakerCoachCard speakerCoach={result.speaker_coach} />}

      {meeting?.id && meeting?.recording_provider === 'recall' && (
        <RecordingPlayer
          meetingId={meeting.id}
          recordingProvider={meeting.recording_provider}
          transcriptSegments={meeting.transcript_segments}
          transcriptText={transcript}
        />
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
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-white">Transcript</p>
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

    </div>
  )
}

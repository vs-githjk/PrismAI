import { useState, useEffect, useCallback } from 'react'
import { CornerDownRight, Lightbulb, Paperclip, Plus, X } from 'lucide-react'
import CalendarCard from './CalendarCard'
import CollapsibleSection from './CollapsibleSection'
import EmailCard from './EmailCard'
import KnowledgeDocCard from '../KnowledgeDocCard'
import MeetingHealthTriangle from './MeetingHealthTriangle'
import RecordingPlayer from './RecordingPlayer'
import SentimentCard from './SentimentCard'
import SpeakerCoachCard from './SpeakerCoachCard'
import SuggestedActions from './SuggestedActions'
import ContentAnalysisCard from './ContentAnalysisCard'
import MeetingTypeControl from './MeetingTypeControl'
import KnowledgeUploadModal from '../KnowledgeUploadModal'
import { listDocs } from '../../lib/knowledge'
import { apiFetch } from '../../lib/api'
import { useCountUp, overallHealth } from '../../lib/healthScore'
import { dueInfo, dueLabel, compareDue } from '../../lib/dueStatus'
import { healthColor } from '../../lib/insights'
import { MEETING_TYPES, resolvedType, hasContentAnalysis } from '../../lib/meetingType'
import { cardGlowStyle, glassCard, subtleText, eyebrow, cardTitle, bodyText } from './dashboardStyles'

const GAUGE_RADIUS = 46
const GAUGE_STROKE = 9
// Half-circumference for a 180° arc (we draw only the top half)
const GAUGE_ARC_LEN = Math.PI * GAUGE_RADIUS

// Health colour comes from the app's ONE scale (lib/insights healthColor:
// >=80 emerald, 60-79 amber, <60 rose, null = slate "no score"). This file used to
// declare its own 30/60 thresholds, which is why a 73-scoring meeting showed an
// amber triangle beside a green Verdict accent on the same screen.

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

export default function MeetingView({ result, meeting, gmailConnected = false, onToggleActionItem, readOnly = false, transcript = '', recordedByEmail = null, workspaceId = null, suggestedEmails = [], onResultUpdate, viewerName = '', actionConnections = {}, teamsWebhook = '' }) {
  const meetingId = meeting?.id ? String(meeting.id) : undefined
  const [pinnedDocs, setPinnedDocs] = useState([])
  const [uploadOpen, setUploadOpen] = useState(false)
  // Content-analysis lens override (re-runs content_analyst via /agent).
  const [typeBusy, setTypeBusy] = useState(false)
  const [typeError, setTypeError] = useState('')
  // Persist the bot-exit dismissal per meeting so a refresh doesn't bring the banner
  // back once the user has acknowledged why the bot left.
  const exitDismissKey = meeting?.id ? `prism:exit-dismiss:${meeting.id}` : null
  const [exitNoteDismissed, setExitNoteDismissed] = useState(false)
  useEffect(() => {
    setExitNoteDismissed(exitDismissKey ? localStorage.getItem(exitDismissKey) === '1' : false)
  }, [exitDismissKey])
  const dismissExitNote = () => {
    setExitNoteDismissed(true)
    if (exitDismissKey) {
      try { localStorage.setItem(exitDismissKey, '1') } catch { /* storage unavailable */ }
    }
  }

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
        <p className="text-lg font-semibold text-[color:var(--db-text-faint)]">No meeting loaded</p>
        <p className={subtleText}>Select a meeting from history or analyze a new one below.</p>
      </div>
    )
  }

  const healthScore = result.health_score
  const sentiment = result.sentiment

  // A fresh/live analysis has no persisted `meeting` object yet (it's set only once
  // the row is loaded from history). We use that to flag the health score as a live
  // estimate — the saved copy is re-scored in a separate pass and is authoritative.
  const isProvisional = !meeting && !readOnly

  // Content analysis (pitch / interview deep-dive). `special` gates the score swap
  // + deep-dive card; the lens is overridable (re-runs content_analyst).
  const special = hasContentAnalysis(result)
  const contentAnalysis = special ? result.content_analysis : null
  const currentType = resolvedType(result)
  const canReanalyze = !!(transcript && transcript.trim())

  const handleTypeChange = async (newType) => {
    if (typeBusy || newType === currentType) return
    setTypeError('')
    // Switching to Standard just drops the deep-dive lens — no LLM needed.
    if (newType === 'standard') {
      onResultUpdate?.({ content_analysis: null, meeting_type: 'standard' })
      return
    }
    if (!canReanalyze) {
      setTypeError('Re-analysis needs the transcript in this view (bot-recorded meetings load it from history).')
      return
    }
    setTypeBusy(true)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 60_000)
    try {
      const res = await apiFetch('/agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: 'content_analyst', transcript, result, meeting_type: newType }),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error('failed')
      const data = await res.json()
      const ca = data?.content_analysis
      if (ca && ca.type === newType && Array.isArray(ca.rubric) && ca.rubric.length) {
        onResultUpdate?.({ content_analysis: ca, meeting_type: newType })
      } else {
        setTypeError('Could not produce a breakdown for that type. Try again.')
      }
    } catch (e) {
      setTypeError(e?.name === 'AbortError' ? 'Re-analysis timed out. Try again.' : 'Re-analysis failed. Please try again.')
    } finally {
      clearTimeout(timeout)
      setTypeBusy(false)
    }
  }

  // Show the balance triangle only when all three sub-scores are present & finite;
  // otherwise fall back to the single-arc gauge (seed/old meetings, mid-analysis).
  const bd = healthScore?.breakdown
  const breakdown = bd && {
    clarity: Number(bd.clarity),
    action: Number(bd.action_orientation),
    engagement: Number(bd.engagement),
  }
  const hasBreakdown = !!breakdown &&
    [bd.clarity, bd.action_orientation, bd.engagement].every((v) => v !== null && v !== undefined) &&
    [breakdown.clarity, breakdown.action, breakdown.engagement].every(Number.isFinite)
  // Overall = mean of axes (shared helper); used for the verdict color tint so it
  // matches the triangle's Overall band instead of the LLM's standalone score.
  const overallScore = overallHealth(healthScore)
  // The score column renders whenever a health analysis exists — a null score
  // shows the triangle in its ungraded state (wireframe + "Overall: —") so the
  // page keeps its visual anchor without inventing a number.
  const hasScorePanel = special || hasBreakdown || !!healthScore

  const actionItems = result.action_items || []
  const openCount = actionItems.filter((item) => !item.completed).length
  // Sort open-first, then by deadline (overdue/soonest first, undated last) —
  // while preserving each item's original index for the completion PATCH.
  const sortedActionItems = actionItems
    // Phrases resolve against the MEETING date (fresh analyses have no meeting
    // object yet — today is then correct, the words were just said).
    .map((item, originalIndex) => ({ item, originalIndex, due: dueInfo(item, meeting?.date) }))
    .sort((a, b) => {
      if (!!a.item.completed !== !!b.item.completed) return a.item.completed ? 1 : -1
      return compareDue(a.due, b.due)
    })

  const DUE_STYLE = {
    overdue: 'border-red-400/30 bg-red-400/[0.10] text-red-300',
    soon: 'border-amber-400/30 bg-amber-400/[0.10] text-amber-300',
    later: 'border-[color:var(--db-border-strong)] bg-[var(--db-fill)] text-[color:var(--db-text-muted)]',
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
          <h3 className="text-sm font-semibold text-[color:var(--db-text)]">Pinned Documents</h3>
        </div>
        <button onClick={() => setUploadOpen(true)}
                className="flex items-center gap-1 rounded border border-[color:var(--db-border)] bg-[var(--db-fill)] px-2 py-1 text-[11px] text-[color:var(--db-text-soft)] hover:bg-[var(--db-fill-strong)]">
          <Plus className="h-3 w-3" /> Add
        </button>
      </div>
      <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
        {pinnedDocs.length === 0 ? (
          <p className="text-[11px] text-[color:var(--db-text-faint)]">No documents pinned to this meeting.</p>
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

  const exitNote = result.exit_note
  const exitAt = exitNote?.at ? new Date(exitNote.at) : null
  const exitTime = exitAt && !isNaN(exitAt) ? exitAt.toLocaleString() : null

  return (
    <div className="space-y-5">
      {exitNote?.reason && !exitNoteDismissed && (
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-400/25 bg-amber-400/10 px-3.5 py-2.5 text-[13px] text-amber-100/90">
          <span className="mt-0.5 shrink-0">⚠️</span>
          <span className="min-w-0 flex-1">
            <span className="font-semibold">Bot exit:</span> {exitNote.reason}
            {exitTime && <span className="text-amber-100/55"> · {exitTime}</span>}
          </span>
          <button
            type="button"
            onClick={dismissExitNote}
            aria-label="Dismiss bot exit notice"
            className="mt-0.5 shrink-0 rounded-md p-0.5 text-amber-100/50 transition-colors hover:bg-amber-400/15 hover:text-amber-100"
          >
            <X size={14} />
          </button>
        </div>
      )}
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <MeetingTypeControl
            label="Analysis lens"
            value={currentType}
            onChange={handleTypeChange}
            options={MEETING_TYPES}
            loading={typeBusy}
            title={canReanalyze
              ? 'Re-analyze this meeting with a different lens (pitch / interview get a deeper breakdown)'
              : 'Change the meeting type — deeper re-analysis needs the transcript loaded in this view'}
          />
          {typeBusy && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--db-text-muted)]">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--db-accent)]" />
              Re-analyzing the transcript… this takes ~15s
            </span>
          )}
          {!typeBusy && typeError && <span className="text-[11px] text-[color:var(--db-warn)]">{typeError}</span>}
        </div>
      )}
      {/* Summary-first record (Aug 2026): TL;DR + full summary lead, full width,
          as the strongest surface on the page. The score becomes a compact right
          rail beside it (stacks below on mobile) — when there is genuinely nothing
          to grade (score null — e.g. a solo bot-command session) the rail
          disappears rather than showing an empty gauge slot, and the summary takes
          the full row. Pinned documents sit below, full width, unchanged. */}
      <div className={hasScorePanel ? 'grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,240px)] lg:items-start' : ''}>
        <section>
          <p className={`${eyebrow} mb-2`}>Summary</p>
          {result.tldr && (
            <p className="mb-2.5 text-[18px] font-bold leading-7 text-[color:var(--db-text)]">{result.tldr}</p>
          )}
          {result.summary ? (
            <p className={bodyText}>{result.summary}</p>
          ) : (
            <p className={subtleText}>No summary generated.</p>
          )}
          {result.topics?.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {result.topics.map((topic, i) => (
                <span key={i} className="rounded-full border border-[color:var(--db-border)] bg-[var(--db-fill)] px-2.5 py-0.5 text-[11px] font-medium text-[color:var(--db-text-muted)]">
                  {topic}
                </span>
              ))}
            </div>
          )}
          {!special && healthScore?.verdict && (
            <figure
              className="mt-3.5 border-l-2 pl-3.5"
              style={{ borderColor: healthColor(overallScore) }}
            >
              <figcaption
                className="text-[9.5px] font-semibold uppercase tracking-[0.18em]"
                style={{ color: healthColor(overallScore) }}
              >
                Verdict
              </figcaption>
              <blockquote className="mt-1 text-[13px] italic leading-6 text-[color:var(--db-text-soft)]">
                {healthScore.verdict}
              </blockquote>
            </figure>
          )}
          {!special && healthScore?.improvement_tip && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.05] px-3 py-2">
              <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-300" aria-hidden="true" />
              <div>
                <p className="text-[9.5px] font-semibold uppercase tracking-[0.16em] text-cyan-300/80">To improve next time</p>
                <p className="mt-0.5 text-[13px] leading-5 text-[color:var(--db-text-soft)]">{healthScore.improvement_tip}</p>
              </div>
            </div>
          )}
        </section>

        {hasScorePanel && (
        <section className="flex min-w-0 flex-col items-center gap-1.5 py-1">
          {special ? (
            // Health triangle (clarity/engagement/action) is the wrong lens for a
            // pitch or interview — show the type's own headline score instead. A
            // missing score must not coerce to a confident 0 (Number(null) is 0
            // and finite) — check null/undefined/'' first, same guard as the
            // health-score branch below, and fall back to the same ungraded state.
            contentAnalysis.headline_score !== null && contentAnalysis.headline_score !== undefined && contentAnalysis.headline_score !== '' ? (
              <>
                <SemicircularGauge score={Number(contentAnalysis.headline_score)} />
                <p className="mt-1.5 text-sm font-medium text-[color:var(--db-text-muted)]">{contentAnalysis.score_label || 'Score'}</p>
              </>
            ) : (
              <>
                <MeetingHealthTriangle ungraded size={216} />
                <p className="mt-1.5 text-sm font-medium text-[color:var(--db-text-muted)]">Not graded</p>
              </>
            )
          ) : hasBreakdown ? (
            // Explicit size: the rail track tops out at 240px; the triangle's own
            // default (248px) would overflow it. 216px leaves 24px of horizontal
            // slack (matching the grid's own gap-6) so the shape never touches the
            // column edge, with margin for the shrink-safe minmax(0,240px) track.
            <MeetingHealthTriangle scores={breakdown} size={216} />
          ) : healthScore?.score !== null && healthScore?.score !== undefined ? (
            <>
              <SemicircularGauge score={healthScore.score} />
              <p className="mt-1.5 text-sm font-medium text-[color:var(--db-text-muted)]">Health score</p>
            </>
          ) : (
            <>
              <MeetingHealthTriangle ungraded size={216} />
              <p className="mt-1.5 text-sm font-medium text-[color:var(--db-text-muted)]">Not graded</p>
            </>
          )}
          {/* Live/unsaved analyses run a separate LLM pass from the saved copy, so the
              score can drift a point or two — flag it as provisional, not authoritative. */}
          {!special && isProvisional && (
            <span
              title="This is the live analysis. The saved copy is re-scored and is the authoritative value."
              className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-cyan-400/25 bg-cyan-400/[0.08] px-2.5 py-0.5 text-[10px] font-medium text-cyan-200/80"
            >
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
              Provisional · live estimate
            </span>
          )}
        </section>
        )}
      </div>

      {pinnedSection}

      {special && <ContentAnalysisCard key={currentType} analysis={contentAnalysis} />}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className={`${glassCard} flex max-h-[40vh] flex-col p-5`} style={cardGlowStyle}>
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <h2 className={cardTitle}>Action items</h2>
            {actionItems.length > 0 && (
              <span
                className={eyebrow}
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
                        : `border-[color:var(--db-border-strong)]${readOnly ? '' : ' group-hover:border-emerald-300'}`
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
                    className="flex items-start gap-3 border-t border-[color:var(--db-border)] py-3 first:border-t-0 first:pt-0"
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
                      <p className={`text-[15px] font-medium leading-snug text-[color:var(--db-text)] ${item.completed ? 'line-through' : ''}`}>
                        {item.task}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <p className="text-xs font-medium text-[color:var(--db-text-faint)]">
                          {item.owner || 'Unowned'}
                          {/* Resolved label over the raw phrase — "tomorrow" from a
                              June meeting must not read as literally tomorrow. */}
                          {due.status === 'later' || due.status === 'stale'
                            ? ` · ${dueLabel(due)}`
                            : !due.status && item.due && item.due !== 'TBD' ? ` · ${item.due}` : ''}
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
            <h2 className={cardTitle}>Decisions</h2>
            {decisions.length > 0 && (
              <span className={`${eyebrow} text-violet-300`}>{decisions.length}</span>
            )}
          </div>
          <div className="-mr-2 min-h-0 flex-1 overflow-y-auto pr-2">
          {decisions.length ? (
            <div>
              {decisions.map((d, i) => {
                const prio = DECISION_PRIORITY[d.importance] || DECISION_PRIORITY[3]
                return (
                  <div
                    key={i}
                    className="border-l-2 border-t border-t-[color:var(--db-border)] pl-3.5 py-3 first:border-t-0 first:pt-0"
                    style={{ borderLeftColor: prio.border }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[15px] font-medium leading-snug text-[color:var(--db-text)]">{d.decision}</p>
                      <span
                        className="mt-0.5 shrink-0 rounded-full border px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
                        style={{ borderColor: prio.border, color: prio.color, background: prio.tint }}
                      >
                        {prio.label}
                      </span>
                    </div>
                    {d.rationale && (
                      <p className="mt-1 text-[12.5px] leading-5 text-[color:var(--db-text-muted)]">{d.rationale}</p>
                    )}
                    {d.owner && <p className="mt-1 text-xs font-medium text-[color:var(--db-text-faint)]">{d.owner}</p>}
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

      {/* Everything below the actions/decisions row is collapsed by default
          (Aug 2026 brief): follow-up first, then the analysis tail. Sections
          expand on click; nothing is removed. */}
      {(!readOnly && (result.suggested_actions?.length > 0 || result.follow_up_email)) || result.calendar_suggestion?.recommended ? (
        <CollapsibleSection title="Follow-up" hint="email · calendar · ready-to-send actions">
          <div className="space-y-4 pt-1">
            {!readOnly && (result.suggested_actions?.length > 0) && (
              <SuggestedActions
                actions={result.suggested_actions}
                connections={actionConnections}
                suggestedEmails={suggestedEmails}
                meetingId={meetingId}
                teamsWebhook={teamsWebhook}
                workspaceId={workspaceId}
                readOnly={readOnly}
              />
            )}
            {!readOnly && (
              <EmailCard
                email={result.follow_up_email}
                gmailConnected={gmailConnected}
                suggestedEmails={suggestedEmails}
                onSave={(updated) => onResultUpdate?.({ follow_up_email: updated })}
                viewerName={viewerName}
                meetingId={meetingId}
                transcript={transcript}
                result={result}
              />
            )}
            <CalendarCard
              suggestion={result.calendar_suggestion}
              meetingDate={meeting?.date}
              meetingTitle={meeting?.title || result?.title || ''}
              readOnly={readOnly}
              suggestedEmails={suggestedEmails}
              meetingId={meetingId}
            />
          </div>
        </CollapsibleSection>
      ) : null}

      {/* Sentiment is per-speaker tone — meaningless for a single-authored
          article/report, so hide it there (covers auto-detected reports too).
          Collapsed by default (Aug 2026 brief) — its own header keeps the
          headline pill visible, so nothing is lost while closed. */}
      {!readOnly && currentType !== 'article' && <SentimentCard sentiment={sentiment} defaultOpen={false} />}

      {/* Talk-time / speaker coaching — N/A for a single-authored article/report. */}
      {!readOnly && currentType !== 'article' && <SpeakerCoachCard speakerCoach={result.speaker_coach} />}

      {meeting?.id && meeting?.recording_provider === 'recall' && (
        <RecordingPlayer
          meetingId={meeting.id}
          recordingProvider={meeting.recording_provider}
          transcriptSegments={meeting.transcript_segments}
          transcriptText={transcript}
        />
      )}

      {transcript && (
        <CollapsibleSection title="Transcript" hint="full text" defaultOpen={false}>
          <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap text-[13px] leading-6 text-[color:var(--db-text)]">
            {transcript}
          </pre>
        </CollapsibleSection>
      )}

    </div>
  )
}

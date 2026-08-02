import { useMemo } from 'react'
import { ChevronRight, Video, ClipboardList, Sparkles, CalendarPlus, MessagesSquare } from 'lucide-react'
import { deriveDisplayTitle, scoreBand } from '../../lib/insights'
import { overallHealth } from '../../lib/healthScore'
import { hasContentAnalysis, typeMeta } from '../../lib/meetingType'
import { collectOpenActions, byMineFirst } from '../../lib/actionItems'
import ActionItemRow from './ActionItemRow'

const island = 'dashboard-island flex min-h-0 flex-col overflow-hidden'
const cardHeading = 'text-[18px] font-semibold tracking-[-0.015em] text-[color:var(--db-text)] sm:text-[22px]'
const emptyCopy = 'text-sm leading-6 text-[color:var(--db-text-muted)]'

/**
 * The launcher, directly above the open action items in BOTH states: greeting
 * headline + the two primary CTAs. A returning user (history present) is
 * welcomed back; a first-run user just gets started, plus the sample offer.
 */
function Launcher({ isEmpty, onLoadSample, canLoadSample, onJoinMeeting, onPasteTranscript, showConnectCalendar, onConnectCalendar }) {
  return (
    <section className="dashboard-home-greeting order-1 flex flex-col px-1 text-left">
      {/* The hero stays in both states — it's the page's aesthetic anchor (owner's
          call). Controlled break so it never wraps mid-phrase. */}
      <h1 className="text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.08] text-[color:var(--db-text)]">
        {isEmpty ? <>Let&rsquo;s get started.</> : <><span className="block">Welcome back,</span>let&rsquo;s get started.</>}
      </h1>
      <p className="mt-3 max-w-md text-[15px] leading-6 text-[color:var(--db-text-muted)]">
        Bring Prism into a live call, or paste a transcript to analyze.
      </p>
      <div className="mt-5 flex flex-col gap-2.5 sm:flex-row sm:flex-wrap">
        {onJoinMeeting && (
          <button
            type="button"
            onClick={onJoinMeeting}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-full bg-cyan-400 px-6 text-sm font-semibold text-[#04222a] shadow-sm transition-all hover:bg-cyan-300"
          >
            <Video className="h-4 w-4" aria-hidden="true" />
            Join a meeting
          </button>
        )}
        {onPasteTranscript && (
          <button
            type="button"
            onClick={onPasteTranscript}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-full border border-white/15 bg-white/[0.04] px-6 text-sm font-medium text-white/85 transition-all hover:bg-white/[0.08]"
          >
            <ClipboardList className="h-4 w-4" aria-hidden="true" />
            Paste a transcript
          </button>
        )}
        {/* Sample data is an empty-state affordance only — offering it next to real
            history invites you to overwrite what you are looking at. */}
        {isEmpty && canLoadSample && (
          <button
            type="button"
            onClick={onLoadSample}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-full border border-white/10 bg-transparent px-6 text-sm font-medium text-white/60 transition-all hover:bg-white/[0.05] hover:text-white/80"
          >
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            See a sample
          </button>
        )}
      </div>
      {showConnectCalendar && (
        <button
          type="button"
          onClick={onConnectCalendar}
          className="group mt-4 inline-flex w-fit items-center gap-2 text-[13px] text-white/50 transition-colors hover:text-cyan-200"
        >
          <CalendarPlus className="h-4 w-4 text-white/40 transition-colors group-hover:text-cyan-300" aria-hidden="true" />
          <span>Connect Google or Outlook calendar to auto-join meetings</span>
          <span className="font-semibold text-cyan-300/80 group-hover:text-cyan-200">Connect →</span>
        </button>
      )}
    </section>
  )
}

/**
 * Compact preview: the four most urgent open items, then a way through to the
 * full page. Home showed all 43 in an internally-scrolling card, which turned the
 * one screen you glance at into a page's worth of list.
 */
function ActionItemsCard({ rows, total, mineCount, onOpenAll, onOpenMeeting, onToggle }) {
  const shown = rows.slice(0, 4)
  const rest = total - shown.length
  return (
    <section id="home-actions" className={`dashboard-home-actions order-3 ${island}`}>
      <button
        type="button"
        onClick={onOpenAll}
        className="group flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5 text-left transition hover:bg-[var(--db-fill)]"
      >
        <h2 className={`${cardHeading} transition group-hover:text-cyan-100`}>Open action items</h2>
        <span className="shrink-0 text-[11.5px] text-[color:var(--db-text-faint)]">
          {total} open{mineCount > 0 ? ` · ${mineCount} yours` : ''}
          <ChevronRight className="ml-1 inline h-3.5 w-3.5 -translate-y-[1px] transition group-hover:translate-x-0.5" aria-hidden="true" />
        </span>
      </button>

      {/* Scrolls internally when the New Meeting panel above squeezes the row. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {shown.length === 0 ? (
          <p className={`px-1 py-2 ${emptyCopy}`}>No open action items yet — they appear here as meetings assign them.</p>
        ) : (
          <>
            {/* Flat and urgency-ordered, not grouped: with four rows, date headings
                would cost more space than they explain. The full page groups. */}
            <ul className="space-y-1.5">
              {shown.map((row) => (
                <ActionItemRow
                  key={`${row.entry.id}-${row.index}`}
                  row={row}
                  onToggle={onToggle}
                  onOpenMeeting={onOpenMeeting}
                  showMeeting
                />
              ))}
            </ul>
            {rest > 0 && (
              <button
                type="button"
                onClick={onOpenAll}
                className="mt-2 w-full rounded-lg border border-[color:var(--db-border)] py-2 text-[12.5px] font-medium text-[color:var(--db-text-muted)] transition hover:border-cyan-400/30 hover:bg-cyan-400/[0.06] hover:text-cyan-100"
              >
                View all {total} action items →
              </button>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** Right column (full height): all past meetings, top-aligned list. */
function MeetingsCard({ history, onOpen, selectedMeetingId }) {
  return (
    <section className={`dashboard-home-meetings ${island}`}>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex flex-col">
          <h2 className={`mb-4 ${cardHeading}`}>Recent meetings</h2>
          {history.length ? (
            <div className="space-y-2.5">
              {/* Newest-first — the fetched/merged history array isn't guaranteed to be
                  date-ordered (a workspace re-fetch can land the newest meeting last),
                  and this card, unlike the sidebar, would otherwise show raw order. */}
              {[...history]
                .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
                .map((entry) => {
                // Pitch / interview meetings score on their own rubric — show that
                // (e.g. "PITCH 72") instead of the misleading health % for them.
                const ca = hasContentAnalysis(entry.result) ? entry.result.content_analysis : null
                const score = ca ? Number(ca.headline_score) : overallHealth(entry.result?.health_score)
                const band = scoreBand(score)
                // null check BEFORE Number() — Number(null) is a finite 0.
                const hasScore = score !== null && score !== undefined && Number.isFinite(Number(score))
                const scoreLabel = ca ? typeMeta(ca.type).short : 'Health'
                const isSelected = entry.id === selectedMeetingId
                // Prefer the one-sentence tldr — the long summary made every card two
                // lines of "Abhinav Dasari engaged with…" boilerplate, six cards deep.
                const summary =
                  entry.result?.tldr || entry.result?.summary || entry.result?.health_score?.verdict || 'No summary recorded.'
                return (
                  <button
                    type="button"
                    key={entry.id}
                    onClick={() => onOpen?.(entry)}
                    className={`group flex w-full items-stretch gap-4 rounded-2xl border bg-gradient-to-br from-white/[0.06] to-white/[0.015] p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:from-white/[0.09] hover:to-white/[0.03] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/16 ${isSelected ? 'border-cyan-200/45' : 'border-[color:var(--db-border)]'}`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-1 text-[19px] font-semibold leading-tight tracking-[-0.01em] text-[color:var(--db-text)]">
                        {deriveDisplayTitle(entry)}
                      </p>
                      <p className="mt-1.5 line-clamp-1 text-[13.5px] leading-6 text-[color:var(--db-text-muted)]">{summary}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end justify-center pl-1">
                      <span className="font-bold leading-none tracking-tight" style={{ color: band.color }}>
                        <span className="text-[28px]">{hasScore ? score : '—'}</span>
                        {hasScore && !ca && <span className="text-[15px]">%</span>}
                      </span>
                      <span className="mt-1.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-[color:var(--db-text-faint)]">{scoreLabel}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          ) : (
            <p className={`px-1 py-2 ${emptyCopy}`}>Saved meetings will appear here.</p>
          )}
        </div>
      </div>
    </section>
  )
}

export default function StatsCanvas({
  history,
  loadFromHistory,
  loadSample,
  canLoadSample = false,
  onJoinMeeting,
  onPasteTranscript,
  upcomingPanel = null,
  upcomingImminent = false,
  openThreads = [],
  onOpenTrend,
  showConnectCalendar = false,
  onConnectCalendar,
  selectedMeetingId = null,
  onToggleAction,
  user = null,
  onOpenAllActions,
}) {
  const safeHistory = history || []
  const isEmpty = safeHistory.length === 0

  // Just the counts and the urgency-ordered head of the list — the full grouped
  // view lives on the Action items page (ActionItemsView).
  const { rows, total, mineCount } = useMemo(() => {
    const all = collectOpenActions(safeHistory, user)
    return {
      rows: [...all].sort(byMineFirst),
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
    }
  }, [safeHistory, user])

  return (
    <div className="dashboard-home-grid">
      <div className="dashboard-home-left">
        <Launcher
          isEmpty={isEmpty}
          onLoadSample={loadSample}
          canLoadSample={canLoadSample}
          onJoinMeeting={onJoinMeeting}
          onPasteTranscript={onPasteTranscript}
          showConnectCalendar={showConnectCalendar}
          onConnectCalendar={onConnectCalendar}
        />
        <ActionItemsCard
          rows={rows}
          total={total}
          mineCount={mineCount}
          onOpenAll={onOpenAllActions}
          onOpenMeeting={loadFromHistory}
          onToggle={onToggleAction}
        />
        {/* Next joinable calendar events — pairs with the "Join a meeting" CTA above.
            The inner component renders nothing (hideEmpty) unless there's genuinely
            something to join; CSS :empty then hides this island shell too. When a
            meeting is imminent/in progress this is the most perishable thing on the
            page, so it jumps ABOVE the action items (CSS order — no remount). */}
        {upcomingPanel && (
          <div className={`dashboard-home-upcoming dashboard-island p-2 ${upcomingImminent ? 'order-2' : 'order-5'}`}>
            {upcomingPanel}
          </div>
        )}
        {/* One line of cross-meeting intelligence: the longest-running unresolved
            thread. Clicks through to Trend, where the full open-threads card lives. */}
        {openThreads.length > 0 && (
          <button
            type="button"
            onClick={onOpenTrend}
            className="dashboard-island group order-4 flex shrink-0 items-center gap-2.5 px-4 py-2.5 text-left transition hover:bg-[var(--db-fill)]"
          >
            <MessagesSquare className="h-4 w-4 shrink-0 text-amber-300/80" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate text-[12.5px] text-[color:var(--db-text-muted)]">
              <span className="font-semibold text-[color:var(--db-text)]">Still open: </span>
              {openThreads[0].thread}
            </span>
            {openThreads.length > 1 && (
              <span className="shrink-0 text-[11px] text-[color:var(--db-text-faint)]">+{openThreads.length - 1} more</span>
            )}
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)] transition group-hover:translate-x-0.5" aria-hidden="true" />
          </button>
        )}
      </div>
      <MeetingsCard history={safeHistory} onOpen={loadFromHistory} selectedMeetingId={selectedMeetingId} />
    </div>
  )
}

import { useMemo } from 'react'
import { CalendarPlus, ChevronRight, ClipboardList, MessagesSquare, Sparkles, Video, Zap } from 'lucide-react'
import { deriveDisplayTitle, scoreBand } from '../../lib/insights'
import { overallHealth } from '../../lib/healthScore'
import { hasContentAnalysis, typeMeta } from '../../lib/meetingType'
import { collectOpenActions } from '../../lib/actionItems'
import { dueInfo } from '../../lib/dueStatus'

const island = 'dashboard-island flex min-h-0 flex-col overflow-hidden'
const cardHeading = 'text-[18px] font-semibold tracking-[-0.015em] text-[color:var(--db-text)] sm:text-[22px]'
const emptyCopy = 'text-sm leading-6 text-[color:var(--db-text-muted)]'

function relativeDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.round((Date.now() - d.getTime()) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

/**
 * The launcher: greeting hero + the two primary CTAs, directly above the
 * Upcoming-meetings card in BOTH states. A returning user (history present) is
 * welcomed back; a first-run user just gets started, plus the sample offer.
 */
function Launcher({ isEmpty, onLoadSample, canLoadSample, onJoinMeeting, onPasteTranscript }) {
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
    </section>
  )
}

/**
 * Next meetings — Home's primary card (it replaced the open-action-items card,
 * Aug 2026 brief). Content is the shared UpcomingMeetings list when a calendar
 * is connected; otherwise an honest connect CTA / empty note, never a hidden
 * card: as the primary card it must exist even when it has nothing to say.
 */
function UpcomingCard({ panel, showConnectCalendar, onConnectCalendar }) {
  return (
    <section className={`dashboard-home-upcoming order-2 ${island}`}>
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5">
        <h2 className={cardHeading}>Next meetings</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {panel || (
          showConnectCalendar ? (
            <button
              type="button"
              onClick={onConnectCalendar}
              className="group flex w-full items-center gap-3 rounded-xl border border-cyan-400/20 bg-cyan-400/[0.06] px-3 py-3 text-left transition hover:bg-cyan-400/[0.11]"
            >
              <CalendarPlus className="h-4 w-4 shrink-0 text-cyan-300" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-[12.5px] leading-snug text-cyan-100/80">
                Connect Google or Outlook calendar to see your upcoming meetings and one-click join.
              </span>
              <span className="shrink-0 text-[12px] font-semibold text-cyan-200">Connect →</span>
            </button>
          ) : (
            <p className={`px-1 py-2 ${emptyCopy}`}>Upcoming calendar meetings appear here.</p>
          )
        )}
      </div>
    </section>
  )
}

/** One line, one door: the task count linking to the Trend hub. Never a list. */
function TaskStrip({ total, mineCount, overdueCount, onOpenTrend }) {
  if (!total) return null
  const parts = [`${total} open task${total === 1 ? '' : 's'}`]
  if (mineCount > 0) parts.push(`${mineCount} yours`)
  if (overdueCount > 0) parts.push(`${overdueCount} overdue`)
  return (
    <button
      type="button"
      onClick={onOpenTrend}
      className="dashboard-island group order-3 flex shrink-0 items-center gap-2.5 px-4 py-2.5 text-left transition hover:bg-[var(--db-fill)]"
    >
      <Zap className="h-4 w-4 shrink-0 text-cyan-300/80" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-[color:var(--db-text-muted)]">
        <span className="font-semibold text-[color:var(--db-text)]">{parts[0]}</span>
        {parts.length > 1 ? ` · ${parts.slice(1).join(' · ')}` : ''}
      </span>
      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[color:var(--db-text-faint)] transition group-hover:translate-x-0.5" aria-hidden="true" />
    </button>
  )
}

/** Right column: compact recent-meeting rows — colored score, title, one-line
 *  tldr, relative date. ~56px per row so ~10 meetings read at a glance. */
function MeetingsCard({ history, onOpen, selectedMeetingId, onOpenCalendar }) {
  const sorted = useMemo(
    () => [...history].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()),
    [history],
  )
  return (
    <section className={`dashboard-home-meetings ${island}`}>
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5">
        <h2 className={cardHeading}>Recent meetings</h2>
        {onOpenCalendar && history.length > 0 && (
          <button
            type="button"
            onClick={onOpenCalendar}
            className="shrink-0 text-[11.5px] text-[color:var(--db-text-faint)] transition hover:text-cyan-200"
          >
            Open calendar →
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {sorted.length ? (
          <div className="space-y-0.5">
            {sorted.map((entry) => {
              // Pitch / interview meetings score on their own rubric — show that
              // (e.g. "PITCH 72") instead of the misleading health % for them.
              const ca = hasContentAnalysis(entry.result) ? entry.result.content_analysis : null
              const score = ca ? Number(ca.headline_score) : overallHealth(entry.result?.health_score)
              const band = scoreBand(score)
              // null check BEFORE Number() — Number(null) is a finite 0.
              const hasScore = score !== null && score !== undefined && Number.isFinite(Number(score))
              const scoreLabel = ca ? typeMeta(ca.type).short : '%'
              const isSelected = entry.id === selectedMeetingId
              const tldr = entry.result?.tldr || entry.result?.summary || entry.result?.health_score?.verdict || ''
              return (
                <button
                  type="button"
                  key={entry.id}
                  onClick={() => onOpen?.(entry)}
                  className={`group flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors hover:bg-[var(--db-fill)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/30 ${
                    isSelected ? 'border-cyan-200/45 bg-[var(--db-fill)]' : 'border-transparent'
                  }`}
                >
                  <span
                    className="w-11 shrink-0 text-right font-bold leading-none tracking-tight tabular-nums"
                    style={{ color: band.color }}
                    title={hasScore ? `${ca ? typeMeta(ca.type).label : 'Health'} ${score}/100` : 'Not scored'}
                  >
                    <span className="text-[17px]">{hasScore ? score : '—'}</span>
                    {hasScore && <span className="text-[10.5px]">{scoreLabel === '%' ? '%' : ''}</span>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold leading-5 text-[color:var(--db-text)]">
                      {deriveDisplayTitle(entry)}
                    </span>
                    {tldr && (
                      <span className="block truncate text-[12px] leading-5 text-[color:var(--db-text-muted)]">{tldr}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-[11px] text-[color:var(--db-text-faint)]">{relativeDate(entry.date)}</span>
                </button>
              )
            })}
          </div>
        ) : (
          <p className={`px-2 py-2 ${emptyCopy}`}>Saved meetings will appear here.</p>
        )}
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
  openThreads = [],
  onOpenTrend,
  onOpenCalendar,
  showConnectCalendar = false,
  onConnectCalendar,
  selectedMeetingId = null,
  user = null,
}) {
  const safeHistory = history || []
  const isEmpty = safeHistory.length === 0

  // Home carries only the COUNTS — the list itself lives in the Trend Task hub.
  const { total, mineCount, overdueCount } = useMemo(() => {
    const all = collectOpenActions(safeHistory, user)
    return {
      total: all.length,
      mineCount: all.filter((r) => r.isMine).length,
      overdueCount: all.filter((r) => {
        const status = dueInfo(r.item, r.entry?.date).status
        return status === 'overdue' || status === 'soon'
      }).length,
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
        />
        <UpcomingCard
          panel={upcomingPanel}
          showConnectCalendar={showConnectCalendar}
          onConnectCalendar={onConnectCalendar}
        />
        <TaskStrip total={total} mineCount={mineCount} overdueCount={overdueCount} onOpenTrend={onOpenTrend} />
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
      <MeetingsCard
        history={safeHistory}
        onOpen={loadFromHistory}
        selectedMeetingId={selectedMeetingId}
        onOpenCalendar={onOpenCalendar}
      />
    </div>
  )
}

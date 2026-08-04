import { useMemo } from 'react'
import { ClipboardList, Sparkles, Video } from 'lucide-react'
import { deriveDisplayTitle, scoreBand } from '../../lib/insights'
import { overallHealth } from '../../lib/healthScore'
import { hasContentAnalysis, typeMeta } from '../../lib/meetingType'
import MeetingHero from './MeetingHero'
import NeedsAttention from './NeedsAttention'

const island = 'dashboard-island flex min-h-0 flex-col overflow-hidden'
const cardHeading = 'text-[18px] font-semibold tracking-[-0.015em] text-[color:var(--db-text)] sm:text-[22px]'
const emptyCopy = 'text-sm leading-6 text-[color:var(--db-text-muted)]'

const RECENT_LIMIT = 5

function relativeDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.round((Date.now() - d.getTime()) / 86400000)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days}d ago`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// The greeting row's action pair — identical size and shape, differing only in
// emphasis: Join is the filled brand primary, Paste the quiet twin.
const heroActionBase =
  'inline-flex h-10 items-center justify-center gap-2 rounded-full px-5 text-[13px] transition-all'
const heroActionPrimary =
  `${heroActionBase} bg-cyan-400 font-semibold text-[#04222a] shadow-sm hover:bg-cyan-300`
const heroActionSecondary =
  `${heroActionBase} border border-white/15 bg-white/[0.04] font-medium text-white/85 hover:bg-white/[0.09]`

/** "Welcome back, Abhinav." — the brand greeting, personalized (owner's call). */
function greetingFor(user) {
  const name = (user?.user_metadata?.full_name || user?.user_metadata?.name || '').trim().split(/\s+/)[0]
  return name ? `Welcome back, ${name}.` : 'Welcome back.'
}

/**
 * The hero row. New users (no history) get the full onboarding hero; returning
 * users get ONE greeting line with compact quick actions beside it, and the
 * state-aware MeetingHero beneath (owner's call: the greeting brand moment
 * stays, slimmed — see ADR 0002 amendment).
 */
function HeroRow({ isEmpty, user, onLoadSample, canLoadSample, onJoinMeeting, onPasteTranscript, hero }) {
  if (isEmpty) {
    return (
      <section className="dashboard-home-hero flex flex-col px-1 text-left">
        <h1 className="text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.08] text-[color:var(--db-text)]">
          Let&rsquo;s get started.
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
          {canLoadSample && (
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
  return (
    <section className="dashboard-home-hero flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-1">
        <h1 className="text-[24px] font-semibold tracking-[-0.02em] text-[color:var(--db-text)]">
          {greetingFor(user)}
        </h1>
        <div className="ml-auto flex shrink-0 items-center gap-2.5">
          {onJoinMeeting && (
            <button type="button" onClick={onJoinMeeting} className={heroActionPrimary}>
              <Video className="h-4 w-4" aria-hidden="true" />
              Join a meeting
            </button>
          )}
          {onPasteTranscript && (
            <button type="button" onClick={onPasteTranscript} className={heroActionSecondary}>
              <ClipboardList className="h-4 w-4" aria-hidden="true" />
              Paste transcript
            </button>
          )}
        </div>
      </div>
      {hero}
    </section>
  )
}

/** Right column (~35%): the last few meetings — compact rows, capped. The
 *  sidebar is the archive; "View all" opens the Calendar view. */
function MeetingsCard({ history, onOpen, selectedMeetingId, onOpenCalendar }) {
  const sorted = useMemo(
    () => [...history].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()),
    [history],
  )
  const shown = sorted.slice(0, RECENT_LIMIT)
  return (
    <section className={`dashboard-home-meetings ${island}`}>
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5">
        <h2 className={cardHeading}>Recent meetings</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {shown.length ? (
          <div className="space-y-0.5">
            {shown.map((entry) => {
              // Pitch / interview meetings score on their own rubric — show that
              // instead of the misleading health % for them.
              const ca = hasContentAnalysis(entry.result) ? entry.result.content_analysis : null
              const score = ca ? Number(ca.headline_score) : overallHealth(entry.result?.health_score)
              const band = scoreBand(score)
              // null check BEFORE Number() — Number(null) is a finite 0.
              const hasScore = score !== null && score !== undefined && Number.isFinite(Number(score))
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
                    {hasScore && !ca && <span className="text-[10.5px]">%</span>}
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
        {sorted.length > 0 && (
          <button
            type="button"
            onClick={onOpenCalendar}
            className="mt-1.5 w-full rounded-lg border border-[color:var(--db-border)] py-2 text-[12.5px] font-medium text-[color:var(--db-text-muted)] transition hover:border-cyan-400/30 hover:bg-cyan-400/[0.06] hover:text-cyan-100"
          >
            View all meetings →
          </button>
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
  heroEnabled = false,
  workspaces = [],
  botLive = false,
  liveAvailable = false,
  onOpenLive,
  onJoinEvent,
  onCantMakeIt,
  openThreads = [],
  onOpenTrend,
  onOpenCalendar,
  showConnectCalendar = false,
  onConnectCalendar,
  selectedMeetingId = null,
  onToggleAction,
  user = null,
}) {
  const safeHistory = history || []
  const isEmpty = safeHistory.length === 0

  return (
    <div className="dashboard-home-grid">
      <HeroRow
        isEmpty={isEmpty}
        user={user}
        onLoadSample={loadSample}
        canLoadSample={canLoadSample}
        onJoinMeeting={onJoinMeeting}
        onPasteTranscript={onPasteTranscript}
        hero={
          <MeetingHero
            enabled={heroEnabled}
            user={user}
            workspaces={workspaces}
            botLive={botLive}
            liveAvailable={liveAvailable}
            onOpenLive={onOpenLive}
            onJoinEvent={onJoinEvent}
            onCantMakeIt={onCantMakeIt}
            onOpenMeeting={loadFromHistory}
            onOpenCalendar={onOpenCalendar}
            showConnectCalendar={showConnectCalendar}
            onConnectCalendar={onConnectCalendar}
          />
        }
      />
      {!isEmpty && (
        <NeedsAttention
          history={safeHistory}
          user={user}
          openThreads={openThreads}
          onToggle={onToggleAction}
          onOpenMeeting={loadFromHistory}
          onOpenTrend={onOpenTrend}
        />
      )}
      <MeetingsCard
        history={safeHistory}
        onOpen={loadFromHistory}
        selectedMeetingId={selectedMeetingId}
        onOpenCalendar={onOpenCalendar}
      />
    </div>
  )
}

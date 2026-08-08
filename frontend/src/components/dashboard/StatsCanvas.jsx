import { useMemo } from 'react'
import { ClipboardList, Mic, Sparkles, Upload, Video } from 'lucide-react'
import { deriveDisplayTitle, scoreBand } from '../../lib/insights'
import { overallHealth } from '../../lib/healthScore'
import { hasContentAnalysis, typeMeta } from '../../lib/meetingType'
import MeetingHero from './MeetingHero'
import NeedsAttention from './NeedsAttention'
import { subtleText } from './dashboardStyles'

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

// THE hero action pair — one definition for both the onboarding hero and the
// returning-user greeting row, so the buttons can never drift apart again:
// full-size pills, Join filled cyan, Paste the quiet outlined twin.
const heroActionBase =
  'inline-flex h-11 items-center justify-center gap-2 rounded-full px-6 text-sm transition-all'
const heroActionPrimary =
  `${heroActionBase} bg-cyan-400 font-semibold text-[#04222a] shadow-sm hover:bg-cyan-300`
const heroActionSecondary =
  `${heroActionBase} border border-white/15 bg-white/[0.04] font-medium text-white/85 hover:bg-white/[0.08]`
const heroActionGhost =
  `${heroActionBase} border border-white/10 bg-transparent font-medium text-white/60 hover:bg-white/[0.05] hover:text-white/80`

/** "Welcome back, Abhinav." — the brand greeting, personalized (owner's call). */
function greetingFor(user) {
  const name = (user?.user_metadata?.full_name || user?.user_metadata?.name || '').trim().split(/\s+/)[0]
  return name ? `Welcome back, ${name}.` : 'Welcome back.'
}

/**
 * The uncarded header block — greeting, one-line product promise, and the
 * full capture row (Join / Paste / Upload / Record / Sample). Content on
 * canvas, not a card: the first card is MeetingHero, rendered as this
 * component's sibling by the caller. New users read "Let's get started."
 * (+ See a sample); returning users read "Welcome back, Abhinav."
 */
function HeroRow({
  isEmpty,
  user,
  onLoadSample,
  canLoadSample,
  onJoinMeeting,
  onPasteTranscript,
  onUploadRecording,
  onRecordAudio,
  micSupported,
}) {
  return (
    <section className="flex flex-col px-1 text-left">
      <h1 className="text-[clamp(2rem,3.6vw,3rem)] font-semibold leading-[1.08] text-[color:var(--db-text)]">
        {isEmpty ? <>Let&rsquo;s get started.</> : greetingFor(user)}
      </h1>
      <p className={`mt-3 max-w-md ${subtleText}`}>
        Drop in a meeting — Prism turns it into decisions, actions, and follow-ups.
      </p>
      <div className="mt-5 flex flex-col gap-2.5 sm:flex-row sm:flex-wrap">
        {onJoinMeeting && (
          <button type="button" onClick={onJoinMeeting} className={heroActionPrimary}>
            <Video className="h-4 w-4" aria-hidden="true" />
            Join a meeting
          </button>
        )}
        {onPasteTranscript && (
          <button type="button" onClick={onPasteTranscript} className={heroActionSecondary}>
            <ClipboardList className="h-4 w-4" aria-hidden="true" />
            Paste a transcript
          </button>
        )}
        {onUploadRecording && (
          <button type="button" onClick={onUploadRecording} className={heroActionSecondary}>
            <Upload className="h-4 w-4" aria-hidden="true" />
            Upload a recording
          </button>
        )}
        {micSupported && onRecordAudio && (
          <button type="button" onClick={onRecordAudio} className={heroActionSecondary}>
            <Mic className="h-4 w-4" aria-hidden="true" />
            Record audio
          </button>
        )}
        {isEmpty && canLoadSample && (
          <button type="button" onClick={onLoadSample} className={heroActionGhost}>
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            See a sample
          </button>
        )}
      </div>
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
    <section className={island}>
      <div className="flex shrink-0 items-baseline justify-between gap-3 border-b border-[color:var(--db-border)] px-4 py-3.5">
        <h2 className={cardHeading}>Recent meetings</h2>
      </div>
      {/* Content is already row-capped (RECENT_LIMIT); max-h is a defensive cap
          now that the grid no longer gives this card a definite height to
          flex-fill — without it, long-wrapped titles could push the card past
          the viewport instead of scrolling internally. */}
      <div className="max-h-[50vh] overflow-y-auto p-2">
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
  onUploadRecording,
  onRecordAudio,
  micSupported = false,
  heroEnabled = false,
  workspaces = [],
  botLive = false,
  liveAvailable = false,
  onOpenLive,
  onJoinEvent,
  onCantMakeIt,
  openThreads = [],
  onOpenTrend,
  onOpenActions,
  onOpenCalendar,
  showConnectCalendar = false,
  onConnectCalendar,
  selectedMeetingId = null,
  onToggleAction,
  user = null,
  assistant = null,
}) {
  const safeHistory = history || []
  const isEmpty = safeHistory.length === 0

  return (
    <div className="dashboard-home-grid">
      <div className="dashboard-home-ops">
        <HeroRow
          isEmpty={isEmpty}
          user={user}
          onLoadSample={loadSample}
          canLoadSample={canLoadSample}
          onJoinMeeting={onJoinMeeting}
          onPasteTranscript={onPasteTranscript}
          onUploadRecording={onUploadRecording}
          onRecordAudio={onRecordAudio}
          micSupported={micSupported}
        />
        {!isEmpty && (
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
        )}
        {!isEmpty && (
          <NeedsAttention
            history={safeHistory}
            user={user}
            openThreads={openThreads}
            onToggle={onToggleAction}
            onOpenMeeting={loadFromHistory}
            onOpenTrend={onOpenTrend}
            onOpenActions={onOpenActions}
          />
        )}
        <MeetingsCard
          history={safeHistory}
          onOpen={loadFromHistory}
          selectedMeetingId={selectedMeetingId}
          onOpenCalendar={onOpenCalendar}
        />
      </div>
      {assistant && <div className="dashboard-home-assistant">{assistant}</div>}
    </div>
  )
}

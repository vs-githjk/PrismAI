import { Check, Clock, UserRound } from 'lucide-react'
import { deriveDisplayTitle, scoreBand } from '../../lib/insights'

const ACTION_WINDOW_MS = 14 * 24 * 60 * 60 * 1000 // open action items: last 2 weeks

const island = 'dashboard-island flex min-h-0 flex-col overflow-hidden'
const cardHeading = 'text-[22px] font-semibold tracking-[-0.015em] text-white'
const emptyCopy = 'text-sm leading-6 text-white/55'

/** Top-left quadrant: static greeting, or a get-started prompt when history is empty. */
function Greeting({ isEmpty, onLoadSample, canLoadSample }) {
  if (isEmpty) {
    return (
      <section className="dashboard-home-greeting flex flex-col justify-center px-1 text-left">
        <h1 className="text-[clamp(2.4rem,4.6vw,4rem)] font-semibold leading-[0.98] text-white">
          Let&rsquo;s get
          <br />
          started.
        </h1>
        <p className="mt-4 max-w-md text-base leading-7 text-white/58">
          Start a new meeting or upload a transcript with the&nbsp;+ in the sidebar.
        </p>
        {canLoadSample && (
          <button
            type="button"
            onClick={onLoadSample}
            className="mt-6 inline-flex h-11 w-fit items-center justify-center gap-2 rounded-full border border-[#2f2f2f] bg-[#18181b] px-6 text-sm font-medium text-[#f2f2f2] shadow-xs transition-all hover:bg-[#27272a]"
          >
            Load sample dashboard
          </button>
        )}
      </section>
    )
  }

  return (
    <section className="dashboard-home-greeting flex flex-col justify-center px-1 text-left">
      <h1 className="text-[clamp(3.5rem,6.6vw,6.25rem)] font-bold leading-[0.9] tracking-[-0.02em] text-white">
        Welcome
        <br />
        Back.
      </h1>
      <p className="mt-5 max-w-md text-base leading-7 text-white/58">
        Pick up where you left off. Your open items and recent meetings are below.
      </p>
    </section>
  )
}

/** Bottom-left quadrant: open action items from the last 2 weeks, click-through to source meeting. */
function ActionItemsCard({ actions, onOpen, onToggle }) {
  return (
    <section className={`dashboard-home-actions ${island}`}>
      <div className="shrink-0 border-b border-white/[0.08] px-4 py-3.5">
        <h2 className={cardHeading}>Open action items</h2>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {actions.length ? (
          <div className="space-y-2">
            {actions.map(({ item, entry, index }) => (
              <div
                key={`${entry.id}-${item.task}-${index}`}
                className="group flex w-full items-start gap-3 rounded-xl border border-white/[0.08] bg-gradient-to-br from-white/[0.06] to-white/[0.015] p-3.5 transition-all duration-200 hover:-translate-y-0.5 hover:from-white/[0.09] hover:to-white/[0.03]"
              >
                <button
                  type="button"
                  onClick={() => onToggle?.(entry, index)}
                  aria-pressed={!!item.completed}
                  aria-label={item.completed ? 'Mark as not done' : 'Mark as done'}
                  className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-white/30 text-transparent transition-all duration-200 hover:border-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300/40"
                >
                  <Check className="h-3 w-3" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => onOpen?.(entry)}
                  className="min-w-0 flex-1 text-left focus-visible:outline-none"
                >
                  <p className="line-clamp-2 text-[15px] font-medium leading-snug text-white">{item.task}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="inline-flex items-center gap-1 text-[11.5px] text-white/50">
                      <UserRound className="h-3 w-3 shrink-0 text-white/35" aria-hidden="true" />
                      <span className="truncate">{item.owner || 'Unowned'}</span>
                    </span>
                    {item.due && (
                      <span className="inline-flex items-center gap-1 text-[11.5px] text-white/50">
                        <Clock className="h-3 w-3 shrink-0 text-white/35" aria-hidden="true" />
                        <span className="truncate">{item.due}</span>
                      </span>
                    )}
                    <span className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-md border border-cyan-200/15 bg-cyan-300/[0.06] px-2 py-0.5 text-[10.5px] font-medium text-cyan-200/70">
                      <span className="max-w-[140px] truncate">{deriveDisplayTitle(entry)}</span>
                    </span>
                  </div>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className={`px-1 py-2 ${emptyCopy}`}>No open action items in the last two weeks.</p>
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
              {history.map((entry) => {
                const score = entry.result?.health_score?.score
                const band = scoreBand(score)
                const hasScore = Number.isFinite(Number(score))
                const isSelected = entry.id === selectedMeetingId
                const summary =
                  entry.result?.summary || entry.result?.health_score?.verdict || 'No summary recorded.'
                return (
                  <button
                    type="button"
                    key={entry.id}
                    onClick={() => onOpen?.(entry)}
                    className={`group flex w-full items-stretch gap-4 rounded-2xl border bg-gradient-to-br from-white/[0.06] to-white/[0.015] p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:from-white/[0.09] hover:to-white/[0.03] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan-300/16 ${isSelected ? 'border-cyan-200/45' : 'border-white/[0.08]'}`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-1 text-[19px] font-semibold leading-tight tracking-[-0.01em] text-white">
                        {deriveDisplayTitle(entry)}
                      </p>
                      <p className="mt-1.5 line-clamp-2 text-[13.5px] leading-6 text-white/55">{summary}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end justify-center pl-1">
                      <span className="font-bold leading-none tracking-tight" style={{ color: band.color }}>
                        <span className="text-[28px]">{hasScore ? score : '—'}</span>
                        {hasScore && <span className="text-[15px]">%</span>}
                      </span>
                      <span className="mt-1.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-white/35">Health</span>
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
  selectedMeetingId = null,
  onToggleAction,
}) {
  const safeHistory = history || []
  const now = Date.now()

  // Open action items from the last 2 weeks, aggregated client-side, newest-first.
  const actions = safeHistory
    .filter((entry) => {
      const t = new Date(entry.date).getTime()
      return Number.isFinite(t) && now - t <= ACTION_WINDOW_MS
    })
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
    .flatMap((entry) =>
      (entry.result?.action_items || [])
        .map((item, index) => ({ item, entry, index }))
        .filter(({ item }) => !item.completed),
    )

  return (
    <div className="dashboard-home-grid">
      <Greeting isEmpty={safeHistory.length === 0} onLoadSample={loadSample} canLoadSample={canLoadSample} />
      <ActionItemsCard actions={actions} onOpen={loadFromHistory} onToggle={onToggleAction} />
      <MeetingsCard history={safeHistory} onOpen={loadFromHistory} selectedMeetingId={selectedMeetingId} />
    </div>
  )
}

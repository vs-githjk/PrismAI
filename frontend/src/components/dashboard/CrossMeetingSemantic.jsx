import { Check, ExternalLink } from 'lucide-react'
import { formatMeetingDate } from '../../lib/insights'
import { Button } from '../ui/button'
import { cardGlowStyle, cardTitle, glassCard, subtleText } from './dashboardStyles'

// B2 — the semantic cross-meeting cards (narrative + topics + open threads +
// decision evolution). Data comes from GET /insights/semantic (one cached Haiku
// pass); meeting_ids are resolved to meeting objects via `resolveMeeting` for
// click-through. These replace the lexical ThemeChips + UnresolvedDecisionsCard.

const TOPIC_STATUS = {
  active: { label: 'Active', cls: 'border-cyan-200/24 bg-cyan-300/10 text-cyan-100' },
  stalled: { label: 'Stalled', cls: 'border-amber-200/24 bg-amber-300/10 text-amber-100' },
  resolved: { label: 'Resolved', cls: 'border-emerald-200/24 bg-emerald-300/10 text-emerald-100' },
}

function MeetingChips({ ids = [], resolveMeeting, onSelect, max = 4 }) {
  const meetings = ids.map(resolveMeeting).filter(Boolean).slice(0, max)
  if (!meetings.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {meetings.map((meeting) => (
        <button
          type="button"
          key={meeting.id}
          onClick={() => onSelect?.(meeting)}
          className="rounded border border-white/[0.08] bg-white/[0.04] px-2 py-0.5 text-[10.5px] text-white/56 transition hover:border-cyan-200/24 hover:text-cyan-100"
        >
          {meeting.title || formatMeetingDate(meeting.date)}
        </button>
      ))}
    </div>
  )
}

function SkeletonRows({ rows = 3 }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="rounded-lg border border-white/[0.06] bg-white/[0.03] px-3 py-3">
          <div className="h-3 w-2/3 animate-pulse rounded bg-white/[0.08]" />
          <div className="mt-2 h-2.5 w-1/2 animate-pulse rounded bg-white/[0.05]" />
        </div>
      ))}
    </div>
  )
}

export function NarrativeBar({ narrative, loading }) {
  if (loading) {
    return (
      <section className={`${glassCard} p-4`} style={cardGlowStyle}>
        <div className="h-3 w-11/12 animate-pulse rounded bg-white/[0.08]" />
        <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-white/[0.05]" />
      </section>
    )
  }
  if (!narrative) return null
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Across your meetings</p>
      <p className="mt-1.5 text-[15px] leading-6 text-white/86">{narrative}</p>
    </section>
  )
}

export function OpenThreadsCard({ threads = [], loading, resolveMeeting, onSelect, onAct, actLabel = 'Act on this', isActed }) {
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Open threads</p>
        <h2 className={cardTitle}>Raised but never closed</h2>
      </div>
      {loading ? (
        <SkeletonRows rows={3} />
      ) : threads.length ? (
        <div className="space-y-2">
          {threads.map((thread, index) => (
            <div key={`${thread.thread}-${index}`} className="rounded-lg border border-amber-200/[0.14] bg-amber-300/[0.05] p-3">
              <p className="text-sm font-semibold leading-snug text-white">{thread.thread}</p>
              {thread.why_open && <p className={`mt-0.5 ${subtleText}`}>{thread.why_open}</p>}
              {thread.suggested_next_step && (
                <p className="mt-1.5 text-[12px] leading-4 text-cyan-100/80">
                  <span className="font-semibold text-cyan-200/90">Next:</span> {thread.suggested_next_step}
                </p>
              )}
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <MeetingChips ids={thread.meeting_ids} resolveMeeting={resolveMeeting} onSelect={onSelect} />
                {onAct && (() => {
                  const acted = isActed?.(thread)
                  if (acted) {
                    return (
                      <span className="inline-flex shrink-0 items-center gap-1.5 text-[11.5px] font-medium text-emerald-300">
                        <Check className="h-3.5 w-3.5" aria-hidden="true" /> Filed
                        {acted.url && (
                          <a href={acted.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-cyan-300 hover:underline">
                            Open <ExternalLink className="h-3 w-3" aria-hidden="true" />
                          </a>
                        )}
                      </span>
                    )
                  }
                  return (
                    <Button variant="accent" size="inline" onClick={() => onAct(thread)} className="shrink-0">
                      {actLabel}
                    </Button>
                  )
                })()}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className={subtleText}>No unresolved threads — subjects raised across meetings are landing in decisions.</p>
      )}
    </section>
  )
}

export function TopicsCard({ topics = [], loading, resolveMeeting, onSelect }) {
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Topics</p>
        <h2 className={cardTitle}>What keeps coming up</h2>
      </div>
      {loading ? (
        <SkeletonRows rows={3} />
      ) : topics.length ? (
        <div className="space-y-2">
          {topics.map((topic, index) => {
            const status = TOPIC_STATUS[topic.status] || TOPIC_STATUS.active
            return (
              <div key={`${topic.topic}-${index}`} className="rounded-lg border border-white/[0.08] bg-black/20 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold leading-snug text-white">{topic.topic}</p>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${status.cls}`}>{status.label}</span>
                </div>
                {topic.gist && <p className={`mt-0.5 ${subtleText}`}>{topic.gist}</p>}
                <MeetingChips ids={topic.meeting_ids} resolveMeeting={resolveMeeting} onSelect={onSelect} />
              </div>
            )
          })}
        </div>
      ) : (
        <p className={subtleText}>Recurring topics appear once themes span a few meetings.</p>
      )}
    </section>
  )
}

export function DecisionEvolutionCard({ items = [], loading, resolveMeeting, onSelect }) {
  return (
    <section className={`${glassCard} p-4`} style={cardGlowStyle}>
      <div className="mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-200/80">Decision evolution</p>
        <h2 className={cardTitle}>How decisions moved</h2>
      </div>
      {loading ? (
        <SkeletonRows rows={2} />
      ) : items.length ? (
        <div className="space-y-3">
          {items.map((item, index) => (
            <div key={`${item.topic}-${index}`} className="rounded-lg border border-violet-200/[0.14] bg-violet-300/[0.05] p-3">
              <p className="text-sm font-semibold text-white">{item.topic}</p>
              <div className="mt-2 space-y-1.5">
                {item.timeline.map((step, stepIndex) => {
                  const meeting = resolveMeeting(step.meeting_id)
                  return (
                    <div key={stepIndex} className="flex gap-2">
                      <div className="mt-1 flex flex-col items-center">
                        <span className="h-1.5 w-1.5 rounded-full bg-violet-300" />
                        {stepIndex < item.timeline.length - 1 && <span className="mt-0.5 h-full w-px flex-1 bg-violet-200/20" />}
                      </div>
                      <div className="pb-1">
                        <p className="text-[13px] leading-5 text-white/82">{step.what_changed}</p>
                        {meeting && (
                          <button
                            type="button"
                            onClick={() => onSelect?.(meeting)}
                            className="text-[10.5px] text-white/44 transition hover:text-cyan-100"
                          >
                            {meeting.title || formatMeetingDate(meeting.date)}
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className={subtleText}>No decision has changed across meetings yet.</p>
      )}
    </section>
  )
}

export function SemanticLockedBanner({ minMeetings = 3 }) {
  return (
    <section className={`${glassCard} p-5 text-center`} style={cardGlowStyle}>
      <p className="text-sm font-semibold text-white/88">Cross-meeting insights unlock after {minMeetings} meetings</p>
      <p className={`mx-auto mt-1 max-w-md ${subtleText}`}>
        Once you have a few analyzed meetings, Prism synthesizes the throughline — recurring topics, threads left open, and how decisions evolved.
      </p>
    </section>
  )
}

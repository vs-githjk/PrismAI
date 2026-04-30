import { Calendar, CheckCircle2, FileText, Mail } from 'lucide-react'
import { formatMeetingDate, scoreBand } from '../../lib/insights'
import { cardGlowStyle, cardTitle, eyebrow, glassCard, subtleText } from './dashboardStyles'

export default function MeetingView({ result, meeting }) {
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
  const openItems = (result.action_items || []).filter((item) => !item.completed)
  const decisions = result.decisions || []
  const sentiment = result.sentiment
  const emailDraft = result.email_draft
  const calendarEvent = result.calendar_event

  return (
    <div className="space-y-3">
      {meeting && (
        <div className="px-0.5">
          <p className={eyebrow}>Current meeting</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-white">{meeting.title || 'Meeting'}</h1>
          {meeting.date && <p className={`mt-0.5 ${subtleText}`}>{formatMeetingDate(meeting.date)}</p>}
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_minmax(0,2fr)]">
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <p className={`${eyebrow} mb-3`}>Health score</p>
          {healthScore?.score !== undefined ? (
            <>
              <p className="text-5xl font-semibold leading-none" style={{ color: band.color }}>
                {healthScore.score}
                <span className="ml-1 text-xl text-white/36">/100</span>
              </p>
              <span
                className="mt-2 inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-semibold"
                style={{ borderColor: `${band.color}44`, color: band.color, background: `${band.color}18` }}
              >
                {band.label}
              </span>
              {healthScore.verdict && (
                <blockquote
                  className="mt-3 border-l-2 pl-3 text-sm leading-5 text-white/62"
                  style={{ borderColor: `${band.color}88` }}
                >
                  {healthScore.verdict}
                </blockquote>
              )}
              {healthScore.badges?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {healthScore.badges.map((badge) => (
                    <span key={badge} className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-white/50">{badge}</span>
                  ))}
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
            <p className="text-sm leading-6 text-white/78">{result.summary}</p>
          ) : (
            <p className={subtleText}>No summary generated.</p>
          )}
        </section>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className={eyebrow}>Action items</p>
              <h2 className={cardTitle}>{openItems.length} open task{openItems.length !== 1 ? 's' : ''}</h2>
            </div>
            <CheckCircle2 className="h-5 w-5 shrink-0 text-cyan-200/70" aria-hidden="true" />
          </div>
          {openItems.length ? (
            <div className="overflow-hidden rounded-lg border border-white/[0.08]">
              {openItems.map((item, i) => (
                <div key={`${item.task}-${i}`} className="border-b border-white/[0.07] px-3 py-2.5 last:border-b-0">
                  <p className="text-sm font-medium text-white">{item.task}</p>
                  <p className={subtleText}>{item.owner || 'Unowned'}{item.due ? ` · ${item.due}` : ''}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className={subtleText}>No open action items in this meeting.</p>
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

      {sentiment?.overall && (
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

      {emailDraft && (
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <div className="mb-3 flex items-center gap-2">
            <Mail className="h-4 w-4 text-cyan-200/70" aria-hidden="true" />
            <p className={eyebrow}>Email draft</p>
          </div>
          <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-white/68">{emailDraft}</pre>
        </section>
      )}

      {calendarEvent?.title && (
        <section className={`${glassCard} p-4`} style={cardGlowStyle}>
          <div className="mb-3 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-cyan-200/70" aria-hidden="true" />
            <p className={eyebrow}>Calendar suggestion</p>
          </div>
          <p className="text-sm font-semibold text-white">{calendarEvent.title}</p>
          {calendarEvent.description && <p className={`mt-1 ${subtleText}`}>{calendarEvent.description}</p>}
        </section>
      )}
    </div>
  )
}

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { apiFetch } from '../../lib/api'
import { Mail, Calendar, Ticket, MessageSquare, Check, Loader2, X, Sparkles, ExternalLink } from 'lucide-react'

// Each suggested action maps to an action_type the agent chose; the concrete tool is
// resolved from what the user actually has connected (task→Jira/Linear, chat→Slack/Teams).
const TYPE_META = {
  email:    { icon: Mail,          label: 'Send email',      verb: 'Send',  accent: '#22d3ee' },
  calendar: { icon: Calendar,      label: 'Add to calendar', verb: 'Create', accent: '#67e8f9' },
  task:     { icon: Ticket,        label: 'File ticket',     verb: 'File',  accent: '#a78bfa' },
  chat:     { icon: MessageSquare, label: 'Post message',    verb: 'Post',  accent: '#34d399' },
}

// Which integration a type needs, and the label shown when it isn't connected.
function resolveTool(type, conn) {
  if (type === 'email') return conn.email ? { tool: 'gmail_send' } : { missing: 'Gmail' }
  if (type === 'calendar') return conn.calendar ? { tool: 'calendar_create_event' } : { missing: 'Google Calendar' }
  if (type === 'task') {
    if (conn.jira) return { tool: 'jira_create_issue' }
    if (conn.linear) return { tool: 'linear_create_issue' }
    return { missing: 'Jira or Linear' }
  }
  if (type === 'chat') {
    if (conn.slack) return { tool: 'slack_post_message' }
    if (conn.teams) return { tool: 'teams_webhook' }
    return { missing: 'Slack or Teams' }
  }
  return { missing: 'an integration' }
}

function plusMinutes(dateStr, timeStr, mins) {
  const d = new Date(`${dateStr}T${timeStr}:00`)
  d.setMinutes(d.getMinutes() + mins)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

function defaultDate() {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function SuggestedActions({ actions = [], connections = {}, suggestedEmails = [], meetingId = null, teamsWebhook = '', readOnly = false }) {
  const [active, setActive] = useState(null)   // the action being reviewed
  const list = (actions || []).filter((a) => a && TYPE_META[a.action_type])
  if (!list.length) return null

  return (
    <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="h-[18px] w-[18px] text-cyan-300" aria-hidden="true" />
        <h3 className="text-[15px] font-semibold text-white/90">Suggested actions</h3>
        <span className="text-[12px] text-white/40">— from your action items, ready to send</span>
      </div>
      <ul className="flex flex-col gap-2">
        {list.map((a, i) => {
          const meta = TYPE_META[a.action_type]
          const Icon = meta.icon
          return (
            <li key={i} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                style={{ background: `${meta.accent}1a`, color: meta.accent }}>
                <Icon className="h-[17px] w-[17px]" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium text-white/85">{a.title || a.task}</p>
                <p className="truncate text-[12px] text-white/45">{a.task}</p>
              </div>
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => setActive(a)}
                  className="shrink-0 rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-[12.5px] font-medium text-cyan-200 transition hover:border-cyan-400/55 hover:bg-cyan-400/15"
                >
                  Review &amp; {meta.verb.toLowerCase()}
                </button>
              )}
            </li>
          )
        })}
      </ul>
      {active && createPortal(
        <ActionModal
          action={active}
          connections={connections}
          suggestedEmails={suggestedEmails}
          meetingId={meetingId}
          teamsWebhook={teamsWebhook}
          onClose={() => setActive(null)}
        />, document.body)}
    </div>
  )
}

function ActionModal({ action, connections, suggestedEmails, meetingId, teamsWebhook, onClose }) {
  const meta = TYPE_META[action.action_type]
  const resolved = resolveTool(action.action_type, connections)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)   // { url } on success
  const [error, setError] = useState('')

  // Editable fields, seeded from the agent's draft.
  const [title, setTitle] = useState(action.title || action.task || '')
  const [body, setBody] = useState(action.body || '')
  const [recipients, setRecipients] = useState([])   // emails (email/calendar)
  const [channel, setChannel] = useState('#general')
  const [date, setDate] = useState(defaultDate())
  const [time, setTime] = useState('10:00')

  const availableEmails = (suggestedEmails || []).filter((e) => e && !recipients.includes(e))

  async function submit() {
    setBusy(true); setError('')
    try {
      // Teams uses the recap webhook route, not the unified tool endpoint.
      if (resolved.tool === 'teams_webhook') {
        const res = await apiFetch('/export/teams', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ webhook_url: teamsWebhook, title: title || 'Action', result: { summary: body } }),
        })
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Teams post failed')
        setDone({})
        return
      }

      let args
      if (resolved.tool === 'gmail_send') {
        if (!recipients.length) { setError('Add at least one recipient.'); setBusy(false); return }
        args = { to: recipients, subject: title, body }
      } else if (resolved.tool === 'calendar_create_event') {
        args = {
          title,
          start: `${date}T${time}:00`,
          end: plusMinutes(date, time, 30),
          attendees: recipients,
          description: body,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }
      } else if (resolved.tool === 'slack_post_message') {
        args = { channel, text: body || title }
      } else {
        // jira_create_issue / linear_create_issue
        args = { title, description: body }
      }

      const res = await apiFetch('/actions/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: resolved.tool, args, meeting_id: meetingId, task: action.task }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Action failed')
      setDone({ url: data.url || data.issue_url || null })
    } catch (e) {
      setError(e.message || 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const isEmail = resolved.tool === 'gmail_send'
  const isCalendar = resolved.tool === 'calendar_create_event'
  const isSlack = resolved.tool === 'slack_post_message'
  const wantsRecipients = isEmail || isCalendar
  const Icon = meta.icon

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0c1118] p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{ background: `${meta.accent}1a`, color: meta.accent }}>
            <Icon className="h-[17px] w-[17px]" aria-hidden="true" />
          </span>
          <h3 className="flex-1 text-[15px] font-semibold text-white/90">{meta.label}</h3>
          <button type="button" onClick={onClose} className="text-white/40 hover:text-white/80">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {resolved.missing ? (
          <div className="rounded-xl border border-amber-400/25 bg-amber-400/10 px-4 py-3 text-[13px] text-amber-200">
            Connect <span className="font-semibold">{resolved.missing}</span> in Settings → Integrations to enable this action.
          </div>
        ) : done ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300">
              <Check className="h-6 w-6" aria-hidden="true" />
            </span>
            <p className="text-[14px] font-medium text-white/85">Done — {meta.verb.toLowerCase()}ed.</p>
            {done.url && (
              <a href={done.url} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-[13px] text-cyan-300 hover:underline">
                Open <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            )}
            <button type="button" onClick={onClose}
              className="mt-1 rounded-lg border border-white/10 bg-white/5 px-4 py-1.5 text-[13px] text-white/80 hover:bg-white/10">
              Close
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <Field label={isEmail ? 'Subject' : isCalendar ? 'Event title' : isSlack ? 'Label' : 'Title'}>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13.5px] text-white/90 outline-none focus:border-cyan-400/45" />
            </Field>

            {wantsRecipients && (
              <Field label={isEmail ? 'To' : 'Attendees'}>
                <div className="flex flex-wrap items-center gap-1.5">
                  {recipients.map((e) => (
                    <span key={e} className="inline-flex items-center gap-1 rounded-full bg-cyan-400/12 px-2.5 py-1 text-[12px] text-cyan-200">
                      {e}
                      <button type="button" onClick={() => setRecipients(recipients.filter((x) => x !== e))}
                        className="text-cyan-200/60 hover:text-cyan-100">×</button>
                    </span>
                  ))}
                </div>
                {availableEmails.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {availableEmails.slice(0, 8).map((e) => (
                      <button key={e} type="button" onClick={() => setRecipients([...recipients, e])}
                        className="rounded-full border border-white/10 px-2.5 py-1 text-[12px] text-white/55 hover:border-cyan-400/40 hover:text-cyan-200">
                        + {e}
                      </button>
                    ))}
                  </div>
                )}
                <input type="email" placeholder="Add an email + Enter"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target.value.trim()) {
                      e.preventDefault()
                      const v = e.target.value.trim()
                      if (!recipients.includes(v)) setRecipients([...recipients, v])
                      e.target.value = ''
                    }
                  }}
                  className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13px] text-white/90 outline-none focus:border-cyan-400/45" />
              </Field>
            )}

            {isCalendar && (
              <div className="flex gap-3">
                <Field label="Date" className="flex-1">
                  <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13px] text-white/90 outline-none focus:border-cyan-400/45" />
                </Field>
                <Field label="Time" className="w-32">
                  <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13px] text-white/90 outline-none focus:border-cyan-400/45" />
                </Field>
              </div>
            )}

            {isSlack && (
              <Field label="Channel">
                <input value={channel} onChange={(e) => setChannel(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13px] text-white/90 outline-none focus:border-cyan-400/45" />
              </Field>
            )}

            <Field label={isEmail ? 'Body' : isCalendar ? 'Description' : 'Message'}>
              <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={isEmail ? 6 : 4}
                className="w-full resize-y rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-[13px] leading-relaxed text-white/90 outline-none focus:border-cyan-400/45" />
            </Field>

            {error && <p className="text-[12.5px] text-rose-300">{error}</p>}

            <div className="mt-1 flex items-center justify-end gap-2">
              <button type="button" onClick={onClose}
                className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-[13px] text-white/75 hover:bg-white/10">
                Cancel
              </button>
              <button type="button" onClick={submit} disabled={busy}
                className="inline-flex items-center gap-2 rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-4 py-2 text-[13px] font-medium text-cyan-100 transition hover:bg-cyan-400/25 disabled:opacity-50">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Check className="h-4 w-4" aria-hidden="true" />}
                {meta.verb}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-[11.5px] font-medium uppercase tracking-wide text-white/40">{label}</span>
      {children}
    </label>
  )
}

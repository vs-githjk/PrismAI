import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Bell, CheckCircle2, Clock, AlertTriangle, Users, CalendarClock, Check, BellRing,
} from 'lucide-react'
import { apiFetch } from '../../lib/api'
import { pushSupported, getPushState, subscribePush } from '../../lib/push'

// Persistent notification center (#9). Polls GET /notifications, shows an unread
// badge, and a dropdown list with click-through to the source meeting. Distinct
// from the transient statusNotify toast — this survives refresh.
//
// Two kinds of item: stored (server tracks read) and synthesized action_due
// (client tracks dismissal in localStorage, since they're recomputed each GET).

const DISMISS_KEY = 'prism_notif_dismissed'   // synthesized ids the user cleared
const POLL_MS = 60000

const META = {
  meeting_ready:      { Icon: CheckCircle2,  color: 'text-cyan-300',   ring: 'bg-cyan-400/12' },
  action_due:         { Icon: Clock,         color: 'text-amber-300',  ring: 'bg-amber-400/12' },
  bot_issue:          { Icon: AlertTriangle, color: 'text-rose-300',   ring: 'bg-rose-400/12' },
  workspace_activity: { Icon: Users,         color: 'text-sky-300',    ring: 'bg-sky-400/12' },
  meeting_soon:       { Icon: CalendarClock, color: 'text-violet-300', ring: 'bg-violet-400/12' },
}

function loadDismissed() {
  try { return new Set(JSON.parse(localStorage.getItem(DISMISS_KEY) || '[]')) }
  catch { return new Set() }
}
function saveDismissed(set) {
  try { localStorage.setItem(DISMISS_KEY, JSON.stringify([...set].slice(-200))) } catch { /* ignore */ }
}

function timeAgo(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  if (Number.isNaN(s)) return ''
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function NotificationBell({ onOpenMeeting, signedOut = false }) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState([])
  const [dismissed, setDismissed] = useState(loadDismissed)
  const [pushState, setPushState] = useState('unsupported') // unsupported|denied|subscribed|default
  const [pushBusy, setPushBusy] = useState(false)
  const wrapRef = useRef(null)

  const load = useCallback(async () => {
    if (signedOut) return
    try {
      const r = await apiFetch('/notifications')
      if (!r.ok) return
      const data = await r.json()
      setItems(data.notifications || [])
    } catch { /* offline — keep last */ }
  }, [signedOut])

  // Poll on mount, every 60s, and when the tab regains focus.
  useEffect(() => {
    if (signedOut) return
    load()
    const t = setInterval(load, POLL_MS)
    const onFocus = () => load()
    window.addEventListener('focus', onFocus)
    return () => { clearInterval(t); window.removeEventListener('focus', onFocus) }
  }, [load, signedOut])

  // Refresh + re-check push state the moment the panel opens.
  useEffect(() => {
    if (!open) return
    load()
    if (pushSupported()) getPushState().then(setPushState)
  }, [open, load])

  const enablePush = async () => {
    setPushBusy(true)
    try {
      await subscribePush()
      setPushState(await getPushState())
    } finally {
      setPushBusy(false)
    }
  }

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  if (signedOut) return null

  // Model: the bell shows everything that needs attention. Badge = how many are
  // in the list. Tick removes one; "Clear all" empties it. No read/unread state.
  const visible = items.filter((n) => !(n.synthesized && dismissed.has(n.id)))
  const badge = visible.length

  const dismissSynth = (id) => {
    setDismissed((prev) => { const next = new Set(prev); next.add(id); saveDismissed(next); return next })
  }

  const clickItem = (n) => {
    if (n.synthesized) dismissSynth(n.id)
    else { setItems((prev) => prev.filter((x) => x.id !== n.id)); apiFetch(`/notifications/${n.id}`, { method: 'DELETE' }).catch(() => {}) }
    if (n.meeting_id != null && onOpenMeeting) onOpenMeeting(n.meeting_id)
    setOpen(false)
  }

  // Clear a single item (the per-row tick). Stored notifications are DELETED
  // server-side so they don't reappear on the next poll; synthesized action_due
  // items are dismissed via localStorage (they're recomputed each fetch).
  const dismissItem = async (n) => {
    if (n.synthesized) { dismissSynth(n.id); return }
    setItems((prev) => prev.filter((x) => x.id !== n.id))
    try { await apiFetch(`/notifications/${n.id}`, { method: 'DELETE' }) } catch { /* ignore */ }
  }

  const clearAll = async () => {
    // Dismiss synthesized (localStorage) + delete all stored (server).
    setDismissed((prev) => {
      const next = new Set(prev)
      visible.forEach((n) => { if (n.synthesized) next.add(n.id) })
      saveDismissed(next); return next
    })
    setItems([])
    try { await apiFetch('/notifications/clear-all', { method: 'POST' }) } catch { /* ignore */ }
  }

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => (signedOut ? null : setOpen((o) => !o))}
        aria-label={badge ? `Notifications, ${badge} unread` : 'Notifications'}
        className="relative flex h-11 w-11 items-center justify-center rounded-full border border-white/[0.10] bg-white/[0.04] text-white/70 transition hover:border-cyan-400/45 hover:bg-white/[0.07] hover:text-white"
      >
        <Bell className="h-[19px] w-[19px]" aria-hidden="true" />
        {badge > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[18px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold leading-[18px] text-white ring-2 ring-[#0e0f13]">
            {badge > 9 ? '9+' : badge}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-white/[0.10] bg-[#0e0f13] shadow-2xl">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
            <span className="text-[13px] font-semibold text-white/85">Notifications</span>
            {badge > 0 && (
              <button
                type="button"
                onClick={clearAll}
                className="flex items-center gap-1 text-[11px] font-medium text-white/45 transition hover:text-white/80"
              >
                <Check className="h-3.5 w-3.5" /> Clear all
              </button>
            )}
          </div>

          <div className="max-h-[min(420px,60vh)] overflow-y-auto">
            {visible.length === 0 ? (
              <div className="px-4 py-10 text-center text-[13px] text-white/40">You're all caught up.</div>
            ) : (
              visible.map((n) => {
                const meta = META[n.type] || META.meeting_ready
                const { Icon } = meta
                // Synthesized action_due: the TASK is the headline; the timing
                // ("Overdue" / "Due in 2d") is an urgency-colored badge, no timestamp.
                // Stored events: title headline + body subline + real time-ago.
                const isSynth = !!n.synthesized
                const headline = isSynth ? (n.body || n.title) : n.title
                const sub = isSynth ? null : n.body
                const badge = isSynth ? n.title : null
                const overdue = badge && badge.toLowerCase().startsWith('overdue')
                const time = isSynth ? '' : timeAgo(n.created_at)
                return (
                  <div
                    key={n.id}
                    className="group flex items-start gap-2 border-b border-white/[0.04] pl-4 pr-2 py-3 transition hover:bg-white/[0.04]"
                  >
                    <button
                      type="button"
                      onClick={() => clickItem(n)}
                      className="flex min-w-0 flex-1 items-start gap-3 text-left"
                    >
                      <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${meta.ring}`}>
                        <Icon className={`h-[17px] w-[17px] ${meta.color}`} aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-white/90">{headline}</span>
                        {badge && (
                          <span className={`mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${overdue ? 'bg-rose-500/15 text-rose-300' : 'bg-amber-500/15 text-amber-300'}`}>
                            {badge}
                          </span>
                        )}
                        {sub && <span className="mt-0.5 block truncate text-[12.5px] text-white/55">{sub}</span>}
                        {time && <span className="mt-1 block text-[11px] text-white/35">{time}</span>}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); dismissItem(n) }}
                      aria-label="Dismiss notification"
                      title="Dismiss"
                      className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white/55 transition hover:bg-white/10 hover:text-white group-hover:text-white/75"
                    >
                      <Check className="h-4 w-4" />
                    </button>
                  </div>
                )
              })
            )}
          </div>

          {/* Meeting-reminder opt-in (Web Push). Hidden when unsupported/denied or
              already subscribed. Enables the 5-min-before reminder with the tab closed. */}
          {(pushState === 'default') && (
            <button
              type="button"
              onClick={enablePush}
              disabled={pushBusy}
              className="flex w-full items-center justify-center gap-2 border-t border-white/[0.07] px-4 py-3 text-[12px] font-medium text-cyan-300/85 transition hover:bg-white/[0.04] hover:text-cyan-200 disabled:opacity-50"
            >
              <BellRing className="h-4 w-4" />
              {pushBusy ? 'Enabling…' : 'Enable meeting reminders'}
            </button>
          )}
          {pushState === 'subscribed' && (
            <div className="flex items-center justify-center gap-1.5 border-t border-white/[0.07] px-4 py-2.5 text-[11px] text-white/40">
              <BellRing className="h-3.5 w-3.5" /> Meeting reminders on
            </div>
          )}
        </div>
      )}
    </div>
  )
}

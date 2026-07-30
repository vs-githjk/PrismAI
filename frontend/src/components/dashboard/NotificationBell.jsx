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
  const [storedUnread, setStoredUnread] = useState(0)
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
      setStoredUnread(data.unread_count || 0)
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

  const visible = items.filter((n) => !(n.synthesized && dismissed.has(n.id)))
  const synthUnread = visible.filter((n) => n.synthesized).length
  const badge = storedUnread + synthUnread

  const markStoredRead = async (id) => {
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
    setStoredUnread((c) => Math.max(0, c - 1))
    try { await apiFetch(`/notifications/${id}/read`, { method: 'POST' }) } catch { /* ignore */ }
  }

  const dismissSynth = (id) => {
    setDismissed((prev) => { const next = new Set(prev); next.add(id); saveDismissed(next); return next })
  }

  const clickItem = (n) => {
    if (n.synthesized) dismissSynth(n.id)
    else if (!n.read) markStoredRead(n.id)
    if (n.meeting_id != null && onOpenMeeting) onOpenMeeting(n.meeting_id)
    setOpen(false)
  }

  const markAllRead = async () => {
    setItems((prev) => prev.map((n) => (n.synthesized ? n : { ...n, read: true })))
    setStoredUnread(0)
    // Also clear synthesized from the badge by dismissing them.
    setDismissed((prev) => {
      const next = new Set(prev)
      visible.forEach((n) => { if (n.synthesized) next.add(n.id) })
      saveDismissed(next); return next
    })
    try { await apiFetch('/notifications/read-all', { method: 'POST' }) } catch { /* ignore */ }
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
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[18px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold leading-[18px] text-white ring-2 ring-[#0b1120]">
            {badge > 9 ? '9+' : badge}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-white/[0.10] bg-[#0d1526]/95 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
            <span className="text-[13px] font-semibold text-white/85">Notifications</span>
            {badge > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="flex items-center gap-1 text-[11px] font-medium text-cyan-300/80 transition hover:text-cyan-200"
              >
                <Check className="h-3.5 w-3.5" /> Mark all read
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
                const unread = n.synthesized || !n.read
                return (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => clickItem(n)}
                    className={`flex w-full items-start gap-3 border-b border-white/[0.04] px-4 py-3 text-left transition hover:bg-white/[0.04] ${unread ? 'bg-white/[0.02]' : ''}`}
                  >
                    <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${meta.ring}`}>
                      <Icon className={`h-[17px] w-[17px] ${meta.color}`} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold text-white/90">{n.title}</span>
                        {unread && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-400" />}
                      </span>
                      {n.body && <span className="mt-0.5 block truncate text-[12.5px] text-white/55">{n.body}</span>}
                      <span className="mt-1 block text-[11px] text-white/35">{timeAgo(n.created_at)}</span>
                    </span>
                  </button>
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

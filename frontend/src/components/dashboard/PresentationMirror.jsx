import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../lib/api'

/**
 * PresentationMirror — Phase 4 of Bot Screen Presentation.
 *
 * Shows the live mirror of what Prism is presenting on-screen inside the meeting.
 * The backend gates the actual stream URL to authenticated workspace members
 * (noVNC view_only is client-soft and the stream URL carries the VNC password),
 * so anonymous viewers get an "active + goal" indicator with no stream.
 *
 * Two modes:
 *   - Presentational: pass `screenshare` ({active, goal, view_url}) directly when
 *     the parent already polls /live (LiveMeetingView).
 *   - Self-polling: pass `liveToken` and it polls /live/{token} via apiFetch
 *     (dashboard live area, where no /live data is threaded down). apiFetch
 *     auto-attaches the signed-in owner's token, so they get the members-only URL.
 */
export default function PresentationMirror({ screenshare: screenshareProp = null, liveToken = null }) {
  const [polled, setPolled] = useState(null)
  const selfPoll = !screenshareProp && !!liveToken
  const timerRef = useRef(null)

  useEffect(() => {
    if (!selfPoll) return
    let alive = true
    const tick = async () => {
      try {
        const res = await apiFetch(`/live/${liveToken}`)
        if (!res.ok) return
        const json = await res.json()
        if (alive) setPolled(json?.screenshare || null)
      } catch {
        /* transient — keep the current frame, retry next tick */
      }
    }
    tick()
    timerRef.current = setInterval(tick, 4000)
    return () => {
      alive = false
      clearInterval(timerRef.current)
    }
  }, [selfPoll, liveToken])

  const sc = screenshareProp || polled
  if (!sc?.active) return null

  const goal = (sc.goal || '').trim()

  return (
    <div
      className="overflow-hidden rounded-2xl border border-cyan-400/25 bg-[var(--db-fill)]"
    >
      <div className="flex items-center gap-2 border-b border-[color:var(--db-border)] px-4 py-2.5">
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400/60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-400" />
        </span>
        <span className="text-xs font-semibold text-cyan-200">Prism is presenting</span>
        {goal && (
          <span className="ml-1 min-w-0 flex-1 truncate text-[11px] text-[color:var(--db-text-faint)]" title={goal}>
            · {goal}
          </span>
        )}
      </div>

      {sc.view_url ? (
        <div className="relative aspect-video w-full bg-[#0a0e14]">
          <iframe
            src={sc.view_url}
            title="Prism presentation"
            allow="fullscreen"
            loading="lazy"
            className="absolute inset-0 h-full w-full border-0"
          />
        </div>
      ) : (
        <div className="px-4 py-4">
          <p className="text-[12px] leading-relaxed text-[color:var(--db-text-muted)]">
            Prism is showing a screen in the meeting.
            {goal ? ` Currently: ${goal}.` : ''}
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-[color:var(--db-text-faint)]">
            Sign in as a workspace member to watch the live screen here.
          </p>
        </div>
      )}
    </div>
  )
}

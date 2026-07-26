import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../lib/api'

const POLL_INTERVAL_MS = 15000
const POLL_MAX_ATTEMPTS = 20  // 15s * 20 = 5min

const REASON_COPY = {
  expired: "Recall.ai's retention window has passed.",
  not_found: 'The bot recording was deleted.',
  no_recording: 'No audio was captured during this meeting.',
  not_a_bot_meeting: null,  // handled by returning null
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const ss = s.toString().padStart(2, '0')
  return h > 0 ? `${h}:${m.toString().padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

export default function RecordingPlayer({
  meetingId,
  recordingProvider,
  transcriptSegments,
  transcriptText,
}) {
  const [state, setState] = useState('loading')  // 'loading' | 'ready' | 'processing' | 'gone'
  const [media, setMedia] = useState(null)        // { url, kind } when ready
  const [reason, setReason] = useState(null)      // when state==='gone'
  const attemptsRef = useRef(0)
  const timeoutRef = useRef(null)
  const abortRef = useRef(null)
  // Cap mid-playback URL refreshes at 1 — if a freshly-fetched URL also fails,
  // the recording is genuinely gone, don't loop.
  const refreshUsedRef = useRef(false)

  // Non-bot meetings render nothing. Must run AFTER hooks above to keep hook order stable.
  const isBotMeeting = recordingProvider === 'recall'

  // Lifted out of the useEffect so onError on the media element can call it
  // again for the URL-refresh-on-expiry path. Stable identity via useCallback.
  const fetchRecording = useCallback(async ({ isRefresh = false } = {}) => {
    if (!isBotMeeting) return
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const res = await apiFetch(`/meetings/${meetingId}/recording`, { signal: controller.signal })
      // Non-2xx (apiFetch doesn't throw on these): right after a meeting the row was
      // JUST POSTed and may not be queryable yet → the endpoint 404s for a moment. Poll
      // (bounded) instead of flashing "The bot recording was deleted." A genuinely
      // missing/forbidden meeting resolves to the terminal state after the cap.
      if (!res.ok) {
        attemptsRef.current += 1
        if (attemptsRef.current >= POLL_MAX_ATTEMPTS) {
          setReason('not_found')
          setState('gone')
          return
        }
        setState('processing')
        timeoutRef.current = setTimeout(() => fetchRecording(), POLL_INTERVAL_MS)
        return
      }
      const data = await res.json().catch(() => ({}))
      if (data.url) {
        setMedia({ url: data.url, kind: data.kind })
        setState('ready')
        return
      }
      if (data.reason === 'not_a_bot_meeting') {
        return  // defensive — provider check above should have prevented this
      }
      // Transient states right after a meeting: Recall hasn't finished attaching the
      // recording yet (`no_recording` = recordings array still empty; `not_ready` = no
      // media URL yet). The recording almost always lands within 1–3 min — poll instead
      // of flashing a terminal "deleted"/"no audio" (the meeting just auto-promoted).
      if (data.reason === 'not_ready' || data.reason === 'no_recording') {
        attemptsRef.current += 1
        if (attemptsRef.current >= POLL_MAX_ATTEMPTS) {
          setState('processing')
          setReason('cap_reached')
          return
        }
        setState('processing')
        timeoutRef.current = setTimeout(() => fetchRecording(), POLL_INTERVAL_MS)
        return
      }
      // expired / not_found (deleted) are genuinely terminal.
      setReason(data.reason || 'not_found')
      setState('gone')
    } catch (err) {
      if (err?.name === 'AbortError') return
      if (isRefresh) {
        setReason('expired')
        setState('gone')
        return
      }
      // Initial fetch failed — the meeting row may have JUST been auto-promoted (or a
      // network blip). Poll a bounded number of times before declaring it gone rather
      // than showing "The bot recording was deleted" on a recording that's still landing.
      attemptsRef.current += 1
      if (attemptsRef.current >= POLL_MAX_ATTEMPTS) {
        setReason('not_found')
        setState('gone')
        return
      }
      setState('processing')
      timeoutRef.current = setTimeout(() => fetchRecording(), POLL_INTERVAL_MS)
    }
  }, [meetingId, isBotMeeting])

  useEffect(() => {
    if (!isBotMeeting) return
    fetchRecording()
    return () => {
      abortRef.current?.abort()
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [meetingId, isBotMeeting, fetchRecording])

  // onError on <video>/<audio>: signed URL likely expired mid-session.
  // Refresh once. If the refresh succeeds, the media src swap will retry play.
  // If it fails or the second URL also errors, fall to 'gone' with reason='expired'.
  const handleMediaError = useCallback(() => {
    if (refreshUsedRef.current) {
      setReason('expired')
      setState('gone')
      return
    }
    refreshUsedRef.current = true
    fetchRecording({ isRefresh: true })
  }, [fetchRecording])

  if (!isBotMeeting) return null

  if (state === 'loading') {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/60">
        Loading recording…
      </div>
    )
  }

  if (state === 'processing') {
    if (reason === 'cap_reached') {
      return (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
          <div className="mb-2">Recording is taking longer than expected.</div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/90 hover:bg-white/10 transition-colors"
          >
            Reload page
          </button>
        </div>
      )
    }
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
        Recording is still being prepared by Recall.ai. This usually takes 1–3 minutes after the meeting ends.
      </div>
    )
  }

  if (state === 'gone') {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
        <div className="font-medium text-white/90">Recording is no longer available</div>
        <div className="mt-1 text-white/50">{REASON_COPY[reason] || 'The recording could not be loaded.'}</div>
      </div>
    )
  }

  // state === 'ready'
  return (
    <SyncedPlayer
      url={media.url}
      kind={media.kind}
      segments={transcriptSegments}
      transcriptText={transcriptText}
      onMediaError={handleMediaError}
    />
  )
}

function SyncedPlayer({ url, kind, segments, transcriptText, onMediaError }) {
  const mediaRef = useRef(null)
  const [activeIdx, setActiveIdx] = useState(-1)
  const lastUpdateRef = useRef(0)
  const userScrolledAtRef = useRef(0)
  const activeRowRef = useRef(null)
  const listRef = useRef(null)

  const hasSegments = Array.isArray(segments) && segments.length > 0

  // Throttled onTimeUpdate handler — ~4Hz
  const handleTimeUpdate = () => {
    const now = performance.now()
    if (now - lastUpdateRef.current < 250) return
    lastUpdateRef.current = now
    const t = mediaRef.current?.currentTime ?? 0
    const idx = findSegmentIndex(segments, t)
    if (idx !== activeIdx) setActiveIdx(idx)
  }

  // Auto-scroll active row into view, but only if user hasn't scrolled in last 3s
  useEffect(() => {
    if (activeIdx < 0 || !activeRowRef.current) return
    const sinceUserScroll = performance.now() - userScrolledAtRef.current
    if (sinceUserScroll < 3000) return
    activeRowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeIdx])

  // User-scroll detector. Covers wheel, touch, AND keyboard (Arrow/Page/Space) —
  // anything that produces a scroll event on the container counts as the user
  // taking over.
  const noteUserScroll = () => {
    userScrolledAtRef.current = performance.now()
  }

  const seekTo = (seconds) => {
    if (!mediaRef.current) return
    // Click-to-seek is an intentional navigation — clear the user-scroll
    // suppression so auto-scroll resumes tracking from the new playhead
    // without the 3s delay if the user had scrolled recently.
    userScrolledAtRef.current = 0
    mediaRef.current.currentTime = seconds
    mediaRef.current.play().catch(() => {})
  }

  return (
    <div className="grid gap-4 md:grid-cols-[3fr_2fr] rounded-2xl border border-white/10 bg-black/40 p-4">
      <div>
        {kind === 'audio' ? (
          <audio
            ref={mediaRef}
            src={url}
            controls
            className="w-full"
            onTimeUpdate={handleTimeUpdate}
            onError={onMediaError}
          />
        ) : (
          <video
            ref={mediaRef}
            src={url}
            controls
            className="w-full rounded-lg"
            onTimeUpdate={handleTimeUpdate}
            onError={onMediaError}
          />
        )}
      </div>
      <div
        ref={listRef}
        onScroll={noteUserScroll}
        className="max-h-[420px] overflow-y-auto rounded-lg border border-white/5 bg-white/5 p-3"
      >
        {hasSegments ? (
          segments.map((seg, i) => {
            const isActive = i === activeIdx
            const ts = formatTime(seg.start)
            const snippet = seg.text.length > 60 ? `${seg.text.slice(0, 60)}…` : seg.text
            return (
              <button
                key={i}
                ref={isActive ? activeRowRef : null}
                onClick={() => seekTo(seg.start)}
                aria-current={isActive ? 'true' : undefined}
                aria-label={`Jump to ${ts} — ${seg.speaker}: ${snippet}`}
                className={
                  'flex w-full items-baseline gap-2 text-left text-xs leading-5 px-2 py-1 rounded transition-colors ' +
                  (isActive
                    ? 'text-sky-400 bg-white/5'
                    : 'text-white/70 hover:text-white hover:bg-white/5')
                }
              >
                <span className="shrink-0 tabular-nums text-[10.5px] text-white/40 font-mono">{ts}</span>
                <span>
                  <span className="font-medium text-white/90">{seg.speaker}: </span>
                  {seg.text}
                </span>
              </button>
            )
          })
        ) : (
          <>
            <p className="mb-2 text-[11px] italic text-white/40">
              Timestamped transcript not available for this meeting — clicking text won&apos;t seek the recording.
            </p>
            <pre className="whitespace-pre-wrap text-xs leading-5 text-white/70">
              {transcriptText || ''}
            </pre>
          </>
        )}
      </div>
    </div>
  )
}

function findSegmentIndex(segments, currentTime) {
  if (!Array.isArray(segments) || segments.length === 0) return -1
  // Binary search for the segment where start <= t < end. Falls back to the
  // last segment that started before currentTime when no exact match (end-of-segment gaps).
  let lo = 0, hi = segments.length - 1, best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const seg = segments[mid]
    if (currentTime < seg.start) {
      hi = mid - 1
    } else if (currentTime >= seg.end) {
      best = mid
      lo = mid + 1
    } else {
      return mid
    }
  }
  return best
}

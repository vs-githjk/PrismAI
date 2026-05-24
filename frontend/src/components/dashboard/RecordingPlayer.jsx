import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../lib/api'

const POLL_INTERVAL_MS = 15000
const POLL_MAX_ATTEMPTS = 20  // 15s * 20 = 5min

const REASON_COPY = {
  expired: "Recall.ai's retention window has passed.",
  not_found: 'The bot recording was deleted.',
  no_recording: 'No audio was captured during this meeting.',
  not_a_bot_meeting: null,  // handled by returning null
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

  // Non-bot meetings render nothing. Must run AFTER hooks above to keep hook order stable.
  const isBotMeeting = recordingProvider === 'recall'

  useEffect(() => {
    if (!isBotMeeting) return
    let cancelled = false

    const fetchOnce = async () => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const res = await apiFetch(`/meetings/${meetingId}/recording`, { signal: controller.signal })
        if (cancelled) return
        const data = await res.json().catch(() => ({}))
        if (data.url) {
          setMedia({ url: data.url, kind: data.kind })
          setState('ready')
          return
        }
        if (data.reason === 'not_ready') {
          attemptsRef.current += 1
          if (attemptsRef.current >= POLL_MAX_ATTEMPTS) {
            setState('processing')
            setReason('cap_reached')
            return
          }
          setState('processing')
          timeoutRef.current = setTimeout(fetchOnce, POLL_INTERVAL_MS)
          return
        }
        if (data.reason === 'not_a_bot_meeting') {
          // Defensive — provider check above should have prevented this
          return
        }
        setReason(data.reason || 'not_found')
        setState('gone')
      } catch (err) {
        if (err?.name === 'AbortError' || cancelled) return
        setReason('not_found')
        setState('gone')
      }
    }

    fetchOnce()

    return () => {
      cancelled = true
      abortRef.current?.abort()
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [meetingId, isBotMeeting])

  if (!isBotMeeting) return null

  if (state === 'loading') {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/60">
        Loading recording…
      </div>
    )
  }

  if (state === 'processing') {
    const copy = reason === 'cap_reached'
      ? 'Recording is taking longer than expected. Refresh the page to try again.'
      : 'Recording is still being prepared by Recall.ai. This usually takes 1–3 minutes after the meeting ends.'
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
        {copy}
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
    />
  )
}

function SyncedPlayer({ url, kind, segments, transcriptText }) {
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

  // User-scroll detector
  const noteUserScroll = () => {
    userScrolledAtRef.current = performance.now()
  }

  const seekTo = (seconds) => {
    if (!mediaRef.current) return
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
          />
        ) : (
          <video
            ref={mediaRef}
            src={url}
            controls
            className="w-full rounded-lg"
            onTimeUpdate={handleTimeUpdate}
          />
        )}
      </div>
      <div
        ref={listRef}
        onWheel={noteUserScroll}
        onTouchMove={noteUserScroll}
        className="max-h-[420px] overflow-y-auto rounded-lg border border-white/5 bg-white/5 p-3"
      >
        {hasSegments ? (
          segments.map((seg, i) => (
            <button
              key={i}
              ref={i === activeIdx ? activeRowRef : null}
              onClick={() => seekTo(seg.start)}
              className={
                'block w-full text-left text-xs leading-5 px-2 py-1 rounded transition-colors ' +
                (i === activeIdx
                  ? 'text-sky-400 bg-white/5'
                  : 'text-white/70 hover:text-white hover:bg-white/5')
              }
            >
              <span className="font-medium text-white/90">{seg.speaker}: </span>
              {seg.text}
            </button>
          ))
        ) : (
          <pre className="whitespace-pre-wrap text-xs leading-5 text-white/70">
            {transcriptText || ''}
          </pre>
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

import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Search } from 'lucide-react'

/**
 * Topbar island: page title (left) + global search pill (right).
 * The title shows the focused meeting's name, or the view label
 * (Home / Trend / Knowledge). When the title overflows its track it
 * slowly cycles horizontally; short titles stay static, and
 * prefers-reduced-motion falls back to a plain ellipsis.
 * `onBack`, when provided (meeting view), renders a back affordance
 * left of the title that returns to Home.
 */
export default function DashboardTopbar({ title, searchValue, onSearchChange, actions = null, onBack = null }) {
  const trackRef = useRef(null)
  const textRef = useRef(null)
  const [shift, setShift] = useState(0) // px the title must travel to reveal its tail; 0 = no marquee

  // Measure overflow against the track; re-measure on title change and resize.
  // The exact shift drives the marquee end position (CSS .is-marquee).
  useEffect(() => {
    const measure = () => {
      const track = trackRef.current
      const text = textRef.current
      if (!track || !text) return
      const overflow = text.scrollWidth - track.clientWidth
      setShift(overflow > 1 ? overflow : 0)
    }
    measure()
    const ro = new ResizeObserver(measure)
    if (trackRef.current) ro.observe(trackRef.current)
    return () => ro.disconnect()
  }, [title])

  const overflowing = shift > 0

  return (
    <header className="dashboard-topbar dashboard-island z-30 flex items-center gap-4 px-6">
      {/* Left: optional back affordance + page title (marquee on overflow) + inline actions */}
      <div className="flex min-w-0 items-center gap-3">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to dashboard"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-white/[0.10] bg-white/[0.04] text-white/70 transition hover:border-cyan-400/45 hover:bg-white/[0.07] hover:text-white"
          >
            <ArrowLeft className="h-[18px] w-[18px]" aria-hidden="true" />
          </button>
        )}
        <div ref={trackRef} className="dashboard-title-track min-w-0">
          <span
            ref={textRef}
            className={`dashboard-title-text${overflowing ? ' is-marquee' : ''}`}
            style={overflowing ? { '--marquee-shift': `${shift}px` } : undefined}
            title={title}
          >
            {title}
          </span>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>

      {/* Right: global search pill */}
      <div className="ml-auto flex h-11 w-[clamp(200px,30vw,380px)] shrink-0 items-center gap-2.5 rounded-full border border-white/[0.10] bg-white/[0.04] px-4 transition focus-within:border-cyan-400/45 focus-within:bg-white/[0.06]">
        <input
          value={searchValue || ''}
          onChange={(e) => onSearchChange?.(e.target.value)}
          placeholder="Search anything..."
          aria-label="Search meetings"
          className="h-full min-w-0 flex-1 bg-transparent text-[14px] font-medium text-white/85 outline-none placeholder:font-normal placeholder:text-white/35"
        />
        <Search className="h-[18px] w-[18px] shrink-0 text-white/45" aria-hidden="true" />
      </div>
    </header>
  )
}

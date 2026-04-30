import { useEffect, useState } from 'react'

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

export default function useCountUp(target, duration = 700) {
  const normalized = Number.isFinite(Number(target)) ? Number(target) : 0
  const [display, setDisplay] = useState(() => normalized)

  useEffect(() => {
    if (prefersReducedMotion()) {
      setDisplay(normalized)
      return
    }

    let frame = null
    let start = null

    const step = (timestamp) => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(eased * normalized))
      if (progress < 1) frame = requestAnimationFrame(step)
    }

    setDisplay(0)
    frame = requestAnimationFrame(step)
    return () => {
      if (frame) cancelAnimationFrame(frame)
    }
  }, [normalized, duration])

  return display
}

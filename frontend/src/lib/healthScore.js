import { useEffect, useState } from 'react'

export function useCountUp(target, duration = 1000) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    if (target === undefined || target === null) return
    let start = null
    const step = (timestamp) => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(eased * target))
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [target, duration])
  return display
}

export const BADGE_POSITIVE = new Set([
  'Clear Decisions',
  'Action-Oriented',
  'Well-Facilitated',
  'Concise',
  'Engaged Team',
  'Inclusive',
])

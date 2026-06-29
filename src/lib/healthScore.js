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

// Single source of truth for a meeting's "Overall" health number.
// Overall = round(mean of the 3 breakdown axes: clarity / action / engagement).
// The triangle and the home "Recent meetings" card MUST both use this so they
// never disagree. Falls back to the LLM's holistic `score` only for legacy
// meetings that have no breakdown. Returns null when nothing is scorable.
export function overallHealth(healthScore) {
  const bd = healthScore?.breakdown
  if (bd) {
    const axes = [bd.clarity, bd.action_orientation, bd.engagement].map(Number)
    if (axes.every(Number.isFinite)) {
      return Math.round((axes[0] + axes[1] + axes[2]) / 3)
    }
  }
  const score = Number(healthScore?.score)
  return Number.isFinite(score) ? Math.round(score) : null
}

export const BADGE_POSITIVE = new Set([
  'Clear Decisions',
  'Action-Oriented',
  'Well-Facilitated',
  'Concise',
  'Engaged Team',
  'Inclusive',
])

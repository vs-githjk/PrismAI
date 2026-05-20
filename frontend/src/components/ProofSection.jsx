import { useEffect, useRef, useState } from 'react'

// Scramble-then-settle number reveal: the displayed value cycles through
// random digits at high frequency during the first 60% of the duration,
// then snaps to the eased count-up for the final 40%. Reads as a slot-
// machine "rolling into place" effect rather than a plain ramp.
function useScrambleNumber(target, durationMs = 1600, start = false) {
  const [val, setVal] = useState(0)
  useEffect(() => {
    if (!start) return
    let raf
    const t0 = performance.now()
    const scrambleUntil = durationMs * 0.6
    // Roughly the digit-count of the target — controls scramble magnitude.
    const magnitude = Math.max(1, Math.ceil(Math.log10(target + 1)))
    const tick = (now) => {
      const elapsed = now - t0
      const p = Math.min(elapsed / durationMs, 1)
      if (elapsed < scrambleUntil) {
        // Pure scramble — random within an order of magnitude of target.
        setVal(Math.random() * Math.pow(10, magnitude))
      } else {
        // Settle phase: ease-out from a randomized starting point to target.
        const settleP = (elapsed - scrambleUntil) / (durationMs - scrambleUntil)
        const eased = 1 - Math.pow(1 - settleP, 3)
        setVal(eased * target)
      }
      if (p < 1) raf = requestAnimationFrame(tick)
      else setVal(target)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, durationMs, start])
  return val
}

function ProofStat({ value, suffix = '', label, sublabel, color, delay = 0, start, parallaxFactor = 0 }) {
  const num = useScrambleNumber(value, 1700, start)
  const display = suffix === '%' || Number.isInteger(value)
    ? Math.round(num).toString()
    : num.toFixed(1)
  const cardRef = useRef(null)

  // Cursor-tracking: drives both the radial glow position AND the 3D tilt
  const handlePointerMove = (e) => {
    const el = cardRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * 100   // 0..100 %
    const y = ((e.clientY - rect.top) / rect.height) * 100
    // Tilt amount: cursor offset from center, capped at ±6 degrees
    const tiltY = ((e.clientX - rect.left) / rect.width - 0.5) * 8
    const tiltX = -((e.clientY - rect.top) / rect.height - 0.5) * 8
    el.style.setProperty('--mx', `${x}%`)
    el.style.setProperty('--my', `${y}%`)
    el.style.setProperty('--tilt-x', `${tiltX}deg`)
    el.style.setProperty('--tilt-y', `${tiltY}deg`)
  }
  const handlePointerLeave = () => {
    const el = cardRef.current
    if (!el) return
    el.style.setProperty('--mx', '50%')
    el.style.setProperty('--my', '0%')
    el.style.setProperty('--tilt-x', '0deg')
    el.style.setProperty('--tilt-y', '0deg')
  }

  return (
    <div
      ref={cardRef}
      className="proof-stat"
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      style={{
        transitionDelay: `${delay}ms`,
        '--stat-color': color,
      }}
    >
      <div className="proof-stat-inner">
        <div className="proof-stat-number-row">
          <span className="proof-stat-number" style={{ color }}>
            {display}
          </span>
          <span className="proof-stat-suffix" style={{ color }}>{suffix}</span>
        </div>
        <div className="proof-stat-label">{label}</div>
        <div className="proof-stat-sublabel">{sublabel}</div>
      </div>
    </div>
  )
}

export default function ProofSection() {
  const sectionRef = useRef(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = sectionRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          obs.disconnect()
        }
      },
      { threshold: 0.25, rootMargin: '0px 0px -10% 0px' }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Scroll-driven parallax: cards drift at slightly different vertical rates
  // as the section moves through the viewport. rAF-throttled so it stays smooth
  // even with the existing prism WebGL behind everything.
  useEffect(() => {
    const section = sectionRef.current
    if (!section) return
    const scrollContainer = section.closest('.landing-page') || window
    if (typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return
    }
    let raf = 0
    let pending = false
    const apply = () => {
      pending = false
      const rect = section.getBoundingClientRect()
      // 0 when section centered in viewport, ± as it scrolls past.
      const center = rect.top + rect.height / 2 - window.innerHeight / 2
      const cards = section.querySelectorAll('.proof-stat')
      cards.forEach((card, i) => {
        // Each card a slightly different factor; middle card stays still-ish.
        const factor = [0.06, 0.03, 0.06][i] ?? 0.05
        const sign = i === 0 ? -1 : i === 2 ? 1 : 0
        card.style.setProperty('--parallax-y', `${sign * center * factor}px`)
      })
    }
    const onScroll = () => {
      if (pending) return
      pending = true
      raf = requestAnimationFrame(apply)
    }
    scrollContainer.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })
    apply()  // initial position
    return () => {
      cancelAnimationFrame(raf)
      scrollContainer.removeEventListener('scroll', onScroll)
      window.removeEventListener('scroll', onScroll)
    }
  }, [])

  return (
    <section
      ref={sectionRef}
      className={`proof-section ${inView ? 'proof-section--in-view' : ''}`}
    >
      {/* Aurora — three slowly-drifting colored blobs sit behind content.
          Pure CSS-animated. Adds atmospheric depth without competing with
          the page-wide prism WebGL also visible behind everything. */}
      <div className="proof-aurora" aria-hidden="true">
        <span className="proof-aurora-blob proof-aurora-blob--cyan" />
        <span className="proof-aurora-blob proof-aurora-blob--violet" />
        <span className="proof-aurora-blob proof-aurora-blob--emerald" />
      </div>

      <div className="proof-container">
        <span className="proof-eyebrow">Built different</span>
        <h2 className="proof-headline">
          Eight minds working in parallel.
          <br />
          <span className="proof-headline-accent">Your meeting, decoded in seconds.</span>
        </h2>
        <p className="proof-subhead">
          Most meeting tools give you a transcript and a summary. PrismAI runs eight
          specialized agents in parallel — decisions, action items, sentiment, health
          scores, follow-up emails — all grounded in your real conversations.
        </p>

        <div className="proof-stats">
          <ProofStat
            value={8}
            label="AI agents"
            sublabel="running in parallel — depth without delay"
            color="#22d3ee"
            delay={0}
            start={inView}
          />
          <ProofStat
            value={2}
            suffix="s"
            label="Average analysis"
            sublabel="from meeting end to full breakdown"
            color="#34d399"
            delay={120}
            start={inView}
          />
          <ProofStat
            value={100}
            suffix="%"
            label="Grounded answers"
            sublabel="every claim cites a real source — no hallucinations"
            color="#a78bfa"
            delay={240}
            start={inView}
          />
        </div>
      </div>
    </section>
  )
}

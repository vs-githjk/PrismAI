import { useRef, useEffect, useState } from 'react'

const FREE_FEATURES = [
  '5 meeting analyses / month',
  'All 7 AI agents included',
  'Paste & upload transcripts',
  'Action items, summaries & decisions',
  'Shareable results link',
]

const PRO_FEATURES = [
  'Unlimited meeting analyses',
  'All 7 AI agents included',
  'Live recording & audio upload',
  'Meeting bot — joins calls automatically',
  'Cross-meeting insights & trends',
  'Priority processing queue',
  'Early access to new agents',
]

function Check() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="pricing-check" aria-hidden="true">
      <circle cx="7" cy="7" r="6.25" stroke="currentColor" strokeWidth="1" />
      <polyline
        points="4,7 6.25,9.25 10.5,4.75"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}

export default function PricingSection({ onGetStarted }) {
  const [visible, setVisible] = useState(false)
  const sectionRef = useRef(null)

  useEffect(() => {
    const obs = new IntersectionObserver(
      ([entry]) => {
        const r = entry.intersectionRatio
        if (r > 0.08) setVisible(true)
      },
      { threshold: [0, 0.08, 1] }
    )
    if (sectionRef.current) obs.observe(sectionRef.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section ref={sectionRef} id="pricing" className="pricing-section scroll-section" style={{ position: 'relative' }}>
      <div className="section-inner">
        <p className="section-eyebrow">Pricing</p>
        <h2 className={`pricing-heading${visible ? ' heading-visible' : ''}`}>
          Simple, transparent pricing
        </h2>
        <p className={`pricing-subhead${visible ? ' subhead-visible' : ''}`}>
          Start free. Upgrade when you're ready.
        </p>

        <div className="pricing-grid">
          {/* Free tier */}
          <div
            className={`pricing-card${visible ? ' card-visible' : ''}`}
            style={{ transitionDelay: visible ? '100ms' : '0ms' }}
          >
            <div className="pricing-tier-name">Free</div>
            <div className="pricing-price">
              <span className="pricing-amount">$0</span>
              <span className="pricing-cadence">/ month</span>
            </div>
            <p className="pricing-blurb">
              For individuals getting started with AI meeting intelligence.
            </p>
            <div className="pricing-divider" />
            <ul className="pricing-features">
              {FREE_FEATURES.map(f => (
                <li key={f} className="pricing-feature">
                  <Check />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="pricing-cta pricing-cta-ghost landing-button-secondary"
              onClick={onGetStarted}
            >
              Get started free
            </button>
          </div>

          {/* Pro tier */}
          <div
            className={`pricing-card pricing-card-pro${visible ? ' card-visible' : ''}`}
            style={{ transitionDelay: visible ? '200ms' : '0ms' }}
          >
            <div className="pricing-badge">Recommended</div>
            <div className="pricing-tier-name">Pro</div>
            <div className="pricing-price">
              <span className="pricing-amount">$X</span>
              <span className="pricing-cadence">/ month</span>
            </div>
            <p className="pricing-blurb">
              For engineering managers who need it to work, every meeting.
            </p>
            <div className="pricing-divider" />
            <ul className="pricing-features">
              {PRO_FEATURES.map(f => (
                <li key={f} className="pricing-feature">
                  <Check />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <button type="button" className="pricing-cta pricing-cta-accent landing-button-primary">
              Book a demo
            </button>
          </div>
        </div>

        <p className="pricing-reassurance">No credit card required. Cancel anytime.</p>
      </div>
    </section>
  )
}

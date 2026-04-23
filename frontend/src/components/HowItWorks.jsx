import { useRef, useEffect, useState } from 'react'

const STEPS = [
  {
    num: '01',
    title: 'Get it in',
    desc: 'Paste a transcript, record live audio, or upload a file.',
  },
  {
    num: '02',
    title: 'Seven agents, in parallel',
    desc: 'An orchestrator routes your meeting to specialized agents that run simultaneously.',
  },
  {
    num: '03',
    title: 'Clarity in ~30 seconds',
    desc: 'Decisions, owners, summaries, emails, and a health score stream back live.',
  },
]

export default function HowItWorks() {
  const [visible, setVisible] = useState(false)
  const [inView, setInView] = useState(false)
  const sectionRef = useRef(null)

  useEffect(() => {
    const obs = new IntersectionObserver(
      ([entry]) => {
        const r = entry.intersectionRatio
        if (r > 0.15) setVisible(true)
        setInView(r > 0.1)
      },
      { threshold: [0, 0.1, 0.15, 1] }
    )
    if (sectionRef.current) obs.observe(sectionRef.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section ref={sectionRef} id="product" className="how-it-works-section scroll-section" style={{ position: 'relative' }}>
      <div className={`section-blur-overlay${inView ? '' : ' active'}`} aria-hidden="true" />
      <div className="section-inner">
        <p className="section-eyebrow">How it works</p>

        <div className="flow-diagram" aria-hidden="true">
          <svg width="36" height="44" viewBox="0 0 36 44" fill="none">
            <rect x="1.75" y="1.75" width="32.5" height="40.5" rx="3.5" stroke="currentColor" strokeWidth="1.5"/>
            <line x1="9" y1="13" x2="27" y2="13" stroke="currentColor" strokeWidth="1.25"/>
            <line x1="9" y1="19" x2="27" y2="19" stroke="currentColor" strokeWidth="1.25"/>
            <line x1="9" y1="25" x2="21" y2="25" stroke="currentColor" strokeWidth="1.25"/>
          </svg>

          <svg width="28" height="10" viewBox="0 0 28 10" fill="none">
            <line x1="0" y1="5" x2="22" y2="5" stroke="currentColor" strokeWidth="1.25"/>
            <polyline points="17,1 23,5 17,9" stroke="currentColor" strokeWidth="1.25" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>

          <svg className={`flow-diagram-prism${visible ? ' prism-shimmer' : ''}`} width="44" height="44" viewBox="0 0 44 44" fill="none">
            <polygon points="22,3 41,22 22,41 3,22" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            <line x1="3" y1="22" x2="41" y2="22" stroke="currentColor" strokeWidth="0.75" opacity="0.4"/>
            <line x1="22" y1="3" x2="41" y2="22" stroke="currentColor" strokeWidth="0.75" opacity="0.3"/>
          </svg>

          <svg width="28" height="10" viewBox="0 0 28 10" fill="none">
            <line x1="0" y1="5" x2="22" y2="5" stroke="currentColor" strokeWidth="1.25"/>
            <polyline points="17,1 23,5 17,9" stroke="currentColor" strokeWidth="1.25" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>

          <svg width="44" height="44" viewBox="0 0 44 44" fill="none">
            <rect x="8" y="12" width="30" height="24" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" opacity="0.3"/>
            <rect x="4" y="8" width="30" height="24" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" opacity="0.6"/>
            <rect x="0" y="4" width="30" height="24" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            <line x1="6" y1="13" x2="22" y2="13" stroke="currentColor" strokeWidth="1" opacity="0.7"/>
            <line x1="6" y1="18" x2="19" y2="18" stroke="currentColor" strokeWidth="1" opacity="0.5"/>
          </svg>
        </div>

        <div className="steps-grid">
          {STEPS.map((step, i) => (
            <div
              key={step.num}
              className={`step-card${visible ? ' step-visible' : ''}`}
              style={{ transitionDelay: visible ? `${i * 60}ms` : '0ms' }}
            >
              <span className="step-num">{step.num}</span>
              <h3 className="step-title">{step.title}</h3>
              <p className="step-desc">{step.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

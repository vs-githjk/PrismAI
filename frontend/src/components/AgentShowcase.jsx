import { useRef, useEffect, useState } from 'react'
import { AGENTS } from '../lib/agents'

export default function AgentShowcase() {
  const [visible, setVisible] = useState(false)
  const sectionRef = useRef(null)

  useEffect(() => {
    const obs = new IntersectionObserver(
      ([entry]) => {
        const r = entry.intersectionRatio
        if (r > 0.1) setVisible(true)
      },
      { threshold: [0, 0.1, 1] }
    )
    if (sectionRef.current) obs.observe(sectionRef.current)
    return () => obs.disconnect()
  }, [])

  return (
    <section ref={sectionRef} className="agent-showcase-section scroll-section" style={{ position: 'relative' }}>
      <div className="section-inner">
        <p className="section-eyebrow">Seven agents</p>
        <div className={`spectrum-hairline${visible ? ' hairline-visible' : ''}`} aria-hidden="true" />
        <div className="agents-grid">
          {AGENTS.map((agent, i) => (
            <div
              key={agent.id}
              className={`agent-card${visible ? ' card-visible' : ''}`}
              style={{ transitionDelay: visible ? `${i * 40}ms` : '0ms' }}
            >
              <div className="agent-card-bg" />
              <div className="agent-card-content">
                <h3 className="agent-name">{agent.label}</h3>
                <p className="agent-desc">{agent.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

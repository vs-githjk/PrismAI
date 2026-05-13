import { useRef, useEffect, useState } from 'react'

const AGENTS = [
  { name: 'Summarizer',         desc: 'Condenses the meeting into a 2–3 sentence TL;DR.' },
  { name: 'Action Items',       desc: 'Extracts who owns what, with due dates.' },
  { name: 'Decisions',          desc: 'Identifies what was actually agreed or resolved.' },
  { name: 'Sentiment',          desc: 'Scores the tone and flags conflict or tension.' },
  { name: 'Email Drafter',      desc: 'Writes a ready-to-send follow-up email.' },
  { name: 'Calendar Suggester', desc: 'Recommends a follow-up meeting with timing.' },
  { name: 'Health Score',       desc: 'Rates meeting quality 0–100 with a breakdown.' },
  { name: 'Speaker Coach',      desc: 'Analyzes talk-time balance and gives per-speaker feedback.' },
]

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
        <p className="section-eyebrow">Eight agents</p>
        <div className={`spectrum-hairline${visible ? ' hairline-visible' : ''}`} aria-hidden="true" />
        <div className="agents-grid">
          {AGENTS.map((agent, i) => (
            <div
              key={agent.name}
              className={`agent-card${visible ? ' card-visible' : ''}`}
              style={{ transitionDelay: visible ? `${i * 40}ms` : '0ms' }}
            >
              <div className="agent-card-bg" />
              <div className="agent-card-content">
                <h3 className="agent-name">{agent.name}</h3>
                <p className="agent-desc">{agent.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

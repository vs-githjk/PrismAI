import { useRef, useEffect, useState } from 'react'

const FOUNDERS = [
  {
    name: 'Founder Name',
    role: 'Co-founder & CEO',
    bullets: [
      'Background in AI product at scale — led orgs of 40+ across multiple teams',
      'Previously built meeting automation tools used by 50k+ engineers',
      'BS Computer Science, focus in distributed systems',
    ],
  },
  {
    name: 'Founder Name',
    role: 'Co-founder & CTO',
    bullets: [
      'Principal engineer background — infra, ML pipelines, real-time systems',
      'Built and scaled production LLM inference at a prior startup',
      'MS Machine Learning; prior research in NLP summarization',
    ],
  },
  {
    name: 'Founder Name',
    role: 'Co-founder & Head of Product',
    bullets: [
      '10 years product at developer-tool companies, B2B SaaS',
      'Led growth from $0 to $12M ARR at a previous company',
      'Obsessed with reducing cognitive overhead for technical teams',
    ],
  },
]

export default function TeamSection() {
  const [visible, setVisible] = useState(false)
  const [inView, setInView] = useState(false)
  const [cardsVisible, setCardsVisible] = useState([false, false, false])
  const sectionRef = useRef(null)
  const cardRefs = useRef([null, null, null])

  useEffect(() => {
    const obs = new IntersectionObserver(
      ([entry]) => {
        const r = entry.intersectionRatio
        if (r > 0.05) setVisible(true)
        setInView(r > 0.05)
      },
      { threshold: [0, 0.05, 0.15] }
    )
    if (sectionRef.current) obs.observe(sectionRef.current)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    const observers = cardRefs.current.map((el, i) => {
      if (!el) return null
      const obs = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            setCardsVisible(prev => {
              const next = [...prev]
              next[i] = true
              return next
            })
          }
        },
        { threshold: 0.18 }
      )
      obs.observe(el)
      return obs
    })
    return () => observers.forEach(o => o?.disconnect())
  }, [])

  return (
    <section ref={sectionRef} id="people" className="team-section scroll-section" style={{ position: 'relative' }}>
      <div className={`section-blur-overlay${inView ? '' : ' active'}`} aria-hidden="true" />
      <div className="section-inner">
        <p className="section-eyebrow">The team</p>
        <h2 className={`team-heading${visible ? ' heading-visible' : ''}`}>
          Built by engineers, for engineers
        </h2>

        <div className="team-stack">
          {FOUNDERS.map((founder, i) => {
            const reversed = i % 2 === 1
            return (
              <div
                key={i}
                ref={el => (cardRefs.current[i] = el)}
                className={`team-card${reversed ? ' team-card-reversed' : ''}${cardsVisible[i] ? ' team-card-visible' : ''}`}
              >
                <div className="team-card-text">
                  <p className="team-card-name">{founder.name}</p>
                  <p className="team-card-role">{founder.role}</p>
                  <ul className="team-bullets">
                    {founder.bullets.map((b, bi) => (
                      <li key={bi} className="team-bullet">
                        <span className="team-bullet-pip" aria-hidden="true" />
                        <span>{b}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="team-card-photo" aria-hidden="true">
                  <div className="team-photo-bg" />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

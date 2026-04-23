import { useState, useEffect } from 'react'
import LogoIcon from './LogoIcon'

const NAV_LINKS = [
  { label: 'prism',   id: 'prism' },
  { label: 'product', id: 'product' },
  { label: 'pricing', id: 'pricing' },
  { label: 'people',  id: 'people' },
]

function scrollTo(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth' })
}

export default function LandingNav({ onSignup }) {
  const [active, setActive] = useState('prism')

  useEffect(() => {
    const container = document.querySelector('.landing-page')
    if (!container) return

    function update() {
      const containerTop = container.getBoundingClientRect().top
      let closest = 'prism'
      let minDist = Infinity
      NAV_LINKS.forEach(({ id }) => {
        const el = document.getElementById(id)
        if (!el) return
        const dist = Math.abs(el.getBoundingClientRect().top - containerTop)
        if (dist < minDist) { minDist = dist; closest = id }
      })
      setActive(closest)
    }

    container.addEventListener('scroll', update, { passive: true })
    update()
    return () => container.removeEventListener('scroll', update)
  }, [])

  return (
    <div
      className="animate-fade-in-up"
      style={{
        position: 'absolute',
        top: '24px',
        left: '15%',
        right: '15%',
        zIndex: 10,
        pointerEvents: 'none',
      }}
    >
      <div className="landing-nav-bar" style={{ pointerEvents: 'auto' }}>

        {/* Logo */}
        <button
          onClick={() => scrollTo('prism')}
          className="logo-btn"
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'none', border: 0, cursor: 'pointer',
            padding: '4px 0',
            justifySelf: 'start',
          }}
          aria-label="Back to top"
        >
          <LogoIcon className="w-9 h-9" />
          <span
            className="prism-logo-text text-xl font-light tracking-wider"
            data-text="_prism"
            style={{ lineHeight: 1 }}
          >
            _prism
          </span>
        </button>

        {/* Nav links */}
        <nav aria-label="Main navigation" style={{ display: 'flex', gap: '2px' }}>
          {NAV_LINKS.map(({ label, id }) => (
            <button
              key={id}
              onClick={() => scrollTo(id)}
              className={`nav-pill-item${active === id ? ' nav-pill-item--active' : ''}`}
            >
              {label}
            </button>
          ))}
        </nav>

        {/* Auth */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <button className="nav-auth-login" onClick={onSignup}>Log in</button>
          <button className="nav-auth-signin" onClick={onSignup}>Sign up</button>
        </div>

      </div>
    </div>
  )
}

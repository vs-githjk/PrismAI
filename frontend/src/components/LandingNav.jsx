import { useEffect, useRef, useState } from 'react'
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

export default function LandingNav({ onSignup, onLogin }) {
  const [active, setActive] = useState('prism')
  const [indicatorStyle, setIndicatorStyle] = useState({ width: 0, x: 0, ready: false })
  const navRef = useRef(null)
  const itemRefs = useRef({})

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

  useEffect(() => {
    function updateIndicator() {
      const nav = navRef.current
      const activeItem = itemRefs.current[active]
      if (!nav || !activeItem) return

      const navBox = nav.getBoundingClientRect()
      const itemBox = activeItem.getBoundingClientRect()
      const x = itemBox.left - navBox.left + nav.scrollLeft

      setIndicatorStyle({
        width: itemBox.width,
        x,
        ready: true,
      })
    }

    updateIndicator()

    const nav = navRef.current
    if (!nav) return

    const resizeObserver = new ResizeObserver(updateIndicator)
    resizeObserver.observe(nav)
    Object.values(itemRefs.current).forEach(item => item && resizeObserver.observe(item))
    nav.addEventListener('scroll', updateIndicator, { passive: true })
    window.addEventListener('resize', updateIndicator)

    return () => {
      resizeObserver.disconnect()
      nav.removeEventListener('scroll', updateIndicator)
      window.removeEventListener('resize', updateIndicator)
    }
  }, [active])

  return (
    <div
      className="landing-nav-frame animate-fade-in-up"
    >
      <div className="landing-nav-bar" style={{ pointerEvents: 'auto' }}>

        {/* Logo */}
        <button
          onClick={() => scrollTo('prism')}
          className="logo-btn landing-nav-logo"
          type="button"
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            background: 'none', border: 0, cursor: 'pointer',
            padding: '4px 0',
          }}
          aria-label="Back to top"
        >
          <LogoIcon className="w-9 h-9" />
          <span
            className="prism-logo-text text-xl font-light tracking-wider"
            data-text="prism"
            style={{ lineHeight: 1 }}
          >
            prism
          </span>
        </button>

        {/* Nav links */}
        <nav
          ref={navRef}
          className="landing-nav-links"
          aria-label="Main navigation"
          style={{ display: 'flex', gap: '2px' }}
        >
          <span
            className={`nav-pill-indicator${indicatorStyle.ready ? ' nav-pill-indicator--ready' : ''}`}
            aria-hidden="true"
            style={{
              width: `${indicatorStyle.width}px`,
              transform: `translateX(${indicatorStyle.x}px)`,
            }}
          />
          {NAV_LINKS.map(({ label, id }) => (
            <button
              key={id}
              ref={el => {
                if (el) itemRefs.current[id] = el
              }}
              onClick={() => scrollTo(id)}
              type="button"
              className={`nav-pill-item${active === id ? ' nav-pill-item--active' : ''}`}
            >
              {label}
            </button>
          ))}
        </nav>

        {/* Auth */}
        <div className="landing-nav-auth">
          <button type="button" className="nav-auth-login" onClick={onLogin || onSignup}>Log in</button>
          <button type="button" className="nav-auth-signin dashboard-signin-button landing-button-primary" onClick={onSignup}>Sign up</button>
        </div>

      </div>
    </div>
  )
}

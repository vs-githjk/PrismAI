import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const navItems = [
  { label: 'Prism',   id: 'prism'   },
  { label: 'Product', id: 'product' },
  { label: 'Pricing', id: 'pricing' },
  { label: 'People',  id: 'people'  },
]

export function PillNav({ onTabChange }) {
  const [activeSection, setActiveSection] = useState('prism')
  const [expanded, setExpanded] = useState(false)
  const [hovering, setHovering] = useState(false)
  const collapseTimer = useRef(null)

  useEffect(() => {
    if (hovering) {
      if (collapseTimer.current) clearTimeout(collapseTimer.current)
      setExpanded(true)
    } else {
      collapseTimer.current = setTimeout(() => setExpanded(false), 500)
    }
    return () => { if (collapseTimer.current) clearTimeout(collapseTimer.current) }
  }, [hovering])

  const handleSectionClick = (id) => {
    setActiveSection(id)
    setHovering(false)
    onTabChange?.(id)
  }

  const activeItem = navItems.find(item => item.id === activeSection)

  return (
    <div
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      style={{
        position: 'relative',
        height: '52px',
        width: expanded ? '500px' : '140px',
        transition: 'width 0.42s cubic-bezier(0.34, 1.2, 0.64, 1)',
        willChange: 'width',
        borderRadius: '999px',
        overflow: 'hidden',
        background: 'linear-gradient(135deg,#fcfcfd 0%,#f3f4f6 40%,#e9eaed 70%,#e2e3e6 100%)',
        boxShadow: expanded
          ? '0 2px 4px rgba(0,0,0,.08),0 8px 20px rgba(0,0,0,.13),0 20px 40px rgba(0,0,0,.10),inset 0 2px 2px rgba(255,255,255,.8),inset 0 -2px 6px rgba(0,0,0,.11),inset 2px 0 6px rgba(0,0,0,.07),inset -2px 0 6px rgba(0,0,0,.07)'
          : '0 2px 6px rgba(0,0,0,.10),0 8px 18px rgba(0,0,0,.09),0 14px 28px rgba(0,0,0,.07),inset 0 2px 1px rgba(255,255,255,.70),inset 0 -2px 5px rgba(0,0,0,.09),inset 2px 0 5px rgba(0,0,0,.06),inset -2px 0 5px rgba(0,0,0,.06)',
      }}
    >
      {/* Top ridge highlight */}
      <div style={{
        position: 'absolute', inset: '0', top: 0, left: 0, right: 0,
        height: '2px', borderRadius: '999px 999px 0 0', pointerEvents: 'none',
        background: 'linear-gradient(90deg,rgba(255,255,255,0) 0%,rgba(255,255,255,.95) 15%,rgba(255,255,255,1) 50%,rgba(255,255,255,.95) 85%,rgba(255,255,255,0) 100%)',
      }} />

      {/* Top hemisphere light */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: '55%',
        pointerEvents: 'none',
        background: 'linear-gradient(180deg,rgba(255,255,255,.42) 0%,rgba(255,255,255,.18) 50%,rgba(255,255,255,0) 100%)',
      }} />

      {/* Directional light (top-left) */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: 'linear-gradient(135deg,rgba(255,255,255,.35) 0%,rgba(255,255,255,.12) 35%,rgba(255,255,255,0) 60%)',
      }} />

      {/* Bottom curvature shadow */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: '45%',
        pointerEvents: 'none',
        background: 'linear-gradient(0deg,rgba(0,0,0,.13) 0%,rgba(0,0,0,.06) 40%,rgba(0,0,0,0) 100%)',
      }} />

      {/* Micro edge */}
      <div style={{
        position: 'absolute', inset: 0, borderRadius: '999px', pointerEvents: 'none',
        boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,.10)',
      }} />

      {/* Content */}
      <div style={{
        position: 'relative', zIndex: 10, height: '100%',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'Inter,-apple-system,BlinkMacSystemFont,"SF Pro",sans-serif',
      }}>
        {/* Collapsed: single active label */}
        {!expanded && (
          <AnimatePresence mode="wait">
            {activeItem && (
              <motion.span
                key={activeItem.id}
                initial={{ opacity: 0, y: 6, filter: 'blur(3px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, y: -6, filter: 'blur(3px)' }}
                transition={{ duration: 0.28, ease: [0.4, 0, 0.2, 1] }}
                style={{
                  fontSize: '15px', fontWeight: 660, color: '#1a1a1a',
                  letterSpacing: '0.4px', whiteSpace: 'nowrap',
                  WebkitFontSmoothing: 'antialiased',
                  textShadow: '0 1px 0 rgba(0,0,0,.3),0 -1px 0 rgba(255,255,255,.75)',
                  userSelect: 'none',
                }}
              >
                {activeItem.label}
              </motion.span>
            )}
          </AnimatePresence>
        )}

        {/* Expanded: all items */}
        {expanded && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-evenly', width: '100%' }}>
            {navItems.map((item, i) => {
              const isActive = item.id === activeSection
              return (
                <motion.button
                  key={item.id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.055, duration: 0.18, ease: 'easeOut' }}
                  onClick={() => handleSectionClick(item.id)}
                  style={{
                    fontSize: '14.5px',
                    fontWeight: isActive ? 660 : 480,
                    color: isActive ? '#1a1a1a' : '#606060',
                    letterSpacing: '0.4px',
                    background: 'none', border: 'none', outline: 'none',
                    padding: '10px 12px', cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    WebkitFontSmoothing: 'antialiased',
                    transform: isActive ? 'translateY(-1px)' : 'none',
                    transition: 'color 0.15s,transform 0.15s',
                    textShadow: isActive
                      ? '0 1px 0 rgba(0,0,0,.3),0 -1px 0 rgba(255,255,255,.75)'
                      : '0 1px 0 rgba(0,0,0,.18),0 -1px 0 rgba(255,255,255,.60)',
                    userSelect: 'none',
                  }}
                  onMouseEnter={e => { if (!isActive) { e.currentTarget.style.color = '#333'; e.currentTarget.style.transform = 'translateY(-0.5px)' } }}
                  onMouseLeave={e => { if (!isActive) { e.currentTarget.style.color = '#606060'; e.currentTarget.style.transform = 'none' } }}
                >
                  {item.label}
                </motion.button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

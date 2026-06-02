import { useEffect, useRef } from 'react'
import Prism from './components/Prism'

// Deterministic full-viewport Prism, driven by an external clock.
// Loaded only when window.location.hash === '#prism-capture'.
// Exposes:
//   window.__prismReady  — true once the canvas + program are mounted
//   window.__prismRenderAt(timeSec) — render one frame at iTime = timeSec
export default function PrismCapture() {
  const handle = useRef(null)

  useEffect(() => {
    const tick = () => {
      if (handle.current && handle.current.renderAt) {
        window.__prismRenderAt = (t) => handle.current.renderAt(t)
        window.__prismReady = true
        // Render one frame so a human visiting this URL sees the prism
        // instead of an empty canvas. The capture script overrides this
        // immediately via its own clock.
        handle.current.renderAt(0)
      } else {
        requestAnimationFrame(tick)
      }
    }
    tick()
    return () => {
      delete window.__prismRenderAt
      delete window.__prismReady
    }
  }, [])

  return (
    <div style={{ position: 'fixed', inset: 0, background: '#000', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -48%)', width: 'max(1080px, 100vw)', height: 'max(1080px, 100vh)' }}>
        <Prism
          height={2}
          baseWidth={3}
          animationType="rotate3d"
          glow={1.1}
          noise={0.1}
          transparent
          scale={2.9}
          hueShift={5.6}
          colorFrequency={1}
          hoverStrength={0}
          inertia={0.04}
          bloom={0.9}
          timeScale={0.3}
          captureHandle={handle}
        />
      </div>
    </div>
  )
}

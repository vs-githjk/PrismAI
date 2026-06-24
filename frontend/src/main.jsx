import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import PrismCapture from './PrismCapture.jsx'
import './index.css'

// Deploy-skew guard: when a new build ships, hashed chunk filenames change and a
// tab opened before the deploy will 404 on a lazily-imported chunk (Vercel serves
// index.html → "Failed to fetch dynamically imported module" → blank screen). Vite
// fires `vite:preloadError` for exactly this; reload once to pick up the fresh
// index.html. A sessionStorage flag prevents an infinite reload loop if the failure
// is something other than stale chunks.
if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', (e) => {
    // Reload at most once per 10s. A stale-chunk skew clears on the first reload
    // (fresh index.html); the cooldown means a genuinely broken deploy can't tight-loop,
    // while deploys spaced apart in a long-lived tab still self-heal.
    const last = Number(sessionStorage.getItem('prism_chunk_reload_ts')) || 0
    if (Date.now() - last > 10000) {
      e.preventDefault()
      sessionStorage.setItem('prism_chunk_reload_ts', String(Date.now()))
      window.location.reload()
    }
  })
}

const isCapture = typeof window !== 'undefined' && window.location.hash === '#prism-capture'

ReactDOM.createRoot(document.getElementById('root')).render(
  isCapture ? (
    <PrismCapture />
  ) : (
    <React.StrictMode>
      <App />
    </React.StrictMode>
  ),
)

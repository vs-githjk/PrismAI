import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import PrismCapture from './PrismCapture.jsx'
import './index.css'

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

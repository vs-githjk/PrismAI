import LogoIcon from './LogoIcon'

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 0 0 2.38-5.88c0-.57-.05-.66-.15-1.18Z"/>
      <path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2.01c-.72.48-1.63.76-2.7.76-2.08 0-3.84-1.4-4.47-3.29H1.84v2.07A8 8 0 0 0 8.98 17Z"/>
      <path fill="#FBBC05" d="M4.51 10.52A4.8 4.8 0 0 1 4.26 9c0-.53.09-1.04.25-1.52V5.41H1.84A8 8 0 0 0 .98 9c0 1.29.31 2.51.86 3.59l2.67-2.07Z"/>
      <path fill="#EA4335" d="M8.98 4.18c1.17 0 2.23.4 3.06 1.2l2.3-2.3C12.95 1.79 11.14 1 8.98 1a8 8 0 0 0-7.14 4.41l2.67 2.07c.63-1.89 2.39-3.3 4.47-3.3Z"/>
    </svg>
  )
}

export default function SignupDialog({ onClose, onGoogle, onTestAccount }) {
  const handleGoogle = () => {
    onGoogle?.()
    onClose()
  }

  const handleTest = () => {
    onTestAccount?.()
    onClose()
  }

  return (
    <div className="signup-overlay" onClick={onClose}>
      <div
        className="signup-dialog"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-dialog-title"
      >
        <button type="button" className="signup-close" onClick={onClose} aria-label="Close dialog">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="14" y1="2" x2="2" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>

        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '1.25rem' }}>
          <LogoIcon style={{ width: 40, height: 40 }} />
        </div>

        <p className="signup-kicker">Meeting intelligence</p>
        <h2 id="auth-dialog-title" className="signup-title">Sign in to Prism</h2>
        <p className="signup-body">
          Analyze transcripts, track action items, and surface insights across every meeting.
        </p>

        <button
          type="button"
          onClick={handleGoogle}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.625rem',
            width: '100%',
            padding: '0.75rem 1.25rem',
            borderRadius: '0.75rem',
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.14)',
            color: 'rgba(255,255,255,0.9)',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 0.15s, border-color 0.15s',
            marginTop: '0.25rem',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.10)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.24)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.14)' }}
        >
          <GoogleIcon />
          Continue with Google
        </button>

        {onTestAccount && (
          <button
            type="button"
            onClick={handleTest}
            style={{
              marginTop: '0.75rem',
              width: '100%',
              padding: '0.5rem',
              background: 'none',
              border: 'none',
              color: 'rgba(255,255,255,0.32)',
              fontSize: '0.75rem',
              cursor: 'pointer',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.32)' }}
          >
            Continue as test account
          </button>
        )}
      </div>
    </div>
  )
}

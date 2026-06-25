import { useState } from 'react'
import { X } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { UI_SCREEN_KEY, VISITED_KEY, TEST_RUN_SESSION_KEY } from '../lib/sessionKeys'

const DASHBOARD_PATH = '/dashboard'

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.58c2.1-1.94 3.27-4.79 3.27-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.58-2.77c-.98.66-2.23 1.06-3.7 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  )
}

function MicrosoftIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#F25022" d="M11.4 11.4H2V2h9.4z" />
      <path fill="#7FBA00" d="M22 11.4h-9.4V2H22z" />
      <path fill="#00A4EF" d="M11.4 22H2v-9.4h9.4z" />
      <path fill="#FFB900" d="M22 22h-9.4v-9.4H22z" />
    </svg>
  )
}

// SSO-only sign-in: Google + Microsoft. Email/password + username were dropped — SSO
// handles both signup and login, so there's no separate mode toggle anymore.
export default function SignupDialog({ onClose }) {
  const [submitError, setSubmitError] = useState('')
  const [loading, setLoading] = useState(false)
  const dashboardUrl = typeof window !== 'undefined' ? `${window.location.origin}${DASHBOARD_PATH}` : DASHBOARD_PATH

  const signInWith = async (provider, options = {}) => {
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    setLoading(true)
    const { error } = await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo: dashboardUrl, ...options },
    })
    if (error) {
      setSubmitError(error.message)
      setLoading(false)
    }
  }

  return (
    <div className="signup-overlay" onMouseDown={onClose}>
      <div
        className="signup-dialog signup-auth-card"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-dialog-title"
      >
        <button type="button" className="signup-close" onClick={onClose} aria-label="Close dialog">
          <X aria-hidden="true" />
        </button>

        <p className="signup-kicker">PrismAI account</p>
        <h2 id="auth-dialog-title" className="signup-title">Sign in to PrismAI.</h2>
        <p className="signup-body">
          Continue with your Google or Microsoft account. Your meeting history and dashboard open right after.
        </p>

        <div className="signup-social-row">
          <button type="button" className="signup-provider-button" onClick={() => signInWith('google')} disabled={loading}>
            <GoogleIcon />
            Google
          </button>
          <button type="button" className="signup-provider-button" onClick={() => signInWith('azure', { scopes: 'email' })} disabled={loading}>
            <MicrosoftIcon />
            Microsoft
          </button>
        </div>

        {submitError && <p className="signup-submit-error" role="alert">{submitError}</p>}

        <p className="signup-mode-note">
          No password needed — single sign-on keeps your account secure.
        </p>
      </div>
    </div>
  )
}

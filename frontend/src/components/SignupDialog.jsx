import { useEffect, useState } from 'react'
import { Loader2, MailCheck, X } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { apiFetch } from '../lib/api'
import { UI_SCREEN_KEY, VISITED_KEY, TEST_RUN_SESSION_KEY } from '../lib/sessionKeys'

const DASHBOARD_PATH = '/dashboard'
const PROVIDER_LABELS = { google: 'Google', azure: 'Microsoft' }

// Asks the backend whether this email belongs to an OAuth-only account (one
// that can never password-login). Best-effort: any failure returns null and
// the caller falls back to a generic message.
async function oauthProviderMessage(email) {
  try {
    const resp = await apiFetch('/auth/provider-hint', {
      method: 'POST',
      skipAuth: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    if (!resp.ok) return null
    const { providers } = await resp.json()
    const labels = (providers || []).map((p) => PROVIDER_LABELS[p] || p)
    if (!labels.length) return null
    const name = labels.join(' / ')
    return `This account uses ${name} — sign in with the ${name} button above.`
  } catch {
    return null
  }
}

function useEscapeToClose(onClose) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
}

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

function AuthField({ id, label, ...props }) {
  return (
    <div className="signup-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="signup-input" {...props} />
    </div>
  )
}

export default function SignupDialog({ mode = 'signup', onModeChange, onClose }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [loading, setLoading] = useState(false)
  const [verificationSent, setVerificationSent] = useState(false)
  const [resetSent, setResetSent] = useState(false)
  const isSignup = mode === 'signup'
  const dashboardUrl = typeof window !== 'undefined'
    ? `${window.location.origin}${DASHBOARD_PATH}`
    : DASHBOARD_PATH

  useEscapeToClose(onClose)

  const signInWith = async (provider, options = {}) => {
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }
    // Session keys are set by App.jsx's SIGNED_IN handler after the OAuth
    // return — writing them here would mark a canceled OAuth attempt as visited.
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

  const goToDashboard = () => {
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    window.location.assign(DASHBOARD_PATH)
  }

  const switchMode = (nextMode) => {
    setPassword('')
    setSubmitError('')
    setVerificationSent(false)
    setResetSent(false)
    onModeChange?.(nextMode)
  }

  const handleForgotPassword = async () => {
    const address = email.trim()
    if (!address) {
      setSubmitError('Enter your email above first, then tap "Forgot password?".')
      return
    }
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }
    setSubmitError('')
    setLoading(true)
    const { error } = await supabase.auth.resetPasswordForEmail(address, { redirectTo: dashboardUrl })
    setLoading(false)
    if (error) setSubmitError(error.message)
    else setResetSent(true)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }

    setLoading(true)
    try {
      if (isSignup) {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { emailRedirectTo: dashboardUrl },
        })
        if (error) throw error
        // Supabase's enumeration protection returns a user with no identities
        // (and no error) when the email is already registered.
        if (data.user && !data.session && data.user.identities?.length === 0) {
          setSubmitError(
            (await oauthProviderMessage(email.trim()))
              || 'An account with this email already exists. Log in instead.'
          )
        } else if (data.session) goToDashboard()
        else setVerificationSent(true)
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        })
        if (error) throw error
        goToDashboard()
      }
    } catch (error) {
      let message = error.message || 'Something went wrong. Try again.'
      // Both errors can mean "this email is a Google/Microsoft account with
      // no password" — check before showing a dead-end message.
      if (/already registered|invalid login credentials/i.test(message)) {
        const hint = await oauthProviderMessage(email.trim())
        if (hint) message = hint
        else if (/already registered/i.test(message)) {
          message = 'An account with this email already exists. Log in instead.'
        }
      }
      setSubmitError(message)
    } finally {
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

        {verificationSent || resetSent ? (
          <div className="signup-verification">
            <div className="signup-verification-icon" aria-hidden="true"><MailCheck /></div>
            <p className="signup-kicker">{resetSent ? 'Reset your password' : 'Verify your email'}</p>
            <h2 id="auth-dialog-title" className="signup-title">Check your inbox.</h2>
            <p className="signup-body">
              {resetSent ? (
                <>We sent a password reset link to <strong>{email.trim()}</strong>. Open it to set a new password.</>
              ) : (
                <>We sent a verification link to <strong>{email.trim()}</strong>. After you confirm, you will be sent to the dashboard.</>
              )}
            </p>
            <button type="button" className="signup-submit" onClick={onClose}>Done</button>
          </div>
        ) : (
          <>
            <p className="signup-kicker">PrismAI account</p>
            <h2 id="auth-dialog-title" className="signup-title">
              {isSignup ? 'Create your account.' : 'Welcome back.'}
            </h2>
            <p className="signup-body">
              {isSignup
                ? 'Save meeting history and open your dashboard after signup.'
                : 'Log in to continue to your dashboard.'}
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

            <div className="signup-divider"><span>or</span></div>

            <form className="signup-form" onSubmit={handleSubmit}>
              <AuthField
                id="auth-email"
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value)
                  setSubmitError('')
                }}
              />
              <AuthField
                id="auth-password"
                label="Password"
                type="password"
                autoComplete={isSignup ? 'new-password' : 'current-password'}
                required
                minLength={isSignup ? 6 : undefined}
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                  setSubmitError('')
                }}
              />

              {!isSignup && (
                <button type="button" className="signup-forgot" onClick={handleForgotPassword} disabled={loading}>
                  Forgot password?
                </button>
              )}

              {submitError && <p className="signup-submit-error" role="alert">{submitError}</p>}

              <button type="submit" className="signup-submit" disabled={loading}>
                {loading && <Loader2 className="signup-spinner" aria-hidden="true" />}
                {isSignup ? 'Sign up' : 'Log in'}
              </button>
            </form>

            <p className="signup-mode-note">
              {isSignup ? 'Already have an account?' : 'New to PrismAI?'}
              <button type="button" onClick={() => switchMode(isSignup ? 'login' : 'signup')}>
                {isSignup ? 'Log in' : 'Sign up'}
              </button>
            </p>

            <p className="signup-consent">
              By continuing, you agree to our{' '}
              <a href="#terms" onClick={onClose}>Terms of Service</a> and{' '}
              <a href="#privacy" onClick={onClose}>Privacy Policy</a>.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

// Shown when the user arrives from a password-recovery email link
// (supabase-js emits PASSWORD_RECOVERY after processing the URL hash).
export function ResetPasswordDialog({ onClose }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  useEscapeToClose(onClose)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    const { error: updateError } = await supabase.auth.updateUser({ password })
    setLoading(false)
    if (updateError) setError(updateError.message)
    else setDone(true)
  }

  return (
    <div className="signup-overlay" onMouseDown={onClose}>
      <div
        className="signup-dialog signup-auth-card"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="reset-dialog-title"
      >
        <button type="button" className="signup-close" onClick={onClose} aria-label="Close dialog">
          <X aria-hidden="true" />
        </button>
        <p className="signup-kicker">PrismAI account</p>
        <h2 id="reset-dialog-title" className="signup-title">
          {done ? 'Password updated.' : 'Set a new password.'}
        </h2>
        {done ? (
          <>
            <p className="signup-body">Use it the next time you log in.</p>
            <button type="button" className="signup-submit" onClick={onClose}>Done</button>
          </>
        ) : (
          <form className="signup-form" onSubmit={handleSubmit}>
            <AuthField
              id="reset-password"
              label="New password"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value)
                setError('')
              }}
            />
            {error && <p className="signup-submit-error" role="alert">{error}</p>}
            <button type="submit" className="signup-submit" disabled={loading}>
              {loading && <Loader2 className="signup-spinner" aria-hidden="true" />}
              Save password
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

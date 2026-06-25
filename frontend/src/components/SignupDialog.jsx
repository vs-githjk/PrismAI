import { useState } from 'react'
import { Loader2, MailCheck, X } from 'lucide-react'
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

function AuthField({ id, label, error, ...props }) {
  return (
    <div className="signup-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className={error ? 'signup-input signup-input-error' : 'signup-input'}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        {...props}
      />
      {error && <p id={`${id}-error`} className="signup-field-error" role="alert">{error}</p>}
    </div>
  )
}

export default function SignupDialog({ mode = 'signup', onModeChange, onClose }) {
  const [form, setForm] = useState({ username: '', email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [submitError, setSubmitError] = useState('')
  const [loading, setLoading] = useState(false)
  const [verificationSent, setVerificationSent] = useState(false)
  const isSignup = mode === 'signup'
  const dashboardUrl = typeof window !== 'undefined' ? `${window.location.origin}${DASHBOARD_PATH}` : DASHBOARD_PATH

  const setField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setErrors((prev) => ({ ...prev, [field]: '' }))
    setSubmitError('')
  }

  const switchMode = (nextMode) => {
    setErrors({})
    setSubmitError('')
    setVerificationSent(false)
    onModeChange?.(nextMode)
  }

  const validate = () => {
    const nextErrors = {}
    const email = form.email.trim()
    if (isSignup && !form.username.trim()) nextErrors.username = 'Choose a username.'
    if (!email) nextErrors.email = 'Enter your email.'
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) nextErrors.email = 'Enter a valid email.'
    if (!form.password) nextErrors.password = 'Enter your password.'
    else if (isSignup && form.password.length < 6) nextErrors.password = 'Use at least 6 characters.'
    setErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  const goToDashboard = () => {
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    window.location.assign(DASHBOARD_PATH)
  }

  const handleGoogle = async () => {
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    setLoading(true)
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: dashboardUrl,
      },
    })
    if (error) {
      setSubmitError(error.message)
      setLoading(false)
    }
  }

  const handleMicrosoft = async () => {
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    setLoading(true)
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'azure',
      options: {
        redirectTo: dashboardUrl,
        scopes: 'email',
      },
    })
    if (error) {
      setSubmitError(error.message)
      setLoading(false)
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSubmitError('')
    if (!validate()) return
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }

    setLoading(true)
    try {
      if (isSignup) {
        const { data, error } = await supabase.auth.signUp({
          email: form.email.trim(),
          password: form.password,
          options: {
            data: { username: form.username.trim() },
            emailRedirectTo: dashboardUrl,
          },
        })
        if (error) throw error
        if (data.session) goToDashboard()
        else setVerificationSent(true)
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: form.email.trim(),
          password: form.password,
        })
        if (error) throw error
        goToDashboard()
      }
    } catch (error) {
      setSubmitError(error.message || 'Something went wrong. Try again.')
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

        {verificationSent ? (
          <div className="signup-verification">
            <div className="signup-verification-icon" aria-hidden="true">
              <MailCheck />
            </div>
            <p className="signup-kicker">Verify your email</p>
            <h2 id="signup-title" className="signup-title">Check your inbox.</h2>
            <p className="signup-body">
              We sent a verification link to <strong>{form.email.trim()}</strong>. After you confirm, you will be sent to the dashboard.
            </p>
            <button type="button" className="signup-submit" onClick={onClose}>Done</button>
          </div>
        ) : (
          <>
            <p className="signup-kicker">PrismAI account</p>
            <h2 id="signup-title" className="signup-title">{isSignup ? 'Create your account.' : 'Welcome back.'}</h2>
            <p className="signup-body">
              {isSignup ? 'Save meeting history and open your dashboard after signup.' : 'Log in to continue to your dashboard.'}
            </p>

            <div className="signup-social-row">
              <button type="button" className="signup-provider-button" onClick={handleGoogle} disabled={loading}>
                <GoogleIcon />
                Google
              </button>
              <button type="button" className="signup-provider-button" onClick={handleMicrosoft} disabled={loading}>
                <MicrosoftIcon />
                Microsoft
              </button>
            </div>

            <div className="signup-divider"><span>or</span></div>

            <form className="signup-form" onSubmit={handleSubmit} noValidate>
              {isSignup && (
                <AuthField
                  id="signup-username"
                  label="Username"
                  type="text"
                  autoComplete="username"
                  value={form.username}
                  onChange={(event) => setField('username', event.target.value)}
                  error={errors.username}
                />
              )}
              <AuthField
                id="signup-email"
                label="Email"
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={(event) => setField('email', event.target.value)}
                error={errors.email}
              />
              <AuthField
                id="signup-password"
                label="Password"
                type="password"
                autoComplete={isSignup ? 'new-password' : 'current-password'}
                value={form.password}
                onChange={(event) => setField('password', event.target.value)}
                error={errors.password}
              />

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
          </>
        )}
      </div>
    </div>
  )
}

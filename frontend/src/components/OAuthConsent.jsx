import { useEffect, useState } from 'react'
import { ShieldCheck, Check } from 'lucide-react'
import { supabase } from '../lib/supabase'
import { apiFetch } from '../lib/api'
import LogoIcon from './LogoIcon'

// OAuth consent screen for the MCP connector (Claude / ChatGPT). Reached when our
// authorization server (backend /oauth/authorize) redirects the browser here with
// the (non-secret) PKCE request params. The user signs in with Supabase, then
// Allow/Deny. On Allow we ask the backend to mint an auth code and bounce back to
// the OAuth client's callback.

const STASH_KEY = 'prism_oauth_consent'

const SCOPE_COPY = {
  'meetings:read': [
    'Read your open action items across meetings',
    'Read meeting summaries and decisions',
    'Search across your meetings and knowledge base',
  ],
}

function parseParams() {
  // Params live after the '?' in the hash route: #oauth-consent?client_id=...
  const hash = window.location.hash || ''
  const qs = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : ''
  const p = new URLSearchParams(qs)
  const obj = {}
  for (const k of ['client_id', 'client_name', 'redirect_uri', 'code_challenge', 'scope', 'state']) {
    const v = p.get(k)
    if (v) obj[k] = v
  }
  if (obj.client_id && obj.redirect_uri && obj.code_challenge) return obj
  // Restore across a sign-in redirect.
  try {
    const stashed = JSON.parse(sessionStorage.getItem(STASH_KEY) || 'null')
    if (stashed?.client_id) return stashed
  } catch { /* noop */ }
  return null
}

export default function OAuthConsent() {
  const [params] = useState(parseParams)
  const [session, setSession] = useState(undefined) // undefined = loading
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!supabase) { setSession(null); return }
    supabase.auth.getSession().then(({ data }) => setSession(data.session || null))
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s || null))
    return () => data.subscription.unsubscribe()
  }, [])

  const clientName = params?.client_name || 'An application'
  const scopeLines = SCOPE_COPY[params?.scope] || SCOPE_COPY['meetings:read']

  const denyUrl = () => {
    const u = new URLSearchParams({ error: 'access_denied' })
    if (params?.state) u.set('state', params.state)
    return `${params.redirect_uri}?${u.toString()}`
  }

  const signIn = (provider) => {
    // Preserve the request across the OAuth round-trip.
    try { sessionStorage.setItem(STASH_KEY, JSON.stringify(params)) } catch { /* noop */ }
    const redirectTo = `${window.location.origin}/#oauth-consent`
    const options = provider === 'azure' ? { scopes: 'email', redirectTo } : { redirectTo }
    supabase.auth.signInWithOAuth({ provider, options })
  }

  const allow = async () => {
    setSubmitting(true); setError('')
    try {
      const res = await apiFetch('/oauth/authorize/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_id: params.client_id,
          redirect_uri: params.redirect_uri,
          code_challenge: params.code_challenge,
          scope: params.scope,
          state: params.state,
        }),
      })
      if (!res.ok) throw new Error('approve failed')
      const data = await res.json()
      sessionStorage.removeItem(STASH_KEY)
      window.location.href = data.redirect_to
    } catch {
      setError('Could not complete the connection. Please try again.')
      setSubmitting(false)
    }
  }

  const shell = (children) => (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: '#07040f' }}>
      <div className="w-full max-w-md rounded-2xl p-7"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
        <div className="flex items-center gap-2.5 mb-5">
          <LogoIcon className="w-7 h-7" />
          <span className="text-sm font-bold gradient-text">PrismAI</span>
        </div>
        {children}
      </div>
    </div>
  )

  if (!params) {
    return shell(
      <p className="text-sm text-white/60">
        This connection link is invalid or has expired. Start again from your assistant’s connector settings.
      </p>
    )
  }

  if (session === undefined) {
    return shell(<p className="text-sm text-white/50">Loading…</p>)
  }

  if (!session) {
    return shell(
      <>
        <h1 className="text-lg font-semibold text-white mb-1.5">Sign in to connect</h1>
        <p className="text-[13px] text-white/55 mb-5">
          <span className="text-white/80">{clientName}</span> wants to connect to your PrismAI account.
          Sign in to review and approve.
        </p>
        <div className="flex flex-col gap-2">
          <button onClick={() => signIn('google')}
            className="w-full py-2.5 rounded-lg text-sm font-semibold text-white transition hover:scale-[1.01]"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
            Continue with Google
          </button>
          <button onClick={() => signIn('azure')}
            className="w-full py-2.5 rounded-lg text-sm font-medium text-white/80 transition"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
            Continue with Microsoft
          </button>
        </div>
      </>
    )
  }

  return shell(
    <>
      <div className="flex items-center gap-2 mb-1.5">
        <ShieldCheck size={18} className="text-cyan-400" />
        <h1 className="text-lg font-semibold text-white">Authorize access</h1>
      </div>
      <p className="text-[13px] text-white/60 mb-4">
        <span className="text-white/85 font-medium">{clientName}</span> is requesting access to your
        PrismAI account{session.user?.email ? ` (${session.user.email})` : ''}.
      </p>

      <div className="rounded-xl p-3.5 mb-5" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <p className="text-[11px] uppercase tracking-wide text-white/40 mb-2">It will be able to</p>
        <ul className="space-y-1.5">
          {scopeLines.map((line, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px] text-white/75">
              <Check size={14} className="text-cyan-400 mt-0.5 shrink-0" />
              {line}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-white/35 mt-2.5">Read-only. It cannot change or delete anything.</p>
      </div>

      {error && <p className="text-[12px] text-red-400 mb-3">{error}</p>}

      <div className="flex gap-2">
        <a href={denyUrl()}
          className="flex-1 text-center py-2.5 rounded-lg text-sm font-medium text-white/70 transition"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}>
          Deny
        </a>
        <button onClick={allow} disabled={submitting}
          className="flex-1 py-2.5 rounded-lg text-sm font-semibold text-white transition hover:scale-[1.01] disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
          {submitting ? 'Connecting…' : 'Allow'}
        </button>
      </div>
    </>
  )
}

import { useEffect, useState } from 'react'
import { Check, Copy, Plus, Trash2, KeyRound } from 'lucide-react'
import { apiFetch, API } from '../lib/api'

// "Connect to Claude / ChatGPT" — manages Personal Access Tokens for the MCP
// connector. Self-contained: talks straight to /account/tokens, not the modal's
// user_settings save flow. The connector is an account-level (personal) thing.

const MCP_URL = `${API}/mcp`

function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* noop */ }
      }}
      className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md font-medium transition"
      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: done ? '#67e8f9' : '#cbd5e1' }}
    >
      {done ? <Check size={12} /> : <Copy size={12} />}
      {done ? 'Copied' : label}
    </button>
  )
}

export default function AssistantConnect({ isSignedIn = false, isTestAccount = false }) {
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [freshToken, setFreshToken] = useState(null) // plaintext, shown once
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/account/tokens')
      const data = res.ok ? await res.json() : { tokens: [] }
      setTokens(data.tokens || [])
    } catch { setTokens([]) } finally { setLoading(false) }
  }

  useEffect(() => {
    if (isSignedIn && !isTestAccount) load()
    else setLoading(false)
  }, [isSignedIn, isTestAccount])

  const createToken = async () => {
    setCreating(true); setError(''); setFreshToken(null)
    try {
      const res = await apiFetch('/account/tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Claude / ChatGPT connector' }),
      })
      if (!res.ok) throw new Error('create failed')
      const data = await res.json()
      setFreshToken(data.token)
      await load()
    } catch { setError('Could not create a token. Try again.') } finally { setCreating(false) }
  }

  const revoke = async (id) => {
    try {
      const res = await apiFetch(`/account/tokens/${id}`, { method: 'DELETE' })
      if (res.ok) setTokens(t => t.filter(x => x.id !== id))
    } catch { /* noop */ }
  }

  if (!isSignedIn || isTestAccount) {
    return (
      <div className="rounded-xl p-3 text-[11px] leading-relaxed text-cyan-100/78"
        style={{ background: 'rgba(14,165,233,0.07)', border: '1px solid rgba(14,165,233,0.18)' }}>
        Sign in to a real account to connect PrismAI to Claude or ChatGPT.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl p-3 text-[11px] text-gray-400 leading-relaxed"
        style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
        Let Claude and ChatGPT pull your meeting outcomes on demand — open action items,
        decisions, and search across your meetings — right inside your assistant.
      </div>

      {/* MCP URL */}
      <div>
        <label className="text-[11px] font-medium text-gray-400">Connector URL</label>
        <div className="mt-1 flex items-center gap-2">
          <code className="flex-1 text-[11px] px-2.5 py-2 rounded-lg text-cyan-200 overflow-x-auto whitespace-nowrap"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            {MCP_URL}
          </code>
          <CopyButton text={MCP_URL} />
        </div>
      </div>

      {/* Token */}
      <div>
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-medium text-gray-400">Access token</label>
          <button
            type="button"
            onClick={createToken}
            disabled={creating}
            className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-lg font-semibold text-white transition disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}
          >
            <Plus size={12} />
            {creating ? 'Generating…' : 'Generate token'}
          </button>
        </div>

        {freshToken && (
          <div className="mt-2 rounded-lg p-3"
            style={{ background: 'rgba(34,211,238,0.06)', border: '1px solid rgba(34,211,238,0.25)' }}>
            <p className="text-[11px] text-amber-300/90 mb-1.5">
              Copy this now — it won’t be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-[11px] px-2 py-1.5 rounded-md text-white overflow-x-auto whitespace-nowrap"
                style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.08)' }}>
                {freshToken}
              </code>
              <CopyButton text={freshToken} />
            </div>
          </div>
        )}

        {error && <p className="mt-1.5 text-[11px] text-red-400">{error}</p>}

        {/* Existing tokens */}
        <div className="mt-2 space-y-1.5">
          {loading && <p className="text-[11px] text-gray-600">Loading…</p>}
          {!loading && tokens.length === 0 && !freshToken && (
            <p className="text-[11px] text-gray-600">No tokens yet. Generate one to connect.</p>
          )}
          {tokens.map(t => (
            <div key={t.id} className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg"
              style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <div className="flex items-center gap-2 min-w-0">
                <KeyRound size={13} className="text-gray-500 shrink-0" />
                <div className="min-w-0">
                  <p className="text-[11px] text-gray-300 truncate">{t.name}</p>
                  <p className="text-[10px] text-gray-600 font-mono truncate">
                    {t.prefix}…{t.last_used_at ? ' · used' : ' · never used'}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => revoke(t.id)}
                title="Revoke"
                className="text-gray-500 hover:text-red-400 transition p-1 shrink-0"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Setup */}
      <div className="rounded-xl p-3 text-[11px] text-gray-400 leading-relaxed space-y-2"
        style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
        <p className="text-gray-300 font-medium">How to connect</p>
        <p>
          <span className="text-gray-300">Claude:</span> Settings → Connectors → Add custom
          connector → paste the Connector URL. When asked for authentication, choose the
          token/header option and paste your access token.
        </p>
        <p>
          <span className="text-gray-300">ChatGPT:</span> Settings → Connectors → Add →
          paste the same Connector URL and token.
        </p>
        <p className="text-gray-600">
          Then ask your assistant: “What are my open action items?” or “Search my meetings for the pricing decision.”
        </p>
      </div>
    </div>
  )
}

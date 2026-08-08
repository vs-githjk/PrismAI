import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Globe, X, ExternalLink, Loader2, ShieldCheck } from 'lucide-react'
import { apiFetch } from '../../lib/api'

/**
 * AIWorkspaceSetup — "Set up my AI workspace" (Phase 4 of Bot Screen Presentation).
 *
 * The AI workspace is a private cloud browser Prism presents FROM in meetings
 * (a persistent Browserbase Context that holds the logins — ADR 0003, the E2B
 * desktop pivot). This modal gets-or-creates it (POST /sandbox/setup) and opens
 * the owner's interactive browser in a new tab so they can log into the sites they
 * want Prism to show (GitHub, Figma, …) — once; later meetings reuse it. It also
 * sets the privacy expectation: teammates see this screen when Prism presents.
 *
 * Portaled to <body> (the dashboard has transformed ancestors that break
 * position:fixed — same reason SuggestedActions / StandInComposer portal).
 */
export default function AIWorkspaceSetup({ onClose }) {
  const [status, setStatus] = useState(null) // { provisioned, running } | null
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [interactiveUrl, setInteractiveUrl] = useState(null)

  // Cheap provisioned/running probe — never creates. Best-effort; a failure just
  // leaves the hint blank.
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const res = await apiFetch('/sandbox/status')
        if (!res.ok) return
        const data = await res.json()
        if (alive) setStatus(data)
      } catch {
        /* non-fatal — hint stays hidden */
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const provisioned = status?.provisioned

  const setupWorkspace = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    // Pre-open the tab synchronously inside the click gesture so the popup
    // blocker doesn't eat it after the ~5s create. We navigate it once the URL
    // is back (or close it on failure).
    const pre = window.open('', '_blank')
    try {
      const res = await apiFetch('/sandbox/setup', { method: 'POST' })
      if (!res.ok) {
        let detail = ''
        try {
          detail = (await res.json())?.detail || ''
        } catch {
          /* ignore */
        }
        if (pre) pre.close()
        if (res.status === 503) {
          setError(
            detail ||
              'Your AI workspace isn’t available yet — the sandbox provider isn’t configured. Ask your admin to enable it.',
          )
        } else if (res.status === 502) {
          setError('The sandbox provider had a hiccup. Give it a moment and try again.')
        } else {
          setError(detail || 'Couldn’t set up your workspace. Please try again.')
        }
        return
      }
      const data = await res.json()
      const url = data?.interactive_url || null
      setInteractiveUrl(url)
      setStatus((s) => ({ provisioned: true, running: true, ...(s || {}) }))
      if (url && pre) {
        try {
          pre.opener = null
        } catch {
          /* some browsers disallow — harmless */
        }
        pre.location = url
      } else if (url) {
        // Popup was blocked — fall back to a same-tab-safe manual link (rendered below).
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    } catch {
      if (pre) pre.close()
      setError('Network error while setting up your workspace. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--db-scrim)] p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Set up my AI workspace"
        onClick={(e) => e.stopPropagation()}
        className="dashboard-body-font w-full max-w-md overflow-hidden rounded-2xl border border-[color:var(--db-border)] bg-[var(--db-popup-base)] shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-start gap-3 border-b border-[color:var(--db-border)] px-5 py-4">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-cyan-400/[0.12] text-cyan-300">
            <Globe className="h-[18px] w-[18px]" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold text-[color:var(--db-text)]">
              Set up my AI workspace
            </h2>
            <p className="mt-0.5 text-[12px] leading-5 text-[color:var(--db-text-faint)]">
              The private browser Prism presents from in meetings.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[color:var(--db-text-faint)] transition hover:bg-[var(--db-fill-strong)] hover:text-[color:var(--db-text-muted)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          {/* Status hint */}
          {status && (
            <div className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 rounded-full ${provisioned ? 'bg-cyan-400' : 'bg-[var(--db-fill-strong)]'}`}
              />
              <span className="text-[11.5px] font-medium text-[color:var(--db-text-muted)]">
                {provisioned
                  ? status.running === false
                    ? 'Workspace set up · paused'
                    : 'Workspace ready'
                  : 'Not set up yet'}
              </span>
            </div>
          )}

          <p className="text-[13px] leading-6 text-[color:var(--db-text-soft)]">
            This is your AI workspace — a private browser Prism presents from in meetings. Log into
            GitHub, Figma, and the sites you want it to show; you sign in once and later meetings
            reuse it. It opens in a new tab that stays private to you during setup.
          </p>

          {/* Privacy expectation */}
          <div className="flex items-start gap-2.5 rounded-xl border border-cyan-400/20 bg-cyan-400/[0.05] px-3.5 py-3">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" />
            <p className="text-[12px] leading-5 text-[color:var(--db-text-muted)]">
              Your teammates will see this screen when Prism presents. Only log into apps you’re
              comfortable showing in a meeting.
            </p>
          </div>

          {error && (
            <div className="rounded-xl border border-red-400/25 bg-red-400/[0.07] px-3.5 py-2.5">
              <p className="text-[12px] leading-5 text-red-300">{error}</p>
            </div>
          )}

          {/* Primary action */}
          <button
            type="button"
            onClick={setupWorkspace}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-full bg-cyan-400 py-2.5 text-sm font-semibold text-[#07040f] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Preparing your workspace…
              </>
            ) : (
              <>
                <ExternalLink className="h-4 w-4" />
                {provisioned || interactiveUrl ? 'Open my workspace' : 'Set up my workspace'}
              </>
            )}
          </button>

          {/* Fallback link if the browser blocked the new tab. */}
          {interactiveUrl && (
            <p className="text-center text-[11px] text-[color:var(--db-text-faint)]">
              Didn’t open?{' '}
              <a
                href={interactiveUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-semibold text-cyan-300 underline-offset-2 hover:underline"
              >
                Open the workspace tab
              </a>
            </p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

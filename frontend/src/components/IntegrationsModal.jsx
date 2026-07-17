import { useState, useEffect } from 'react'
import { apiFetch } from '../lib/api'
import { writeIntegrationStore } from '../lib/integrationStore'

const TABS = ['Slack', 'Teams', 'Notion', 'Calendar', 'Outlook', 'Gmail', 'Linear', 'Jira']

// OAuth-based tabs are NOT workspace-configurable in v1 — they stay personal.
const OAUTH_TABS = ['Calendar', 'Outlook', 'Gmail']

// Token/webhook providers that CAN be configured per-workspace. Field `key`s match
// the personal user_settings field names exactly (the backend expects the same shape).
const WS_PROVIDERS = {
  Slack: {
    provider: 'slack',
    fields: [
      { key: 'slack_bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password',
        hint: 'Lets the bot POST messages via commands (e.g. "post this to #team"). From api.slack.com/apps → your app → OAuth & Permissions → Bot User OAuth Token.' },
      { key: 'slack_webhook', label: 'Incoming Webhook URL', placeholder: 'https://hooks.slack.com/services/...',
        hint: 'Used to push meeting summaries to one channel. Optional if you only need bot-command posting.' },
    ],
  },
  Teams: {
    provider: 'teams',
    fields: [
      { key: 'teams_webhook', label: 'Workflows Webhook URL', placeholder: 'https://prod-XX.westus.logic.azure.com/...',
        hint: 'A Power Automate "Workflows" (or legacy Office 365) incoming-webhook URL for the channel summaries should post to.' },
    ],
  },
  Notion: {
    provider: 'notion',
    fields: [
      { key: 'notion_token', label: 'Integration Token', placeholder: 'secret_...', type: 'password',
        hint: 'From notion.so/my-integrations → New integration → Internal Integration Token. Share the target page with the integration.' },
      { key: 'notion_page_id', label: 'Parent Page ID', placeholder: '32-character page ID or full page URL',
        hint: 'The page new meeting notes are created under — paste the page URL or its 32-char ID.' },
    ],
  },
  Linear: {
    provider: 'linear',
    fields: [
      { key: 'linear_api_key', label: 'Linear API Key', placeholder: 'lin_api_...', type: 'password',
        hint: 'A personal API key from linear.app/settings/api. Lets the bot create issues from action items.' },
    ],
  },
  Jira: {
    provider: 'jira',
    fields: [
      { key: 'jira_base_url', label: 'Site URL', placeholder: 'yoursite.atlassian.net',
        hint: 'Your Jira Cloud site, e.g. yoursite.atlassian.net (with or without https://).' },
      { key: 'jira_email', label: 'Account Email', placeholder: 'you@company.com',
        hint: 'The Atlassian account email that owns the API token.' },
      { key: 'jira_api_token', label: 'API Token', placeholder: 'Atlassian API token', type: 'password',
        hint: 'Create one at id.atlassian.com/manage-profile/security/api-tokens.' },
      { key: 'jira_project_key', label: 'Default Project Key', placeholder: 'e.g. PRISM',
        hint: 'The project new issues are created in (overridable per request in chat).' },
    ],
  },
}

function Field({ label, placeholder, value, onChange, type = 'text', hint, disabled = false }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-400 mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full rounded-xl px-3 py-2.5 text-xs text-gray-200 outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600"
        style={{ background: 'rgba(0,0,0,0.35)', opacity: disabled ? 0.55 : 1 }}
      />
      {hint && <p className="text-[10px] text-gray-600 mt-1.5 leading-relaxed">{hint}</p>}
    </div>
  )
}

function Toggle({ label, checked, onChange, hint, disabled = false }) {
  return (
    <div className="rounded-xl p-3 flex items-start justify-between gap-3"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div>
        <p className="text-xs font-medium text-gray-300">{label}</p>
        {hint && <p className="text-[10px] text-gray-500 mt-1.5 leading-relaxed max-w-xs">{hint}</p>}
      </div>
      <button
        type="button"
        aria-pressed={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className="relative w-11 h-6 rounded-full transition-colors flex-shrink-0 disabled:cursor-not-allowed disabled:opacity-50"
        style={{ background: checked ? 'linear-gradient(135deg, #0284c7, #0d9488)' : 'rgba(255,255,255,0.08)' }}>
        <span
          className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform"
          style={{ left: '2px', transform: checked ? 'translateX(20px)' : 'translateX(0)' }}
        />
      </button>
    </div>
  )
}

const AUTO_JOIN_OPTIONS = [
  { value: 'off',    label: 'Off',               hint: 'No automatic behavior — join manually from the panel.' },
  { value: 'ask',    label: 'Ask me',             hint: 'Show a prompt when a meeting starts within 5 minutes.' },
  { value: 'auto',   label: 'Auto-join all',      hint: 'Automatically send the bot when a meeting link starts.' },
  { value: 'marked', label: 'Auto-join starred',  hint: 'Only auto-join meetings you\'ve starred in the panel.' },
]

export default function IntegrationsModal({ integrations, userId = null, onSave, onClose, calendarConnected, onConnectCalendar, onDisconnectCalendar, outlookConnected = false, onConnectOutlook, onDisconnectOutlook, autoJoinSetting = 'off', onAutoJoinChange, isSignedIn = false, isTestAccount = false }) {
  const [tab, setTab] = useState('Slack')
  const [slackWebhook, setSlackWebhook] = useState(integrations.slack_webhook || '')
  const [notionToken, setNotionToken] = useState(integrations.notion_token || '')
  const [notionPageId, setNotionPageId] = useState(integrations.notion_page_id || '')
  const [autoSendSlack, setAutoSendSlack] = useState(Boolean(integrations.auto_send_slack))
  const [autoSendNotion, setAutoSendNotion] = useState(Boolean(integrations.auto_send_notion))
  const [teamsWebhook, setTeamsWebhook] = useState(integrations.teams_webhook || '')
  const [autoSendTeams, setAutoSendTeams] = useState(Boolean(integrations.auto_send_teams))
  const [testingSlack, setTestingSlack] = useState(false)
  const [slackTestResult, setSlackTestResult] = useState(null) // 'ok' | 'err'
  const [testingTeams, setTestingTeams] = useState(false)
  const [teamsTestResult, setTeamsTestResult] = useState(null) // 'ok' | 'err'

  // Agentic tool integrations (stored in Supabase user_settings)
  const [linearApiKey, setLinearApiKey] = useState(integrations.linear_api_key || '')
  const [slackBotToken, setSlackBotToken] = useState(integrations.slack_bot_token || '')
  const [jiraBaseUrl, setJiraBaseUrl] = useState(integrations.jira_base_url || '')
  const [jiraEmail, setJiraEmail] = useState(integrations.jira_email || '')
  const [jiraApiToken, setJiraApiToken] = useState(integrations.jira_api_token || '')
  const [jiraProjectKey, setJiraProjectKey] = useState(integrations.jira_project_key || '')
  const [savingTools, setSavingTools] = useState(false)
  const [toolSaveResult, setToolSaveResult] = useState(null) // 'ok' | 'err'
  // Verify ticket-integration creds before relying on them mid-meeting (Cluster B).
  const [testingJira, setTestingJira] = useState(false)
  const [jiraTestResult, setJiraTestResult] = useState(null) // {ok, account_name?, error?, project_ok?}
  const [testingLinear, setTestingLinear] = useState(false)
  const [linearTestResult, setLinearTestResult] = useState(null)

  // ── Per-workspace integrations scope ────────────────────────────────────
  // scope === 'personal' → today's behavior, 100% unchanged. Otherwise scope is a
  // workspace id and all reads/writes route to the workspace integrations API.
  const [scope, setScope] = useState('personal')
  const [wsList, setWsList] = useState([])            // [{id, name, role, ...}]
  const [wsData, setWsData] = useState(null)          // {integrations:[...], can_edit}
  const [wsLoading, setWsLoading] = useState(false)
  const [wsForm, setWsForm] = useState({})            // typed creds for the current workspace edit
  const [wsSaving, setWsSaving] = useState(false)
  const [wsSaveResult, setWsSaveResult] = useState(null) // 'ok' | 'err'
  const [wsTestState, setWsTestState] = useState({ provider: null, testing: false, result: null })

  // Fetch the user's workspaces once (only for real, signed-in accounts).
  useEffect(() => {
    if (!isSignedIn || isTestAccount) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await apiFetch('/workspaces')
        const data = await res.json()
        const list = Array.isArray(data) ? data : (data?.workspaces || [])
        if (!cancelled) setWsList(list)
      } catch (err) {
        console.warn('[IntegrationsModal] Failed to load workspaces:', err)
      }
    })()
    return () => { cancelled = true }
  }, [isSignedIn, isTestAccount])

  async function loadWsIntegrations(wsId) {
    setWsLoading(true)
    try {
      const res = await apiFetch(`/workspaces/${wsId}/integrations`)
      const data = await res.json()
      setWsData(data && typeof data === 'object' ? data : null)
    } catch (err) {
      console.warn('[IntegrationsModal] Failed to load workspace integrations:', err)
      setWsData(null)
    } finally {
      setWsLoading(false)
    }
  }

  function switchScope(next) {
    setScope(next)
    setWsForm({})
    setWsSaveResult(null)
    setWsData(null)
    setWsTestState({ provider: null, testing: false, result: null })
    if (next !== 'personal') loadWsIntegrations(next)
  }

  function wsStatus(provider) {
    const list = wsData?.integrations || []
    return list.find(i => i.provider === provider) || null
  }

  async function wsSaveProvider() {
    const cfg = WS_PROVIDERS[tab]
    if (!cfg || scope === 'personal') return
    const config = {}
    cfg.fields.forEach(f => { config[f.key] = wsForm[f.key] || '' })
    setWsSaving(true)
    setWsSaveResult(null)
    try {
      const res = await apiFetch(`/workspaces/${scope}/integrations/${cfg.provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, enabled: true }),
      })
      if (!res.ok) throw new Error('save failed')
      setWsSaveResult('ok')
      setWsForm({})
      setWsTestState({ provider: null, testing: false, result: null })
      await loadWsIntegrations(scope)
    } catch (err) {
      console.warn('[IntegrationsModal] Failed to save workspace integration:', err)
      setWsSaveResult('err')
    } finally {
      setWsSaving(false)
    }
  }

  async function wsDisconnect() {
    const cfg = WS_PROVIDERS[tab]
    if (!cfg || scope === 'personal') return
    setWsSaving(true)
    setWsSaveResult(null)
    try {
      const res = await apiFetch(`/workspaces/${scope}/integrations/${cfg.provider}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('delete failed')
      setWsForm({})
      setWsTestState({ provider: null, testing: false, result: null })
      await loadWsIntegrations(scope)
    } catch (err) {
      console.warn('[IntegrationsModal] Failed to disconnect workspace integration:', err)
      setWsSaveResult('err')
    } finally {
      setWsSaving(false)
    }
  }

  async function wsTest(provider) {
    setWsTestState({ provider, testing: true, result: null })
    const body = { provider }
    if (provider === 'jira') {
      Object.assign(body, {
        jira_base_url: wsForm.jira_base_url || '',
        jira_email: wsForm.jira_email || '',
        jira_api_token: wsForm.jira_api_token || '',
        jira_project_key: wsForm.jira_project_key || '',
      })
    } else if (provider === 'linear') {
      body.linear_api_key = wsForm.linear_api_key || ''
    }
    try {
      const res = await apiFetch('/integrations/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({ ok: false, error: 'Test failed.' }))
      setWsTestState({ provider, testing: false, result: data })
    } catch {
      setWsTestState({ provider, testing: false, result: { ok: false, error: 'Could not reach the server.' } })
    }
  }

  const activeWs = wsList.find(w => String(w.id) === String(scope)) || null

  // Re-seed the server-side tool tokens when they arrive/change. useState only
  // captures the initial prop, so a modal opened before /user-settings resolved would
  // show blank Jira/Linear fields — and then a save would null them out server-side
  // (the "integration details disappear" bug). This syncs from the parent's loaded
  // values without clobbering active edits (the deps are props, which only change on
  // load, never while the user is typing).
  useEffect(() => {
    setLinearApiKey(integrations.linear_api_key || '')
    setSlackBotToken(integrations.slack_bot_token || '')
    setJiraBaseUrl(integrations.jira_base_url || '')
    setJiraEmail(integrations.jira_email || '')
    setJiraApiToken(integrations.jira_api_token || '')
    setJiraProjectKey(integrations.jira_project_key || '')
  }, [integrations.linear_api_key, integrations.slack_bot_token, integrations.jira_base_url,
      integrations.jira_email, integrations.jira_api_token, integrations.jira_project_key])

  async function save() {
    if (isTestAccount) return
    const updated = {
      slack_webhook: slackWebhook,
      notion_token: notionToken,
      notion_page_id: notionPageId,
      auto_send_slack: autoSendSlack,
      auto_send_notion: autoSendNotion,
      teams_webhook: teamsWebhook,
      auto_send_teams: autoSendTeams,
      linear_api_key: linearApiKey,
      slack_bot_token: slackBotToken,
      jira_base_url: jiraBaseUrl,
      jira_email: jiraEmail,
      jira_api_token: jiraApiToken,
      jira_project_key: jiraProjectKey,
    }
    writeIntegrationStore(userId, {
      slack_webhook: slackWebhook,
      notion_token: notionToken,
      notion_page_id: notionPageId,
      auto_send_slack: autoSendSlack,
      auto_send_notion: autoSendNotion,
      teams_webhook: teamsWebhook,
      auto_send_teams: autoSendTeams,
    })

    // Save tool tokens to backend (Supabase user_settings)
    if (isSignedIn) {
      try {
        await apiFetch('/user-settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            linear_api_key: linearApiKey || null,
            slack_bot_token: slackBotToken || null,
            jira_base_url: jiraBaseUrl || null,
            jira_email: jiraEmail || null,
            jira_api_token: jiraApiToken || null,
            jira_project_key: jiraProjectKey || null,
          }),
        })
      } catch (err) {
        console.warn('[IntegrationsModal] Failed to save tool settings:', err)
      }
    }

    onSave(updated)
    onClose()
  }

  async function testSlack() {
    if (isTestAccount) return
    if (!slackWebhook.trim()) return
    setTestingSlack(true)
    setSlackTestResult(null)
    try {
      const res = await apiFetch('/export/slack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          webhook_url: slackWebhook,
          title: 'PrismAI test',
          result: { health_score: { score: null }, summary: '✅ PrismAI connected successfully!', action_items: [], decisions: [] },
        }),
      })
      setSlackTestResult(res.ok ? 'ok' : 'err')
    } catch {
      setSlackTestResult('err')
    } finally {
      setTestingSlack(false)
    }
  }

  async function testTeams() {
    if (isTestAccount) return
    if (!teamsWebhook.trim()) return
    setTestingTeams(true)
    setTeamsTestResult(null)
    try {
      const res = await apiFetch('/export/teams', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          webhook_url: teamsWebhook,
          title: 'PrismAI test',
          result: { health_score: { score: null }, summary: '✅ PrismAI connected successfully!', action_items: [], decisions: [] },
        }),
      })
      setTeamsTestResult(res.ok ? 'ok' : 'err')
    } catch {
      setTeamsTestResult('err')
    } finally {
      setTestingTeams(false)
    }
  }

  async function testJira() {
    if (isTestAccount) return
    setTestingJira(true)
    setJiraTestResult(null)
    try {
      const res = await apiFetch('/integrations/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: 'jira',
          jira_base_url: jiraBaseUrl,
          jira_email: jiraEmail,
          jira_api_token: jiraApiToken,
          jira_project_key: jiraProjectKey,
        }),
      })
      const data = await res.json().catch(() => ({ ok: false, error: 'Test failed.' }))
      setJiraTestResult(data)
    } catch {
      setJiraTestResult({ ok: false, error: 'Could not reach the server.' })
    } finally {
      setTestingJira(false)
    }
  }

  async function testLinear() {
    if (isTestAccount) return
    setTestingLinear(true)
    setLinearTestResult(null)
    try {
      const res = await apiFetch('/integrations/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'linear', linear_api_key: linearApiKey }),
      })
      const data = await res.json().catch(() => ({ ok: false, error: 'Test failed.' }))
      setLinearTestResult(data)
    } catch {
      setLinearTestResult({ ok: false, error: 'Could not reach the server.' })
    } finally {
      setTestingLinear(false)
    }
  }

  function renderWorkspace() {
    const wsName = activeWs?.name || 'Workspace'

    // OAuth providers are personal-only in v1.
    if (OAUTH_TABS.includes(tab)) {
      return (
        <div className="rounded-xl p-4 text-[11px] text-gray-400 leading-relaxed"
          style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
          Calendar &amp; email stay personal — connect them under <span className="text-gray-200">Personal</span>.
          Workspace scope covers Slack, Teams, Notion, Linear, and Jira.
        </div>
      )
    }

    const cfg = WS_PROVIDERS[tab]
    if (!cfg) return null

    if (wsLoading) {
      return <p className="text-xs text-gray-500 py-2">Loading workspace integrations…</p>
    }

    const status = wsStatus(cfg.provider)
    const connected = !!status?.connected
    const canEdit = !!wsData?.can_edit
    const label = status?.label || ''
    const testable = cfg.provider === 'jira' || cfg.provider === 'linear'
    const testResult = wsTestState.provider === cfg.provider ? wsTestState.result : null
    const testing = wsTestState.provider === cfg.provider && wsTestState.testing

    return (
      <div className="space-y-4">
        {/* Current status */}
        <div className="rounded-xl p-3 flex items-center gap-2.5"
          style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
          <span className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: connected ? '#34d399' : 'rgba(255,255,255,0.2)' }} />
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-200">
              {connected ? 'Connected' : 'Not configured'}
              {connected && label && <span className="text-gray-500 font-normal"> · {label}</span>}
            </p>
            <p className="text-[10px] text-gray-600 mt-0.5">Shared across the “{wsName}” workspace.</p>
          </div>
        </div>

        {/* Owner: editable fields. Member: disabled + note. */}
        {canEdit ? (
          <>
            {cfg.fields.map(f => (
              <Field
                key={f.key}
                label={f.label}
                placeholder={f.placeholder}
                type={f.type || 'text'}
                hint={f.hint}
                value={wsForm[f.key] || ''}
                onChange={val => setWsForm(prev => ({ ...prev, [f.key]: val }))}
              />
            ))}
            <p className="text-[10px] text-gray-600 leading-relaxed px-0.5">
              {connected
                ? 'Secrets are never shown — re-enter credentials to update this connection.'
                : 'Credentials are stored on the workspace and used for every member’s meetings.'}
            </p>

            {testable && (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => wsTest(cfg.provider)}
                  disabled={testing}
                  className="text-[11px] px-3 py-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#cbd5e1' }}>
                  {testing ? 'Testing…' : 'Test connection'}
                </button>
                {testResult && (
                  <span className={`text-[11px] ${testResult.ok && !testResult.error ? 'text-emerald-400' : testResult.ok ? 'text-amber-400' : 'text-red-400'}`}>
                    {testResult.ok && !testResult.error
                      ? `✓ Connected as ${testResult.account_name}${testResult.project_ok ? ' · project OK' : ''}`
                      : (testResult.error || 'Connection failed')}
                  </span>
                )}
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={wsSaveProvider}
                disabled={wsSaving}
                className="text-xs px-4 py-2 rounded-lg font-semibold text-white transition-all hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
                {wsSaving ? 'Saving…' : 'Save to workspace'}
              </button>
              {connected && (
                <button
                  onClick={wsDisconnect}
                  disabled={wsSaving}
                  className="text-xs px-3 py-2 rounded-lg transition-all text-red-400 hover:text-red-300 disabled:opacity-50"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}>
                  Disconnect
                </button>
              )}
              {wsSaveResult === 'ok' && <span className="text-[11px] text-emerald-400">✓ Saved</span>}
              {wsSaveResult === 'err' && <span className="text-[11px] text-red-400">Save failed</span>}
            </div>
          </>
        ) : (
          <>
            {cfg.fields.map(f => (
              <Field
                key={f.key}
                label={f.label}
                placeholder={connected ? '••••••••' : 'Not configured'}
                type={f.type || 'text'}
                value=""
                onChange={() => {}}
                disabled
              />
            ))}
            <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
              style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
              {connected
                ? <>Configured by the workspace{label ? <> · <span className="text-gray-300">{label}</span></> : null}.</>
                : 'Not configured.'}
              {' '}Only the workspace owner can change this.
            </div>
          </>
        )}
      </div>
    )
  }

  const showScopeSwitcher = isSignedIn && !isTestAccount && wsList.length > 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}>
      <div className="dashboard-popup w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden animate-fade-in-up">

        {/* Header */}
        <div className="px-5 py-4 flex items-center justify-between"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <div>
            <h3 className="text-sm font-semibold text-white">Integrations</h3>
            <p className="text-[11px] text-gray-500 mt-0.5">
              {scope === 'personal'
                ? 'Connect PrismAI to your tools — stored securely on your account.'
                : `Shared across the “${activeWs?.name || 'workspace'}” — only the workspace owner can change these.`}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300 transition-colors p-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex flex-wrap px-5 pt-4 gap-1.5">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                tab === t ? 'text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
              style={tab === t ? { background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' } : {}}
            >
              {t === 'Slack' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
                </svg>
              )}
              {t === 'Teams' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M20.625 8.127q.55 0 1.025.205.475.205.83.561.357.357.561.832.205.475.205 1.025v4.682q0 .735-.281 1.383-.281.648-.762 1.13-.48.48-1.129.761-.648.281-1.382.281-.595 0-1.155-.193-.56-.193-1.013-.557-.302.857-.86 1.547-.56.69-1.293 1.178-.732.488-1.59.745-.857.258-1.777.258-1.001 0-1.894-.314-.892-.315-1.629-.875-.736-.56-1.281-1.336-.545-.776-.838-1.703H2.812q-.337 0-.578-.24-.24-.241-.24-.579V7.187q0-.337.24-.578.241-.24.578-.24h6.504q-.176-.493-.176-1.025 0-.61.234-1.149.235-.538.633-.937.398-.398.937-.633.539-.234 1.149-.234.61 0 1.148.234.54.235.938.633.398.399.632.937.235.54.235 1.149 0 .532-.176 1.025h4.553zM12.094 3.516q-.293 0-.55.111-.258.111-.451.305-.193.193-.305.45-.111.258-.111.551t.111.55q.112.258.305.451.193.194.45.305.258.111.551.111.293 0 .55-.111.258-.111.452-.305.193-.193.304-.45.112-.258.112-.551t-.112-.55q-.111-.258-.304-.451-.194-.194-.451-.305-.258-.111-.55-.111zm-.703 16.371q.768 0 1.336-.521.568-.522.65-1.278v-7.265H3.328v6.504q0 .55.205 1.025.205.475.561.832.357.356.832.561.475.205 1.025.205h4.44z"/>
                </svg>
              )}
              {t === 'Notion' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.14c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z"/>
                </svg>
              )}
              {t === 'Calendar' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                  <line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
              )}
              {t === 'Outlook' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M11.4 11.4H2V2h9.4z"/>
                  <path d="M22 11.4h-9.4V2H22z" opacity="0.7"/>
                  <path d="M11.4 22H2v-9.4h9.4z" opacity="0.7"/>
                  <path d="M22 22h-9.4v-9.4H22z" opacity="0.5"/>
                </svg>
              )}
              {t === 'Gmail' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z"/>
                </svg>
              )}
              {t === 'Linear' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3.357 16.643a.755.755 0 0 1 0-1.069L14.786 4.146c.15-.149.349-.223.548-.223s.399.074.548.223a.755.755 0 0 1 0 1.069L4.454 16.643a.783.783 0 0 1-1.097 0zm-.843 3.572a.755.755 0 0 1 0-1.069L16.643 5.017a.783.783 0 0 1 1.097 0 .755.755 0 0 1 0 1.069L3.611 20.215a.783.783 0 0 1-1.097 0zm3.2.856a.755.755 0 0 1 0-1.069l11.429-11.428a.783.783 0 0 1 1.097 0 .755.755 0 0 1 0 1.069L6.811 21.071a.783.783 0 0 1-1.097 0z"/>
                </svg>
              )}
              {t === 'Jira' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 12.483V1.005A1.001 1.001 0 0 0 23.013 0z"/>
                </svg>
              )}
              {t}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="px-5 py-4 space-y-4">
          {isTestAccount && (
            <div className="rounded-xl p-3 text-[11px] leading-relaxed text-cyan-100/78"
              style={{ background: 'rgba(14,165,233,0.07)', border: '1px solid rgba(14,165,233,0.18)' }}>
              Integrations are disabled in test run. Create or log in to a real account to connect external tools.
            </div>
          )}

          {/* Scope switcher — Personal | <workspaces>. Hidden entirely when the user
              has no workspaces (personal-only, unchanged). */}
          {showScopeSwitcher && (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                onClick={() => switchScope('personal')}
                className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                  scope === 'personal' ? 'text-cyan-200' : 'text-gray-500 hover:text-gray-300'
                }`}
                style={scope === 'personal'
                  ? { background: 'rgba(34,211,238,0.10)', border: '1px solid rgba(34,211,238,0.30)' }
                  : { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                Personal
              </button>
              {wsList.map(ws => (
                <button
                  key={ws.id}
                  onClick={() => switchScope(ws.id)}
                  className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                    String(scope) === String(ws.id) ? 'text-cyan-200' : 'text-gray-500 hover:text-gray-300'
                  }`}
                  style={String(scope) === String(ws.id)
                    ? { background: 'rgba(34,211,238,0.10)', border: '1px solid rgba(34,211,238,0.30)' }
                    : { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                  {ws.name}
                </button>
              ))}
            </div>
          )}

          {/* Save-target badge — never leave it ambiguous where creds land. */}
          {showScopeSwitcher && (
            <div className="flex items-center gap-2 -mt-1">
              <span className="text-[10px] uppercase tracking-wide text-gray-600">Editing</span>
              <span className="px-2 py-0.5 rounded-md text-[10px] font-semibold"
                style={scope === 'personal'
                  ? { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.10)', color: '#cbd5e1' }
                  : { background: 'rgba(34,211,238,0.10)', border: '1px solid rgba(34,211,238,0.30)', color: '#67e8f9' }}>
                {scope === 'personal' ? 'Personal' : `${activeWs?.name || 'Workspace'} · workspace`}
              </span>
            </div>
          )}

          {scope !== 'personal' && renderWorkspace()}

          {scope === 'personal' && (<>
          {tab === 'Slack' && (
            <>
              <Field
                label="Incoming Webhook URL"
                placeholder="https://hooks.slack.com/services/..."
                value={slackWebhook}
                onChange={setSlackWebhook}
                disabled={isTestAccount}
                hint="Create an incoming webhook in your Slack app settings. Tokens are saved only in your browser."
              />
              {slackWebhook.trim() && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={testSlack}
                    disabled={testingSlack || isTestAccount}
                    className="text-xs px-3 py-1.5 rounded-lg transition-all disabled:opacity-50"
                    style={{ background: 'rgba(14,165,233,0.1)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                    {testingSlack ? 'Sending...' : 'Send test message'}
                  </button>
                  {slackTestResult === 'ok' && <span className="text-xs text-emerald-400">✓ Connected</span>}
                  {slackTestResult === 'err' && <span className="text-xs text-red-400">Failed — check URL</span>}
                </div>
              )}
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                When you export to Slack, PrismAI sends a formatted summary with action items and decisions to your webhook channel.
              </div>
              <Toggle
                label="Auto-send recap after every meeting"
                checked={autoSendSlack}
                onChange={setAutoSendSlack}
                disabled={isTestAccount}
                hint="When enabled, PrismAI will post the meeting recap to Slack automatically after analysis finishes."
              />
            </>
          )}

          {tab === 'Teams' && (
            <>
              <Field
                label="Workflows Webhook URL"
                placeholder="https://prod-XX.westus.logic.azure.com/..."
                value={teamsWebhook}
                onChange={setTeamsWebhook}
                disabled={isTestAccount}
                hint="In Teams: channel ⋯ → Workflows → 'Post to a channel when a webhook request is received' → copy the URL. Saved only in your browser."
              />
              {teamsWebhook.trim() && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={testTeams}
                    disabled={testingTeams || isTestAccount}
                    className="text-xs px-3 py-1.5 rounded-lg transition-all disabled:opacity-50"
                    style={{ background: 'rgba(14,165,233,0.1)', color: '#7dd3fc', border: '1px solid rgba(14,165,233,0.2)' }}>
                    {testingTeams ? 'Sending...' : 'Send test message'}
                  </button>
                  {teamsTestResult === 'ok' && <span className="text-xs text-emerald-400">✓ Connected</span>}
                  {teamsTestResult === 'err' && <span className="text-xs text-red-400">Failed — check URL</span>}
                </div>
              )}
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                PrismAI posts a formatted recap card (summary, action items, decisions) to your Teams channel. Uses Power Automate Workflows — the current method, since Microsoft is retiring the classic Incoming Webhook connector.
              </div>
              <Toggle
                label="Auto-send recap after every meeting"
                checked={autoSendTeams}
                onChange={setAutoSendTeams}
                disabled={isTestAccount}
                hint="When enabled, PrismAI will post the meeting recap to Teams automatically after analysis finishes."
              />
            </>
          )}

          {tab === 'Notion' && (
            <>
              <Field
                label="Integration Token"
                placeholder="secret_..."
                value={notionToken}
                onChange={setNotionToken}
                type="password"
                disabled={isTestAccount}
                hint="Create a Notion integration at notion.so/my-integrations and copy the secret token."
              />
              <Field
                label="Parent Page ID"
                placeholder="32-character page ID or full page URL"
                value={notionPageId}
                onChange={setNotionPageId}
                disabled={isTestAccount}
                hint="The page where meeting analyses will be created. Share that page with your integration first."
              />
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                PrismAI will create a new Notion page for each meeting with full analysis: summary, action items (as checkboxes), decisions, email draft, and health score.
              </div>
              <Toggle
                label="Auto-create a Notion page after every meeting"
                checked={autoSendNotion}
                onChange={setAutoSendNotion}
                disabled={isTestAccount}
                hint="When enabled, PrismAI will create a Notion recap page automatically as soon as the analysis completes."
              />
            </>
          )}

          {tab === 'Calendar' && (
            <div className="space-y-4">
              {/* Connection status */}
              <div className="rounded-xl p-4 flex items-center gap-3"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
                  style={{ background: calendarConnected ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.05)' }}>
                  {calendarConnected ? (
                    <svg className="w-4 h-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="3" y="4" width="18" height="18" rx="2"/>
                      <line x1="16" y1="2" x2="16" y2="6"/>
                      <line x1="8" y1="2" x2="8" y2="6"/>
                      <line x1="3" y1="10" x2="21" y2="10"/>
                    </svg>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-200">
                    {calendarConnected ? 'Google Calendar connected' : 'Google Calendar'}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {calendarConnected
                      ? 'Upcoming meetings will appear in your workspace.'
                      : 'Connect to see upcoming meetings and join with one click.'}
                  </p>
                </div>
              </div>

              {/* Connect / Disconnect button */}
              {calendarConnected ? (
                <button
                  onClick={() => { onDisconnectCalendar?.(); onClose() }}
                  disabled={isTestAccount}
                  className="w-full text-xs py-2.5 rounded-xl transition-all text-red-400 hover:text-red-300"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}>
                  Disconnect Google Calendar
                </button>
              ) : (
                <button
                  onClick={() => { onConnectCalendar?.(); onClose() }}
                  disabled={isTestAccount}
                  className="w-full text-xs py-2.5 rounded-xl font-semibold text-white transition-all hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #4285F4, #34A853)' }}>
                  Connect Google Calendar
                </button>
              )}

              {/* Auto-join setting — only shown when connected */}
              {calendarConnected && (
                <div className="space-y-2">
                  <p className="text-[11px] font-medium text-gray-400 px-0.5">Auto-join behavior</p>
                  {AUTO_JOIN_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => onAutoJoinChange?.(opt.value)}
                      disabled={isTestAccount}
                      className="w-full flex items-start gap-3 rounded-xl p-3 text-left transition-all"
                      style={autoJoinSetting === opt.value
                        ? { background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.25)' }
                        : { background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                      <div className={`w-4 h-4 rounded-full flex-shrink-0 mt-0.5 flex items-center justify-center border ${autoJoinSetting === opt.value ? 'border-sky-400' : 'border-gray-600'}`}>
                        {autoJoinSetting === opt.value && (
                          <div className="w-2 h-2 rounded-full bg-sky-400" />
                        )}
                      </div>
                      <div>
                        <p className={`text-xs font-medium ${autoJoinSetting === opt.value ? 'text-sky-300' : 'text-gray-300'}`}>{opt.label}</p>
                        <p className="text-[10px] text-gray-600 mt-0.5 leading-relaxed">{opt.hint}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                PrismAI requests read-only access to your primary calendar. It detects Zoom, Google Meet, and Teams links and lets you join with one click — no link pasting required.
              </div>
            </div>
          )}

          {tab === 'Outlook' && (
            <div className="space-y-4">
              <div className="rounded-xl p-4 flex items-center gap-3"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
                  style={{ background: outlookConnected ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.05)' }}>
                  {outlookConnected ? (
                    <svg className="w-4 h-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M11.4 11.4H2V2h9.4z"/><path d="M22 11.4h-9.4V2H22z" opacity="0.7"/>
                      <path d="M11.4 22H2v-9.4h9.4z" opacity="0.7"/><path d="M22 22h-9.4v-9.4H22z" opacity="0.5"/>
                    </svg>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-200">
                    {outlookConnected ? 'Outlook Calendar connected' : 'Outlook Calendar'}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {outlookConnected
                      ? 'Your upcoming Outlook meetings appear in your workspace.'
                      : 'Connect to see upcoming Outlook meetings (incl. Teams links) and join with one click.'}
                  </p>
                </div>
              </div>

              {outlookConnected ? (
                <button
                  onClick={() => { onDisconnectOutlook?.(); onClose() }}
                  disabled={isTestAccount}
                  className="w-full text-xs py-2.5 rounded-xl transition-all text-red-400 hover:text-red-300"
                  style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}>
                  Disconnect Outlook Calendar
                </button>
              ) : (
                <button
                  onClick={() => { onConnectOutlook?.(); onClose() }}
                  disabled={isTestAccount}
                  className="w-full text-xs py-2.5 rounded-xl font-semibold text-white transition-all hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #0078D4, #0a5ca8)' }}>
                  Connect Outlook Calendar
                </button>
              )}

              {/* Auto-join behavior — the SAME global setting as Google Calendar; it
                  applies to every connected calendar, so configuring it here or under
                  the Calendar tab is equivalent. */}
              {outlookConnected && (
                <div className="space-y-2">
                  <p className="text-[11px] font-medium text-gray-400 px-0.5">Auto-join behavior</p>
                  {AUTO_JOIN_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => onAutoJoinChange?.(opt.value)}
                      disabled={isTestAccount}
                      className="w-full flex items-start gap-3 rounded-xl p-3 text-left transition-all"
                      style={autoJoinSetting === opt.value
                        ? { background: 'rgba(14,165,233,0.08)', border: '1px solid rgba(14,165,233,0.25)' }
                        : { background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                      <div className={`w-4 h-4 rounded-full flex-shrink-0 mt-0.5 flex items-center justify-center border ${autoJoinSetting === opt.value ? 'border-sky-400' : 'border-gray-600'}`}>
                        {autoJoinSetting === opt.value && (
                          <div className="w-2 h-2 rounded-full bg-sky-400" />
                        )}
                      </div>
                      <div>
                        <p className={`text-xs font-medium ${autoJoinSetting === opt.value ? 'text-sky-300' : 'text-gray-300'}`}>{opt.label}</p>
                        <p className="text-[10px] text-gray-600 mt-0.5 leading-relaxed">{opt.hint}</p>
                      </div>
                    </button>
                  ))}
                  <p className="text-[10px] text-gray-600 px-0.5 leading-relaxed">
                    Shared with Google Calendar — applies to all connected calendars.
                  </p>
                </div>
              )}

              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                PrismAI requests read-only access to your Outlook calendar (Microsoft Graph). It surfaces upcoming meetings and detects Teams/Zoom/Meet links so you can join in one click.
              </div>
            </div>
          )}

          {tab === 'Gmail' && (
            <div className="space-y-4">
              <div className="rounded-xl p-4 flex items-center gap-3"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
                  style={{ background: calendarConnected ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.05)' }}>
                  {calendarConnected ? (
                    <svg className="w-4 h-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-gray-500" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z"/>
                    </svg>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-200">
                    {calendarConnected ? 'Gmail connected via Google' : 'Gmail'}
                  </p>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    {calendarConnected
                      ? 'PrismAI can send and read emails using your Google account.'
                      : 'Connect Google Calendar first — Gmail uses the same Google connection.'}
                  </p>
                </div>
              </div>

              {!calendarConnected && (
                <button
                  onClick={() => { onConnectCalendar?.(); onClose() }}
                  disabled={isTestAccount}
                  className="w-full text-xs py-2.5 rounded-xl font-semibold text-white transition-all hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg, #4285F4, #34A853)' }}>
                  Connect Google Account
                </button>
              )}

              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                Gmail tools let PrismAI send follow-up emails and read your inbox when you ask in the chat. For example: "email the action items to the team" or "check my inbox for replies."
              </div>
            </div>
          )}

          {tab === 'Linear' && (
            <>
              <Field
                label="Linear API Key"
                placeholder="lin_api_..."
                value={linearApiKey}
                onChange={setLinearApiKey}
                type="password"
                disabled={isTestAccount}
                hint="Create a personal API key at linear.app/settings/api. This lets PrismAI create issues from action items."
              />
              {linearApiKey.trim() && (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={testLinear}
                    disabled={isTestAccount || testingLinear}
                    className="text-[11px] px-3 py-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#cbd5e1' }}>
                    {testingLinear ? 'Testing…' : 'Test connection'}
                  </button>
                  {linearTestResult && (
                    <span className={`text-[11px] ${linearTestResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                      {linearTestResult.ok ? `✓ Connected as ${linearTestResult.account_name}` : (linearTestResult.error || 'Connection failed')}
                    </span>
                  )}
                </div>
              )}
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                With Linear connected, you can ask PrismAI to create issues directly from the chat. For example: "create a Linear issue for the auth bug we discussed."
              </div>
            </>
          )}

          {tab === 'Jira' && (
            <>
              <Field
                label="Site URL"
                placeholder="yoursite.atlassian.net"
                value={jiraBaseUrl}
                onChange={setJiraBaseUrl}
                disabled={isTestAccount}
                hint="Your Jira Cloud site, e.g. yoursite.atlassian.net (with or without https://)."
              />
              <Field
                label="Account Email"
                placeholder="you@company.com"
                value={jiraEmail}
                onChange={setJiraEmail}
                disabled={isTestAccount}
                hint="The Atlassian account email that owns the API token."
              />
              <Field
                label="API Token"
                placeholder="Atlassian API token"
                value={jiraApiToken}
                onChange={setJiraApiToken}
                type="password"
                disabled={isTestAccount}
                hint="Create one at id.atlassian.com/manage-profile/security/api-tokens. Stored on your account."
              />
              <Field
                label="Default Project Key"
                placeholder="e.g. PRISM"
                value={jiraProjectKey}
                onChange={setJiraProjectKey}
                disabled={isTestAccount}
                hint="The project new issues are created in (you can override per request in chat)."
              />
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={testJira}
                  disabled={isTestAccount || testingJira || !jiraBaseUrl.trim() || !jiraEmail.trim() || !jiraApiToken.trim()}
                  className="text-[11px] px-3 py-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-40"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#cbd5e1' }}>
                  {testingJira ? 'Testing…' : 'Test connection'}
                </button>
                {jiraTestResult && (
                  <span className={`text-[11px] ${jiraTestResult.ok && !jiraTestResult.error ? 'text-emerald-400' : jiraTestResult.ok ? 'text-amber-400' : 'text-red-400'}`}>
                    {jiraTestResult.ok && !jiraTestResult.error
                      ? `✓ Connected as ${jiraTestResult.account_name}${jiraTestResult.project_ok ? ' · project OK' : ''}`
                      : (jiraTestResult.error || 'Connection failed')}
                  </span>
                )}
              </div>
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                With Jira connected, ask PrismAI to file issues from chat. For example: "create a Jira ticket for the login bug we discussed."
              </div>
            </>
          )}
          </>)}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}>
          <button onClick={onClose}
            className="text-xs px-4 py-2 rounded-lg text-gray-400 hover:text-white transition-colors"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
            {scope === 'personal' ? 'Cancel' : 'Close'}
          </button>
          {/* Workspace scope saves per-provider inline; the footer Save is personal-only. */}
          {scope === 'personal' && (
            <button onClick={save}
              disabled={isTestAccount}
              className="text-xs px-4 py-2 rounded-lg font-semibold text-white transition-all hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
              Save
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

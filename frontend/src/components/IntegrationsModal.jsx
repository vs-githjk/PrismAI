import { useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const TABS = ['Slack', 'Notion']

function Field({ label, placeholder, value, onChange, type = 'text', hint }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-400 mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl px-3 py-2.5 text-xs text-gray-200 outline-none border border-white/8 focus:border-sky-500/40 placeholder-gray-600"
        style={{ background: 'rgba(0,0,0,0.35)' }}
      />
      {hint && <p className="text-[10px] text-gray-600 mt-1.5 leading-relaxed">{hint}</p>}
    </div>
  )
}

export default function IntegrationsModal({ integrations, onSave, onClose }) {
  const [tab, setTab] = useState('Slack')
  const [slackWebhook, setSlackWebhook] = useState(integrations.slack_webhook || '')
  const [notionToken, setNotionToken] = useState(integrations.notion_token || '')
  const [notionPageId, setNotionPageId] = useState(integrations.notion_page_id || '')
  const [testingSlack, setTestingSlack] = useState(false)
  const [slackTestResult, setSlackTestResult] = useState(null) // 'ok' | 'err'

  function save() {
    const updated = { slack_webhook: slackWebhook, notion_token: notionToken, notion_page_id: notionPageId }
    localStorage.setItem('prism_slack_webhook', slackWebhook)
    localStorage.setItem('prism_notion_token', notionToken)
    localStorage.setItem('prism_notion_page_id', notionPageId)
    onSave(updated)
    onClose()
  }

  async function testSlack() {
    if (!slackWebhook.trim()) return
    setTestingSlack(true)
    setSlackTestResult(null)
    try {
      const res = await fetch(`${API}/export/slack`, {
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}>
      <div className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden animate-fade-in-up"
        style={{ background: '#0f172a', border: '1px solid rgba(255,255,255,0.1)' }}>

        {/* Header */}
        <div className="px-5 py-4 flex items-center justify-between"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
          <div>
            <h3 className="text-sm font-semibold text-white">Integrations</h3>
            <p className="text-[11px] text-gray-500 mt-0.5">Connect PrismAI to your tools — tokens stay in your browser.</p>
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300 transition-colors p-1">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex px-5 pt-4 gap-1">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                tab === t ? 'text-white' : 'text-gray-500 hover:text-gray-300'
              }`}
              style={tab === t ? { background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' } : {}}
            >
              {t === 'Slack' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
                </svg>
              )}
              {t === 'Notion' && (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.14c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z"/>
                </svg>
              )}
              {t}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="px-5 py-4 space-y-4">
          {tab === 'Slack' && (
            <>
              <Field
                label="Incoming Webhook URL"
                placeholder="https://hooks.slack.com/services/..."
                value={slackWebhook}
                onChange={setSlackWebhook}
                hint="Create an incoming webhook in your Slack app settings. Tokens are saved only in your browser."
              />
              {slackWebhook.trim() && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={testSlack}
                    disabled={testingSlack}
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
                hint="Create a Notion integration at notion.so/my-integrations and copy the secret token."
              />
              <Field
                label="Parent Page ID"
                placeholder="32-character page ID or full page URL"
                value={notionPageId}
                onChange={setNotionPageId}
                hint="The page where meeting analyses will be created. Share that page with your integration first."
              />
              <div className="rounded-xl p-3 text-[11px] text-gray-500 leading-relaxed"
                style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                PrismAI will create a new Notion page for each meeting with full analysis: summary, action items (as checkboxes), decisions, email draft, and health score.
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}>
          <button onClick={onClose}
            className="text-xs px-4 py-2 rounded-lg text-gray-400 hover:text-white transition-colors"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
            Cancel
          </button>
          <button onClick={save}
            className="text-xs px-4 py-2 rounded-lg font-semibold text-white transition-all hover:scale-[1.02]"
            style={{ background: 'linear-gradient(135deg, #0284c7, #0d9488)' }}>
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

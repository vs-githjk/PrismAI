// Browser-local integration tokens (Slack webhook, Notion token, auto-send flags),
// scoped PER USER. They used to be saved under global keys (prism_slack_webhook, …),
// so switching accounts on the same browser inherited the previous account's tokens.
// Scoping by user id isolates each account while keeping the "tokens stay in your
// browser" model (nothing is sent to our server).

const NAMES = ['slack_webhook', 'notion_token', 'notion_page_id', 'auto_send_slack', 'auto_send_notion']

function key(name, userId) {
  return userId ? `prism_${name}__${userId}` : `prism_${name}`
}

export function readIntegrationStore(userId) {
  return {
    slack_webhook: localStorage.getItem(key('slack_webhook', userId)) || '',
    notion_token: localStorage.getItem(key('notion_token', userId)) || '',
    notion_page_id: localStorage.getItem(key('notion_page_id', userId)) || '',
    auto_send_slack: localStorage.getItem(key('auto_send_slack', userId)) === '1',
    auto_send_notion: localStorage.getItem(key('auto_send_notion', userId)) === '1',
  }
}

export function writeIntegrationStore(userId, v) {
  localStorage.setItem(key('slack_webhook', userId), v.slack_webhook || '')
  localStorage.setItem(key('notion_token', userId), v.notion_token || '')
  localStorage.setItem(key('notion_page_id', userId), v.notion_page_id || '')
  localStorage.setItem(key('auto_send_slack', userId), v.auto_send_slack ? '1' : '0')
  localStorage.setItem(key('auto_send_notion', userId), v.auto_send_notion ? '1' : '0')
}

// One-time cleanup of the old global (unscoped) keys so a prior account's tokens
// can't bleed into a different account on this browser. Safe to call on every load.
export function purgeLegacyGlobalIntegrationKeys() {
  NAMES.forEach((n) => localStorage.removeItem(`prism_${n}`))
}

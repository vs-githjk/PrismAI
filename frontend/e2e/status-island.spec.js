import { test, expect } from '@playwright/test'

/**
 * E2E coverage for the StatusIsland + Live/Share sub-views feature (Phases C–F).
 * One focused test per behaviour — no backend needed; each test stubs only the
 * API it exercises. `?testRun=1` puts the app in the signed-in test account.
 *
 * Covers:
 *  C — error pill (Retry/Dismiss), live→island mapping, analysed island
 *  E — "Meeting saved" + "Reconnecting…" transient notifications
 *  D — pinned live row in the sidebar
 *  F — mobile: no idle pill + viewport-centered overlay (portal)
 */

const HOME = '/dashboard?testRun=1'
const LIVE = '/dashboard?testRun=1#live/abc123def456'
const ISLAND = '.dashboard-status-island'

// Neutralise the noisy auth/history calls so they don't error or hang. Tests
// override the endpoint they actually assert on, registered AFTER this so they win.
async function stubBackend(page) {
  const json = (body) => ({ status: 200, contentType: 'application/json', body })
  await page.route('**/workspaces', (r) => r.fulfill(json('[]')))
  await page.route('**/meetings**', (r) => r.fulfill(json('[]')))
  await page.route('**/insights**', (r) => r.fulfill(json('{}')))
  await page.route('**/knowledge/**', (r) => r.fulfill(json('{"docs":[]}')))
  await page.route('**/chat-sessions/**', (r) => r.fulfill(json('[]')))
  await page.route('**/calendar/**', (r) => r.fulfill(json('{}')))
}

// Open the new-meeting panel and kick off an analysis. A transcript with no
// "Name:" labels skips the speaker modal and runs immediately.
async function startAnalysis(page, transcript) {
  await page.getByRole('button', { name: 'New meeting' }).click()
  await page.getByPlaceholder('Paste your meeting transcript here...').fill(transcript)
  await page.getByRole('button', { name: 'Analyze Meeting' }).click()
}

const PLAIN_TRANSCRIPT =
  'We shipped the checkout feature on Friday and QA will cover the weekend before the launch.'

test.beforeEach(async ({ page }) => {
  await stubBackend(page)
})

test('Phase C: the dev status toggle is gone from the topbar', async ({ page }) => {
  await page.goto(HOME)
  // The old "◇ idle" debug button must not exist.
  await expect(page.locator('button', { hasText: '◇' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /cycle status island/i })).toHaveCount(0)
})

test('Phase C: desktop idle shows the tiny capsule pill', async ({ page }) => {
  await page.goto(HOME)
  const pill = page.locator(`header ${ISLAND}`).first()
  await expect(pill).toBeVisible()
  const box = await pill.boundingBox()
  expect(box.width).toBeLessThan(60) // the ~34px idle capsule, not an expanded pill
})

test('Phase C/E: failed analysis → error pill with Retry + Dismiss', async ({ page }) => {
  let calls = 0
  await page.route('**/analyze-stream', (r) => {
    calls += 1
    return r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' })
  })

  await page.goto(HOME)
  await startAnalysis(page, PLAIN_TRANSCRIPT)

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('Analysis failed')
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Dismiss error' })).toBeVisible()

  // Retry re-runs the analysis (the stub is hit again).
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect.poll(() => calls).toBeGreaterThanOrEqual(2)

  // Dismiss clears the error pill.
  await page.getByRole('button', { name: 'Dismiss error' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('Phase C/E: successful analysis → "Meeting saved" toast then Analysed island', async ({ page }) => {
  // Mock the SSE stream: one result chunk, then [DONE]. Small delay so the
  // Analysing state is observable.
  await page.route('**/analyze-stream', async (r) => {
    await new Promise((res) => setTimeout(res, 600))
    const body =
      'data: {"summary":"We shipped checkout and planned QA.","health_score":{"score":82},"agents_run":["summarizer"]}\n' +
      'data: [DONE]\n'
    return r.fulfill({ status: 200, contentType: 'text/event-stream', body })
  })

  await page.goto(HOME)
  await startAnalysis(page, PLAIN_TRANSCRIPT)

  // Analysing pill appears while the stream is open.
  await expect(page.locator(ISLAND).filter({ hasText: 'Analysing' })).toBeVisible()
  // On [DONE]: saveToHistory fires the "Meeting saved" notification…
  await expect(page.locator(ISLAND).filter({ hasText: 'Meeting saved' })).toBeVisible()
  // …which reverts (~2.5s) to the Analysed island.
  await expect(page.locator(ISLAND).filter({ hasText: 'Analysed' })).toBeVisible({ timeout: 6000 })
})

test('Phase C/D: live sub-view → in-shell title, Live island, pinned sidebar row', async ({ page }) => {
  await page.route('**/live/**', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'recording', transcript_lines: [], commands: [] }),
    }),
  )

  await page.goto(LIVE)

  // Topbar title renders in-shell (chrome inherited, not a standalone page).
  await expect(page.locator('header')).toContainText('Live meeting')
  // Island reflects the live state.
  await expect(page.locator(ISLAND).filter({ hasText: 'Live' })).toBeVisible()
  // Sidebar has the pinned live row (Phase D).
  await expect(page.locator('aside').getByText('Live meeting')).toBeVisible()
})

test('Phase C: live "done" status maps the island to Analysed', async ({ page }) => {
  await page.route('**/live/**', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'done',
        transcript: 'done transcript',
        result: { summary: 'Wrapped up.', health_score: { score: 70 } },
      }),
    }),
  )

  await page.goto(LIVE)
  await expect(page.locator(ISLAND).filter({ hasText: 'Analysed' })).toBeVisible()
})

test('Phase E: live disconnect fires a "Reconnecting…" notification', async ({ page }) => {
  // Abort the live poll → the first failed fetch fires the reconnect toast.
  await page.route('**/live/**', (r) => r.abort())

  await page.goto(LIVE)
  await expect(page.locator(ISLAND).filter({ hasText: 'Reconnecting' })).toBeVisible()
})

test('Phase F: mobile drops the idle pill and centers the active overlay on the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route('**/live/**', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'recording', transcript_lines: [], commands: [] }),
    }),
  )

  // Idle home on mobile: NO pill at all.
  await page.goto(HOME)
  await expect(page.locator(ISLAND)).toHaveCount(0)

  // Active state on mobile: the pill renders, but portaled OUT of the header
  // (into <body>) and centered on the true viewport.
  await page.goto(LIVE)
  const pill = page.locator(ISLAND).filter({ hasText: 'Live' })
  await expect(pill).toBeVisible()
  await expect(page.locator(`header ${ISLAND}`)).toHaveCount(0) // not inside the topbar
  const box = await pill.boundingBox()
  const center = box.x + box.width / 2
  expect(Math.abs(center - 195)).toBeLessThan(30) // ~viewport center (390 / 2)
})

import { test, expect } from '@playwright/test'

const EMAIL = 'new.user@example.com'
const PASSWORD = 'correct horse battery staple'

test('login submits email/password and displays invalid credentials', async ({ page }) => {
  let submitted
  await page.route('**/auth/v1/token?grant_type=password', async (route) => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 'invalid_credentials',
        msg: 'Invalid login credentials',
        message: 'Invalid login credentials',
      }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Welcome back.' })).toBeVisible()
  await dialog.getByLabel('Email').fill(EMAIL)
  await dialog.getByLabel('Password').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Log in', exact: true }).click()

  await expect(dialog.getByRole('alert')).toHaveText('Invalid login credentials')
  expect(submitted).toMatchObject({ email: EMAIL, password: PASSWORD })
})

const signupUser = (identities) => ({
  id: '11111111-1111-4111-8111-111111111111',
  aud: 'authenticated',
  role: 'authenticated',
  email: EMAIL,
  phone: '',
  app_metadata: { provider: 'email', providers: ['email'] },
  user_metadata: {},
  identities,
  created_at: '2026-07-30T00:00:00.000Z',
  updated_at: '2026-07-30T00:00:00.000Z',
  is_anonymous: false,
})

test('signup submits email/password and shows email confirmation', async ({ page }) => {
  let submitted
  await page.route('**/auth/v1/signup**', async (route) => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        // A genuinely new user comes back with an email identity.
        user: signupUser([{ id: '11111111-1111-4111-8111-111111111111', provider: 'email' }]),
        session: null,
      }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Get started', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Create your account.' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Google' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Microsoft' })).toBeVisible()
  await dialog.getByLabel('Email').fill(EMAIL)
  await dialog.getByLabel('Password').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Sign up', exact: true }).click()

  await expect(dialog.getByRole('heading', { name: 'Check your inbox.' })).toBeVisible()
  await expect(dialog).toContainText(EMAIL)
  expect(submitted).toMatchObject({ email: EMAIL, password: PASSWORD })
})

test('signup with an existing email shows an error, not the inbox screen', async ({ page }) => {
  await page.route('**/auth/v1/signup**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      // Supabase enumeration protection: existing email → user with no identities.
      body: JSON.stringify({ user: signupUser([]), session: null }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Get started', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email').fill(EMAIL)
  await dialog.getByLabel('Password').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Sign up', exact: true }).click()

  await expect(dialog.getByRole('alert')).toHaveText('An account with this email already exists. Log in instead.')
  await expect(dialog.getByRole('heading', { name: 'Check your inbox.' })).toHaveCount(0)

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('failed login on an OAuth-only account points at the provider button', async ({ page }) => {
  await page.route('**/auth/v1/token?grant_type=password', (route) =>
    route.fulfill({
      status: 400,
      contentType: 'application/json',
      body: JSON.stringify({ code: 'invalid_credentials', msg: 'Invalid login credentials' }),
    })
  )
  await page.route('**/auth/provider-hint', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ providers: ['google'] }),
    })
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email').fill(EMAIL)
  await dialog.getByLabel('Password').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Log in', exact: true }).click()

  await expect(dialog.getByRole('alert')).toHaveText(
    'This account uses Google — sign in with the Google button above.'
  )
})

test('forgot password sends a recovery email and shows the inbox screen', async ({ page }) => {
  let recoverBody
  await page.route('**/auth/v1/recover**', async (route) => {
    recoverBody = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()

  const dialog = page.getByRole('dialog')

  // Without an email, it nudges instead of firing a request
  await dialog.getByRole('button', { name: 'Forgot password?' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Enter your email above first')

  await dialog.getByLabel('Email').fill(EMAIL)
  await dialog.getByRole('button', { name: 'Forgot password?' }).click()

  await expect(dialog.getByRole('heading', { name: 'Check your inbox.' })).toBeVisible()
  await expect(dialog).toContainText('password reset link')
  expect(recoverBody).toMatchObject({ email: EMAIL })
})

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

test('signup submits email/password and shows email confirmation', async ({ page }) => {
  let submitted
  await page.route('**/auth/v1/signup**', async (route) => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: {
          id: '11111111-1111-4111-8111-111111111111',
          aud: 'authenticated',
          role: 'authenticated',
          email: EMAIL,
          phone: '',
          app_metadata: { provider: 'email', providers: ['email'] },
          user_metadata: {},
          identities: [],
          created_at: '2026-07-30T00:00:00.000Z',
          updated_at: '2026-07-30T00:00:00.000Z',
          is_anonymous: false,
        },
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

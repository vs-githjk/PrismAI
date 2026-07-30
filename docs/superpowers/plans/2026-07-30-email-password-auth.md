# Email/Password Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore secure email/password signup and login through Supabase Auth while preserving Google and Microsoft OAuth.

**Architecture:** The browser continues to use the installed Supabase client as the authentication backend. `SignupDialog` adds the removed email/password controls and calls `signUp` or `signInWithPassword`; every resulting session follows the existing `App.jsx` session listener, `apiFetch` bearer-token attachment, and FastAPI `require_user_id` validation. No password is sent to FastAPI or stored in a PrismAI table.

**Tech Stack:** React 18, Supabase JS 2.101.1, Playwright 1.61, Vite 5, existing FastAPI/Supabase bearer-token validation.

## Global Constraints

- Make no backend production-code or database-schema change.
- Add no dependency and no new test framework.
- Keep Google and Microsoft OAuth behavior and the current consent links unchanged.
- Add only email and password fields; omit username, confirm-password, and password-reset UI.
- Trim the email only. Never trim, transform, log, or persist the password outside Supabase Auth.
- Let the Supabase project password policy remain authoritative.
- Support both Supabase signup outcomes: immediate session or email confirmation.
- Keep `backend/recall_routes.py` and `backend/tests/test_recording.py` unstaged and out of every auth commit.
- Do not push without a separate user request.

---

## File map

| File | Responsibility |
|------|----------------|
| `frontend/src/components/SignupDialog.jsx` | Render OAuth plus email/password modes and invoke Supabase Auth. |
| `frontend/e2e/auth.spec.js` | Exercise the login error path, signup confirmation path, and served privacy disclosure without a real Supabase project. |
| `frontend/playwright.config.js` | Supply isolated fake browser-safe Supabase values to the Playwright Vite server. |
| `docs/legal/privacy-policy.md` | Keep the source legal draft accurate about managed email/password credentials. |
| `frontend/public/legal/privacy-policy.md` | Serve the same legal text in the application. |

---

### Task 1: Restore managed email/password authentication

**Files:**
- Create: `frontend/e2e/auth.spec.js`
- Modify: `frontend/playwright.config.js`
- Modify: `frontend/src/components/SignupDialog.jsx`

**Interfaces:**
- Consumes: `SignupDialog({ mode: 'signup' | 'login', onModeChange(nextMode), onClose() })`, already supplied by `LandingScreen`.
- Consumes: `supabase.auth.signUp`, `supabase.auth.signInWithPassword`, and the existing `supabase.auth.signInWithOAuth`.
- Produces: the normal Supabase persisted session consumed by `App.jsx` and `frontend/src/lib/api.js`.

- [ ] **Step 1: Configure an isolated fake Supabase origin for browser tests**

Add `env` to the existing `webServer` object in `frontend/playwright.config.js`:

```js
  webServer: {
    command: 'npm run dev -- --port 5180 --strictPort',
    url: 'http://localhost:5180',
    reuseExistingServer: true,
    timeout: 60_000,
    env: {
      ...process.env,
      VITE_SUPABASE_URL: 'http://127.0.0.1:54321',
      VITE_SUPABASE_ANON_KEY: 'playwright-anon-key',
    },
  },
```

These are deliberately fake public test values. Playwright intercepts every
request to this origin, so tests never reach a real Supabase project.

- [ ] **Step 2: Write the failing authentication tests**

Create `frontend/e2e/auth.spec.js`:

```js
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
  await page.route('**/auth/v1/signup', async (route) => {
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
```

- [ ] **Step 3: Run the new tests and verify the red state**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: both tests fail because the current SSO-only dialog has no email or
password controls and ignores the signup/login mode props. A timeout waiting for
`Email`, `Password`, `Welcome back.`, or `Create your account.` is the expected
failure; a network request to a real Supabase project is not.

- [ ] **Step 4: Restore the smallest form implementation**

In `frontend/src/components/SignupDialog.jsx`, change the icon import:

```js
import { Loader2, MailCheck, X } from 'lucide-react'
```

Add this field component immediately after `MicrosoftIcon`:

```jsx
function AuthField({ id, label, ...props }) {
  return (
    <div className="signup-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="signup-input" {...props} />
    </div>
  )
}
```

Change the component signature and add the form state:

```jsx
export default function SignupDialog({ mode = 'signup', onModeChange, onClose }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [loading, setLoading] = useState(false)
  const [verificationSent, setVerificationSent] = useState(false)
  const isSignup = mode === 'signup'
  const dashboardUrl = typeof window !== 'undefined'
    ? `${window.location.origin}${DASHBOARD_PATH}`
    : DASHBOARD_PATH
```

Keep the existing `signInWith(provider, options)` function unchanged. Add these
helpers after it:

```jsx
  const goToDashboard = () => {
    sessionStorage.removeItem(TEST_RUN_SESSION_KEY)
    sessionStorage.setItem(VISITED_KEY, '1')
    sessionStorage.setItem(UI_SCREEN_KEY, 'app')
    window.location.assign(DASHBOARD_PATH)
  }

  const switchMode = (nextMode) => {
    setPassword('')
    setSubmitError('')
    setVerificationSent(false)
    onModeChange?.(nextMode)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSubmitError('')
    if (!supabase) {
      setSubmitError('Supabase auth is not configured yet.')
      return
    }

    setLoading(true)
    try {
      if (isSignup) {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { emailRedirectTo: dashboardUrl },
        })
        if (error) throw error
        if (data.session) goToDashboard()
        else setVerificationSent(true)
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
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
```

Replace the current content after the close button with this mode-aware content.
The existing Google/Microsoft calls, CSS classes, and legal links are reused:

```jsx
        {verificationSent ? (
          <div className="signup-verification">
            <div className="signup-verification-icon" aria-hidden="true">
              <MailCheck />
            </div>
            <p className="signup-kicker">Verify your email</p>
            <h2 id="auth-dialog-title" className="signup-title">Check your inbox.</h2>
            <p className="signup-body">
              We sent a verification link to <strong>{email.trim()}</strong>.
              After you confirm, you will be sent to the dashboard.
            </p>
            <button type="button" className="signup-submit" onClick={onClose}>Done</button>
          </div>
        ) : (
          <>
            <p className="signup-kicker">PrismAI account</p>
            <h2 id="auth-dialog-title" className="signup-title">
              {isSignup ? 'Create your account.' : 'Welcome back.'}
            </h2>
            <p className="signup-body">
              {isSignup
                ? 'Save meeting history and open your dashboard after signup.'
                : 'Log in to continue to your dashboard.'}
            </p>

            <div className="signup-social-row">
              <button
                type="button"
                className="signup-provider-button"
                onClick={() => signInWith('google')}
                disabled={loading}
              >
                <GoogleIcon />
                Google
              </button>
              <button
                type="button"
                className="signup-provider-button"
                onClick={() => signInWith('azure', { scopes: 'email' })}
                disabled={loading}
              >
                <MicrosoftIcon />
                Microsoft
              </button>
            </div>

            <div className="signup-divider"><span>or</span></div>

            <form className="signup-form" onSubmit={handleSubmit}>
              <AuthField
                id="auth-email"
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value)
                  setSubmitError('')
                }}
              />
              <AuthField
                id="auth-password"
                label="Password"
                type="password"
                autoComplete={isSignup ? 'new-password' : 'current-password'}
                required
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value)
                  setSubmitError('')
                }}
              />

              {submitError && (
                <p className="signup-submit-error" role="alert">{submitError}</p>
              )}

              <button type="submit" className="signup-submit" disabled={loading}>
                {loading && <Loader2 className="signup-spinner" aria-hidden="true" />}
                {isSignup ? 'Sign up' : 'Log in'}
              </button>
            </form>

            <p className="signup-mode-note">
              {isSignup ? 'Already have an account?' : 'New to PrismAI?'}
              <button
                type="button"
                onClick={() => switchMode(isSignup ? 'login' : 'signup')}
              >
                {isSignup ? 'Log in' : 'Sign up'}
              </button>
            </p>

            <p className="signup-consent">
              By continuing, you agree to our{' '}
              <a href="#terms" onClick={onClose}>Terms of Service</a> and{' '}
              <a href="#privacy" onClick={onClose}>Privacy Policy</a>.
            </p>
          </>
        )}
```

- [ ] **Step 5: Run the focused tests and verify green**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: `2 passed`. Confirm the captured bodies contain the exact password
typed in the test and that no request escapes the fake Supabase origin.

- [ ] **Step 6: Run the frontend production build**

Run from `frontend`:

```powershell
npm run build
```

Expected: exit code `0`. The existing large-chunk warning is allowed; compilation
errors are not.

- [ ] **Step 7: Commit only the auth UI and test harness**

```powershell
git add -- frontend/src/components/SignupDialog.jsx frontend/e2e/auth.spec.js frontend/playwright.config.js
git diff --cached --check
git commit -m "Restore email password authentication"
```

Before committing, `git diff --cached --name-only` must list exactly those three
files. Do not stage the two local transcript files.

---

### Task 2: Correct the served credential disclosure and complete verification

**Files:**
- Modify: `frontend/e2e/auth.spec.js`
- Modify: `docs/legal/privacy-policy.md`
- Modify: `frontend/public/legal/privacy-policy.md`

**Interfaces:**
- Consumes: the existing `/#privacy` hash route and `LegalPage` Markdown renderer.
- Produces: identical source and served privacy-policy copies that accurately describe Supabase-managed credentials.

- [ ] **Step 1: Add a failing privacy-disclosure check**

Append to `frontend/e2e/auth.spec.js`:

```js
test('privacy policy explains managed email/password credentials', async ({ page }) => {
  await page.goto('/#privacy')
  await expect(page.getByRole(
    'heading',
    { name: 'PrismAI Privacy Policy', exact: true },
  )).toBeVisible()
  await expect(page.getByText(
    /Supabase Auth processes the credentials on our behalf/i,
  )).toBeVisible()
  await expect(page.getByText(
    /PrismAI does not receive or store your plaintext password/i,
  )).toBeVisible()
})
```

- [ ] **Step 2: Run the test and verify the red state**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: the first two auth tests pass and the privacy test fails because the
current draft mentions only Google/Microsoft SSO.

- [ ] **Step 3: Update both policy copies with the same paragraph**

In both `docs/legal/privacy-policy.md` and
`frontend/public/legal/privacy-policy.md`, replace the current
`**a. Account & identity.**` paragraph with:

```markdown
**a. Account & identity.** Regardless of sign-in method, we receive your email
address and a unique account identifier. When you use Google or Microsoft SSO,
we do not receive or store your Google/Microsoft password. When you create an
account with email and password, Supabase Auth processes the credentials on our
behalf. PrismAI does not receive or store your plaintext password.
```

- [ ] **Step 4: Verify the policies are identical and the tests pass**

Run from the repository root:

```powershell
git diff --no-index --exit-code docs/legal/privacy-policy.md frontend/public/legal/privacy-policy.md
```

Expected: exit code `0`.

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: `3 passed`.

- [ ] **Step 5: Verify the unchanged backend token boundary**

Run from `backend`:

```powershell
python -m unittest tests.test_auth
```

Expected: all existing auth tests pass. No backend auth test or production file
should change because email/password and OAuth sessions use the same bearer token.

- [ ] **Step 6: Run final static and build checks**

Run from the repository root:

```powershell
git diff --check
git diff --name-only
```

Expected: no whitespace errors. Before the policy commit, the unstaged list may
include the two user-owned transcript files; they must remain untouched.

Run from `frontend`:

```powershell
npm run build
```

Expected: exit code `0`, with only the existing large-chunk warning allowed.

- [ ] **Step 7: Commit only the policy and its regression check**

```powershell
git add -- frontend/e2e/auth.spec.js docs/legal/privacy-policy.md frontend/public/legal/privacy-policy.md
git diff --cached --check
git commit -m "Document managed email password authentication"
```

Before committing, `git diff --cached --name-only` must list exactly those three
files.

- [ ] **Step 8: Record the deployment-only Supabase requirements**

The implementation handoff must state all four operational requirements:

1. Enable the Supabase Email provider.
2. Allow the production and local `/dashboard` URLs as auth redirects.
3. Configure production SMTP when email confirmation is enabled.
4. Configure password strength, rate limits, CAPTCHA, and leaked-password
   protection in Supabase.

No repository secret, service-role key, real password, or real test account is
created by this plan.

---

## Final acceptance checklist

- [ ] Landing "Log in" opens email/password login.
- [ ] Landing "Get started" opens email/password account creation.
- [ ] The dialog can switch between login and signup.
- [ ] Login calls only the Supabase password-grant endpoint.
- [ ] Signup calls only the Supabase signup endpoint and handles `session: null`.
- [ ] Google and Microsoft buttons remain available.
- [ ] The privacy policy accurately describes managed credentials.
- [ ] No FastAPI endpoint, database migration, custom password storage, or dependency was added.
- [ ] Playwright auth checks, backend auth tests, and the frontend build pass.
- [ ] `backend/recall_routes.py` and `backend/tests/test_recording.py` remain unstaged.

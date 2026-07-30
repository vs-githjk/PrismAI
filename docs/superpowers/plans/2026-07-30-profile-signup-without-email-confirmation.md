# Profile Signup Without Email Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect a username and preferred name during email/password signup, show the preferred name in the dashboard, and let correctly configured Supabase projects create an immediate session without email confirmation.

**Architecture:** The browser continues to call Supabase Auth directly. Signup adds `username` and `full_name` to Supabase user metadata while the email and unchanged password remain managed by Supabase Auth; login remains email/password only. The existing session listener, bearer-token path, backend verification, OAuth providers, and no-session safety fallback remain unchanged.

**Tech Stack:** React 18, Supabase JS 2.101.1, Playwright 1.61, Vite 5, existing FastAPI/Supabase bearer-token validation.

## Global Constraints

- Supabase Auth remains the only system that receives and manages passwords.
- Email/password login accepts email only; do not imply or add username login.
- Add only required Username and Preferred name signup fields.
- Trim username, preferred name, and email. Never trim, transform, log, or persist the password outside Supabase Auth.
- Store signup metadata as `username` and `full_name`; do not use metadata for authorization or RLS.
- Do not add a backend authentication endpoint, profile table, database migration, dependency, phone number, date of birth, password confirmation, or custom password rules.
- Keep Google and Microsoft OAuth, the mode switch, consent links, existing session plumbing, and the no-session confirmation fallback.
- Keep both privacy-policy copies byte-identical.
- Do not modify `frontend/e2e/status-island.spec.js`.
- Keep `backend/recall_routes.py` and `backend/tests/test_recording.py` unstaged and out of every commit.
- Do not delete or modify existing Supabase users without separate explicit authorization.
- Do not push without a separate user request.

---

## File Map

| File | Responsibility |
| --- | --- |
| `frontend/e2e/auth.spec.js` | Verify profile metadata submission, immediate-session navigation, visible preferred name, OAuth preservation, and existing login errors. |
| `frontend/src/components/SignupDialog.jsx` | Collect signup profile fields and send them as Supabase Auth metadata. |
| `frontend/src/components/dashboard/DashboardSidebar.jsx` | Prefer the supplied profile name over the email local part. |
| `frontend/src/index.css` | Keep the taller four-field signup card usable on short viewports. |
| `docs/legal/privacy-policy.md` | Disclose the additional signup profile data in the source policy. |
| `frontend/public/legal/privacy-policy.md` | Serve the identical disclosure in the application. |

---

### Task 1: Collect and display signup profile metadata

**Files:**
- Modify: `frontend/e2e/auth.spec.js`
- Modify: `frontend/src/components/SignupDialog.jsx`
- Modify: `frontend/src/components/dashboard/DashboardSidebar.jsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `SignupDialog({ mode, onModeChange, onClose })`, the existing Supabase client, and the existing `goToDashboard()` helper.
- Produces: Supabase `user_metadata.username` and `user_metadata.full_name`; dashboard account-name precedence of full name, username, then email local part.

- [ ] **Step 1: Replace the confirmation-first signup test with an immediate-session profile test**

In `frontend/e2e/auth.spec.js`, add these constants after `PASSWORD`:

```js
const USERNAME = 'newuser'
const PREFERRED_NAME = 'New User'
```

Replace the existing signup test with:

```js
test('signup submits profile metadata and opens the dashboard', async ({ page }) => {
  let submitted
  await page.route('**/auth/v1/signup**', async (route) => {
    submitted = route.request().postDataJSON()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'playwright-access-token',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: 1785373200,
        refresh_token: 'playwright-refresh-token',
        user: {
          id: '11111111-1111-4111-8111-111111111111',
          aud: 'authenticated',
          role: 'authenticated',
          email: EMAIL,
          phone: '',
          app_metadata: { provider: 'email', providers: ['email'] },
          user_metadata: {
            username: USERNAME,
            full_name: PREFERRED_NAME,
          },
          identities: [],
          created_at: '2026-07-30T00:00:00.000Z',
          updated_at: '2026-07-30T00:00:00.000Z',
          is_anonymous: false,
        },
      }),
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Get started', exact: true }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Create your account.' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Google' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Microsoft' })).toBeVisible()
  await dialog.getByLabel('Username').fill(`  ${USERNAME}  `)
  await dialog.getByLabel('Preferred name').fill(`  ${PREFERRED_NAME}  `)
  await dialog.getByLabel('Email').fill(`  ${EMAIL}  `)
  await dialog.getByLabel('Password').fill(PASSWORD)
  await dialog.getByRole('button', { name: 'Sign up', exact: true }).click()

  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(page.getByText(PREFERRED_NAME, { exact: true }).first()).toBeVisible()
  expect(submitted).toMatchObject({
    email: EMAIL,
    password: PASSWORD,
    data: {
      username: USERNAME,
      full_name: PREFERRED_NAME,
    },
  })
})
```

- [ ] **Step 2: Run the focused test and verify the red state**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: the login test passes and the signup test fails because the dialog has no Username or Preferred name controls. A failure caused by a real network request is not an acceptable red state.

- [ ] **Step 3: Add the two signup-only fields and metadata**

In `frontend/src/components/SignupDialog.jsx`, add profile state beside the current email state:

```jsx
  const [username, setUsername] = useState('')
  const [preferredName, setPreferredName] = useState('')
```

Change the signup options to:

```jsx
          options: {
            data: {
              username: username.trim(),
              full_name: preferredName.trim(),
            },
            emailRedirectTo: dashboardUrl,
          },
```

Immediately before the existing Email field, add:

```jsx
              {isSignup && (
                <>
                  <AuthField
                    id="auth-username"
                    label="Username"
                    type="text"
                    autoComplete="username"
                    required
                    pattern=".*\S.*"
                    value={username}
                    onChange={(event) => {
                      setUsername(event.target.value)
                      setSubmitError('')
                    }}
                  />
                  <AuthField
                    id="auth-preferred-name"
                    label="Preferred name"
                    type="text"
                    autoComplete="name"
                    required
                    pattern=".*\S.*"
                    value={preferredName}
                    onChange={(event) => {
                      setPreferredName(event.target.value)
                      setSubmitError('')
                    }}
                  />
                </>
              )}
```

Do not add these fields in login mode. Keep the no-session branch and its current inbox UI as a defensive fallback.

- [ ] **Step 4: Display the preferred name in the dashboard sidebar**

In `frontend/src/components/dashboard/DashboardSidebar.jsx`, replace `accountName` with:

```jsx
  const accountName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.username ||
    user?.email?.split('@')[0] ||
    (isDemoMode ? 'Demo session' : 'Guest')
```

- [ ] **Step 5: Keep the taller dialog usable on short screens**

In the existing `.signup-dialog` rule in `frontend/src/index.css`, add:

```css
  max-height: calc(100vh - 2rem);
  overflow-y: auto;
```

- [ ] **Step 6: Run the focused authentication suite**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
```

Expected: `2 passed`. Confirm the captured request contains trimmed email and metadata plus the exact unmodified password, and the immediate-session response reaches `/dashboard`.

- [ ] **Step 7: Run the frontend production build**

Run from `frontend`:

```powershell
npm run build
```

Expected: exit code `0`. The existing large-chunk warning is allowed.

- [ ] **Step 8: Commit only the profile signup UI and test**

```powershell
git add -- frontend/e2e/auth.spec.js frontend/src/components/SignupDialog.jsx frontend/src/components/dashboard/DashboardSidebar.jsx frontend/src/index.css
git diff --cached --name-only
git diff --cached --check
git commit -m "Collect signup profile metadata"
```

The staged file list must contain exactly the four files above.

---

### Task 2: Update the account-data disclosure and complete repository verification

**Files:**
- Modify: `docs/legal/privacy-policy.md`
- Modify: `frontend/public/legal/privacy-policy.md`

**Interfaces:**
- Consumes: the signup metadata names `username` and `full_name` from Task 1.
- Produces: byte-identical source and served privacy-policy disclosures.

- [ ] **Step 1: Update both policy copies with the same paragraph**

In both policy files, replace the current `**a. Account & identity.**` paragraph with:

```markdown
**a. Account & identity.** Regardless of sign-in method, we receive your email
address and a unique account identifier. When you create an account with email
and password, we also receive the username and preferred name you provide, and
Supabase Auth processes your credentials on our behalf. When you use Google or
Microsoft SSO, we do not receive or store your Google/Microsoft password.
PrismAI does not receive or store your plaintext password.
```

- [ ] **Step 2: Verify the policy copies are byte-identical**

Run from the repository root:

```powershell
git diff --no-index --exit-code docs/legal/privacy-policy.md frontend/public/legal/privacy-policy.md
```

Expected: exit code `0`.

- [ ] **Step 3: Verify the unchanged backend authentication boundary**

Run from `backend`:

```powershell
python -m unittest tests.test_auth
```

Expected: all 16 existing auth tests pass. No backend auth file should change.

- [ ] **Step 4: Repeat the focused frontend checks**

Run from `frontend`:

```powershell
npm run test:e2e -- auth.spec.js
npm run build
```

Expected: `2 passed`, then a successful production build with only the existing chunk-size warning allowed.

- [ ] **Step 5: Check the complete repository diff**

Run from the repository root:

```powershell
git diff --check
git diff --name-only
```

Expected before the policy commit: only the two policy files from this task plus the two user-owned transcript files may be unstaged. The transcript files must remain untouched.

- [ ] **Step 6: Commit only the two policy copies**

```powershell
git add -- docs/legal/privacy-policy.md frontend/public/legal/privacy-policy.md
git diff --cached --name-only
git diff --cached --check
git commit -m "Document signup profile metadata"
```

The staged file list must contain exactly the two policy files.

---

### Task 3: Disable email confirmation in the Supabase project

**Files:**
- No repository files.

**Interfaces:**
- Consumes: the existing Supabase project used by `VITE_SUPABASE_URL`.
- Produces: email/password signup responses that contain an immediate session.

- [ ] **Step 1: Change only the Email provider confirmation setting**

In Supabase Dashboard, open the project used by the frontend, navigate to
Authentication provider settings for Email, turn **Confirm Email** off, and
save. Do not disable the Email provider, password policy, rate limits, or attack
protection.

- [ ] **Step 2: Verify the saved setting**

Reload the Email provider settings page and confirm **Confirm Email** remains
off. Do not create a real test account or delete the existing unconfirmed user
as part of automated execution.

- [ ] **Step 3: Record the existing-account caveat**

The implementation handoff must state that the earlier unconfirmed account may
need to be manually confirmed or explicitly deleted before the same email can
be registered again. Account deletion requires separate authorization.

---

## Final Acceptance Checklist

- [ ] Signup collects required Username, Preferred name, Email, and Password.
- [ ] Login remains Email and Password only.
- [ ] Signup sends trimmed `username`, `full_name`, and email with the exact password.
- [ ] An immediate Supabase session navigates to `/dashboard`.
- [ ] The dashboard displays the preferred name, then username, then email local part.
- [ ] Google and Microsoft OAuth and consent links remain.
- [ ] The no-session confirmation UI remains only as a safety fallback.
- [ ] Both privacy-policy copies are identical and disclose the profile fields.
- [ ] No backend endpoint, profile table, migration, dependency, or custom password storage is added.
- [ ] Focused Playwright auth tests, backend auth tests, and frontend build pass.
- [ ] Supabase Confirm Email is off and the rest of the Email provider security settings remain enabled.
- [ ] User-owned transcript edits remain unstaged and untouched.
- [ ] Nothing is pushed without a separate user request.

# Email/Password Authentication — Design Spec

**Date:** 2026-07-30  
**Branch:** `fixed-changes`  
**Status:** Approved — ready for implementation  
**Scope:** Restore email/password signup and login through Supabase Auth while
keeping Google and Microsoft OAuth unchanged.

## Problem

The landing-page authentication dialog currently offers only Google and
Microsoft. `LandingScreen` still distinguishes signup from login and passes that
mode into `SignupDialog`, but the dialog ignores it after email/password support
was removed in commit `dd6220d`.

PrismAI already has the rest of the flow:

- the Supabase browser client persists and refreshes sessions;
- `App.jsx` restores sessions and reacts to sign-in events;
- `apiFetch` attaches the Supabase access token;
- FastAPI validates that token through `require_user_id`;
- the removed form's CSS remains in `frontend/src/index.css`.

## Design

Restore the former flow at its existing seam: `SignupDialog.jsx`.

- Keep Google and Microsoft buttons.
- Accept the existing `mode` and `onModeChange` props.
- Add email and password fields only. Do not restore the unused username field.
- Login with `supabase.auth.signInWithPassword({ email, password })`.
- Create accounts with `supabase.auth.signUp`, setting
  `emailRedirectTo` to `/dashboard`.
- If signup returns a session, open the dashboard immediately. If it returns no
  session, show the existing "Check your inbox" confirmation state.
- Use native required/email validation and let the Supabase project password
  policy remain authoritative.
- Preserve the current Terms of Service and Privacy Policy consent text.
- Never trim, transform, log, or store the password outside Supabase Auth.

No FastAPI signup/login endpoint, password table, schema migration, dependency,
or custom password hashing is added. Email/password sessions produce the same
Supabase access token as OAuth sessions, so the existing backend validation is
already the backend for this feature.

## Security and data flow

1. The browser sends the email and password directly to Supabase Auth over TLS.
2. Supabase stores and validates the managed credential.
3. Supabase returns a session or sends a confirmation email.
4. The frontend sends only the session access token to PrismAI's API.
5. `backend/auth.py` validates the token and derives the authenticated user ID.

Passwords must never enter FastAPI, PrismAI application tables, logs,
`localStorage`, or `sessionStorage`. Keep the Supabase service-role key
backend-only.

The displayed privacy policy will be corrected to cover email/password accounts:
Supabase processes the credential, while PrismAI does not receive or store the
plaintext password.

## Files

| File | Change |
|------|--------|
| `frontend/src/components/SignupDialog.jsx` | Restore the email/password form and managed Supabase calls. |
| `frontend/e2e/auth.spec.js` | Cover login submission/error and signup confirmation behavior. |
| `frontend/playwright.config.js` | Give auth tests an isolated fake Supabase URL/key. |
| `docs/legal/privacy-policy.md` | Correct account-credential disclosure. |
| `frontend/public/legal/privacy-policy.md` | Keep the served policy copy identical. |

No backend production file changes.

## Supabase project configuration

- Enable the Email provider.
- Allow the deployed `/dashboard` URL and local dashboard URL as auth redirects.
- Keep email confirmation enabled or disabled intentionally; the UI supports
  either outcome.
- Configure production SMTP before relying on confirmation email delivery.
- Configure password strength, rate limits, CAPTCHA, and leaked-password
  protection centrally in Supabase.

## Testing

Use the existing Playwright setup; add no test framework.

1. Login mode sends a password-grant request and displays a mocked invalid
   credentials response.
2. Signup mode sends a signup request and displays "Check your inbox" when the
   mocked response has no session.
3. Run the frontend production build.
4. Run the existing backend auth tests because all protected requests still use
   the same bearer-token boundary.

Before deployment, manually verify signup with the project's real confirmation
setting, confirmation-link redirect, successful login, wrong-password handling,
OAuth regression, refresh persistence, sign-out, and one authenticated API call.

## Out of scope

- Username, display-name, and confirm-password fields.
- Password-reset UI.
- Adding a password to an existing OAuth-only identity.
- Replacing Google-only prompts on invite and signed-out share/demo surfaces.
- Custom password rules or credential storage in PrismAI.

These can be added only when a concrete user need justifies the extra surface.

## Acceptance criteria

1. "Log in" opens email/password login; "Get started" opens account creation.
2. Users can switch between login and account creation inside the dialog.
3. Valid credentials create the normal persisted Supabase session and open the
   dashboard.
4. Invalid credentials produce a visible error without navigation.
5. Signup supports both immediate-session and email-confirmation configurations.
6. Google and Microsoft OAuth behavior is unchanged.
7. No password reaches PrismAI's backend or storage.
8. Focused Playwright checks and the frontend production build pass.

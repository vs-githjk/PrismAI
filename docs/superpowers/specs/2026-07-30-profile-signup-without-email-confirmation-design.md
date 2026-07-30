# Profile Signup Without Email Confirmation

**Date:** 2026-07-30
**Status:** Approved

## Goal

Let beta users create a PrismAI account with a username, preferred name,
email address, and password, then enter the dashboard immediately without
following an email-confirmation link.

## Decisions

- Supabase Auth remains the only system that receives and manages passwords.
- Email confirmation is disabled in the Supabase Email provider settings.
- Users sign in with email and password. Supabase password authentication does
  not support usernames, so username login is deliberately deferred.
- Username and preferred name are profile metadata, not authentication or
  authorization data.
- Google and Microsoft OAuth remain available.
- No backend authentication endpoint, profile table, database migration, or
  dependency is added.

## Signup UI

Signup displays four required fields:

1. Username
2. Preferred name
3. Email
4. Password

No phone number, date of birth, password confirmation, or custom password
rules are added. Supabase's configured password policy remains authoritative.
The existing OAuth buttons, mode switch, and legal consent links remain.

Login continues to display only email and password, with an email label that
does not imply username login.

## Data Flow

Signup calls `supabase.auth.signUp` with:

- `email`: trimmed
- `password`: unchanged
- `options.data.username`: trimmed
- `options.data.full_name`: the trimmed preferred name

Supabase stores the email and password credentials in Auth and stores the two
profile values in `auth.users.raw_user_meta_data`. The existing application
already reads `user_metadata.full_name` for meeting ownership, viewer names,
and stand-in attribution.

With Confirm Email disabled, signup returns a session and the existing
dashboard navigation runs immediately. The current no-session inbox screen is
retained only as a defensive fallback if the Supabase project is accidentally
configured to require confirmation.

Login continues to call `supabase.auth.signInWithPassword` directly with the
trimmed email and unchanged password. Sessions continue through the existing
Supabase listener, bearer-token attachment, and FastAPI token validation.

## Display Behavior

The dashboard sidebar displays the first available value in this order:

1. `user_metadata.full_name`
2. `user_metadata.username`
3. The email local part

Other existing consumers of `full_name` require no change.

## Username Semantics

For this beta, username is a display handle:

- It is not a login identifier.
- It is not guaranteed globally unique.
- It must not be used in RLS, authorization, or other security decisions
  because Supabase user metadata is user-editable.

True username login would require a normalized unique profile table plus a
private, rate-limited backend or Edge Function that resolves the identifier
without exposing email addresses. That work is outside this change.

## Privacy and Security

Both privacy-policy copies will disclose that PrismAI receives the user's
username and preferred name in addition to the email address and account ID.
The copies must remain byte-identical.

Disabling Confirm Email means PrismAI does not prove that a new user controls
the supplied email address. This is an explicitly accepted beta tradeoff.
Password strength, rate limits, CAPTCHA, and leaked-password protection remain
Supabase configuration responsibilities. Passwords are never logged, placed in
application tables, or sent to FastAPI.

## Error Handling

- Native required and email input validation handles empty or malformed fields.
- Supabase errors appear in the existing accessible dialog alert.
- The submit button remains disabled while a request is running.
- If signup unexpectedly returns no session, the existing confirmation
  fallback is shown instead of navigating without authentication.

## Verification

The focused Playwright authentication suite will verify:

- Login still submits the exact email and password and displays a mocked
  invalid-credentials response.
- Signup submits trimmed username and preferred-name metadata with the exact
  password.
- A mocked immediate Supabase session navigates to `/dashboard`.
- Google and Microsoft buttons remain present.

The frontend production build must pass, both privacy-policy files must compare
identically, and the existing backend auth tests must remain green. The
unrelated status-island baseline failures remain out of scope.

## Deployment Steps

Before testing:

1. In Supabase Dashboard, open Authentication, the Email provider settings,
   and turn Confirm Email off.
2. Delete the earlier unconfirmed test account or manually confirm it before
   attempting to register the same email again.
3. Keep the Email provider, password policy, rate limits, and attack-protection
   settings enabled.

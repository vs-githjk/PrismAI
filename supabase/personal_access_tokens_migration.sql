-- personal_access_tokens: long-lived, user-issued API keys that let an external
-- tool (the Claude / ChatGPT MCP connector) authenticate AS a PrismAI user and
-- pull ONLY that user's data. Our normal auth is a ~1h Supabase session JWT,
-- which a user can't paste into an external app — so this table backs a
-- paste-able credential.
--
-- Security model:
--   * We store ONLY a SHA-256 hash of the token (`token_hash`), never the
--     plaintext. The plaintext is shown to the user exactly once at creation.
--   * `token_prefix` is a short non-secret display label (e.g. "prism_pat_AbC1…")
--     so the UI can list tokens recognizably without revealing the secret.
--   * Revocation is a soft delete (`revoked_at`) so a leaked token dies instantly.
--
-- workspace_id: '' (empty string, NOT null) = the token spans ALL of the user's
-- workspaces + personal (v1 default). A future per-workspace-scoped token would
-- set this to a specific workspace id — the column ships now so that's a pure
-- additive feature with NO later migration. (Workspace convention: text, ''=all.)
--
-- RLS ENABLED with NO policies: the backend reads/writes via the service-role
-- client (auth.supabase), which bypasses RLS; the anon/authenticated browser keys
-- are denied. The token hash is a secret — there is no direct browser access.
--
-- NOT in schema.sql, so this does NOT auto-apply on boot — run it manually
-- (SQL editor or python supabase/migrate.py). Idempotent.

create table if not exists personal_access_tokens (
  id           uuid primary key default gen_random_uuid(),
  user_id      text not null,
  name         text not null default 'API token',
  token_hash   text not null unique,
  token_prefix text not null,
  workspace_id text not null default '',
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz
);

-- Hot path is resolve-by-hash on every MCP request; the unique index on
-- token_hash already covers that. This index speeds the per-user list view.
create index if not exists idx_pat_user on personal_access_tokens (user_id);

alter table personal_access_tokens enable row level security;

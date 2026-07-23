-- Per-workspace integrations (#2) — an admin (workspace owner) connects Jira /
-- Linear / Slack / Teams / Notion once per workspace, and every action taken in
-- that workspace's meetings routes there (falling back to the acting user's
-- personal integration when the workspace hasn't configured one). Personal
-- (non-workspace) meetings are unchanged.
--
-- One row per (workspace, provider). `config` mirrors the user_settings field
-- names so the resolver output is a drop-in for the existing tool paths.
-- workspace_id is TEXT (workspace-model convention — workspace_members.user_id /
-- workspace_id are text). Idempotent. Run any time after workspace_migration.sql.
--
-- SECURITY: this table holds secrets (API tokens, webhooks). All access is
-- server-side via the service-role key (SUPABASE_KEY), which BYPASSES RLS.
-- We enable RLS with NO policies → the anon/authenticated client keys the
-- frontend holds are denied entirely, so a signed-in user can never read
-- another workspace's tokens directly. Owner-only WRITES are additionally
-- enforced in the API layer (_require_owner).

create table if not exists workspace_integrations (
  workspace_id  text not null,
  provider      text not null,          -- 'jira' | 'linear' | 'slack' | 'teams' | 'notion'
  config        jsonb not null default '{}'::jsonb,
  enabled       boolean not null default true,
  configured_by text,                   -- user_id of the owner who set it (audit)
  updated_at    timestamptz not null default now(),
  primary key (workspace_id, provider)
);

create index if not exists workspace_integrations_ws_idx on workspace_integrations(workspace_id);

-- Deny all client-key access; the service-role backend bypasses this. No policies
-- on purpose — nothing should reach this table except server-side (service role).
alter table workspace_integrations enable row level security;

-- OAuth 2.1 authorization-server tables for the MCP connector (Milestone B).
-- Claude.ai's custom-connector UI only supports OAuth (no static-header/token
-- entry), so we run a minimal AS: Dynamic Client Registration + PKCE auth-code
-- flow + refresh rotation. Identity is Supabase (Google/MS SSO); we issue our own
-- opaque tokens bound to a user_id, which `resolve_mcp_user` validates.
--
-- All three tables store only SHA-256 HASHES of secrets (codes/tokens), never the
-- plaintext. RLS ENABLED with NO policies → service-role backend only (anon/
-- authenticated browser keys denied). NOT in schema.sql — run manually or via
-- python supabase/migrate.py (added to MIGRATION_ORDER). Idempotent.

-- Registered OAuth clients (Claude registers itself via DCR).
create table if not exists oauth_clients (
  client_id           text primary key,
  client_secret_hash  text,                       -- null for public (PKCE) clients
  client_name         text,
  redirect_uris       jsonb not null default '[]', -- allowlist of exact redirect URIs
  created_at          timestamptz not null default now()
);

-- Short-lived authorization codes (PKCE). Consumed exactly once at /token.
create table if not exists oauth_auth_codes (
  code_hash       text primary key,
  client_id       text not null,
  user_id         text not null,
  redirect_uri    text not null,
  code_challenge  text not null,                   -- PKCE S256 challenge
  scope           text not null default 'meetings:read',
  expires_at      timestamptz not null,
  used            boolean not null default false,
  created_at      timestamptz not null default now()
);

-- Issued access + refresh tokens. Refresh rotates on use.
create table if not exists oauth_tokens (
  id                   uuid primary key default gen_random_uuid(),
  access_token_hash    text not null unique,
  refresh_token_hash   text unique,
  client_id            text not null,
  user_id              text not null,
  scope                text not null default 'meetings:read',
  access_expires_at    timestamptz not null,
  refresh_expires_at   timestamptz,
  revoked_at           timestamptz,
  created_at           timestamptz not null default now()
);

create index if not exists idx_oauth_tokens_user on oauth_tokens (user_id);
create index if not exists idx_oauth_codes_expiry on oauth_auth_codes (expires_at);

alter table oauth_clients    enable row level security;
alter table oauth_auth_codes enable row level security;
alter table oauth_tokens     enable row level security;

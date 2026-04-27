-- Run this in Supabase Dashboard → SQL Editor.
-- Safe to re-run: every statement is idempotent (IF NOT EXISTS / IF NOT EXISTS column).
-- This consolidates calendar_migration.sql + tools_migration.sql + bot_commands_migration.sql
-- into one script that works whether or not the tables already exist.

-- ── user_settings ────────────────────────────────────────────────────────────

create table if not exists user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  updated_at timestamptz not null default now()
);

alter table user_settings add column if not exists google_access_token    text;
alter table user_settings add column if not exists google_refresh_token   text;
alter table user_settings add column if not exists google_token_expires_at timestamptz;
alter table user_settings add column if not exists calendar_connected      boolean not null default false;
alter table user_settings add column if not exists linear_api_key          text;
alter table user_settings add column if not exists slack_bot_token         text;

alter table user_settings enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'user_settings' and policyname = 'users can manage own settings'
  ) then
    create policy "users can manage own settings"
      on user_settings for all
      using (auth.uid() = user_id)
      with check (auth.uid() = user_id);
  end if;
end
$$;

-- ── bot_sessions ─────────────────────────────────────────────────────────────

create table if not exists bot_sessions (
  bot_id     text primary key,
  user_id    uuid references auth.users(id) on delete cascade,
  status     text not null default 'joining',
  error      text,
  transcript text,
  result     jsonb,
  commands   jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Backfill columns that may be missing if the table was created before this migration
alter table bot_sessions add column if not exists created_at timestamptz not null default now();
alter table bot_sessions add column if not exists updated_at timestamptz not null default now();
alter table bot_sessions add column if not exists commands   jsonb not null default '[]'::jsonb;
alter table bot_sessions add column if not exists result     jsonb;
alter table bot_sessions add column if not exists transcript text;
alter table bot_sessions add column if not exists error      text;
alter table bot_sessions add column if not exists user_id    uuid references auth.users(id) on delete cascade;

create index if not exists bot_sessions_user_id_idx on bot_sessions(user_id);

alter table bot_sessions enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where tablename = 'bot_sessions' and policyname = 'users can manage own bot sessions'
  ) then
    create policy "users can manage own bot sessions"
      on bot_sessions for all
      using (auth.uid() = user_id)
      with check (auth.uid() = user_id);
  end if;
end
$$;

-- ── append_bot_command RPC ────────────────────────────────────────────────────

create or replace function append_bot_command(p_bot_id text, p_command jsonb)
returns void
language sql
as $$
  update bot_sessions
  set
    commands   = coalesce(commands, '[]'::jsonb) || jsonb_build_array(p_command),
    updated_at = now()
  where bot_id = p_bot_id;
$$;

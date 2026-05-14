-- Consolidated idempotent schema for PrismAI.
-- Every statement uses IF NOT EXISTS or DO $$ guards — safe to run multiple times.
-- Executed automatically on backend startup via migrations.py.

-- ── meetings + chats: add user_id ────────────────────────────────────────────
alter table if exists meetings
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table if exists chats
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

create index if not exists meetings_user_id_idx on meetings(user_id);
create index if not exists chats_user_id_idx on chats(user_id);

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'chats_meeting_id_user_id_key'
  ) then
    alter table chats add constraint chats_meeting_id_user_id_key unique (meeting_id, user_id);
  end if;
end
$$;

-- ── user_settings ─────────────────────────────────────────────────────────────
create table if not exists user_settings (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  updated_at timestamptz not null default now()
);

alter table user_settings add column if not exists google_access_token     text;
alter table user_settings add column if not exists google_refresh_token    text;
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

-- ── action_refs ───────────────────────────────────────────────────────────────
create table if not exists action_refs (
  id         bigserial primary key,
  user_id    uuid references auth.users(id),
  meeting_id bigint references meetings(id) on delete cascade,
  action_item text,
  tool       text,
  external_id text,
  resolved   boolean default false,
  created_at timestamptz default now()
);

create index if not exists action_refs_user_id_idx on action_refs(user_id);

-- ── bot_sessions ──────────────────────────────────────────────────────────────
create table if not exists bot_sessions (
  bot_id         text primary key,
  user_id        uuid references auth.users(id) on delete cascade,
  status         text not null default 'joining',
  error          text,
  transcript     text,
  result         jsonb,
  commands       jsonb not null default '[]'::jsonb,
  memory_summary text,
  live_state     jsonb,
  live_token     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- Backfill columns that may be missing on tables created before this migration
alter table bot_sessions add column if not exists user_id        uuid references auth.users(id) on delete cascade;
alter table bot_sessions add column if not exists error          text;
alter table bot_sessions add column if not exists transcript     text;
alter table bot_sessions add column if not exists result         jsonb;
alter table bot_sessions add column if not exists commands       jsonb not null default '[]'::jsonb;
alter table bot_sessions add column if not exists created_at     timestamptz not null default now();
alter table bot_sessions add column if not exists updated_at     timestamptz not null default now();
alter table bot_sessions add column if not exists memory_summary text;
alter table bot_sessions add column if not exists live_state     jsonb;
alter table bot_sessions add column if not exists live_token     text;

create index if not exists bot_sessions_user_id_idx    on bot_sessions(user_id);
create unique index if not exists bot_sessions_live_token_idx on bot_sessions(live_token);

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

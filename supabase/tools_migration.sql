-- Add tool integration columns to user_settings
-- Run this in the Supabase SQL editor.

alter table user_settings add column if not exists linear_api_key text;
alter table user_settings add column if not exists slack_bot_token text;

-- Bot sessions: persistent bot state (replaces in-memory bot_store)
create table if not exists bot_sessions (
  bot_id text primary key,
  user_id uuid references auth.users(id) on delete cascade,
  status text not null default 'joining',
  error text,
  transcript text,
  result jsonb,
  commands jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists bot_sessions_user_id_idx on bot_sessions(user_id);

alter table bot_sessions enable row level security;

create policy "users can manage own bot sessions"
  on bot_sessions for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

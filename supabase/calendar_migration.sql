-- user_settings: stores per-user integration tokens (calendar, future integrations)
-- Run this in the Supabase SQL editor before enabling Google Calendar features.

create table if not exists user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  google_access_token  text,
  google_refresh_token text,
  google_token_expires_at timestamptz,
  calendar_connected   boolean not null default false,
  updated_at           timestamptz not null default now()
);

-- Only the owner can read/write their own row (RLS is bypassed by service_role key on backend)
alter table user_settings enable row level security;

create policy "users can manage own settings"
  on user_settings for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

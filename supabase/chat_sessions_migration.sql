-- Per-meeting ephemeral chat sessions.
-- Replaces the single-row-per-(meeting,user) `chats` model:
-- multiple rows per meeting are allowed; backend prunes to the 3 most recent.

create extension if not exists "pgcrypto";

create table if not exists chat_sessions (
    id uuid primary key default gen_random_uuid(),
    meeting_id bigint not null,
    user_id uuid not null references auth.users(id) on delete cascade,
    messages jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_chat_sessions_meeting_user_created
    on chat_sessions (meeting_id, user_id, created_at desc);

alter table chat_sessions enable row level security;

drop policy if exists "Users access their own chat sessions" on chat_sessions;
create policy "Users access their own chat sessions"
    on chat_sessions
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

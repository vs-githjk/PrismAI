-- Stand-in async proxy (Feature A): a workspace member who can't attend a meeting
-- has Prism represent them. `proxy_representations` holds the per-meeting stand-in
-- (drafted from action items + the user's profile, approved before delivery, then
-- delivered by a scheduled bot). `proxy_profiles` is the user's standing context the
-- bot draws from and enriches on approval.
--
-- Convention (matches workspace_members / meetings): user_id + workspace_id are TEXT,
-- not uuid. Backend uses the service-role key, so these tables are written server-side;
-- RLS policies below are defense-in-depth for any direct client access.

create extension if not exists "pgcrypto";

-- ── Standing per-user proxy profile ──────────────────────────────────────────
create table if not exists proxy_profiles (
    user_id        text primary key,
    role_focus     text default '',
    standing_notes text default '',
    structured     jsonb not null default '{}'::jsonb,
    updated_at     timestamptz not null default now()
);

alter table proxy_profiles enable row level security;
drop policy if exists "Users manage their own proxy profile" on proxy_profiles;
create policy "Users manage their own proxy profile"
    on proxy_profiles for all
    using (auth.uid()::text = user_id)
    with check (auth.uid()::text = user_id);

-- ── Per-meeting stand-in representation ───────────────────────────────────────
create table if not exists proxy_representations (
    id                uuid primary key default gen_random_uuid(),
    workspace_id      text,                       -- null = personal meeting
    meeting_url       text not null,              -- NORMALIZED — the bind key
    calendar_event_id text,
    meeting_label     text default '',
    scheduled_for     timestamptz,                -- meeting start (for join_at + expiry)
    join_at           timestamptz,                -- when the scheduled bot will join
    author_user_id    text not null,
    author_name       text not null default '',
    author_email      text default '',
    draft_body        text default '',            -- working text (conversation output)
    approved_body     text default '',            -- frozen on approve; what gets delivered
    structured        jsonb not null default '{}'::jsonb,
    status            text not null default 'draft'
                      check (status in ('draft','pending','delivered','expired','canceled')),
    scheduled_bot_id  text,                       -- Recall bot created to deliver this
    delivered_bot_id  text,                       -- bot that actually delivered (audit)
    created_at        timestamptz not null default now(),
    approved_at       timestamptz,
    delivered_at      timestamptz
);

-- Persisted composer conversation (the "saves that chat to memory" part), so
-- reopening a stand-in resumes the chat instead of regenerating from scratch.
alter table proxy_representations
    add column if not exists messages jsonb not null default '[]'::jsonb;

create index if not exists idx_proxy_rep_bind
    on proxy_representations (workspace_id, meeting_url, status);
create index if not exists idx_proxy_rep_author
    on proxy_representations (author_user_id, status);

alter table proxy_representations enable row level security;
drop policy if exists "Authors manage their own stand-ins" on proxy_representations;
create policy "Authors manage their own stand-ins"
    on proxy_representations for all
    using (auth.uid()::text = author_user_id)
    with check (auth.uid()::text = author_user_id);

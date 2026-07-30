-- #9 Notifications — persistent notification center (bell + unread + history).
-- Also mirrored in backend/schema.sql (auto-applied on boot); this file is the
-- manual-runner copy for supabase/migrate.py. Idempotent, safe to re-run.
--
-- user_id / workspace_id are TEXT (workspace convention). Stored rows cover
-- event-driven types (meeting_ready / bot_issue / workspace_activity /
-- meeting_soon); action_due is synthesized fresh at GET-time (never stored).
-- RLS ENABLED with NO policies: anon/authenticated keys are denied; the
-- service-role backend bypasses RLS and scopes every query by user_id.

create table if not exists notifications (
  id           bigserial primary key,
  user_id      text not null,
  type         text not null,
  title        text,
  body         text,
  meeting_id   bigint,
  link         text,
  workspace_id text,
  read         boolean not null default false,
  dedup_key    text,
  created_at   timestamptz not null default now()
);
create index if not exists notifications_user_idx on notifications(user_id, read, created_at desc);
-- Idempotent event hooks: (user_id, dedup_key) inserts once. NULLs are distinct
-- in Postgres, so non-deduped rows (dedup_key null) never collide.
create unique index if not exists notifications_dedup_idx on notifications(user_id, dedup_key);
alter table notifications enable row level security;

-- Web Push subscriptions (for the meeting_soon out-of-app reminder).
create table if not exists push_subscriptions (
  id         bigserial primary key,
  user_id    text not null,
  endpoint   text not null unique,
  p256dh     text not null,
  auth       text not null,
  created_at timestamptz not null default now()
);
create index if not exists push_subscriptions_user_idx on push_subscriptions(user_id);
alter table push_subscriptions enable row level security;

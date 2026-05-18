-- Workspace + meeting-bot dedup tables.
-- Idempotent: safe to re-run.

create extension if not exists "pgcrypto";

create table if not exists workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by uuid not null references auth.users(id) on delete cascade,
  invite_token uuid not null default gen_random_uuid(),
  created_at timestamptz not null default now()
);

create unique index if not exists workspaces_invite_token_idx on workspaces(invite_token);
create index if not exists workspaces_created_by_idx on workspaces(created_by);

create table if not exists workspace_members (
  workspace_id uuid not null references workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  user_email text not null default '',
  role text not null default 'member',
  joined_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create index if not exists workspace_members_user_id_idx on workspace_members(user_id);
create index if not exists workspace_members_workspace_id_idx on workspace_members(workspace_id);

-- Per-meeting bot registration, used by /join-meeting for workspace dedup
-- so two teammates joining the same meeting don't both spawn Recall bots.
create table if not exists meeting_bots (
  bot_id text primary key,
  meeting_url text not null,
  owner_user_id uuid not null references auth.users(id) on delete cascade,
  status text not null default 'joining',
  created_at timestamptz not null default now()
);

create index if not exists meeting_bots_meeting_url_idx on meeting_bots(meeting_url);
create index if not exists meeting_bots_owner_user_id_idx on meeting_bots(owner_user_id);
create index if not exists meeting_bots_status_idx on meeting_bots(status);

-- meetings.workspace_id: optional FK so meetings can be scoped to a workspace.
-- ON DELETE SET NULL: deleting a workspace leaves the meetings behind in the
-- owner's personal scope. Matches workspace_routes.py:172 expectation.
alter table meetings
  add column if not exists workspace_id uuid references workspaces(id) on delete set null;

-- meetings.recorded_by_user_id: who actually pressed "join meeting". Used by
-- the UI to attribute shared-bot meetings to the teammate who recorded them.
alter table meetings
  add column if not exists recorded_by_user_id uuid references auth.users(id) on delete set null;

create index if not exists meetings_workspace_id_idx on meetings(workspace_id);
create index if not exists meetings_recorded_by_user_id_idx on meetings(recorded_by_user_id);

create table action_refs (
  id bigserial primary key,
  user_id uuid references auth.users(id),
  meeting_id bigint references meetings(id) on delete cascade,
  action_item text,
  tool text,
  external_id text,
  resolved boolean default false,
  created_at timestamptz default now()
);
create index on action_refs(user_id);

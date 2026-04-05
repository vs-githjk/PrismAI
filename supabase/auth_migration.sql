alter table meetings
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table chats
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

create index if not exists meetings_user_id_idx on meetings(user_id);
create index if not exists chats_user_id_idx on chats(user_id);
create unique index if not exists chats_user_id_meeting_id_idx on chats(user_id, meeting_id);

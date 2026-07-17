-- custom_keyterms: a per-user / per-workspace glossary of proper nouns used to
-- ground Deepgram nova-3 transcription (keyterm prompting). When a user corrects
-- a mis-transcribed term in chat (e.g. "MD Academy" -> "FDE Academy" via the
-- correct_meeting_text tool), the corrected spelling is stored here so FUTURE
-- meetings transcribe it right at the source. Read by recall_routes._gather_keyterms.
--
-- workspace_id: '' (empty string, NOT null) = personal, matching the workspace
-- convention used elsewhere (proxy_profiles) so the composite unique key works
-- without partial indexes. user_id / workspace_id are text (workspace convention).
--
-- RLS ENABLED with NO policies: the backend reads/writes via the service-role
-- client (auth.supabase), which bypasses RLS; the anon/authenticated client keys
-- are denied. There is no direct browser access to this table.
--
-- NOT in schema.sql, so this does NOT auto-apply on boot — run it manually
-- (SQL editor or python supabase/migrate.py). Idempotent.

create table if not exists custom_keyterms (
  id          bigserial primary key,
  user_id     text not null,
  workspace_id text not null default '',
  term        text not null,
  created_at  timestamptz not null default now(),
  unique (user_id, workspace_id, term)
);

create index if not exists idx_custom_keyterms_user on custom_keyterms (user_id);
create index if not exists idx_custom_keyterms_ws   on custom_keyterms (workspace_id);

alter table custom_keyterms enable row level security;

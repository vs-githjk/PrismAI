-- cross_meeting_cache: durable cache for the B2 semantic cross-meeting synthesis
-- (cross_meeting_synthesis.get_semantic_insights). ONE cached Haiku pass over a
-- scope's recent meeting digests → narrative + topics + open_threads +
-- decision_evolution. Recompute only when the meeting SET changes.
--
-- scope_id: "user:{user_id}" for a personal Trend view, "ws:{workspace_id}" for a
-- workspace one (prefixed so a user_id can never collide with a workspace_id). text.
-- meeting_set_hash: sha256 of the sorted meeting ids that were synthesized — a new
-- meeting changes the hash → cache miss → recompute. The backend keeps exactly ONE
-- row per scope (upserts the current hash, deletes the others).
-- payload: the synthesized JSON (+ generated_at). No secrets.
--
-- RLS ENABLED with NO policies: the backend reads/writes via the service-role client
-- (auth.supabase), which bypasses RLS; the anon/authenticated keys are denied. No
-- direct browser access.
--
-- NOT in schema.sql, so this does NOT auto-apply on boot — run it manually
-- (SQL editor or python supabase/migrate.py). Idempotent.

create table if not exists cross_meeting_cache (
  scope_id          text not null,
  meeting_set_hash  text not null,
  payload           jsonb not null,
  generated_at      timestamptz not null default now(),
  primary key (scope_id, meeting_set_hash)
);

create index if not exists idx_cross_meeting_cache_scope on cross_meeting_cache (scope_id);

alter table cross_meeting_cache enable row level security;

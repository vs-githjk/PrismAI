-- supabase/personas_migration.sql
-- Personas feature: per-user override + workspace default + audit on meetings.
-- Apply BEFORE deploying backend code that references these columns
-- (resolve_persona queries persona_preset / default_persona).

-- 1. User-level persona override.
alter table user_settings
  add column if not exists persona_preset text default 'default',
  add column if not exists persona_custom_prompt text;

alter table user_settings
  drop constraint if exists user_settings_persona_preset_check;
alter table user_settings
  add constraint user_settings_persona_preset_check
  check (persona_preset in ('default', 'concise', 'formal', 'cheeky', 'socratic', 'custom'));

alter table user_settings
  drop constraint if exists user_settings_persona_custom_len;
alter table user_settings
  add constraint user_settings_persona_custom_len
  check (persona_custom_prompt is null or char_length(persona_custom_prompt) <= 500);

-- 2. Workspace-level default. Preset-only — no 'custom' allowed.
alter table workspaces
  add column if not exists default_persona text default 'default';

alter table workspaces
  drop constraint if exists workspaces_default_persona_check;
alter table workspaces
  add constraint workspaces_default_persona_check
  check (default_persona in ('default', 'concise', 'formal', 'cheeky', 'socratic'));

-- 3. Audit field on meetings. Nullable — pre-feature rows stay NULL.
--    No CHECK constraint so renamed/removed presets don't break old rows.
alter table meetings
  add column if not exists persona_used text;

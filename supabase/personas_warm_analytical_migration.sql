-- supabase/personas_warm_analytical_migration.sql
-- Extend the persona vocabulary with two new presets: 'warm' and 'analytical'.
-- Mirrors the drop-then-recreate pattern in personas_migration.sql so existing
-- rows referencing the old values keep validating; no data migration needed.
-- Run AFTER personas_migration.sql. Idempotent: safe to re-run.

-- 1. user_settings.persona_preset — full vocabulary including 'custom'.
alter table user_settings
  drop constraint if exists user_settings_persona_preset_check;
alter table user_settings
  add constraint user_settings_persona_preset_check
  check (persona_preset in (
    'default', 'concise', 'formal', 'cheeky', 'socratic',
    'warm', 'analytical',
    'custom'
  ));

-- 2. workspaces.default_persona — preset-only (no 'custom' — admin can't
--    inject arbitrary text into all members' meetings).
alter table workspaces
  drop constraint if exists workspaces_default_persona_check;
alter table workspaces
  add constraint workspaces_default_persona_check
  check (default_persona in (
    'default', 'concise', 'formal', 'cheeky', 'socratic',
    'warm', 'analytical'
  ));

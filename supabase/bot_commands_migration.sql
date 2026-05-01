-- Atomic command append for bot_sessions.commands (avoids read-modify-write race).
-- Run this in the Supabase SQL Editor.

create or replace function append_bot_command(p_bot_id text, p_command jsonb)
returns void
language sql
as $$
  update bot_sessions
  set
    commands   = coalesce(commands, '[]'::jsonb) || jsonb_build_array(p_command),
    updated_at = now()
  where bot_id = p_bot_id;
$$;

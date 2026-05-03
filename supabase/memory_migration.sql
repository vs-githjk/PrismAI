-- Memory system migration — adds two columns to bot_sessions.
-- Run in Supabase SQL Editor before deploying the memory system.
-- Safe to run multiple times (IF NOT EXISTS guards).

ALTER TABLE bot_sessions
  ADD COLUMN IF NOT EXISTS memory_summary TEXT,
  ADD COLUMN IF NOT EXISTS live_state JSONB;

-- Run this in the Supabase SQL editor.
-- Adds live_token to bot_sessions so live-share links survive server restarts.
ALTER TABLE bot_sessions ADD COLUMN IF NOT EXISTS live_token TEXT;
CREATE INDEX IF NOT EXISTS idx_bot_sessions_live_token ON bot_sessions(live_token);

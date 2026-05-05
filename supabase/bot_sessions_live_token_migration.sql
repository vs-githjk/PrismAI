-- Add live_token column to bot_sessions so the live-share index survives Render restarts.
-- Run this in the Supabase SQL Editor.

alter table bot_sessions add column if not exists live_token text unique;

create index if not exists bot_sessions_live_token_idx on bot_sessions(live_token);

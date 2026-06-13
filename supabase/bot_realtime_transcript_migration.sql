-- Durable realtime transcript — survives Render free-tier restarts.
-- The live bot accumulates the meeting transcript in memory (bot_store). If the
-- server restarts mid-meeting OR during post-meeting processing, that buffer is lost,
-- and when Recall.ai produced 0 recordings the analysis has nothing to fall back on
-- ("Transcript processing timed out"). This column persists the streamed transcript so
-- _process_bot_transcript can recover it via _db_load after any restart.
-- Run in the Supabase SQL editor AFTER recording_migration.sql. Idempotent: safe to re-run.

alter table bot_sessions
  add column if not exists realtime_transcript text;        -- newline-joined "Speaker: text" lines

-- Meeting Recording Playback — adds Recall.ai recording metadata to meetings
-- and a server-trust staging column on bot_sessions for transcript segments.
-- Run in the Supabase SQL editor AFTER all previous workspace + knowledge migrations.
-- Idempotent: safe to re-run.

alter table meetings
  add column if not exists recall_bot_id text,
  add column if not exists recording_provider text,         -- 'recall' | future: 'supabase'
  add column if not exists transcript_segments jsonb;       -- Segment[] | null

alter table bot_sessions
  add column if not exists transcript_segments jsonb;       -- staging area, server-pulled at save time

create index if not exists meetings_recall_bot_id_idx
  on meetings(recall_bot_id) where recall_bot_id is not null;

-- meeting_bots.workspace_id — make a bot's workspace durable so a server-side persist
-- (e.g. after a restart that wiped the in-memory bot_store, or when a dashboard tab
-- crashed/closed before saving) can promote the analysed meeting into the RIGHT
-- workspace instead of falling back to personal. Stored as text to match the
-- workspace_members convention (workspace ids are text, not uuid). Idempotent.

alter table meeting_bots add column if not exists workspace_id text;

-- One-time recovery (no-op on any other database): a meeting whose analysis completed
-- but whose dashboard tab crashed before POST /meetings, so it was never promoted. Stamp
-- its workspace so the startup backfill (recover_active_bots) restores it into the
-- correct workspace (Prism Developers) rather than personal.
update meeting_bots
   set workspace_id = 'b58ac24e-ec95-473e-80b9-7d4a75de30a1'
 where bot_id = '234b6897-8d42-455c-9bb1-7aabbce2da0b'
   and workspace_id is null;

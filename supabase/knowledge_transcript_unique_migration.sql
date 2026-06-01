-- supabase/knowledge_transcript_unique_migration.sql
-- Prevents a race where two concurrent save_meeting calls both pass the
-- application-level "already indexed?" check and double-index the same
-- transcript. The Python code's idempotency check + this DB-level guard
-- together close the window. The conflict is caught and treated as a
-- successful idempotent return.
-- Run AFTER knowledge_meeting_source_migration.sql.

create unique index if not exists knowledge_docs_meeting_transcript_unique
  on knowledge_docs (meeting_id)
  where source_type = 'meeting_transcript' and deleted_at is null;

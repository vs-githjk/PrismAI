-- supabase/knowledge_contextual_migration.sql
-- Phase 2: store original content separately from the embedded-with-preamble version.
-- Citations show ORIGINAL content; embeddings are generated from the preamble + content.
-- Run AFTER knowledge_meeting_source_migration.sql.

alter table knowledge_chunks
  add column if not exists embedded_content text;

-- Backfill: for existing chunks (which were embedded without a preamble),
-- embedded_content equals content. Future inserts will set it explicitly.
update knowledge_chunks
  set embedded_content = content
  where embedded_content is null;

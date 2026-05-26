-- supabase/knowledge_meeting_source_migration.sql
-- Allow 'meeting_transcript' as a knowledge_docs source_type.
-- Run in Supabase SQL editor AFTER knowledge_workspace_migration.sql.

alter table knowledge_docs
  drop constraint if exists knowledge_docs_source_type_check;

alter table knowledge_docs
  add constraint knowledge_docs_source_type_check
  check (source_type in ('pdf', 'docx', 'txt', 'url', 'notion', 'gdrive', 'meeting_transcript'));

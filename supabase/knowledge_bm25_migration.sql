-- supabase/knowledge_bm25_migration.sql
-- Phase 3 of smart-RAG v1: BM25 lexical index over chunks.
-- Run AFTER knowledge_workspace_migration.sql and knowledge_contextual_migration.sql.
-- Apply in the Supabase SQL editor.

-- 1. Generated tsvector column (auto-updated by Postgres on every write).
alter table knowledge_chunks
  add column if not exists content_tsv tsvector
  generated always as (
    to_tsvector('english', coalesce(embedded_content, content))
  ) stored;

-- 2. GIN index for fast `@@` lookups.
create index if not exists knowledge_chunks_tsv_idx
  on knowledge_chunks using gin(content_tsv);

-- 3. Sibling RPC: same caller/workspace scoping as knowledge_search, but
--    BM25 ranking via ts_rank_cd instead of cosine similarity.
drop function if exists knowledge_search_bm25(text, uuid, uuid[], bigint, int);

create or replace function knowledge_search_bm25(
    query_text text,
    caller_user_id uuid,
    caller_workspace_ids uuid[],
    meeting_filter bigint,
    match_limit int
)
returns table (
    id uuid,
    doc_id uuid,
    content text,
    embedded_content text,
    metadata jsonb,
    chunk_index int,
    doc_name text,
    source_type text,
    score float,
    match_type text
)
language sql stable
as $$
    select
        c.id,
        c.doc_id,
        c.content,
        c.embedded_content,
        c.metadata,
        c.chunk_index,
        d.name as doc_name,
        d.source_type,
        ts_rank_cd(c.content_tsv, plainto_tsquery('english', query_text))::float as score,
        'bm25'::text as match_type
    from knowledge_chunks c
    join knowledge_docs d on d.id = c.doc_id
    where d.deleted_at is null
      and (
        c.user_id = caller_user_id
        or d.workspace_id = any(caller_workspace_ids)
      )
      and (meeting_filter is null or d.meeting_id = meeting_filter)
      and c.content_tsv @@ plainto_tsquery('english', query_text)
    order by score desc
    limit match_limit;
$$;

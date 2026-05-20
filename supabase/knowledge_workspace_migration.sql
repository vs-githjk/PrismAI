-- Knowledge Base — Workspace scoping migration
-- Run in the Supabase SQL editor AFTER knowledge_migration.sql.
--
-- The base knowledge migration scoped docs to a single user_id. For a workspace
-- product, knowledge must be shareable across a team. This migration:
--   1. Adds workspace_id to knowledge_docs + knowledge_chunks (null = personal)
--   2. Updates the knowledge_search RPC to return chunks the caller can see:
--      their own personal docs OR any doc shared into a workspace they belong to
--   3. Widens RLS so workspace members can read shared docs/chunks
--
-- Sensitivity tiers are reused from the base migration. The application layer
-- (knowledge_proactive.py) still enforces public/internal/confidential rules.


-- ── 1. Add workspace_id columns ───────────────────────────────────────────────
alter table knowledge_docs
  add column if not exists workspace_id uuid references workspaces(id) on delete set null;

-- Denormalized onto chunks so the similarity search can filter by workspace
-- in the same query without joining back to knowledge_docs.
alter table knowledge_chunks
  add column if not exists workspace_id uuid references workspaces(id) on delete set null;

create index if not exists knowledge_docs_workspace_id_idx   on knowledge_docs(workspace_id);
create index if not exists knowledge_chunks_workspace_id_idx on knowledge_chunks(workspace_id);


-- ── 2. RLS — let workspace members read shared docs/chunks ────────────────────
-- The backend uses the service-role key (bypasses RLS), so these policies are a
-- safety net for any anon-key access path. Owner keeps full management rights;
-- workspace members get read access to docs shared into their workspace.

drop policy if exists "workspace members can read shared docs" on knowledge_docs;
create policy "workspace members can read shared docs"
  on knowledge_docs for select
  using (
    auth.uid() = user_id
    or workspace_id in (
      select workspace_id from workspace_members where user_id = auth.uid()
    )
  );

drop policy if exists "workspace members can read shared chunks" on knowledge_chunks;
create policy "workspace members can read shared chunks"
  on knowledge_chunks for select
  using (
    auth.uid() = user_id
    or workspace_id in (
      select workspace_id from workspace_members where user_id = auth.uid()
    )
  );


-- ── 3. Workspace-aware similarity search RPC ──────────────────────────────────
-- Adds caller_workspace_ids: the set of workspaces the caller belongs to.
-- A chunk matches when it is the caller's own (user_id) OR shared into one of
-- their workspaces. The Python caller (knowledge_service.search_knowledge)
-- resolves the caller's workspace_ids and passes them in.

create or replace function knowledge_search(
  query_embedding      vector(1536),
  caller_user_id       uuid,
  caller_workspace_ids uuid[] default '{}',
  meeting_filter       bigint default null,
  match_limit          int    default 5,
  min_score            float  default 0.0
)
returns table (
  chunk_id     uuid,
  doc_id       uuid,
  doc_name     text,
  source_type  text,
  sensitivity  text,
  workspace_id uuid,
  meeting_id   bigint,
  content      text,
  metadata     jsonb,
  score        float
)
language sql
stable
as $$
  select
    c.id   as chunk_id,
    c.doc_id,
    d.name as doc_name,
    d.source_type,
    d.sensitivity,
    d.workspace_id,
    d.meeting_id,
    c.content,
    c.metadata,
    1 - (c.embedding <=> query_embedding) as score
  from knowledge_chunks c
  join knowledge_docs d on d.id = c.doc_id
  where d.deleted_at is null
    and d.status = 'ready'
    and (
      c.user_id = caller_user_id
      or d.workspace_id = any(caller_workspace_ids)
    )
    and (
      meeting_filter is null
      or d.meeting_id is null
      or d.meeting_id = meeting_filter
    )
    and (1 - (c.embedding <=> query_embedding)) >= min_score
  order by c.embedding <=> query_embedding
  limit match_limit;
$$;

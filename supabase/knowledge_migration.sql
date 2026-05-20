-- Knowledge Base migration
-- Adds document storage, vector embeddings, and query audit log for meeting-aware RAG.
-- Run in the Supabase SQL editor AFTER auth_migration.sql and tools_migration.sql.
--
-- Setup checklist
-- ───────────────
-- 1. Run this file in the Supabase SQL editor
-- 2. Add OPENAI_API_KEY and TAVILY_API_KEY to backend/.env
-- 3. Add the "drive.readonly" scope to your Google Cloud OAuth consent screen
--    (no code change — the existing google_access_token will pick it up after the
--     user re-consents)


-- ── 0. pgvector extension ─────────────────────────────────────────────────────

create extension if not exists vector;


-- ── 1. knowledge_docs ─────────────────────────────────────────────────────────
-- One row per uploaded document or connected source.
-- meeting_id = NULL  →  global user library
-- meeting_id = <id>  →  pinned to a specific meeting
--
-- Sensitivity tiers:
--   'public'       → may appear in any meeting, proactive surfacing allowed
--   'internal'     → default; proactive surfacing allowed only when pinned to the meeting
--   'confidential' → never proactively surfaced; only on-demand (explicit "Prism, …" lookup)
--                    AND only when the doc is pinned to the meeting OR the global library
--                    is explicitly invoked.

create table if not exists knowledge_docs (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  meeting_id      bigint references meetings(id) on delete cascade,

  name            text not null,
  source_type     text not null
    check (source_type in ('pdf', 'docx', 'txt', 'url', 'notion', 'gdrive')),

  source_url      text,           -- original URL (url / notion / gdrive sources)
  file_path       text,           -- Supabase Storage path (pdf / docx / txt uploads)
  size_bytes      bigint,         -- for the 50 MB / user-quota guard
  embedding_model text not null default 'text-embedding-3-small',
  -- stored so re-embedding after a model change is targeted, not a full wipe

  sensitivity     text not null default 'internal'
    check (sensitivity in ('public', 'internal', 'confidential')),

  chunk_count     int not null default 0,
  status          text not null default 'processing'
    check (status in ('processing', 'ready', 'error', 'stale')),

  error_message   text,           -- populated when status = 'error'
  last_synced_at  timestamptz not null default now(),
  deleted_at      timestamptz,    -- soft delete; nightly cleanup hard-deletes after 30 days
  created_at      timestamptz not null default now()
);

create index if not exists knowledge_docs_user_id_idx    on knowledge_docs(user_id);
create index if not exists knowledge_docs_meeting_id_idx on knowledge_docs(meeting_id);
create index if not exists knowledge_docs_status_idx     on knowledge_docs(status);

-- Partial index — only "live" docs participate in retrieval/listing.
create index if not exists knowledge_docs_active_idx
  on knowledge_docs(user_id, deleted_at)
  where deleted_at is null;

alter table knowledge_docs enable row level security;

create policy "users can manage own knowledge docs"
  on knowledge_docs for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── 2. knowledge_chunks ───────────────────────────────────────────────────────
-- Chunked text + vector embeddings.
-- user_id is denormalized here so the similarity search can filter by user
-- in the same query without joining back to knowledge_docs.

create table if not exists knowledge_chunks (
  id           uuid primary key default gen_random_uuid(),
  doc_id       uuid not null references knowledge_docs(id) on delete cascade,
  user_id      uuid not null references auth.users(id) on delete cascade,

  content      text not null,
  embedding    vector(1536),      -- OpenAI text-embedding-3-small dimensions
  chunk_index  int not null,      -- 0-based position within the source document
  metadata     jsonb not null default '{}',
  -- e.g. { "page": 3, "heading": "Q2 Budget", "is_table": true }

  created_at   timestamptz not null default now()
);

create index if not exists knowledge_chunks_doc_id_idx  on knowledge_chunks(doc_id);
create index if not exists knowledge_chunks_user_id_idx on knowledge_chunks(user_id);

-- IVFFlat index for fast approximate nearest-neighbour search.
-- lists = 100 is a good starting point for up to ~1 M rows; tune upward as data grows.
create index if not exists knowledge_chunks_embedding_idx
  on knowledge_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

alter table knowledge_chunks enable row level security;

create policy "users can manage own knowledge chunks"
  on knowledge_chunks for all
  using  (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── 3. knowledge_queries ──────────────────────────────────────────────────────
-- Lightweight audit log.
-- Lets you see what questions the bot answered from docs vs. falling back
-- to web search or asking the user — useful for diagnosing retrieval quality.

create table if not exists knowledge_queries (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  bot_id      text,               -- Recall.ai bot_id if triggered during a meeting
  query_text  text not null,
  matched_doc uuid references knowledge_docs(id) on delete set null,
  match_score float,              -- cosine similarity of the best chunk (0–1)
  fallback    text                -- null | 'web_search' | 'asked_user'
    check (fallback in ('web_search', 'asked_user') or fallback is null),

  created_at  timestamptz not null default now()
);

create index if not exists knowledge_queries_user_id_idx on knowledge_queries(user_id);
create index if not exists knowledge_queries_bot_id_idx  on knowledge_queries(bot_id);

alter table knowledge_queries enable row level security;

create policy "users can read own knowledge queries"
  on knowledge_queries for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── 4. user_settings additions ────────────────────────────────────────────────
-- Google Drive reuses the existing google_access_token — no new OAuth flow needed
-- (just add the drive.readonly scope on the Google Cloud OAuth consent screen).
-- Notion uses an Integration Token the user pastes in Settings → Integrations
-- (consistent with the existing /export/notion pattern).

alter table user_settings
  add column if not exists notion_access_token      text,
  add column if not exists gdrive_knowledge_enabled boolean not null default false;


-- ── 5. similarity search RPC ──────────────────────────────────────────────────
-- Returns top-k chunks for a query embedding, scoped to a user and an
-- optional meeting context. Used by knowledge_lookup tool.
--
-- meeting_scope rules:
--   • If meeting_id is provided, return chunks from docs where
--     meeting_id = $meeting_id OR meeting_id IS NULL (global library).
--   • Proactive surfacing should pass a meeting_id and additionally filter
--     in application code: sensitivity = 'public' OR doc.meeting_id = $meeting_id.
--   • Soft-deleted docs are always excluded.

create or replace function knowledge_search(
  query_embedding vector(1536),
  caller_user_id  uuid,
  meeting_filter  bigint default null,
  match_limit     int  default 5,
  min_score       float default 0.0
)
returns table (
  chunk_id    uuid,
  doc_id      uuid,
  doc_name    text,
  source_type text,
  sensitivity text,
  content     text,
  metadata    jsonb,
  score       float
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
    c.content,
    c.metadata,
    1 - (c.embedding <=> query_embedding) as score
  from knowledge_chunks c
  join knowledge_docs d on d.id = c.doc_id
  where c.user_id = caller_user_id
    and d.deleted_at is null
    and d.status = 'ready'
    and (
      meeting_filter is null
      or d.meeting_id is null
      or d.meeting_id = meeting_filter
    )
    and (1 - (c.embedding <=> query_embedding)) >= min_score
  order by c.embedding <=> query_embedding
  limit match_limit;
$$;

-- Migration #21: per-workspace stand-in profiles + cross-workspace borrow scope.
--
-- WHY: `proxy_profiles` previously held ONE row per user (user_id was the primary key),
-- and enrichment-on-approve accumulated durable facts from EVERY stand-in (personal +
-- all workspaces) into that single profile. `_draft_system` then injected it into every
-- draft, so personal context bled into team meetings (and vice-versa). We now key the
-- profile by (user_id, workspace_id) so each space grows its own "who they are" — the
-- stand-in is the real you *there*. When a space is too thin to draft from, the composer
-- asks to BORROW from another space you belong to (recorded per-representation in
-- `proxy_representations.borrow_scopes`) instead of leaking.
--
-- Personal is stored as workspace_id = '' (empty string, NOT null) so the composite
-- primary key and upsert conflict target (user_id, workspace_id) work without partial
-- indexes. Idempotent: safe to re-run.
--
-- Convention (matches the rest of the schema): user_id + workspace_id are TEXT.

-- 1. proxy_profiles: add workspace_id, repoint primary key to (user_id, workspace_id).
alter table proxy_profiles
    add column if not exists workspace_id text not null default '';

-- Existing single-row-per-user profiles become each user's Personal profile
-- (workspace_id = '' via the column default). Repoint the primary key.
alter table proxy_profiles drop constraint if exists proxy_profiles_pkey;
alter table proxy_profiles add constraint proxy_profiles_pkey primary key (user_id, workspace_id);

-- 2. proxy_representations: remember which spaces the user authorized borrowing from for
-- this stand-in, so refinements keep the widened scope. [] = no borrowing; an entry of
-- null inside the array means Personal.
alter table proxy_representations
    add column if not exists borrow_scopes jsonb not null default '[]'::jsonb;

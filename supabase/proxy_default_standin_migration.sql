-- Migration #22: per-space default stand-in.
--
-- A saved "what Prism says for me when I don't compose something specific" message, kept
-- per (user, workspace) like the rest of the stand-in profile. It seeds the composer so a
-- member with thin data (or no time to compose) is still represented with one approve,
-- instead of starting from a blank draft. Idempotent.

alter table proxy_profiles
    add column if not exists default_standin text not null default '';

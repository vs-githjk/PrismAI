-- Sandbox (bot screen presentation) — Phase 1 credentials persistence.
--
-- Persists the per-user E2B desktop sandbox identity on user_settings:
--   sandbox_id         — the E2B sandbox to reconnect/resume for this user
--   sandbox_auth_key   — the VNC stream auth key; generated CLIENT-side at
--                        stream.start() and UNRECOVERABLE afterwards, so it
--                        must be stored at create time
--   sandbox_stream_url — the assembled noVNC URL for the live view
-- All nullable (null = no sandbox provisioned yet). Idempotent.
-- Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md

alter table user_settings add column if not exists sandbox_id         text;
alter table user_settings add column if not exists sandbox_auth_key   text;
alter table user_settings add column if not exists sandbox_stream_url text;

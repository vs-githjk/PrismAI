-- One row per (recall_bot_id, user_id): the DB-level backstop for the
-- meeting-save races (server persist vs owner/teammate browser saves vs
-- fan-out — each does lookup-then-upsert, so two concurrent writers can both
-- miss and both insert). App-side dedup converges the common orderings; this
-- index makes the residual TOCTOU duplicate impossible at the only layer all
-- writers and processes share.
--
-- Dedup existing violations first (keep the OLDEST row per pair — it's the one
-- existing share links and fan-out ids already reference). Idempotent.

DELETE FROM meetings m
USING meetings m2
WHERE m.recall_bot_id IS NOT NULL
  AND m2.recall_bot_id = m.recall_bot_id
  AND m2.user_id = m.user_id
  AND m2.id < m.id;

CREATE UNIQUE INDEX IF NOT EXISTS meetings_bot_user_unique
  ON meetings (recall_bot_id, user_id)
  WHERE recall_bot_id IS NOT NULL;

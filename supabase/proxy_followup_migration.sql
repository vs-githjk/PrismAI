-- Stand-in follow-up brief (close the loop) — after a stand-in meeting is analysed,
-- Prism briefs the absent author on what happened for them (decisions affecting them,
-- answers to the questions their stand-in relayed, tasks now assigned to them). The
-- brief is stamped on the representation (shown in the Stand-in section) and emailed.
-- Run AFTER proxy_representations_migration.sql. Idempotent.

alter table proxy_representations add column if not exists followup_brief      text;
alter table proxy_representations add column if not exists followup_meeting_id bigint;
alter table proxy_representations add column if not exists followup_sent_at    timestamptz;

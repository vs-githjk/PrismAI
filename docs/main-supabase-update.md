# Cofounder update — stand-in bugs: what's fixed, what you need to run

Context: the two problems from your stand-in meeting — **duplicated action items** and
**no post-meeting email** — are both fixed. The code fixes ship with the next deploy of
`main`. Part of the cause was *database state* on the main Supabase project, which
needs one manual run there (Abhinav's localhost points at his personal Supabase, where
all four stand-in tables were missing entirely — that alone explains the missing
emails).

---

## What you need to do on the main Supabase project

### 1. Check what's missing

SQL editor:

```sql
select table_name from information_schema.tables
where table_schema = 'public'
  and table_name in ('proxy_profiles','proxy_representations',
                     'workspace_integrations','custom_keyterms');
```

If `proxy_representations` is absent, every stand-in write has been failing silently —
nothing was ever recorded as delivered, so there was nothing to build a follow-up
email from.

### 2. Run the missing migrations

Paste these from `supabase/` **in order** (all idempotent — re-running an applied one
is a no-op):

1. `proxy_representations_migration.sql` — `proxy_profiles` + `proxy_representations` (stand-in core)
2. `proxy_workspace_profiles_migration.sql` — per-workspace profiles + `borrow_scopes`
3. `proxy_default_standin_migration.sql` — `proxy_profiles.default_standin`
4. `proxy_followup_migration.sql` — `followup_brief` / `followup_meeting_id` / `followup_sent_at` (**this powers the post-meeting email**)
5. `workspace_integrations_migration.sql` — per-workspace Slack/Jira/etc. configs
6. `custom_keyterms_migration.sql` — transcription glossary (Deepgram keyterms)

Verify: re-run the query above (expect 4 rows), plus

```sql
select column_name from information_schema.columns
where table_name = 'proxy_representations' and column_name like 'followup%';
```

(expect 3 rows).

These are **not** in `schema.sql`, so the backend's boot auto-migration will never
create them — SQL editor, or `python supabase/migrate.py` with the main project's
`DATABASE_URL`, is the only way. `migrate.py` on the branch now lists all of them.

### 3. Nothing to run for the duplicate-row constraint

The new `meetings(recall_bot_id, user_id)` unique index was added to
`backend/schema.sql`, so Render's boot migration applies it automatically on deploy
(`DATABASE_URL` is already set in `render.yaml`). **Heads-up:** it deletes existing
duplicate rows first, keeping the oldest of each pair (the one existing share links
and fan-out ids point at). Expect it to clean up the duplicates from your meeting.

---

## What the code fixes do

**Duplicated action items.** A teammate whose dashboard auto-saved a bot meeting they
didn't own had the bot reference stripped, which bypassed every dedup guard and
inserted a *second* copy of the meeting — doubling its action items everywhere they're
aggregated (workspace Brief, insights). Saves now converge to one row per member per
bot, with a database unique constraint as the backstop for the concurrent-write case.

**Missing post-meeting email.** The stand-in follow-up brief — what you missed, what's
now on you, the summary, plus answers to anything you asked the bot to find out,
emailed from your own Gmail — was only dispatched when the server won an internal race
against the browser save. It now dispatches after every analysis, and a startup pass
recovers briefs interrupted by a restart. The brief is claimed in the database before
sending, so overlapping deploys can't double-email; if the email fails, only the send
is retried, never a second brief.

**Five security issues found and closed during review** (all consequences of the dedup
change, caught before merge): a crafted `POST /meetings` referencing another user's
`recall_bot_id` could fetch their meeting recording, tombstone their bot (killing
server-side persistence for it), or — via workspace fan-out — overwrite teammates'
meeting rows and null their share tokens. Additionally, `recorded_by_user_id` was
client-supplied yet decided meeting ownership, so omitting it made you "owner" of
someone else's meeting and its delete/move cascades. Bot references are now
authorization-checked at save, the recording endpoint verifies the caller against the
bot rather than the row, ownership is server-derived from the bot's true owner, and
destructive workspace cascades require real bot ownership.

---

## How to verify end-to-end once deployed

1. Someone clicks **Can't make it** on an upcoming meeting, writes what the bot should
   relay, approves.
2. The rest of you hold the meeting; the bot posts the stand-in update in chat.
3. After analysis, the absent person should have: the meeting **once** in workspace
   history (no duplicate), a "Your brief from this meeting" expander on the Stand-in
   page, and the brief in their inbox.

The email requires that person to have connected their Google account in PrismAI (that
grants the Gmail send scope) and their stand-in to carry an author email. Without
Gmail, the in-app brief still appears — only the email is skipped.

---

## Known limitation worth knowing

Membership checks are cached per process for 5 minutes, so a member removed from a
workspace can still pass the new recording capability check on an already-warm worker
for up to that long. Pre-existing behavior, not introduced here, but it's the trust
boundary the recording gate now rests on.

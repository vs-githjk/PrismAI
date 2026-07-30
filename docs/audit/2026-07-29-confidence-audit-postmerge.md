# PrismAI confidence audit — 2026-07-29 (post-merge)

Re-audit of the merged HEAD (after origin/main's voice-agent rewrite + model
migration landed). Same method as the 2026-07-28 audit: 23 auditors (incl. a
dedicated `backend/voice/` auditor + merge-reconciliation and model-migration
lenses) → dedup → adversarial verification → completeness critic. Plus a **delta
pass** re-checking all 29 prior highs against current code.

**50 confirmed** (13 high, 27 medium, 10 low); 4 refuted. See the prior report
(`2026-07-28-confidence-audit.md`) for the carried-over issues in full.

---

## Headline: what the merge changed

**The merge fixed 1 of the 29 prior high-severity findings. The other 28 are
still present.** The merge brought main's *features* (voice pipeline, model
migration, cross-meeting synthesis) — it did not touch the security/data-loss
issues from the last audit, so all of those remain exactly as reported.

- ✅ **Fixed:** the non-transient-LLM-error silent-empty-analysis bug (B1) — main
  added the `_accepts_temperature` + OpenAI-fallback handling in `llm_call`.
- ⚠️ **But the model migration opened a *new* silent-empty-analysis path** (H1
  below): Sonnet-5's adaptive thinking now eats the token budget and truncates
  agent JSON. So the "blank cards, no error" failure mode didn't go away — it
  moved.

**The merge also introduced new problems of its own** — the voice pipeline is
brand-new attack/failure surface, and the reconciliation left live defects. Those
are the 13 highs below; the ones marked **[NEW]** did not exist before the merge.

---

## HIGH severity (13)

### New from the merge / voice rewrite / model migration

**H1. [NEW] Sonnet-5 adaptive thinking shares the 4096 `max_tokens` budget with
agent JSON → silent truncation → blank cards.**
`backend/agents/utils.py:190` · model
`llm_call` sends `max_tokens=4096` with no `thinking`/effort control. On
`claude-sonnet-5` (now the agent default), omitting `thinking` runs **adaptive
thinking at effort=high** — and `max_tokens` is a hard ceiling on thinking +
output *combined*. On a dense/long transcript, thinking eats 2–3K tokens and the
JSON truncates at `stop_reason: max_tokens`. `json.loads` raises; both retries
truncate identically (deterministic for a given length), so the agent returns
`_DEFAULT` and the card renders **empty with no error**. Truncation is a 200, so
the OpenAI fallback never fires.
→ *An hour-long meeting or an Article/Report analyzes to blank summary /
action-items / decisions cards, intermittently, with nothing in the logs.*
Fix: set an explicit `thinking` budget (or disable it for the JSON agents) and/or
raise `max_tokens` well above the largest expected output. **This is the #1 thing
to fix — it silently breaks the core product on exactly the meetings that matter
most.**

**H10. [NEW] `main.py` hard-imports the voice package (→ pipecat chain) unguarded
— any missing voice dep takes the *whole* backend down.**
`backend/main.py:44` · merge
`from voice.audio_routes import router` at module top eagerly imports
`voice.pipeline`, which hard-imports the full pipecat chain (Flux STT,
VADProcessor, Cartesia, silero/onnxruntime) at module scope — no try/except, no
lazy import (unlike the `loguru` block 20 lines above, and unlike
`sandbox/provider.py` which lazy-imports each SDK). `pipecat-ai==1.5.0` is a WIP
pin.
→ *Reproduced locally: `python -c "import main"` and pytest collection both abort
with `ModuleNotFoundError: pipecat`. On any deploy where the pipecat/onnxruntime
chain fails to resolve, uvicorn can't import `main:app` and **every endpoint
502s** — a voice-only dependency problem becomes a total outage.*
Fix: wrap the voice import + router registration in try/except (degrade to
voice-off), or lazy-import inside the route handlers.

**H11. [NEW] Muted bot still speaks agent results + blocked-capability lines on
the default two-channel path — the mute kill-switch regressed.**
`backend/voice/voice_channel.py:185` · race
`handle_command` checks `state['muted']` once at entry, then awaits the
multi-second `agent_channel.run` tool loop. On return, the success narration and
the blocked-cap narration `_speak(...)` run with **no mute re-check**, and the
new two-channel path never installs a `SpeakingSession`, so `hard_stop`'s
interrupt can't reach them. The legacy `_process_command` honored mute
mid-action; the rewrite dropped that on the now-default path (`PRISM_TWO_CHANNEL`
defaults on).
→ *User says "Prism, email the recap," realizes the meeting is sensitive, hits
Mute — and seconds later the bot announces "Done, I've emailed the recap" aloud
into the meeting. The full reply also posts to chat regardless of mute.*
Fix: re-check `state['muted']` (and the barge interrupt seq) immediately before
each `_speak`/chat-post in `handle_command`.

**H12. [NEW/sharper] Boot migration (`schema.sql`) omits
`bot_sessions.realtime_transcript` + `transcript_segments` → live-transcript
restart persistence silently no-ops.**
`backend/schema.sql:119` · restart-loss
`schema.sql` is the only migration run at boot (`migrations.py`). Its
`bot_sessions` stops at `workspace_id`; `realtime_transcript` exists only in
`bot_realtime_transcript_migration.sql` (in *no* auto-applied path and *not* in
CLAUDE.md's migration list — orphaned). `_maybe_persist_transcript` upserts those
columns every live meeting; `_db_save` swallows the "column does not exist" error
as a silent no-op.
→ *Render restarts mid-meeting (the exact scenario the column was added for);
`_db_load` reads back empty, and if Recall produced 0 recordings the user gets
"Transcript processing timed out" with an empty meeting.*

**H13. [NEW/sharper] `schema.sql` also omits the `meetings` recording columns →
`save_meeting` + `get_meeting` hard-500 on a fresh DB.**
`backend/storage_routes.py:402` · drift
`recall_bot_id` / `recording_provider` / `transcript_segments` live only in
`recording_migration.sql` (absent from `schema.sql` *and* `migrate.py`).
`save_meeting`'s upsert and `GET /meetings/{id}`'s SELECT reference all three with
no try/except.
→ *A freshly-provisioned staging/dev/DR DB (relying on the documented tooling)
500s on every meeting save and every meeting open.* Latent, not a live incident
(prod is hand-migrated) — but it's the default outcome for any new environment.

### Carried over from 2026-07-28 (still present — merge didn't touch them)

**H2. Taint contract not enforced in the chat tool loop.** `chat_routes.py:388` ·
security. `web_search` (attacker-controlled content) doesn't strip tools
afterward; `calendar_update_event`/`correct_meeting_text` are `confirm=False`, so
poisoned web content can silently PATCH the user's real calendar.

**H3. Hybrid RAG search KeyErrors on its success case.**
`knowledge_service.py:128` · drift. Vector RPC returns `chunk_id`, `_rrf_merge`
reads `row['id']`. Still broken; still masked by tests that stub `id`. Core KB
retrieval dies whenever vector matches exist. One-line fix.

**H4. OCR/PDF rasterization runs on the event loop.**
`knowledge_ingest/pdf_loader.py:36` · blocking. One scanned PDF freezes webhooks +
live bot + all chat on the single worker.

**H5. `POST /meetings` has no workspace-membership check.**
`storage_routes.py:422` · security. Any authed user injects a meeting into any
workspace's history + RAG.

**H6. `borrow_scopes` unvalidated → cross-workspace exfiltration.**
`proxy_routes.py:782` · security.

**H7. Screenshare-fallback posts the interactive browser URL to the whole room.**
`presentation.py:231` · security. `view_url` is only cosmetically view-only for
Browserbase (`?navbar=false`). (Note: my navbar split from 2 days ago fixed the
*setup* surface, not this fallback path.)

**H8. Meeting-save success toast fires before the POST; failure = silent loss.**
`App.jsx:2053` · error-handling.

**H9. Workspace-integration save wipes every field the owner didn't re-type.**
`IntegrationsModal.jsx:202` · config.

---

## MEDIUM severity (27)

### New merge / voice / model damage
- **`realtime_routes.py:4501` [merge]** — `/bot/{id}/mode` calls the deleted
  `ambient_loop.update_mode` → **AttributeError/500 on every call**. Currently
  the shipped UI only sets mode at join, so blast radius is API/operator/future
  in-call toggle — but the endpoint is 100% broken.
- **`realtime_routes.py:1523` [drift]** — mode-vocabulary drift: `set_bot_mode`
  sets `engagement_mode` but never `state['mode']`, so the ambient KB lane is
  decoupled from a mid-meeting Auto/Manual switch.
- **`voice/speaker_page.py:68` [security]** — **reflected XSS** in the public
  `/voice/speaker-page/{token}`: the raw token is injected into HTML/JS with no
  validation or escaping.
- **`voice/bridge.py:96` [error-handling]** — `bridge.speak()` gates on pipeline
  existence, not speaker-socket connectivity → permanent mute + dead MP3 fallback
  if the renderer never attaches.
- **`recall_routes.py:1191` [restart-loss]** — boot recovery re-spawns the
  proactive checker + pollers but **not the voice pipeline** → a recovered bot is
  a "looks-alive" deaf+mute zombie.
- **`voice/pipeline.py:269` [restart-loss]** — `VoicePipeline._t0` resets on every
  reconnect → durable seek timestamps collide with the earlier part of the
  meeting.
- **`realtime_routes.py:4504` + `deploy.yml:36` [merge/untested]** — the merge
  silently changed realtime contracts (removed `_GAP_MAX_WAIT_S`, reshaped
  `set_bot_mode`), **breaking ~17 tests that no CI runs**, so they shipped
  undetected.
- **`App.jsx:2480` [model]** — the 120s client-side analysis abort wasn't
  re-tuned for the slower Sonnet-5 agents; long meetings may abort client-side.
- **Light-theme × merge regressions** — `ChatPanel.jsx:972`, `LiveMeetingView.jsx:188`,
  `SuggestedActions.jsx:88` render white/near-black text on the light page
  background → **effectively blank/unreadable in light mode** (the light theme was
  your branch; these components came from main without tokens).
- **`UpcomingMeetings.jsx:189` [merge]** — Outlook self-email misclassification
  (carried over, re-confirmed): personal meetings tagged into a workspace and
  fanned out to the team.

### Carried over (still present)
- `analysis_routes.py:77` — SSE counts failed-agent `_DEFAULT` as "succeeded",
  defeating the frontend's no-usable-results guard (this is *why* H1's blank cards
  get saved).
- `agents/summarizer.py:55` — only 2 of 10 agents tolerate prose-wrapped JSON;
  the rest bare-parse and silently default (compounds H1).
- `tools/calendar.py:235` — calendar create/update `confirm=False`, sends real
  invites without approval.
- `export_routes.py:301` — Teams webhook validated by substring, not hostname →
  unauthenticated SSRF.
- `proxy_routes.py:205` — fuzzy owner match on bare first names misattributes work.
- `proxy_routes.py:831` — `approve()` has no status guard → re-approving a
  delivered stand-in resets it to pending.
- `storage_routes.py:222` — `date[:16]` dedup hides distinct same-minute meetings.
- `workspace_routes.py:438` — integration shows "connected" while the resolver
  ignores a partial config.
- `ChatPanel.jsx:852` / `StandInComposer.jsx:152` — confirm-tool / stand-in
  approve report success on failure.
- `migrations.py:25` — startup blocks on `run_migrations()` with no psycopg2
  connect timeout.
- `supabase/auth_migration.sql:1` — base `meetings`/`chats` tables are created by
  no migration in the repo.

---

## Refuted (checked, not real)
1. Vector vs BM25 `meeting_filter` asymmetry skewing hybrid retrieval — the SQL
   difference is real but doesn't change ranking as claimed.
2. Fan-out/RAG `create_task` GC loss — `_fan_out_to_workspace` has zero await
   points, so GC can't fire mid-task.
3. SSE-without-`[DONE]` shows a partial unsaved result — misreads the chunked
   transport behavior.
4. Server auto-promote + browser POST double-insert — unreachable on the
   single-worker deployment.

---

## Suggested triage order (post-merge)

1. **H1 — Sonnet thinking/`max_tokens`** — silently blanks core analysis on your
   most important meetings. Highest value, small fix.
2. **H10 — guard the voice import** — one try/except stands between a voice dep
   hiccup and a total backend outage.
3. **H11 — mute kill-switch** — the bot speaking after being silenced is a trust
   /privacy failure in a live meeting.
4. **The broken tests + CI (`deploy.yml`)** — the merge broke ~17 tests nothing
   runs; fixing CI (prior H20) would have caught H10/H11/the mode 500 pre-merge.
5. **Light-mode readability** (ChatPanel/LiveMeetingView/SuggestedActions) — your
   new light theme is visibly broken on merged-in components.
6. **The 28 carried-over criticals** — the write-path tenancy holes (H5/H6),
   hybrid-search crash (H3), and meeting-save silent loss (H8) haven't moved.

Raw verified findings + per-finding evidence: `tasks/wh299cjir.output`.

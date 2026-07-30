# PrismAI findings verification — 2026-07-29

Every finding from both audits (2026-07-28 pre-merge + 2026-07-29 post-merge),
deduplicated to **111 unique findings**, re-checked by a *skeptical* verifier
whose default stance was disbelief — it had to prove each failure is reachable
in the **real deployment** (single uvicorn worker, feature flags at their actual
defaults, only endpoints a shipped frontend path calls). Several were also
confirmed or refuted by running code directly (marked EMPIRICAL).

## Verdict distribution

| Verdict | Count | Meaning |
|---|---|---|
| **REAL** | 56 | Mechanism holds and the bad outcome is reachable as claimed |
| **PARTIAL** | 49 | A real defect, but the audit overstated it (wrong blast radius, guarded on the common path, needs a non-default flag, or edge-case only) |
| **NOT A PROBLEM** | 6 | Misreads the code, unreachable, already guarded, or fixed by the merge |

After honest re-rating: **9 high, 38 medium, 58 low, 6 none.** The audits
over-weighted severity — pressure-testing against real reachability dropped most
"highs" a rung. Net: 9 findings genuinely deserve high priority.

## Empirically confirmed (I ran/read these directly, not just an LLM opinion)

- **`import main` → `ModuleNotFoundError: pipecat`** and **pytest collection fails
  with 2 errors** (same cause). The unguarded voice import is real — a missing
  voice dep takes the whole app down. (This local venv also lacks pipecat, so I
  could not run the full suite here.)
- **`ambient_loop.update_mode` does not exist** but is called twice in
  `realtime_routes.py:4501/4509` → `/bot/{id}/mode` 500. Confirmed by grep AND by
  a failing test (`test_ambient_wiring.py::test_set_mode` → the exact
  `AttributeError`).
- **The merge broke real tests:** running the realtime/mode subset, **6 failed**
  (3 `SharedGapTests`, 3 `ModeEndpointTests`/`PreJoinModeSeedTests`) — with no CI,
  they shipped green-in-name-only.
- **`_rrf_merge` reads `row["id"]`** while the vector RPC returns `chunk_id` →
  hybrid-search KeyError. Confirmed by reading both.
- **LLM-fallback finding is FIXED:** read `utils.py:205` — a non-transient error
  now `break`s (not `raise`) and falls through to the OpenAI fallback at L213.
  The merge's model-migration restructure fixed it.

## The 6 that are NOT actually problems

1. **#7 Non-transient LLM errors skip fallback → empty analysis**
   (`agents/utils.py:141`). **Fixed by the merge** — verified by direct read
   (falls through to OpenAI fallback). Was real pre-merge.
2. **#84 MS calendar token lifecycle "untested → bug"** (`ms_calendar_routes.py`).
   The *code* is correct (refresh + rotate + user-scoped wipes); the finding was
   really about missing tests. (Note: the distinct 401-wipe bug **#82 is still
   REAL** — see below.)
3. **#67 `workspace_migration.sql` uuid-vs-text drift.** The uuid file is
   internally consistent; the `text`-with-`''` convention lives in *separate*
   tables (proxy/integrations). No contradiction in practice.
4. **#30 `workspace_routes` maybe_single None deref → 500.** Guarded / not
   reachable as claimed.
5. **#69 `sendRecap` 404-fallback regression** (`App.jsx`). The claim is explicitly
   about a *future* refactor; current code already does the safe thing
   (`if status !== 404 return`).
6. **#89 Mode-vocabulary drift decouples the ambient KB gate.** Real latent drift,
   but unreachable: the ambient lane is flag-gated OFF by default
   (`autonomous_enabled()`), so no user hits it.

## The 9 that stayed HIGH

| # | File | Problem | Reachable |
|---|---|---|---|
| 91 | `agents/utils.py:190` | Sonnet-5 adaptive thinking shares the 4096 `max_tokens` budget → JSON truncates → blank analysis cards, no error | yes |
| 21 | `knowledge_service.py:128` | Hybrid search KeyError (`row['id']` vs RPC `chunk_id`) — breaks KB retrieval whenever vector matches exist | yes |
| 22 | `knowledge_routes.py:183` | Doc upload/PATCH accept arbitrary `workspace_id` (no membership check) → cross-workspace RAG injection | yes |
| 27 | `storage_routes.py:382` | `save_meeting` upsert on client PK → overwrite/re-own any user's meeting row | yes |
| 33 | `proxy_routes.py:783` | Unvalidated `borrow_scopes` → pull meeting data from arbitrary workspaces | yes |
| 96 | `storage_routes.py:422` | `POST /meetings` no membership check → inject a meeting into any workspace + fan-out + RAG | yes |
| 54 | `App.jsx:1224` | Pending invite silently lost after Google OAuth → every signed-out invitee onboarding fails | yes |
| 55 | `App.jsx:2057` | Meeting-save success toast before the POST; failure = silent permanent loss | yes |
| 44 | `presentation.py:231` | Screenshare-fallback posts the (cosmetically view-only) interactive browser URL to the whole room | conditional |

The write-path tenancy cluster (22, 27, 33, 96) is the same shape as before and
remains the highest-leverage fix set — the guard functions already exist on the
read paths. #91 (Sonnet thinking) is the newest and silently degrades the core
product.

## Notable downgrades (audit said high; verifier says lower)

- **#1 realtime webhook token bypass → LOW.** Real, but zero incremental blast
  radius: the legacy `/realtime-events` route is already fully unauthenticated by
  design, an easier path to the same outcome. Fix both or neither.
- **#22-series live-bot tool authority, /analyze DoS, SLACK/LINEAR global
  fallback → mostly PARTIAL/medium.** Real, but each is bounded by a default-off
  flag, the documented "unauthenticated by design" surface, or an operator
  opt-in — not the unconditional high the audit implied.
- **#3 instant-ack-after-mute → REAL/medium** (survived): the ack leaks a canned
  phrase after mute in the fused path.
- **#82 MS 401 token wipe → REAL/medium** (survived, distinct from #84).

---

# Full annotated list (all 111)

Grouped by verdict, then severity. `#` = master id.

## NOT A PROBLEM — false alarms (6)

**#7 [NONE] agents/utils.py:141** — Non-transient LLM errors skip the OpenAI fallback and are swallowed silently by every agent, produci
- verdict: NOT_A_PROBLEM · reachable: no
- EMPIRICALLY CONFIRMED FIXED: utils.py:205 breaks (not raise) on non-transient err -> falls through to OpenAI fallback L213.

**#30 [NONE] workspace_routes.py:29** — workspace_routes dereferences maybe_single() results without the None guard used everywhere else — a
- verdict: NOT_A_PROBLEM · reachable: no
- See above.

**#67 [NONE] supabase/workspace_migration.sql:17** — Checked-in workspace_migration.sql declares uuid columns while four other migrations + CLAUDE.md ins
- verdict: NOT_A_PROBLEM · reachable: no
- workspace_migration.sql:6-52 defines workspaces/workspace_members/meeting_bots as uuid, internally consistent (meetings.workspace_id uuid + knowledge_workspace_migration.sql:17,85 uuid + knowledge_search uuid[]). The text-with-'' convention lives in SEPARATE tables — custom_keyterms_migration.sql:21, proxy_workspace_profiles_migration.sql

**#69 [NONE] frontend/e2e/status-island.spec.js:1** — Frontend test coverage is one Playwright spec; App.jsx state machine, sendRecap 404-only fallback, a
- verdict: NOT_A_PROBLEM · reachable: no
- The claimed failure is explicitly hypothetical ("a refactor loosens the 404-only condition") — it describes a future regression, not the current code. App.jsx:1532-1534 already does exactly the safe thing: `if (wres.status !== 404) return { ok: false, routedTo: 'workspace' }` — a transient 500 returns failure and does NOT fall through to 

**#84 [NONE] ms_calendar_routes.py:88** — Entire MS calendar token lifecycle has zero tests while its Google mirror has already drifted
- verdict: NOT_A_PROBLEM · reachable: no
- Current MS token code is correct: get_valid_ms_token (ms_calendar_routes.py:109-132) refreshes within 60s of expiry, persists the new access token AND rotated refresh token (124-126); both wipe paths — disconnect (203-209) and dead-token 401 (266-273) — are scoped .eq(user_id), no over-wide wipe. Refresh failure degrades gracefully to 401

**#89 [NONE] realtime_routes.py:1523** — Mode vocabulary drift: mode endpoint sets engagement_mode but never state['mode'] (ambient gate)
- verdict: NOT_A_PROBLEM · reachable: no
- set_bot_mode (realtime_routes.py:4486-4512) never sets state["mode"] for auto/manual, and the ambient KB gate reads state["mode"] (1523) — a real latent drift. But the outcome is unreachable: (a) ambient lane is flag-gated at 1520 by autonomous_enabled() (ambient_loop.py:30-31, PRISM_AUTONOMOUS=="1"), and render.yaml does NOT set it (only

## REAL (56)

**#21 [HIGH] knowledge_service.py:128** — Hybrid search crashes: vector RPC returns 'chunk_id' but _rrf_merge reads row['id']
- verdict: REAL · reachable: yes
- EMPIRICALLY CONFIRMED: _rrf_merge reads row["id"] (L128/132); vector RPC returns chunk_id, no id col.
- fix: In _rrf_merge key rows by `row.get("id") or row.get("chunk_id")` (and use that key in the sort/assign at :135-137); also fixes knowledge_lookup.py:94 `m.get("id")` returning None. Or alias chunk_id→id

**#22 [HIGH] knowledge_routes.py:183** — Doc upload/PATCH accept arbitrary workspace_id with no membership check — cross-workspace RAG inject
- verdict: REAL · reachable: yes
- upload_file (knowledge_routes.py:140-194) passes Form workspace_id into _insert_doc_row (116-137) with NO membership check; same for upload-url (202-206), connect-source (219-223). PATCH update_doc (343) scopes only .eq(user_id) — own doc, but sets any workspace_id, no ws check. ingest_doc propagates doc_workspace_id onto every chunk (kno
- fix: In upload/upload-url/connect-source/PATCH, when workspace_id is set, verify caller ∈ workspace_members (reuse get_user_workspace_ids) and 403 otherwise, before stamping it on the doc/chunks.

**#27 [HIGH] storage_routes.py:382** — save_meeting upsert on client-supplied PK lets any authenticated user overwrite any other user's mee
- verdict: REAL · reachable: yes
- storage_routes.py:402-417 upserts {"id": entry.id, "user_id": user_id, ...all client fields} with no on_conflict and no ownership check; default conflict target is PK meetings.id, so ON CONFLICT(id) DO UPDATE overwrites+re-owns any existing row. supabase uses SUPABASE_KEY = service_role (auth.py:37; .env.example:91 "bypasses RLS"), so no 
- fix: Before upsert, read the row for entry.id; if it exists and its user_id != caller, reject (403) or mint a fresh server-side id; ideally generate id server-side (bigserial) instead of trusting the clien

**#33 [HIGH] proxy_routes.py:783** — Unvalidated borrow_scopes lets any authenticated user pull meeting data from arbitrary workspaces
- verdict: REAL · reachable: yes
- converse() (proxy_routes.py:780-789) merges body.borrow_scopes with NO membership check (is_workspace_member only used at :642 for the rep's OWN ws in create). _fetch_meetings_for_scopes (:236-237) queries q.eq("workspace_id", sc) with no user_id filter on the service-role client (auth.py:37, SUPABASE_KEY=service-role per CLAUDE.md) → RLS
- fix: In converse(), drop any borrow_scope the caller isn't a member of: filter body.borrow_scopes to ids in _borrow_options(user_id, ws) (or per-scope is_workspace_member) before merging into borrow.

**#44 [HIGH] presentation.py:231** — Screenshare-fallback posts wrapper URL to full meeting chat; view-only is client-soft, so any partic
- verdict: REAL · reachable: conditional
- presentation.py:214 mints token view_only=True; :229-233 posts wrapper_url to the FULL meeting chat on screenshare-block. present_routes.py:89-142: /present/{token} and /vnc are PUBLIC (token = only capability); /vnc returns provider.view_url. That "view-only" URL is not enforced: default provider is browserbase (.env.example:152) whose v
- fix: Issue a provider-enforced read-only credential (or an input-dropping view proxy) instead of relying on client-side view_only/navbar-hiding; and never post the wrapper link to the full meeting chat — s

**#54 [HIGH] fe:App.jsx:1224** — Pending-invite restore after Google OAuth is a same-document hash change — invite silently dropped
- verdict: REAL · reachable: yes
- App.jsx:1224 `window.location.replace('/dashboard#invite/${pendingInvite}')` runs from the OAuth-callback URL `/dashboard` (redirectTo=`${origin}/dashboard`, App.jsx:1342; Supabase cleans its OAuth hash before emitting SIGNED_IN, lib/supabase.js:12 default implicit flow). Target differs only in the fragment → a same-document fragment navi
- fix: Hash-only replace won't re-read the module-level token; after setting `/dashboard#invite/TOKEN` force a full reload (`window.location.reload()`), or make invites reactive by routing `#invite/` through

**#55 [HIGH] fe:App.jsx:2057** — Meeting save fires a success toast before the POST and never checks the response — silent data loss
- verdict: REAL · reachable: yes
- App.jsx:2053 fires notifyStatus success 'Meeting saved' synchronously; lines 2049-2052 already pushed the entry into history + set meetingId/shareToken; POST at 2057 has only `.catch()` (2061) resetting savedMeetingRef/meetingId. lib/api.js:20 returns raw `fetch()`, which resolves (not rejects) on HTTP 401/500 — so `res.ok` is never check
- fix: Chain `.then(res => { if (!res.ok) throw })`; only toast 'Meeting saved' on success; on failure remove the optimistic history entry, clear meetingId/shareToken/savedMeetingRef, and show an error toast

**#91 [HIGH] agents/utils.py:190** — Sonnet-5 adaptive-thinking is ON by default and shares the 4096 max_tokens budget with agent JSON → 
- verdict: REAL · reachable: yes
- EMPIRICALLY CONFIRMED: utils.py:180-185 sends max_tokens w/ no thinking param; Sonnet-5 adaptive thinking default.
- fix: Give agent calls headroom the thinking can't eat: pass an explicit larger max_tokens (e.g. 8192) in llm_call for agents, or set thinking={"type":"disabled"} (or a low output_config effort) on the sonn

**#96 [HIGH] storage_routes.py:422** — POST /meetings never checks workspace membership — any authed user injects a meeting into any worksp
- verdict: REAL · reachable: yes
- storage_routes.py:346-444 save_meeting takes client-supplied entry.workspace_id and never calls is_workspace_member. Line 422-424 fans out to every workspace member via _fan_out_to_workspace (line 304-343, upsert with user_id=member_id, attacker title/transcript/result). auth.py:37 supabase=create_client(SUPABASE_URL,SUPABASE_KEY) is serv
- fix: In save_meeting, when entry.workspace_id is set, require is_workspace_member(client, user_id, entry.workspace_id) and raise 403 otherwise — mirror the read paths — before writing/fanning out/indexing.

**#3 [MEDIUM] realtime_routes.py:4349** — Pending instant-ack is not cancelled by mute or a stop command — bot speaks after being silenced
- verdict: REAL · reachable: yes
- _arm_ack schedules _fire() (realtime_routes.py:2157-2167): sleeps ack_delay_s()=1.2 (ack_phrases.py:16) then uploads unconditionally — NO session/mute check. Armed for every spoken command at line 3174 (PRISM_ACK default 1, ack_phrases.py:15; RECALL_API_KEY set in prod). Stop-command path (4058-4105, PRISM_BARGE_IN default ON at 217) and 
- fix: Call _cancel_ack(state) in the stop-command block (near line 4076) and in set_bot_mute (near 4530); or gate _fire() on session.is_cancelled / state.get("muted") before uploading.

**#5 [MEDIUM] recall_routes.py:1220** — Stand-in reps are matched by meeting_url with no time window — pending reps never expire and deliver
- verdict: REAL · reachable: yes
- recall_routes.py:1280-1283 selects pending reps by meeting_url only — no scheduled_for/occurrence/time filter; docstring line 1265 confirms "Runs for ANY bot". Triggered on in_call_recording (lines 1042, 2716, 3004) with only a per-bot _standin_delivered guard. No code sets status "expired" (grep: zero standin hits) so pending reps never 
- fix: In deliver_standins_for_bot, filter pending reps to those whose scheduled_for is within a window of the bot's actual join time (e.g. same day / ±few hours), and add a sweep that marks reps with a long

**#6 [MEDIUM] recall_routes.py:546** — _gather_keyterms runs ~7 synchronous Supabase queries on the event loop inside async join/schedule/a
- verdict: REAL · reachable: yes
- _gather_keyterms (recall_routes.py:555) runs ~7-9 sequential blocking supabase-py .execute() calls: custom_keyterms 626/630, workspace_members 641, knowledge_docs 652/657, knowledge_chunks 670/674, meetings 686 (+get_user_workspace_ids). supabase is the SYNC client (auth.py:37 create_client, imported recall_routes.py:20). It is called dir
- fix: Wrap the blocking call in the async callers: await asyncio.to_thread(_gather_keyterms, user_id, workspace_id) so the ~8 DB round-trips run off the event loop (optionally cache/parallelize the queries)

**#14 [MEDIUM] chat_routes.py:719** — /chat/confirm-tool returns tool failures as HTTP 200 and ChatPanel then displays 'Executed <tool>' —
- verdict: REAL · reachable: yes
- confirm_tool (chat_routes.py:722-723) returns confirm_and_execute's dict at HTTP 200. confirm_and_execute (registry.py:145-155) returns the handler result verbatim; gmail_send (gmail.py:64-65) RETURNS {"error":...} on a 401/placeholder rather than raising. Frontend ChatPanel.jsx:852-857: `if(!res.ok) throw` misses a 200+error body, then `
- fix: In confirm_tool, treat result.get("error") as a failure (return non-200 or {ok:false,error}); in ChatPanel read data.error and render a failed state instead of defaulting to "Executed <tool>".

**#17 [MEDIUM] chat_routes.py:241** — /chat/sign ownership check bypassable via '..' path traversal — signs other users' private chat imag
- verdict: REAL · reachable: yes
- chat_routes.py:242 guards only `p.startswith(f"{user_id}/")`, then _sign_chat_image (line 194) passes the raw path to storage3 create_signed_url. storage3 file_api.py:43-47 (relative_path_to_parts) splits on '/' and file_api.py:69 does yarl `_base_url.joinpath(*parts)`. Empirically (installed storage3 2.28.3 / yarl 1.23.0): joinpath COLLA
- fix: Before signing, reject/normalize paths containing '..' (e.g. os.path.normpath then re-verify startswith, or require path == f"{user_id}/" + basename with no separators beyond the prefix).

**#19 [MEDIUM] tools/meeting_edit.py:76** — correct_meeting_text: LLM-chosen, unconfirmed, un-undoable substring rewrite of title + result + tra
- verdict: REAL · reachable: yes
- meeting_edit.py:76 `re.compile(re.escape(find), re.IGNORECASE)` + subn (line 27) — pure substring, no \b, so find='Ana' hits 'analysis'→'Annalysis'. Lines 77-95 rewrite title+result+transcript and persist in one .update(). confirm=False (line 163); registry.py:102 only holds when confirm truthy, so it runs inline unconfirmed. No backup → 
- fix: Match on token/word boundaries (or require an exact-word toggle), set confirm=True with a preview of affected occurrences, and snapshot the prior title/result/transcript for one-click undo.

**#24 [MEDIUM] knowledge_routes.py:379** — Resync deletes all chunks before download can fail; doc stranded in 'processing', transcript docs de
- verdict: REAL · reachable: yes
- knowledge_routes.py:379 deletes all chunks, :381 sets status="processing", THEN :390 downloads synchronously in the request with no try/except; :391 schedules ingest only if download succeeds. A storage failure raises → doc stranded in "processing", chunks gone, ingest_doc's error handler never runs. Transcript docs are deterministically 
- fix: Delete chunks only AFTER a successful download/ingest (wrap resync in try/except that restores prior status on failure); and special-case source_type=='meeting_transcript' to re-run index_meeting_tran

**#31 [MEDIUM] storage_routes.py:607** — patch_meeting silently no-ops on teammate-copy ids in workspace mode (delete was fixed for this exac
- verdict: REAL · reachable: yes
- patch_meeting (storage_routes.py:627) updates with .eq("id",meeting_id).eq("user_id",user_id); a teammate-copy id → 0 rows, returns {"ok":True} silently. This is the exact class delete_meeting documents+fixed at 559-564. GET /meetings dedup (216-227) fetches ALL members' rows, collapses by date[:16], and keeps a teammate's row when the ca
- fix: Mirror the delete_meeting fix: load the row by id, verify workspace membership, then UPDATE the caller's own copy resolved via recall_bot_id / (workspace_id,date) instead of requiring id+user_id (and 

**#35 [MEDIUM] proxy_routes.py:831** — Recurring-URL resume returns a delivered rep: composer dead-ends on /message and approve flips deliv
- verdict: REAL · reachable: yes
- create_representation resume (proxy_routes.py:669-678) filters only `.neq("status","canceled")`, most-recent first; _normalize_meeting_url (recall_routes.py:338-344) strips query/fragment so a recurring link matches week-to-week → last week's `delivered` rep (status set recall_routes.py:1297) is resumed. converse (proxy_routes.py:774-775)
- fix: Scope the resume query to still-actionable statuses (e.g. `.in_("status",["draft","pending"])`) or match the specific occurrence (scheduled_for) so a new occurrence of a recurring URL starts a fresh r

**#38 [MEDIUM] recall_routes.py:948** — Lifecycle poller covers only ~10h after approve; startup recovery's 6h created_at cutoff can't rescu
- verdict: REAL · reachable: yes
- recall_routes.py:1010 sleeps `min(lead, 6*3600)`; :1014 `deadline = time.time()+4*3600` → poller covers only ~10h after approve. proxy_routes.py:45 `_join_at_ok` only lower-bounds join time (no upper cap), and :31/:845 schedule on approve with flag default ON; StandInComposer→/approve ships (DashboardPage.jsx:1743). recall_routes.py:1179 
- fix: For scheduled bots, keep the poller alive until join_at+buffer (not a fixed approve+10h), and pass join_at through recover_active_bots's re-spawn plus anchor its recovery cutoff on scheduled_for, not 

**#39 [MEDIUM] export_routes.py:301** — Teams webhook validated by substring anywhere in URL — unauthenticated SSRF relay
- verdict: REAL · reachable: yes
- export_routes.py:301 gates on `url.startswith("https://") and ("logic.azure.com" in url or "webhook.office.com" in url)` — substring-anywhere, so `https://internal-host/admin?x=webhook.office.com` and `https://webhook.office.com.attacker.com/` both pass, then line 307 `client.post(url, json=payload)` fires to the attacker's host. Route at
- fix: Parse the URL and match the hostname (urlparse().hostname) exactly against an allowlist (`webhook.office.com`, `*.webhook.office.com`, `*.logic.azure.com`) instead of substring-in-URL, and reject priv

**#51 [MEDIUM] supabase/migrate.py:38** — supabase/migrate.py (the documented 'preferred' runner) cannot correctly provision a DB: it omits ~1
- verdict: REAL · reachable: conditional
- migrate.py:38-52 lists only 13 of ~30 migration files (omits workspace_migration, all knowledge_*, personas, recording, chat_sessions, etc.). Fresh DB: pos1 full_schema_fix.sql never creates meetings/chats; pos2 auth_migration.sql:1 `alter table meetings` (no `if exists`) → "relation meetings does not exist"; migrate.py:74-77 exits(1). Li
- fix: Regenerate MIGRATION_ORDER to include every file in dependency order (add workspace_migration before meeting_bots_workspace, plus knowledge_*/personas/etc.), guard every `create policy` with DO$$if no

**#59 [MEDIUM] fe:components/UpcomingMeetings.jsx:189** — Outlook attendee list includes the caller's own email, so matchWorkspace tags personal meetings as w
- verdict: REAL · reachable: yes
- ms_calendar_routes.py:294-298 builds attendee_emails with NO self-exclusion; Google's calendar_routes.py:352-354 filters `not a.get("self")` — clear asymmetry. The caller's own email is in every workspace's member_emails (workspace_routes.py:100-116, from workspace_members.user_email). matchWorkspace (UpcomingMeetings.jsx:184-192) returns
- fix: Exclude the signed-in user's email in ms_calendar_routes attendee_emails (mirror Google's self-exclusion by comparing against the caller's Graph /me address), or drop the caller's own email in matchWo

**#60 [MEDIUM] fe:components/ChatPanel.jsx:312** — ChatPanel: in-flight save resurrects the old session id after 'New chat', making the next thread ove
- verdict: REAL · reachable: yes
- ChatPanel.jsx:302-312 chains saves on saveChainRef and, at line 312, unconditionally writes `sessionIdRef.current = data.session.id` after the round-trip. "New chat" (lines 649-651) sets `sessionIdRef.current = null`. If the last-turn save for OLD is in flight when New chat is clicked (window ≈700ms debounce + network RTT), its line-312 c
- fix: Add a generation/epoch ref bumped in "New chat"; capture it when chaining a save and skip the line-312 write-back (and the whole upsert) if the ref changed, so a stale in-flight save can't resurrect t

**#62 [MEDIUM] fe:components/DashboardPage.jsx:1295** — Suggested Actions gate on PERSONAL integrations while /actions/execute routes to WORKSPACE creds — m
- verdict: REAL · reachable: yes
- DashboardPage.jsx:1295-1302 builds actionConnections purely from props.integrations (jira_api_token/linear_api_key/slack_bot_token/teams_webhook). App.jsx:1146-1158 shows props.integrations is populated ONLY from personal sources (readIntegrationStore + /user-settings); no workspace-integrations config is ever merged. So for a member with
- fix: In DashboardPage, fetch GET /workspaces/{activeWorkspaceId}/integrations and OR its per-provider `configured` status into actionConnections (jira/linear/slack/teams) so the gate matches the backend's 

**#63 [MEDIUM] fe:components/DashboardPage.jsx:829** — persistResultPatch swallows PATCH failures — chat/card edits report success but silently revert on r
- verdict: REAL · reachable: yes
- DashboardPage.jsx:815-831: persistResultPatch does optimistic setResult+history update, then fires PATCH /meetings/{id} with `.catch(() => {})` (l.829) and never checks res.ok. lib/api.js:20-28: apiFetch returns raw fetch — does NOT reject on 401/500/502, so those resolve and network errors are swallowed. ChatPanel.jsx:471-476 (agent reru
- fix: In persistResultPatch, await the response, check res.ok, and on failure surface an error (e.g. toast/revert optimistic state) instead of `.catch(() => {})`; propagate failure so ChatPanel doesn't emit

**#64 [MEDIUM] fe:components/IntegrationsModal.jsx:202** — Workspace integration save replaces entire provider config, blanking every untouched field
- verdict: REAL · reachable: yes
- IntegrationsModal.jsx:202 `config[f.key] = wsForm[f.key] || ''` sends every provider field, '' for untouched (fields render blank since secrets are never shown, line 483). workspace_routes.py:460-468: `clean` keeps the empty keys and the upsert full-REPLACES `config` (on_conflict, no merge) → stored bot_token destroyed. workspace_integrat
- fix: In wsSaveProvider omit blank fields (or backend-merge over the existing stored config) so an untouched secret field means "keep," not "clear"; add an explicit clear affordance for intentional removal.

**#65 [MEDIUM] fe:components/ProxyProfile.jsx:111** — Window-focus refetch clobbers unsaved profile, notes, and default-standin edits
- verdict: REAL · reachable: yes
- ProxyProfile.jsx:111-112 attaches window 'focus' → reload → loadProfileAndReps(). That fn (76-81) unconditionally does setRoleFocus/setNotes(clean(...))/setDefaultStandin from the server profile on pRes.ok, with no dirty-state guard. Those three state values back the controlled Role input (363), Standing-notes textarea (372) and default-s
- fix: Guard the focus reload against unsaved edits (track a dirty flag / compare to last-loaded values) and skip setRoleFocus/setNotes/setDefaultStandin when dirty, or only reload reps+digest on focus, not 

**#68 [MEDIUM] .github/workflows/deploy.yml:16** — No CI executes any tests — 870 green backend tests + Playwright suite exist, but every deploy is ung
- verdict: REAL · reachable: yes
- .github/workflows/deploy.yml is the ONLY workflow (Glob: no other yml/yaml under .github); steps run checkout→npm ci→npm run build→deploy-pages with NO pytest/npm test/playwright step (grep in .github = NONE). render.yaml:6-7 deploys backend with only pip install + uvicorn, no tests, auto on push to main. Suites exist and are large: 92 ba
- fix: Add a required CI job (e.g. test.yml on pull_request + push to main) running backend pytest and frontend npm run test:e2e, gating deploy/merge on green.

**#71 [MEDIUM] recall_routes.py:2222** — join_meeting dedup is check-then-act across multi-second awaits — simultaneous joins spawn duplicate
- verdict: REAL · reachable: yes
- recall_routes.py:2520 `_find_shared_workspace_bot` (and 2507/2535 helpers) only read `meeting_bots`; the Recall bot is created at 2560 `await client.post(...)` and the row is inserted only AFTER at 2605. No asyncio.Lock in the file; workspace_migration.sql:31-41 gives `meeting_bots` a bot_id PK and a NON-unique meeting_url index. Dedup su
- fix: Wrap dedup-check→create→insert in a per-normalized-URL asyncio.Lock (single-worker prod) and re-check dedup after acquiring; ideally insert a claim row / atomic upsert before creating the Recall bot.

**#72 [MEDIUM] realtime_routes.py:2665** — Synchronous Supabase client called directly on the event loop throughout the realtime webhook hot pa
- verdict: REAL · reachable: yes
- auth.py:37 create_client → SYNC supabase Client (not AsyncClient), reused in recall_routes.py:20. recall_routes.py:152 _db_save does supabase.table().upsert().execute() (blocking HTTP), no to_thread. realtime_routes.py:2735 re-serializes the FULL transcript ("\n".join(rt_lines), cap 8000) + transcript_segments JSONB every 8 lines (2644,27
- fix: Wrap _db_save/_db_save_memory/_db_append_command in await asyncio.to_thread(...) (or a background write queue) so the sync supabase call runs off the event loop; also persist incrementally instead of 

**#77 [MEDIUM] perception_state.py:522** — Live-bot owner identity is display-name based and spoofable; the participant-ID hardening is default
- verdict: REAL · reachable: yes
- perception_state.py:522-526: is_owner_speaker matches owner "Abhinav Dasari" against speaker "Abhinav" via first-name fallback (True). realtime_routes.py:4112 comment: display name is "attacker-controllable". Default path is two-channel (realtime_routes.py:460-466, PRISM_TWO_CHANNEL default ON): voice/agent_channel.py:86 computes is_owner
- fix: Bind owner identity to Recall's stable participant_id (wire is_owner_with_lock/maybe_lock_owner_id into the default two-channel agent_channel/voice_channel and make it on by default), not the attacker

**#82 [MEDIUM] ms_calendar_routes.py:267** — /ms-calendar/events 401 handler permanently wipes a possibly-valid refresh token (diverges from Goog
- verdict: REAL · reachable: yes
- ms_calendar_routes.py:262-274 — on a Graph 401 the handler unconditionally nulls ms_access_token AND ms_refresh_token AND ms_token_expires_at. Google mirror (calendar_routes.py:325-332) only flips calendar_connected=False, preserving both tokens — confirming the divergence. get_valid_ms_token (lines 109-132) attempts refresh only near exp
- fix: Mirror Google: on 401 set only outlook_connected=False (and optionally clear ms_access_token) but PRESERVE ms_refresh_token so a valid refresh survives a transient/pre-expiry 401.

**#85 [MEDIUM] fe:App.jsx:2107** — Record mode duplicates the transcript quadratically: onresult joins e.results from index 0 and re-ap
- verdict: REAL · reachable: yes
- App.jsx:2127-2134 startRecording.onresult: with continuous=true (2124), e.results is Chrome's cumulative SpeechRecognitionResultList, so `Array.from(e.results).map(r=>r[0].transcript).join(' ')` (2128) rebuilds the FULL transcript every event; line 2130 then APPENDS it onto prev.record instead of replacing → e1="s1", e2="s1\ns1 s2", e3 ad
- fix: e.results is already cumulative — replace instead of append: set next=text (or iterate from e.resultIndex to append only new results).

**#86 [MEDIUM] fe:lib/extractAudio.js:40** — Upload tab executes runtime-fetched code from unpkg.com with no subresource integrity
- verdict: REAL · reachable: yes
- extractAudio.js:40 hardcodes coreBase='https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm'; lines 45-48 toBlobURL()-fetch ffmpeg-core.js/.wasm (plain fetch, no SRI) then line 53 ffmpeg.load() executes it in a worker. On failure lines 49-51/56-60 throw "Couldn't download the audio converter…" and null the promise — retry hits the same unpkg UR
- fix: Vendor @ffmpeg/core locally (bundle via Vite import.meta.url or serve from your own origin) instead of unpkg — removes the CDN availability single-point-of-failure and the untrusted-CDN execution path

**#93 [MEDIUM] agents/sentiment.py:46** — sentiment failure streams sentiment:null, wiping the safe default and diverging from the non-stream 
- verdict: REAL · reachable: yes
- sentiment.py:46,97: `_DEFAULT={"sentiment":None}` returned after 2 failed attempts. analysis_routes.py:77 uses `key in agent_result` (key-presence, not truthiness), so `{"sentiment":None}` passes → streams `{"agent":"sentiment","sentiment":null}` and line 80 appends "sentiment" to succeeded_agents (streamed at :97). App.jsx:2543 `accumula
- fix: In analysis_routes.py:77 gate on a truthy value, not key presence (e.g. `if key and agent_result.get(key):`), matching _state_to_result; or have sentiment.run() return the neutral DEFAULT object inste

**#94 [MEDIUM] fe:components/ChatPanel.jsx:852** — confirm-tool reports 'Executed' even when the confirmed action failed
- verdict: REAL · reachable: yes
- jira.py:126-138 returns {"error":"Jira API error 401:…"} on non-2xx WITHOUT raising; registry.py:144-155 (confirm_and_execute) passes that dict through unchanged; chat_routes.py:722-723 returns it as HTTP 200. Frontend ChatPanel.jsx:852-858: `if(!res.ok) throw` passes on 200, then `data.summary || 'Executed ${pc.tool}'` renders the succes
- fix: In the confirm onClick, branch on the JSON body: if `data.error` (or `!data.success`), surface a failure message and keep/mark the card as failed instead of adding an "Executed" toolsUsed badge.

**#98 [MEDIUM] fe:components/ChatPanel.jsx:972** — ChatPanel is unreadable in light mode: hardcoded near-black bubble/composer backgrounds paired with 
- verdict: REAL · reachable: yes
- Light theme is a shipped, persisted, one-click feature: DashboardPage.jsx:679 reads localStorage 'prism_dashboard_theme', toggleTheme (680) is exposed in DashboardSidebar.jsx:427-430, and line 683-685 applies .theme-light to <html> so tokens cascade into ChatPanel. index.css:1039-1042 flips --db-text to #0f172a / --db-text-soft to #334155
- fix: Replace hardcoded bg-[#0d0e10]/bg-[#08090a]/from-[#0c4a6e] and text-white in ChatPanel with theme tokens (var(--db-fill)/--db-glass-*/--db-text) so backgrounds and text flip together in light mode.

**#105 [MEDIUM] recall_routes.py:1191** — Recovery re-spawns proactive checker + pollers but never the voice pipeline — recovered bot is a 'lo
- verdict: REAL · reachable: yes
- Voice is the default live path: _recall_bot_create_json (recall_routes.py 759-798) unconditionally wires the Flux audio WS + drops transcript.data; voice/bridge.py routes turns into command dispatch and drives TTS; voice_router mounted unconditionally (main.py:93). audio_routes._resolve_bot (78-85) reads ONLY in-memory _realtime_token_ind
- fix: Persist realtime_token in bot_sessions and re-register it in _db_load/recover_active_bots, AND give audio_routes._resolve_bot the same bot_id-based restart fallback the /realtime-events/{token} webhoo

**#107 [MEDIUM] voice/speaker_page.py:68** — Reflected XSS in public /voice/speaker-page/{token} — raw token injected into HTML/JS, no validation
- verdict: REAL · reachable: yes
- speaker_page.py:68,118 embeds the path token unescaped: `_TEMPLATE.replace("__TOKEN__", token)` into `var TOKEN = "__TOKEN__";` in a <script>, served text/html via HTMLResponse (audio_routes.py:139). Handler (audio_routes.py:135-139) is public, unauthenticated, no validation ("An invalid token still serves the page"); router always regist

**#109 [MEDIUM] voice/bridge.py:96** — bridge.speak() gates on pipeline existence, not speaker-socket connectivity -> permanent mute + dead
- verdict: REAL · reachable: yes
- bridge.py:96 gates only on `session is None or session.pipeline is None`; the pipeline is created the moment the audio-in WS connects (audio_routes.py:157), independent of the separate speaker socket. SpeakerConnection.send_pcm silently drops PCM when `_ws is None` (pipeline.py:142-150, comment: "the bot is mute... every log line still sa
- fix: In bridge.speak, also `return False` when the speaker socket isn't attached (e.g. `not session.connection.connected`) so the caller falls back to the MP3 upload path.

**#110 [MEDIUM] voice/voice_channel.py:185** — Bot muted mid-action still speaks agent-result and blocked-capability narration (two-channel path)
- verdict: REAL · reachable: yes
- voice_channel.py: mute checked ONLY at entry (L143); dispatch calls agent_channel.run (L168, multi-second, no mute check in agent_channel.py), then narrates with NO re-check — blocked-cap _send_chat_response L175 + _speak L177, and result _send_chat_response L183 + _speak L185. Mute endpoint (realtime 4515, shipped UI App.jsx:914) does se
- fix: After agent_channel.run returns, re-check state.get("muted") (and/or barge.interrupted_since) before the chat/voice narration at voice_channel.py L173-186; skip narration if muted.

**#8 [LOW] agents/health_score.py:44** — Sentiment's failure default {"sentiment": None} poisons the Tier-2 context and crashes health_score
- verdict: REAL · reachable: yes
- Confirmed end-to-end. sentiment.py:46,97 returns {"sentiment": None} on double-fail (no throw). analysis_service.py:250 `r.get("sentiment",{}).get("sentiment",{})` yields None (key present, {} default unused) → context["sentiment"]=None. health_score.py:44-45 `context.get("sentiment",{})` returns None, then `None.get("overall")` → Attribu
- fix: In analysis_service._tier1_barrier coalesce None: `(r.get("sentiment") or {}).get("sentiment") or {}`; also harden health_score.py:44 to `context.get("sentiment") or {}` and fix analysis_routes.py:77 

**#12 [LOW] cross_meeting_service.py:120** — Cross-meeting 'tense meetings' insight keys on sentiment labels the agent's vocabulary can no longer
- verdict: REAL · reachable: yes
- sentiment.py:10-19 defines overall vocab as collaborative|aligned|decision-making|exploratory|frictional|divergent|rushed|draining|neutral — none is tense/unresolved/conflicted. cross_meeting_service.py:146 increments tense_meetings only when overall in {tense,unresolved,conflicted}, so current-agent meetings never count; frictional/diver
- fix: Rekey the tension count to the current vocabulary (e.g. frictional, divergent, draining, unresolved-arc) in both cross_meeting_service.py:146 and lib/insights.js:106.

**#20 [LOW] fe:components/ChatPanel.jsx:127** — Overbroad deterministic intent regexes silently reroute per-meeting questions to the wrong surface
- verdict: REAL · reachable: yes
- detectGlobalIntent (ChatPanel.jsx:140) matches a bare /trend/ (also 139 /over time/, 143 /history of/). "what was the sentiment trend in this meeting?" fails detectAgentIntent (line 158 needs a re-run verb like reanalyze/rerun) so globalIntent wins at line 379/486. /chat/global body (line 495) omits transcript/result/meeting_id → answers 
- fix: Add a per-meeting scope guard: when a meeting is loaded and the message references "this meeting/here", prefer /chat; narrow bare /trend/, /over time/, /history of/ to require an explicit multi-meetin

**#25 [LOW] knowledge_service.py:276** — Conflict detection is dead code on every real path — the documented trust-layer banner can never fir
- verdict: REAL · reachable: yes
- knowledge_service.py:276 gates conflict detection on `if not hybrid`; line 282 (`rows[0]["possible_conflict"]=True`) is the ONLY writer of the flag and lives inside that branch. Signature line 148 sets `hybrid: bool = True` as default. Every prod caller uses the default: knowledge_lookup.py:63 (on-demand RAG, no hybrid arg), knowledge_pro
- fix: Make conflict detection rank-aware so it runs in hybrid mode (e.g. flag when top-2 come from different docs with near-equal RRF rank), or pass hybrid=False in knowledge_lookup — currently line 276's g

**#26 [LOW] knowledge_service.py:348** — All PDF chunks inherit page-1 metadata — citations always point to the wrong page
- verdict: REAL · reachable: yes
- knowledge_service.py:348 `base_meta = (loaded.page_metadata or [{}])[0]` keeps only page-1 meta, then :349 passes it to chunk_text for the whole doc. chunker.py:59,81 stamp `dict(base_metadata)` onto EVERY chunk → all carry {"page":1}. pdf_loader.py:42 correctly builds per-page meta that is discarded. Stored at knowledge_service.py:377, s
- fix: Chunk per-page in ingest_doc (iterate loaded.page_metadata, call chunk_text per page with that page's meta) instead of concatenating loaded.text and using page_metadata[0].

**#28 [LOW] workspace_routes.py:438** — Workspace integration shows 'connected' while the resolver silently ignores it and routes to persona
- verdict: REAL · reachable: yes
- workspace_routes.py:438 computes `connected = bool(r) and bool(cfg)` — true for any non-empty config dict, e.g. Jira `{jira_base_url:'', jira_email:'x@y.com', jira_api_token:'tok'}`. `_integration_label` (line 399-401) reads only email/project_key, so it renders a label. But workspace_integrations.py:106 gates the overlay on `all(_nonempt
- fix: Compute `connected` from the resolver's own PROVIDER_FIELDS['required'] completeness (all required fields non-empty), and reject incomplete configs in the PUT handler.

**#36 [LOW] proxy_routes.py:207** — Bidirectional substring owner matching misattributes other people's tasks into drafts and follow-up 
- verdict: REAL · reachable: yes
- proxy_routes.py:207 `if n and (n in o or o in n)` is bidirectional substring matching. `_author_names` (484-486) feeds it the bare first name ("dan") plus email prefix, so an item owned by "Dana" matches ("dan" in "dana"). This flows into the delivered draft via `_gather_my_items`→`_items_block` (265,707,755) and independently into the fo
- fix: Replace substring containment with token/word-boundary equality: tokenize owner and each known name, match on exact token overlap instead of `in`.

**#57 [LOW] fe:lib/dueStatus.js:11** — dueInfo fallback anchors relative due-phrases to viewing time — legacy items can never show overdue
- verdict: REAL · reachable: yes
- dueStatus.js:11 calls resolveDatePhrase(item.due) with no reference arg; resolveDate.js:79 defaults reference=new Date() (viewing time). For a bare weekday, resolveDate.js:43 nextWeekday(ref,dow,includeToday=true) resolves to the COMING Thursday (0-6 days out), so dueStatus.js:19-20 yields diffDays 0..6 → 'soon'/'later', never 'overdue'. 
- fix: Have dueInfo accept the meeting's date and pass it as resolveDatePhrase's `reference` so relative/no-year phrases anchor to when the meeting occurred, not viewing time.

**#66 [LOW] fe:components/KnowledgeBase.jsx:15** — KnowledgeBase refresh has no catch: a failed listDocs shows the 'No documents yet' empty state and l
- verdict: REAL · reachable: yes
- KnowledgeBase.jsx:15-23 `refresh` is try/finally with NO catch: on throw, setDocs never runs but finally sets loading=false. listDocs (lib/knowledge.js:4-11,15-22) throws Error on any non-2xx (401/5xx) or fetch network reject. On fresh mount docs=[] + loading=false → render falls to lines 62-80 empty state "No documents in {scope} yet". u
- fix: Add a catch in refresh that sets an error state (render a distinct error card, not the empty state) and does NOT clobber docs; keep prior docs on failure.

**#78 [LOW] fe:App.jsx:339** — Solo / single-speaker meetings render and persist a fabricated 'Neutral' sentiment card
- verdict: REAL · reachable: yes
- orchestrator.py:57-58 drops sentiment when _count_speakers<2 (solo/no-speaker-label transcripts), so the agent never runs. App.jsx:339 DEFAULT_RESULT.sentiment={overall:'neutral',score:50,arc:'stable',speakers:[]}; :2501 accumulated seeds from it and no sentiment chunk overwrites it. MeetingView.jsx:144+548 render SentimentCard for any no
- fix: Gate SentimentCard at MeetingView.jsx:548 on sentiment actually computed (e.g. result.agents_run?.includes('sentiment') or speakers.length), or have SentimentCard return null for the untouched default

**#79 [LOW] fe:lib/api.js:3** — Dev port mismatch: CLAUDE.md says run backend on 8000, but frontend API base default, backend WEBHOO
- verdict: REAL · reachable: conditional
- Genuine inconsistency confirmed: CLAUDE.md:19 says `uvicorn main:app --reload --port 8000`, but frontend/.env:3 (committed) sets `VITE_API_URL=http://localhost:8001` and frontend/src/lib/api.js:3 falls back to `http://localhost:8001`. A dev following CLAUDE.md's 8000 would have the frontend hit :8001 → connection-refused. Note: the findin
- fix: Make CLAUDE.md, frontend/.env, and api.js default agree on one dev port (change CLAUDE.md to --port 8001, or vice-versa).

**#80 [LOW] analysis_routes.py:108** — Per-IP rate limiting keys on request.client.host, which behind Render's proxy is the load-balancer I
- verdict: REAL · reachable: yes
- analysis_routes.py:108 keys the limiter on request.client.host. render.yaml:7 runs `uvicorn main:app` with no --forwarded-allow-ips and no FORWARDED_ALLOW_IPS env. uvicorn 0.46.0 config.py:342 defaults forwarded_allow_ips to "127.0.0.1"; proxy_headers.py rewrites scope["client"] only when the immediate peer is trusted. Render's router is 
- fix: Set FORWARDED_ALLOW_IPS='*' (or --forwarded-allow-ips) and derive client IP from the first X-Forwarded-For hop, or move these paid endpoints behind auth / a per-user cap.

**#95 [LOW] knowledge_routes.py:264** — Several knowledge_routes endpoints call Supabase .execute() synchronously on the event loop
- verdict: REAL · reachable: yes
- knowledge_routes.py:264 (workspace membership) and :273 (docs order/select) call raw synchronous `.execute()` inside async `list_docs`, unlike siblings get_doc (:305,:318), delete (:379-380), upload (:36,:88) which all `await _execute(...)`. The helper knowledge_service.py:36-44 exists precisely for this: its docstring says calling `.exec
- fix: Wrap both list_docs queries in `await _execute(...)` (membership check and `q.order(...).execute()`), matching the rest of the module.

**#100 [LOW] fe:components/dashboard/LiveMeetingView.jsx:188** — LiveMeetingView uses hardcoded white/gray text that vanishes under the new dashboard light theme
- verdict: REAL · reachable: yes
- Light theme is real+shipped: DashboardPage.jsx:679-686 toggles `theme-light` on documentElement (default 'dark'), sidebar item at DashboardSidebar.jsx:424-430. index.css:1033-1050 makes the dashboard light (--db-page-bg #eef1f5, glass #ffffff). LiveMeetingView is mounted inside that region (DashboardPage.jsx:1612-1613, no dark wrapper). L
- fix: Replace text-white/40|50 at LiveMeetingView.jsx:188,197 with theme tokens, e.g. style={{color:'var(--db-text-faint)'}} (same for the shared-loading text).

**#108 [LOW] voice/audio_routes.py:149** — /voice/audio-in single-ingress guard has a check-accept-set race → duplicate pipelines and wrong-pip
- verdict: REAL · reachable: yes
- audio_routes.py:149 checks session.audio_socket_active, :155 `await ws.accept()` yields, :156 sets the flag — a genuine check-await-set TOCTOU in the single event loop. Two coroutines for one bot can both pass :149 while suspended at :155, then both build a VoicePipeline (:157-161, with another `await` at :160); session.pipeline is clobbe
- fix: Claim the slot before any await: set session.audio_socket_active=True immediately after the check and before `await ws.accept()`, or wrap check-and-set in a per-bot asyncio.Lock.

## PARTIAL — real defect but overstated (49)

**#13 [MEDIUM] chat_routes.py:386** — Taint contract (taints_context) is not enforced in the chat tool loop — prompt injection via web_sea
- verdict: PARTIAL · reachable: yes
- chat_routes.py:353-431 (_tool_calling_loop) never calls is_tainted; tools/tool_choice stay in call_kwargs across max_iterations=3. The contract (registry.py:31, is_tainted :49) IS enforced in realtime_routes.py:3624 and voice/agent_channel.py:225, but NOT here. web_search auto-registers (tools/__init__.py:3, requires=None, web_search.py:1
- fix: In _tool_calling_loop, after each iteration's tool executions, if any executed tool name is_tainted(), pop tools/tool_choice from call_kwargs (mirror realtime_routes._strip_tools_if_tainted) so no fur

**#15 [MEDIUM] tools/calendar.py:235** — calendar_create_event / calendar_update_event are confirm=False, contradicting the chat prompt's 'sy
- verdict: PARTIAL · reachable: yes
- calendar.py:235/269 both confirm=False, while gmail.py:150/jira.py:194/linear.py:155/slack.py:186 are confirm=True — so the /chat prompt (chat_routes.py:552-553 "for actions that send/post/create, the system will ask the user to confirm") is honored by every write tool EXCEPT the two calendar writes. Reachable in default prod: shipped Cha
- fix: Set confirm=True on calendar_create_event/calendar_update_event to match the other write tools, and add an explicit-reschedule-verb + unambiguous-title guardrail to calendar_update_event's description

**#23 [MEDIUM] knowledge_ingest/pdf_loader.py:36** — OCR and PDF rasterization run synchronously on the FastAPI event loop during ingest
- verdict: PARTIAL · reachable: conditional
- pdf_loader.py:36-37: async load() calls blocking page.get_pixmap(dpi=200)+pytesseract with no to_thread. Runs on the single-worker loop via knowledge_routes.py:193 (async ingest_doc as a Starlette BackgroundTask = awaited on loop) and analysis_routes.py:160 (awaited in the unauth /extract-document handler, shipped App.jsx:2214). So event-
- fix: Wrap the loader body in asyncio.to_thread (offload get_pixmap + pytesseract), and either install tesseract in render.yaml's build or explicitly disable/flag OCR so scanned PDFs don't silently return e

**#45 [MEDIUM] sandbox/computer_use.py:96** — Computer-use loop's only guard against destructive actions in the owner's logged-in browser is the s
- verdict: PARTIAL · reachable: conditional
- Mechanism confirmed: translate_action (computer_use.py:129-180) maps left_click/type/key/navigate with only coord/scroll clamps, and browserbase_provider._do_act (309-365) executes them unconditionally — the ONLY destructive-action guard is the system prompt (computer_use.py:96-106, "READ-ONLY presenter... NEVER merge/deploy/approve"). Sa
- fix: Add a code-level backstop instead of trusting the prompt: present from a NON-authenticated/view-only browser session (not the owner's logged-in Context), or require explicit human confirmation before 

**#50 [MEDIUM] sandbox/computer_use.py:367** — CU loop accumulates every screenshot in the message history unbounded, and speaks raw exception text
- verdict: PARTIAL · reachable: yes
- Both underlying defects are real. computer_use.py:347+356-367 appends assistant turn + a fresh base64 PNG per tool_use every step, never pruned (capped at max_steps=25, line 230); re-sends all prior shots each turn. computer_use.py:318-319 yields raw `{exc}`; presentation.py:243 speaks it and :250 chats it — so any model error's raw text 
- fix: Cap history to the last 1-2 screenshots (replace older tool_result images with a text placeholder), and replace raw `{exc}` in the yielded line with a generic "I hit a problem showing that — stopping 

**#83 [MEDIUM] render.yaml:26** — render.yaml omits MICROSOFT_CLIENT_ID/SECRET; losing them converts a config error into permanent tok
- verdict: PARTIAL · reachable: conditional
- ms_calendar_routes.py:64-66 refresh_ms_token returns None when MS_CLIENT_ID/SECRET empty; :115 the success block is skipped so :132 returns the stale expired token; /ms-calendar/events :262-274 then gets a 401 and nulls ms_access_token AND ms_refresh_token with no config-vs-revocation distinction — permanent, survives restoring the env va
- fix: In the /ms-calendar/events 401 handler, don't clear ms_refresh_token when the preceding refresh failed due to missing MS_CLIENT_ID/SECRET (surface a config error instead); and add MICROSOFT_CLIENT_ID/

**#1 [LOW] realtime_routes.py:3824** — Tokenized realtime webhook is bypassable: the 'lost token' fallback accepts any attacker-chosen toke
- verdict: PARTIAL · reachable: yes
- Mechanism is real: realtime_events_tokenized (realtime_routes.py:3861) falls back when token not in _realtime_token_index (3881), accepts if payload_bot_id is a known bot (3900-3908), re-binds attacker's token (3928), processes forged payload (3929). Test at test_security_hardening.py:282 confirms unknown-token+known-bot is accepted; bot_
- fix: To close it meaningfully, add Recall webhook HMAC verification (like RECALL_WEBHOOK_SECRET on /recall-webhook, recall_routes.py:2961) to BOTH /realtime-events routes, or retire the legacy unauthentica

**#2 [LOW] realtime_routes.py:4233** — Chat-message sender names skip _safe_speaker_name sanitization — transcript-line forgery / prompt in
- verdict: PARTIAL · reachable: conditional
- realtime_routes.py:2702 `_record_human_chat_line` builds `line = f"{sender or 'Someone'}: {text}"` with sender raw — no `_safe_speaker_name`. sender comes from webhook line 4360 (`sender_obj.get('name')`, attacker-controlled) and is passed unaltered at 4394. The parallel AUDIO path DOES sanitize: line 4115 `_safe_speaker_name(...)`, comme
- fix: In `_record_human_chat_line` (line 2702), wrap sender with `_safe_speaker_name(sender)` before building the line, matching the audio path at 4115.

**#4 [LOW] recall_routes.py:2687** — call_ended via webhook or stand-in poller skips _db_load — durable realtime transcript lost after a 
- verdict: PARTIAL · reachable: yes
- Mechanism is code-accurate. recall_webhook call_ended (recall_routes.py:2985-3014) builds a bare bot_store entry with NO _db_load, then runs _process_bot_transcript; _poll_standin_lifecycle call_ended (1045-1053) does bot_store.setdefault(bare) with no _db_load. _process_bot_transcript reads realtime lines only from bot_store (2241, 2271)
- fix: Call _db_load(bot_id) into bot_store at the top of _process_bot_transcript when realtime_transcript_lines is empty (or in the webhook/poller call_ended branches), mirroring /bot-status:2687.

**#9 [LOW] analysis_routes.py:77** — SSE success accounting counts failure defaults as success and leaks stray agent/agent_error keys int
- verdict: PARTIAL · reachable: yes
- analysis_routes.py:77 gates success on presence (`key in agent_result`), not truthiness. agents/sentiment.py:46 `_DEFAULT={"sentiment":None}` returned on failure (:97, caught not raised) → `"sentiment" in {...}` True → pushed to succeeded_agents (:80) and final agents_run (:97), so the diagnostic does mislabel a failed sentiment as run. T
- fix: Gate success on a truthy value (`if key and agent_result.get(key):`) to match _state_to_result, and drop the control keys `agent`/`agent_error` from what the frontend merges into (or persists as) `res

**#10 [LOW] agents/orchestrator.py:57** — The solo-meeting sentiment gate is defeated by the 'Meeting participants:' header that build_analysi
- verdict: PARTIAL · reachable: conditional
- Mechanism is real: build_analysis_transcript prepends literal line "Meeting participants:" (analysis_service.py:151-152,160) whenever speakers is non-empty; _orchestrator_node counts speakers on that header-prepended text (analysis_service.py:167); _count_speakers treats any short colon-prefixed line as a speaker, so "Meeting participants
- fix: Compute the sentiment speaker-count gate on req.transcript (the raw body) before the header is prepended — or have _count_speakers skip the "Meeting participants:" header/bullet block.

**#11 [LOW] agents/utils.py:59** — Prose-tolerant JSON parsing was added only to content_analyst; the other nine agents still hard-fail
- verdict: PARTIAL · reachable: conditional
- Premise is wrong: prose-tolerant _parse_json exists in TWO agents, not one — content_analyst.py:123-134 AND sentiment.py:49-61 (its comment: "most parse-fragile of the agents"). The other 8 (summarizer.py:55, decisions.py:26, action_items.py:34, health_score.py:70, calendar_suggester.py:90, email_drafter.py:70, speaker_coach.py:27, decisi
- fix: Hoist the prose-tolerant _parse_json (strip_fences → json.loads → slice outermost {...}) into utils.py and use it at every agent's parse site for consistency.

**#16 [LOW] chat_routes.py:42** — Pending tool confirmations are in-memory and consumed before execution — restart/multi-worker 404s, 
- verdict: PARTIAL · reachable: yes
- chat_routes.py:21 `_pending_tools` is an in-memory module dict (lost on restart); :22 `_PENDING_TTL=300` (5min) so a 6-min read expires; `_pop_pending` (43-47) `.pop()`s the entry BEFORE execution and returns None if expired; confirm_tool (712-714) then 404s; `confirm_and_execute` runs at 722 after the pop → one-shot, no retry. Frontend C
- fix: Pop pending entry only after confirm_and_execute succeeds (else re-store); persist pending confirmations in Supabase to survive restart; surface the 404/error in ChatPanel instead of console.warn only

**#18 [LOW] chat_routes.py:283** — _get_user_settings swallows every exception into {} — integrations silently vanish for the turn, and
- verdict: PARTIAL · reachable: yes
- Mechanism is real and unflagged. chat_routes.py:284-285: bare `except Exception: return {}` turns any Supabase settings-fetch failure into empty settings. registry.py:64: get_available_tools drops each tool whose `requires` cred is absent, so `{}` → gmail/calendar/slack/linear tools disappear (per-meeting chat: "no email tools"). confirm_
- fix: In _get_user_settings distinguish "no row" (return {}) from "fetch raised" — on exception re-raise so callers surface a 503/"temporarily unavailable" instead of silently dropping tools; and in confirm

**#29 [LOW] storage_routes.py:221** — date[:16] workspace dedup both hides distinct same-minute meetings and duplicates the same meeting a
- verdict: PARTIAL · reachable: conditional
- storage_routes.py:221-224 keys dedup on date[:16] (minute). Fan-out (304-341) copies entry.date verbatim, so all copies of ONE meeting share an identical date → dedup is correct on the common path. App.jsx:2025 stamps date=new Date().toISOString() at each client's save. Scenario A (two DISTINCT transcripts saved same-workspace, same wall-
- fix: Dedup on a stable identity (recall_bot_id for bot meetings; recorded_by_user_id + origin id or content hash for pasted) and use date[:16] only as a last-resort fallback.

**#32 [LOW] workspace_routes.py:295** — workspace_members.user_email is client-supplied and never verified against the authenticated identit
- verdict: PARTIAL · reachable: yes
- workspace_routes.py:272,295 write client-supplied body.user_email verbatim; auth.py:99,128 confirm require_user_id returns only the token sub and discards the real email Supabase returns — so the field is genuinely unverified. But it is never an authz key: upsert on_conflict=workspace_id,user_id (line 298) limits an attacker to their OWN 
- fix: Derive member email server-side from the validated token (extend require_user_id/_validate_remote to return email) instead of trusting body.user_email in accept_invite and workspace create.

**#34 [LOW] proxy_routes.py:117** — _enrich_profile's fire-and-forget read→LLM→full-row upsert corrupts the profile — persists LLM error
- verdict: PARTIAL · reachable: yes
- proxy_routes.py:477-479 `_llm_reply` returns literal "Sorry, I had trouble drafting that. Try again?" on exception; :113-116 `_JUNK` guard omits that sentinel, so :117-124 upserts it into standing_notes on any LLM outage. Enrich fires unconditionally on every approve (:864, no flag), endpoint shipped (StandInComposer.jsx:142). REAL. But "
- fix: Have _llm_reply signal failure distinguishably (raise, or return a sentinel), and skip the enrich upsert on failure — or add both _llm_reply fallback strings to the reject set before persisting standi

**#37 [LOW] proxy_routes.py:602** — Follow-up email sends BEFORE the DB stamp — missing migration #23 columns mean the email fires but n
- verdict: PARTIAL · reachable: conditional
- proxy_routes.py:602 sends the email, then :604 does the DB update — ordering claim is literally true, and if migration #23 cols are missing (confirmed manual-only via proxy_followup_migration.sql; absent from schema.sql) the update raises and is caught+logged at :606 after the email went out. But overstated: (a) conditional — needs the op
- fix: Write the brief row first (followup_brief/meeting_id), then email, then set followup_sent_at in a follow-up update — so a missing-column or DB error can't leave an email sent with no record.

**#40 [LOW] calendar_routes.py:146** — get_valid_token silently hands back an expired Google token when refresh fails or refresh_token is m
- verdict: PARTIAL · reachable: conditional
- Mechanism real: calendar_routes.py:141 gates refresh on `expires_at_str and refresh_token`, so a missing refresh_token skips refresh and returns the stale token (135/163); on refresh failure refresh_google_token returns None (85/108) and the old token is kept (146-149). create-event maps the tool's 401 error to 502 (470-471; tools/calenda
- fix: In /calendar/create-event, detect a 401 from the tool result (mirror /calendar/events:325-332): mark calendar_connected=False and raise HTTP 401 "reconnect" instead of a generic 502; optionally have g

**#41 [LOW] calendar_resolution.py:218** — Natural-language date resolution anchors 'today' to server UTC — evening users west of UTC get day-s
- verdict: PARTIAL · reachable: yes
- Real callers never hit the cited line 218 (`datetime.now().date()`): action_items.py:20 and calendar_suggester.py:84 both pass `reference_date=datetime.now(timezone.utc).date()` (grep confirms only these two callers + tests, all passing reference_date). So the operative UTC anchor is at the callers, not line 218's dead default. The substa
- fix: Capture/propagate the user's timezone and compute reference_date as their local date (e.g. zoneinfo) instead of datetime.now(timezone.utc).date() at action_items.py:20 and calendar_suggester.py:84.

**#42 [LOW] calendar_resolution.py:120** — Bare-weekday rule resolves PAST references ('last Friday') to a future date
- verdict: PARTIAL · reachable: conditional
- calendar_resolution.py:120-121 matches a bare `\bfriday\b` (inside "last Friday") and returns `_next_weekday(..., include_current_week=True)` → a FUTURE Friday; no "last"/past handling exists, and the dateparser fallback (which understands "last") never runs because line 221 already returned non-None (line 226 gates fallback on `resolved 
- fix: In _resolve_date_handrolled, detect a preceding "last/past/previous" (or generally past-tense context) before the bare-weekday rule and either skip resolution or subtract a week; and in calendar_sugge

**#43 [LOW] actions_routes.py:48** — Any DB error during workspace resolution silently reroutes a workspace action to PERSONAL credential
- verdict: PARTIAL · reachable: conditional
- actions_routes.py:50-52 does swallow the DB error and return None — a real silent degradation. But line 71 is `_meeting_workspace_id(...) or (req.workspace_id or "").strip() or None`: on the None, it falls back to the client-supplied workspace id. The shipped frontend reliably sends it (DashboardPage.jsx:1578 workspaceId={activeWorkspaceI
- fix: In _meeting_workspace_id, don't let an exception masquerade as "no workspace" — re-raise (or return a sentinel that keeps the client-provided req.workspace_id) so a transient Supabase error can't sile

**#46 [LOW] presentation.py:271** — Browserbase keep-alive sessions are never released in any normal flow — billed until provider timeou
- verdict: PARTIAL · reachable: conditional
- Confirmed: provider.pause() (the only session release) is called in app code ONLY at sandbox_routes.py:225 (persist-failure recovery). The /sandbox/setup happy path (sandbox_routes.py:238-244) and the present finally (presentation.py:266-278: only stop_screenshare/revoke/pop) never pause; no reaper exists (present_tokens.py:56). browserba
- fix: Mint the setup/interactive session as non-keep_alive (the user's tab holds it up and it self-terminates on close), reserving keep_alive for the CU present loop; and/or call provider.pause() in present

**#47 [LOW] present_routes.py:210** — Wrapper reconnect is structurally dead for the default (Browserbase) provider: resumed is always fal
- verdict: PARTIAL · reachable: conditional
- present_routes.py:118,142 sets resumed=asleep; :83-86 falls back to `not is_alive` for a non-E2B ref. browserbase_provider.py:257-282 is_alive tracks the durable Context (always alive during a present) → resumed ALWAYS False. present_routes.py:210-216 sameStream compares host+path only; browserbase_provider.py:455-461 debugger_fullscreen_
- fix: For a non-E2B ref, base `resumed` on session-level identity: return the Browserbase session_id/live_url and have the wrapper reload when it changes, or diff the query (session id) not just host+path —

**#48 [LOW] present_tokens.py:13** — Restart mid-present strands the Recall screenshare on a 410 'presentation ended' page and kills the 
- verdict: PARTIAL · reachable: conditional
- Mechanism is real: _tokens (present_tokens.py:29) and _active (presentation.py:46) are in-memory. Restart wipes both. present_vnc returns 410 when token is gone (present_routes.py:111) → wrapper JS ended_() shows full-bleed "This presentation has ended." (present_routes.py:218-224,232,275). The stop-sharing kill phrase is fully guarded by
- fix: Persist active-present state (bot_id→token) so recover_active_bots can call stop_screenshare + revoke_for_bot on boot; and make the "stop sharing" handler fall back to rc.stop_screenshare(bot_id) even

**#49 [LOW] sandbox/browserbase_provider.py:369** — _ensure_session has no synchronization: concurrent to_thread callers mint duplicate keep-alive sessi
- verdict: PARTIAL · reachable: conditional
- browserbase_provider.py:369-378 (_ensure_session) has no lock: get→_session_running→pop→_create_session→assign, and both inner calls are network I/O that releases the GIL (_session_running sessions.retrieve :450; _create_session sessions.create :412). self._sessions is a singleton dict (:172; provider.py:112-136). Concurrent callers are r
- fix: Wrap _ensure_session's get/check/create/store in a per-sandbox_id threading.Lock (it runs in to_thread worker threads) so concurrent callers reuse or release the loser instead of double-minting; mirro

**#52 [LOW] migrations.py:31** — Boot auto-migration runs schema.sql as one all-or-nothing batch, swallows every failure, has no conn
- verdict: PARTIAL · reachable: conditional
- migrations.py:24-33 confirms the mechanical claims: cur.execute(sql) runs schema.sql as one multi-statement simple query (server-side implicit txn = all-or-nothing), bare `except Exception` logs one line and returns, and psycopg2.connect(db_url) has no connect_timeout. But the harmful outcome is overstated: (1) schema.sql:2 is fully idemp
- fix: Add connect_timeout to psycopg2.connect and make a migration failure loud/alerting (or fail boot) instead of a single swallowed log line.

**#53 [LOW] meeting_memory.py:556** — restore_memory_state drops muted/mode/ambient cooldowns — a muted bot un-mutes itself after a restar
- verdict: PARTIAL · reachable: conditional
- Real gap: get_memory_snapshot's live_state_payload (meeting_memory.py:540-552) — the only blob persisted via _db_save_memory (realtime_routes.py:2788-2789) — omits muted/mode; restore_memory_state (meeting_memory.py:556-575) restores neither. The mute endpoint sets state["muted"] in memory only, no DB write (realtime_routes.py:4520-4522);
- fix: Add muted + manual_mode/engagement_mode to get_memory_snapshot's live_state_payload and restore them in restore_memory_state; have /mute and /mode endpoints call _db_save_memory.

**#56 [LOW] fe:App.jsx:1885** — Resume-polling-after-refresh closes over user=null — save, share token, and auto-send silently skipp
- verdict: PARTIAL · reachable: yes
- Stale closure is real: resume effect App.jsx:1881 ([] deps) calls startPolling at first mount when authSession is null (declared null App.jsx:822; resolves async in getSession().then at App.jsx:1204, a microtask after mount effects). Pinned saveToHistory hits !user early return (App.jsx:2012-2016 → setMeetingId/setShareToken null); pinned
- fix: Gate the resume effect on authReady (add to deps / start once user known) or read user+integrations via refs inside startPolling, so its closure sees the resolved values instead of first-render nulls.

**#58 [LOW] fe:App.jsx:999** — Non-OK /meetings history fetch silently renders an empty dashboard; stale workspace id never cleared
- verdict: PARTIAL · reachable: yes
- App.jsx:999 `r => (r.ok ? r.json() : [])` → `setHistory([])` on any non-OK response, blanking the dashboard. storage_routes.py:191-192 returns 403 for a non-member workspace_id, and App.jsx:824-825 keeps `activeWorkspaceId` in sessionStorage; DashboardPage.jsx:917-923 loads `/workspaces` but no code reconciles a stale active id against it
- fix: On non-OK /meetings (esp. 403) leave history unchanged instead of clearing to []; and add an effect reconciling activeWorkspaceId against the fetched /workspaces list, resetting to null (Personal) whe

**#61 [LOW] fe:components/DashboardPage.jsx:867** — Meeting-switch flush race: refreshPastSessions does not wait for ChatPanel's unmount flush despite t
- verdict: PARTIAL · reachable: yes
- Mechanism is real but overstated. ChatPanel.jsx:329-336 flushes on unmount fire-and-forget; persistThread (300-317) posts the full array; storage_routes.py:843-850 does a full-array `.update`. DashboardPage.jsx:864-876 fires an independent GET on meeting-switch with no ordering vs the flush, and ChatPanel.jsx:286-294 adopts activeSession.
- fix: On remount, don't blindly adopt the GET result — chain the refetch after the outgoing flush promise, or keep the longer/newer thread (compare length/updated_at) before overwriting.

**#70 [LOW] tests/test_recall_routes.py:32** — Test suite integrity depends on import-order luck: modules unconditionally replace sys.modules['anal
- verdict: PARTIAL · reachable: conditional
- test_recall_routes.py:32 and test_main_routes.py:79 both unconditionally do `sys.modules["analysis_service"] = fake` at import, with no restore (test_recall_routes.py:70-72 teardown only touches RECALL_API_KEY/bot_store). test_analysis_service.py:19 and test_content_analysis.py:20 `import analysis_service` and use real symbols (e.g. _orch
- fix: Install the fake only if the real analysis_service can't import (or restore prior sys.modules entry in tearDownModule) instead of unconditionally overwriting it.

**#73 [LOW] recall_routes.py:2292** — Autonomous/ambient mode and the in-meeting mute kill-switch silently revert to default on restart
- verdict: PARTIAL · reachable: conditional
- Mechanism is real: get_initial_memory_state defaults mode="utterance"/muted=False (meeting_memory.py:111-112); mode is never persisted — _db_save at join writes only status/user_id/live_token/owner_name/workspace_id (recall_routes.py:2593-94), live_state_payload omits mode/muted (meeting_memory.py:540-552), restore_memory_state omits them
- fix: Add mode+muted to get_memory_snapshot.live_state_payload and restore them in restore_memory_state; also carry initial_mode through _db_save/_db_load so the join-time mode survives a mid-meeting restar

**#74 [LOW] realtime_routes.py:148** — Persona wake word stops working after restart; proactive nudges revert to 'Prism'
- verdict: PARTIAL · reachable: conditional
- Mechanism real: `_BOT_WAKE_ALIAS` (realtime_routes.py:100) is in-memory, set only by `_get_settings_for_bot` (line 1817), read by `_wake_patterns_for_bot` (149-150) and the nudge builder (2956). Restart recovery `_db_load` (recall_routes.py:157-209) restores `bot_store` + respawns `_run_proactive_checker` (178) but never re-warms settings
- fix: In `_db_load`'s recovery branch (recall_routes.py ~175, next to the proactive-checker respawn) schedule `_get_settings_for_bot(bot_id)` / `init_bot_realtime(bot_id)` to re-populate `_BOT_WAKE_ALIAS` b

**#75 [LOW] realtime_routes.py:3285** — Live bot fires email/Slack/ticket tools with the owner's credentials for ANY meeting participant (ow
- verdict: PARTIAL · reachable: conditional
- Default prod IS gated. realtime_routes.py:466 `_two_channel_on()` = `getenv("PRISM_TWO_CHANNEL","1")!="0"` → ON; render.yaml sets no such var. When on, both dispatch paths (voice :3831, chat :4417) route to bus.submit → voice_channel.handle_command → agent_channel.run, whose owner-gate at voice/agent_channel.py:126-137 (`if _tool_def.get(
- fix: Lift the legacy owner-gate at realtime_routes.py:3371 out of the `if _injection_guard_on():` block so it is always-on (matching agent_channel.py:129), preventing a PRISM_TWO_CHANNEL=0 rollback from si

**#76 [LOW] storage_routes.py:96** — GET /user-settings returns raw integration API tokens in plaintext despite 'non-sensitive fields' co
- verdict: PARTIAL · reachable: yes
- storage_routes.py:96-103 returns linear_api_key/slack_bot_token/jira_api_token verbatim despite the "non-sensitive fields" comment; App.jsx:1147-1158 + IntegrationsModal.jsx:277-285 confirm the shipped frontend fetches and re-seeds them. Real defect. But auth.py:103 + storage_routes.py:94 (.eq user_id) make it self-only — no cross-user le
- fix: Return masked tokens on read (last-4 or a "configured" boolean) and adopt a write-only "leave blank to keep existing" edit model so save() never nulls unchanged secret fields.

**#81 [LOW] ms_calendar_routes.py:115** — get_valid_ms_token silently returns the expired access token when refresh fails
- verdict: PARTIAL · reachable: conditional
- ms_calendar_routes.py:114-116: on refresh failure new_token is None, guard skipped, stale access_token (line 105) returned — mechanism is real. But line 82-85 return None on transient 503/timeout, and the real harm is downstream: the /events 401 handler (lines 262-274) then wipes ms_access_token + the still-valid ms_refresh_token, forcing
- fix: When refresh_ms_token returns None for an expired token, raise 503 (transient) instead of returning the stale token; and only wipe stored tokens in the /events 401 handler after a genuine refresh atte

**#87 [LOW] fe:lib/extractAudio.js:124** — ffmpeg exec-failure diagnostic is dead code: readFile on the missing output throws before the log-ta
- verdict: PARTIAL · reachable: yes
- extractAudio.js:120-127: exec() returns an exit code (no reject on nonzero); line 124 `readFile(outName)` runs before the code!==0 log-tail diagnostic at 125-127. When ffmpeg fails before creating output.mp3, readFile rejects (Emscripten ENOENT) and propagates to App.jsx:2168-2173, shown as "Could not prepare this file: <FS error>" with n
- fix: Check `if (code !== 0)` and throw the log-tail error BEFORE calling readFile (or wrap readFile in try/catch and fall through to the log-tail diagnostic on failure).

**#88 [LOW] realtime_routes.py:4501** — /bot/{id}/mode calls deleted ambient_loop.update_mode → AttributeError (500) on every request
- verdict: PARTIAL · reachable: conditional
- CONFIRMED: ambient_loop.update_mode does not exist — grep of entire backend finds only the two call sites (realtime_routes.py:4501, 4509); ambient_loop.py has no such def and no __getattr__. So set_bot_mode 500s for mode in {auto,manual,utterance,autonomous} (line 4494-4512); None/invalid return early (no crash), matching the "real mode v
- fix: Delete the two ambient_loop.update_mode(...) calls (lines 4501, 4509) — mode is already applied via gate.set_mode / state["manual_mode"]; also update the stale test_set_mode expectations.

**#90 [LOW] realtime_routes.py:2157** — Instant ack is not cancelled on mute — bot speaks/acks ~1.2s after being muted
- verdict: PARTIAL · reachable: conditional
- Real gap but non-default. In the FUSED path only, `_fire` (realtime_routes.py:2157-2167) uploads the ack after 1.2s with no muted re-check, and `set_bot_mute` (4515-4540) cancels the session (`sess.cancel()`) but never cancels `state["_ack_task"]` (cleanup_bot_state:4620 shows the missing cancel). `_process_command`'s finally `_cancel_ack
- fix: In set_bot_mute, cancel state["_ack_task"] (as cleanup_bot_state does); also add a state.get("muted") re-check inside _fire before uploading.

**#92 [LOW] agents/summarizer.py:55** — Only sentiment and content_analyst tolerate prose-wrapped JSON; the other 8 agents bare-parse and si
- verdict: PARTIAL · reachable: yes
- Grep confirms only sentiment.py:49-61 and content_analyst.py:123-133 slice the outermost {...} on json.loads failure; summarizer.py:55, decisions.py:26, action_items.py:34, health_score.py:70, email_drafter.py:70, speaker_coach.py:27, calendar_suggester.py:90, action_executor.py:135 bare-parse json.loads(strip_fences(raw)). strip_fences (
- fix: Hoist sentiment/content_analyst's _parse_json into utils.py and use it in all agents (or make strip_fences slice outermost {...} on json.loads failure).

**#97 [LOW] fe:App.jsx:2480** — 120s client-side analysis abort was not re-tuned for the Sonnet-5 agent migration
- verdict: PARTIAL · reachable: conditional
- App.jsx:2480 sets a 120s controller.abort; 2557-2558 shows the exact timeout message. Sonnet migration is real: agents/utils.py:65 defaults AGENT_MODEL=claude-sonnet-5, dispatched via analysis_service.py:182,269; .env.example:35 confirms. So the slower-model premise holds and 120s is more likely hit than pre-migration. But tiers run in PA
- fix: Raise the client abort to ~180-240s (or make it adaptive to include cold-start slack), and/or persist the accumulated partial result on AbortError so a timed-out run isn't fully lost.

**#99 [LOW] fe:components/dashboard/SuggestedActions.jsx:88** — SuggestedActions card (and LiveMeetingView) render white text on the light page background — effecti
- verdict: PARTIAL · reachable: conditional
- Light theme ships (DashboardSidebar.jsx:427-430 toggle → DashboardPage.jsx:679-686 applies .theme-light; index.css:1033-1042 sets --db-page-bg #eef1f5 + dark text tokens). Sibling cards use those tokens (dashboardStyles.js:10-13; SentimentCard/MeetingView text-[color:var(--db-text)]) so they flip. SuggestedActions.jsx hardcodes white thro
- fix: In the inline card (not the dark ActionModal), swap hardcoded text-white/* and bg-white/* for --db-text/--db-text-muted/--db-fill tokens so it adapts to .theme-light.

**#101 [LOW] fe:components/StandInComposer.jsx:152** — Stand-in approve failure is swallowed silently — user can't tell it didn't save
- verdict: PARTIAL · reachable: yes
- StandInComposer.jsx:150 `setPhase('approved')` is inside the try AFTER `if(!res.ok) throw` (line 147), so on 500/network-drop it never runs. The success screen at lines 171-185 renders only when `phase==='approved'`, so it is NEVER shown on failure — the component stays in `phase==='chatting'` with the editable draft + "Approve" button st
- fix: In the approve catch block, surface a transient error (e.g. an inline "couldn't save — try again" message or reuse the phase='error'/Retry pattern from start) instead of the empty `/* keep editing */`

**#102 [LOW] supabase/auth_migration.sql:1** — Base meetings and chats tables are created by no migration in the repo
- verdict: PARTIAL · reachable: conditional
- Real defect confirmed: repo-wide grep finds NO `create table meetings/chats`. backend/schema.sql:6-13 (the boot-run consolidated schema, executed by migrations.py:28 via main.py:52) uses `alter table if exists meetings/chats` — silently no-ops on a fresh DB, no crash. So a brand-new provision gets no base tables and later 500s on every me
- fix: Add `create table if not exists meetings(...)` and `create table if not exists chats(...)` to backend/schema.sql so a fresh DB fully bootstraps.

**#103 [LOW] main.py:44** — main.py hard-imports the new voice package (→ pipecat) unguarded — any missing voice dep takes the W
- verdict: PARTIAL · reachable: conditional
- main.py:44 `from voice.audio_routes import router` is unguarded; audio_routes.py:27 imports voice.pipeline, which hard-imports pipecat.* at top level (pipeline.py:37-58, no guard) — so a pipecat-core import error does crash `import main`. Mechanism confirmed. BUT default prod doesn't trigger it: requirements.txt:57 pins pipecat-ai==1.5.0 
- fix: Wrap the voice_router import (main.py:44) and its include_router (main.py:93) in try/except like the loguru guard above, so a voice-dep failure disables only /voice/* instead of the whole backend.

**#104 [LOW] voice/voice_channel.py:336** — Eager-EOT speculative voice call is never adopted for wake-word-addressed commands (norm mismatch)
- verdict: PARTIAL · reachable: conditional
- Real asymmetry: on_eager_turn (voice_channel.py:318) stores spec.norm from Flux's RAW transcript (wake word intact); _Speculation.__init__:255 sets norm=_norm_cmd(raw). Multi-person path strips the wake word via _detect_command (realtime_routes.py:1199, def 1729-1752) before bus.submit→handle_command. _normalize_cmd (realtime_routes.py:17
- fix: In on_eager_turn, strip the wake word from the eager transcript (run through _detect_command, fall back to raw for solo free-flow) before computing spec.norm so it matches the stripped confirmed comma

**#106 [LOW] voice/pipeline.py:269** — VoicePipeline._t0 resets on every (re)connect — durable seek timestamps collide with the earlier par
- verdict: PARTIAL · reachable: conditional
- pipeline.py:269 sets `_t0=time.monotonic()` in __init__, read only by recording_elapsed() (366-369); never persisted/re-anchored. audio_routes.py:157 builds a NEW VoicePipeline per /voice/audio-in connection; finally (168-174) resets audio_socket_active but keeps the VoiceSession, so a reconnect rebuilds with _t0=now. realtime_segments su
- fix: Anchor t0 to a durable per-bot recording start (store elapsed at teardown, seed new pipeline t0 = now - saved_offset, or keep a wall-clock start in bot_store) instead of a fresh per-pipeline monotonic

**#111 [LOW] schema.sql:119** — schema.sql (auto boot migration) omits bot_sessions.realtime_transcript + transcript_segments — live
- verdict: PARTIAL · reachable: conditional
- schema.sql lines 86-119 list bot_sessions cols (incl. newly-added leave_reason/owner_name/workspace_id) but omit realtime_transcript + transcript_segments — a real inconsistency since schema.sql IS kept current for other cols. But the claimed data-loss is NOT reachable in prod: those cols are applied via the documented manual SQL-editor s
- fix: Backfill `alter table bot_sessions add column if not exists realtime_transcript text;` and `transcript_segments jsonb;` (plus the meetings recording cols) into schema.sql so the boot-path migration ma

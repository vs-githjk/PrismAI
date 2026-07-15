# Feature Deep Dive — Reliability + Effectiveness Audit

**Started:** Jul 15 2026 · **Lens:** does each feature (a) *work / fail gracefully / say what it did* (reliability) AND (b) *earn its place from a user's POV* — keep / improve / tweak / expand / cut. Founder-view, not developer-view.

Grounded in code (not docs): router sizes, in-memory state, except-block audit, view inventory. Companion to the consolidation sprint (`2026-07-13-consolidation-sprint.md`). Modals migrate opportunistically as each feature is touched.

---

## Cross-cutting risks (hit many features — highest leverage)

- **A. Durability.** `bot_store` / `_processing_bots` / `_standin_delivered` / wake caches are module-level in-memory (`recall_routes.py:93`, `realtime_routes.py:86`) — lost on Render restart. `recover_active_bots()` mitigates but bounded to bots <6h (`recall_routes.py:1061`). Deploy mid-meeting degrades live context. (AWS-migration driver, parked — but cheap partial fixes exist: persist the few critical keys to `bot_sessions`.)
- **B. Silent failures.** 25 `except…: pass` swallow errors (of 215 excepts; 108 log). Most best-effort, but unaudited swallows are exactly how "it said Done but nothing happened" (Calendar/Jira) slips through.
- **C. Complexity concentration.** `realtime_routes.py` (3768 L) + `recall_routes.py` (2444 L) = 58% of route code, both the bot lifecycle — highest latent-bug density; Cluster A (voice) lives here.

---

## Per-feature assessment

Legend: **R** = reliability, **E** = effectiveness (user POV), **→** = verdict.

### Capture & analysis
1. **Meeting capture (paste/upload/record/join)** — R: join depends on Recall+dedup (solid); *upload* uses in-browser ffmpeg-wasm (~30MB, fragile); record = mic-quality dependent. E: 4 modes may be *too many* — join is the star, paste is the demo fallback, upload/record are heavy tails. **→ IMPROVE:** make join the obvious primary; clarify when to use each; harden or de-emphasize upload/record.
2. **Analysis pipeline (~12 agents)** — R: parallel streaming + `llm_call` fallback, robust; speaker-name bug fixed. E: rich but risks noise — is every agent (sentiment / coach / health) actually *read and acted on*, or over-production? **→ ASSESS + IMPROVE:** lead with what users act on (summary, actions, decisions); make secondary agents collapsible. Does each agent earn its place?

### Live
3. **Live bot loop (wake/solo/TTS)** — R: 3768-line surface, in-memory, restart-fragile. E: the *differentiator* but Cluster A (latency, wake mishearing, interrupt, memory) — voice quality is make-or-break; a mishear craters trust. **→ HIGHEST-CEILING IMPROVE (voice redo).** Also assess: is the *spoken* channel worth the complexity vs chat-first?
4. **Live catch-up ("Ask Prism, just you")** — R: token-gated, low-risk. E: genuinely useful for latecomers, private. Underexposed. **→ KEEP, surface more.**
5. **Stand-in async proxy** — R: complex, restart-fragile; Cluster B "stand-in input" bug. E: ambitious/unique but niche + onboarding-heavy; risk few discover or trust it. **→ ASSESS HARD:** is ROI worth the complexity? Fix input bug; consider simplifying.

### Knowledge & chat
6. **Knowledge / RAG** — R: mature (smart-RAG phases), trust layer good. E: valuable *if* docs added — the gap is users understanding *why* to add docs. **→ KEEP, improve value-onboarding.**
7. **Chat (meeting/global/agent/image)** — R: well-built, 977-line panel. E: solid; but 3 modes switch invisibly (regex-routed) — user may not know which brain they're talking to. **→ KEEP, improve mode transparency.**

### Actions & integrations
8. **Suggested Actions** — R: recently hardened (dup-filing, destination labels). E: high-value, approve-first is right. **→ KEEP (already improving).**
9. **Integrations (7 providers)** — R: server-side now (`user_settings`); Cluster B Jira no-action. E: breadth good; per-USER not per-workspace (#2 parked); setup friction. **→ HARDEN each; per-workspace later.**
10. **Calendar (OAuth/events/create/view)** — R: Cluster B "Calendar fail"; PKCE race fixed prior. E: table-stakes for a meeting product. **→ FIX reliability (verify create-event + OAuth end-to-end).**

### Collaboration & supporting
11. **Workspaces + invites + fan-out** — R: solid but dedup logic is intricate. E: enables the team story. **→ KEEP, verify fan-out edge cases.**
12. **Insights (cross-meeting)** — R: fine. E: value scales with meeting volume — for a light user it may look empty/thin. **→ ASSESS: is it earning attention or is it a graveyard tab?**
13. **Recording playback** — low-risk. **→ KEEP.**
14. **Personas** — polish/delight. E: does it add real value or is it decoration? **→ ASSESS (light).**
15. **Auth (SSO-only)** — mature. **→ KEEP.**
16. **Notifications** — not built (handed off). **→ GAP** — decide if it's needed for the trust story.

---

## Ranked execution plan

**Tier 1 — Trust foundations (reliability + transparency): ✅ DONE (Jul 15)**
1. ✅ **Cluster B** — B-1/B-3/B-4/B-5 + health-provisional already fixed + deployed (verified in code); B-2 (notes-to-all) built (`6f35595`).
2. ✅ **Silent-failure audit** — all 25 `except: pass` triaged: **21 correct fail-safe**, 4 given diagnostic logs (action-ref persist [the "Done but not tracked" case], owner-email ×2, MS token-refresh). Conclusion: no silent-failure epidemic.
3. ✅ **Durability partial fix** — `_db_load` now restores `live_token` (was persisted but dropped on load → live/notes link survives restart) + new persisted `owner_name`/`workspace_id` columns on `bot_sessions` (email-FROM-owner sender + workspace fan-out/persona survive a mid-meeting restart). Migration via `schema.sql` (idempotent, auto-applies on boot).

**Tier 2 — Effectiveness (user POV):**  ⛔ VOICE = DEVAJ (owns Cluster A voice agent, done ~Jul 16 — DON'T touch the realtime/voice path)
4. ✅ **Analysis surfacing** — Sentiment now collapsible (keystone-aware: defaults OPEN, label pill + arc stay in header). `90c5eec`.
5. ~~Live bot voice redo~~ → **DEVAJ owns this.** Skip.
6. ✅ **Stand-in double-down = close the loop.** Was one-way (deliver → silence); built the **follow-up brief**: after analysis, brief each absent author (what happened for you / answers to what you asked / tasks now yours / what they need from you) — stamped on the rep (ProxyProfile "Your brief" expander) + emailed via their own Gmail (best-effort). `proxy_routes.generate_standin_followups`; migration #23 (MANUAL). NOT yet committed.

**Tier 3 — Opportunistic / assess:**
7. Insights, Personas, Notifications — keep/improve/cut calls.
8. Integrations hardening + per-workspace (#2).
9. Modal migrations — fold into whichever feature is being touched (StandInComposer, IntegrationsModal, ChatPanel, SuggestedActions, App.jsx, DashboardPage inline).

---

## Decisions (Jul 15, from user)
- **Analysis agents = NO pruning.** Sentiment + health are keystones (stay prominent). Speaker coaching already a dropdown. *Later:* make sentiment collapsible too (like coaching + transcript). Effectiveness item #4 becomes "make sentiment a dropdown," not "demote agents."
- **Stand-in = double down, critically.** Not cut — but audit it hard so it becomes genuinely high-impact (discovery, trust, the input bug), not just present.
- **Tier 1/2/3 = priority ordering across the whole app**, not per-feature depth. Mature KEEP features get least attention.

## Progress log
- Jul 15: audit written. Modal foundation done (`ui/dialog` re-skinned, KnowledgeUploadModal migrated — `b786469`, local). Button foundation live on main (`1788424`).
- Jul 15: **Tier 1 #1 — Cluster B verification DONE.** B-1 (leave reason), B-3 (calendar surfacing; root cause = Google OAuth config, external), B-4 (Jira re-seed), B-5 (stand-in input guard), health-score "provisional" — all present in current code + on main (deployed, never live-verified by user). Only B-2 was open.
- Jul 15: **Tier 1 COMPLETE.** #2 silent-failure audit (21/25 correct, 4 logged) + #3 durability fix (`_db_load` restores live_token; `owner_name`/`workspace_id` now persisted+restored via schema.sql columns). Not yet committed. **Next: Tier 2 — analysis surfacing (sentiment→dropdown), stand-in double-down, or live-bot voice.**
- Jul 15: **B-2 (notes-to-all) BUILT.** Timing reality: analysis completes AFTER the meeting ends (dead chat), and the bot can't know when a meeting will end — so delivery is attached to *reliable events*, not end-detection. The bot already broadcasts the persistent `/#live/{token}` link at intro (and `/live` serves the final `result` once done, so it *becomes* the notes page). Added `post_late_join_link` (recall_routes) fired from the `participant_events.join` handler (realtime_routes) — re-posts the same link to anyone who joins AFTER the intro (guarded by `intro_sent` + once-per-pid), so late-joiners get the notes link too. Intro copy now frames the link as persistent notes. No toggle needed (no NEW sharing — intro already broadcasts this link). 3 tests, 744 total. **Not yet committed/pushed.**

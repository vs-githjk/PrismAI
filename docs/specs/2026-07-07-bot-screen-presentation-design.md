# Bot Screen Presentation (Computer Use in Meetings)

**Date:** 2026-07-07 · **Status:** Ready to build (grilled 2026-07-12 — all
branches resolved; see ADR 0002) · **Owner:** Abhinav (solo)

## Context

Today PrismAI's meeting bot is input-only with two narrow output channels: it
records/transcribes (Recall.ai), speaks via `output_audio`, and posts text via
`send_chat_message`. When a user asks it to do something, `_process_command`
(`realtime_routes.py:2718`) runs a gpt-4o-mini tool-calling loop over the registry
in `tools/` and reports the result as text/voice.

That's fine for simple, structured actions (add to calendar, create a Linear
issue). It breaks down for visual / open-ended actions ("pull up that GitHub PR",
"walk us through the staging dashboard") — there's no surface for the bot to show
work, and no execution environment that can drive a browser/desktop with the
user's logged-in sessions.

This feature gives the bot a screen it can present into the meeting: a per-user
persistent sandbox desktop where it runs an open-ended computer-use loop, streamed
live into the call as the bot's screenshare while it narrates. Structured tools
stay silent; only tools flagged `presents=True` trigger the screen.

Key enabling facts (verified against primary docs, Jul 2026 research pass):
- Recall.ai Output Media (`POST /bot/{id}/output_media/` with
  `{"screenshare": {"kind": "webpage", "config": {"url": ...}}}`) streams a webpage
  you control into the meeting as the bot's screenshare, and **can start ad-hoc on
  a live bot mid-call** (documented). Stop = DELETE same path. NOTE: the endpoint
  literally named `/output_screenshare/` is JPEG-static-images only — do not build
  against it. "The bot's screen" = a live-view URL we point Recall at.
- The sandbox must expose a viewable live URL (noVNC / hosted desktop stream),
  publicly reachable, self-authenticating via token-in-URL (Recall's documented
  recommended pattern; Recall's browser cannot send headers or log in).
- Per-user creds already follow a `user_settings`-column pattern; `sandbox_id` fits.
- Everything browser/sandbox/computer-use related is greenfield — no existing code.

## Decisions (locked)

- **Sandbox provider: abstract.** Thin `SandboxProvider` protocol; one concrete
  adapter first, others swappable by env. **Primary candidate: E2B** (see
  Persistence model — ranking revised Jul 2026 after verification research;
  Blaxel is the challenger, Daytona dropped to third). No second adapter until
  actually needed.
- **MVP capability: open-ended computer use** (click/type/navigate any app) driven
  by Claude computer use — not a single browse-a-URL tool.
- **Trigger: per-tool `presents` flag on `register_tool`.** Deterministic, one
  boolean. `computer_use` is `presents=True`; calendar/linear/slack/gmail stay False.
- **Persistence: full-state memory snapshots as the hot tier + disk as the
  durability net** (decided Jul 2026, see Persistence model below).

## Persistence model (decided): full state + disk durability net

**The sandbox runs ONLY while presenting — resume-on-demand, no pre-warm.**
Full state is what makes lazy viable:
- On "pull up X": the ack phrase covers ~2–3s, and Recall's own output_media
  startup (bot Chromium loads the page + platform screenshare handshake) is
  ~2–10s regardless — the ~1s memory-snapshot resume runs CONCURRENTLY inside
  latency we pay anyway. Resume adds ~zero critical path.
- Disk snapshot resume is a reboot (desktop stack + browser relaunch, ~5–20s) —
  it pokes out past both covers, which would force pre-warming at bot join, i.e.
  paying for a running sandbox every meeting hour (~$0.10–0.17/hr, ~$10+/user/mo
  for heavy meeting users) for a feature most meetings never invoke. Full state =
  pay only during presents plus a short idle tail.

Extra wins for full state: E2B **auto-resume-on-request** (documented: any HTTP
request to the sandbox URL wakes it — Recall merely loading the stream URL resumes
the desktop; explicitly incompatible with filesystem-only snapshots) and stable
URLs (sandbox ID and thus the noVNC URL survive pause/resume).

**Memory snapshots are a cache, not a vault.** Blaxel's docs disclaim data
persistence for standby; E2B has multi-cycle fidelity bug reports (e2b-dev/E2B
#1031 open; #884 closed). So: browser profile periodically synced to durable disk
(the login vault). Snapshot corrupts → one cold boot, logins survive; never
re-login-everything.

**Provider ranking (verified):**
- **E2B (primary)**: pause persists fs+memory+processes (documented), resume ~1s,
  billing stops on pause, paused kept indefinitely, auto-resume-on-request, stable
  deterministic stream URL (`https://6080-{sandboxId}.e2b.app/vnc.html?...`).
  Needs Pro ($150/mo): Hobby kills sandboxes after 1h running. Persist the stream
  authKey + sandboxId in DB at first `stream.start()` — the key is generated
  client-side and unrecoverable after a backend restart. Desktop+pause combo is
  undocumented territory → torture-test spike required.
- **Blaxel (challenger)**: auto-standby 15s after last connection, ~25ms resume
  claim, first-party `cua-xfce` computer-use template (XFCE + noVNC + CUA
  computer-server API), ~$1/user/mo suspended. Unknowns: wake-on-URL-request is
  NOT documented; low tiers force-expire sandboxes (7/30 days) destroying logins;
  root fs is tmpfs (data wiped on destroy) → volume sync mandatory.
- **Daytona (third)**: container class (the one with documented computer-use) is
  disk-only ("pause is not supported"); VM pause preserves memory but latency AND
  pause-state billing are undocumented; preview URLs show a warning interstitial
  skippable only via custom header (impossible for Recall) unless Tier 3 or a
  proxy fronts it.

## Wrapper page (new component, required)

Recall must point at a thin page **we host**, not the provider's raw noVNC URL:
- Pause/standby kills the viewer's WebSocket on BOTH E2B and Blaxel (documented),
  and stock noVNC does not auto-reconnect — the wrapper embeds the provider URL
  and auto-retries, so the screenshare survives resume cycles.
- **Rotating per-present tokens, not a permanent URL** (grill Jul 2026): stable
  wrapper route + a token minted per presentation and expired when it ends. A
  chat-posted fallback link or a screen-scraped URL is then worthless after the
  present — no one can reopen the owner's desktop later (during another
  meeting's present or an interactive setup session). Permanence bought nothing:
  Recall gets a fresh URL on every `output_media` call, and the handler resumes
  the sandbox explicitly. Cleanly separates view-only (Recall, dashboard mirror)
  from interactive (workspace setup / future takeover).

## Failure contract (grill Jul 2026)

Every failure resolves to something SAID; every terminal path STOPS the
screenshare (a dead present never lingers as the room's screen).
- **Platform denies the share** (host settings): post the tokenized view link in
  chat — "I can't share my screen here — watch along: <link>" (link dies with
  the present).
- **Resume fails / sandbox gone**: one-liner; if the sandbox is deleted/expired
  (vs unreachable), the actionable variant: "…re-run Set up my AI workspace."
- **Login wall mid-task** (most likely in practice): the CU loop treats a login
  page as TERMINAL — never attempts login (no passwords by design), never burns
  steps around it. Speaks: "GitHub's logged me out — <owner>, re-run setup."
- **Loop stuck**: max-steps/timeout end it; error milestone spoken; step trail
  in the dashboard log shows where it wandered.
- **Human preempts the share** (single-presenter platforms): treat as CANCEL,
  not error — human wins, loop stops silently.

## Solo mode (grill Jul 2026)

- Presents allowed in solo free-flow; verb gate unchanged (speaker IS the owner
  in personal scope, ADR 0002 holds).
- **Solo free-flow SUSPENDS while a present is active** — the bot listens only
  for its wake word and the stop phrase (one flag check in
  `_solo_freeflow_eligible`). Otherwise steering chatter ("scroll down", "no,
  the other file") — which does NOT verb-match — floods the normal command loop
  and the bot chattily replies to every mutter while driving. Mental model: a
  presenting bot is busy; interrupt it by name.
- **Self-narration risk**: walkthrough narration is long and can contain gate
  verbs ("let me walk us through…"). `_looks_like_bot_participant` should
  exclude it, but attribution at this speech volume is untested — the e2e spike
  MUST include: solo meeting, walkthrough present, assert zero self-triggered
  commands. (Per-bot present serialization caps the blast radius at one
  "already presenting" reply regardless.)
- Mid-present STEERING is explicitly out of v1 (the loop takes one goal). A
  verb-gate-matching ask during a present → one chat-only line ("say stop
  sharing to take over"). Future: goal-amendment steering — utterances append
  to the goal between steps, same insertion point as the cancel check; the hard
  part is interaction design, not architecture.

## Recall constraints (verified) — bot-create changes

- **Variant is fixed at creation, no live upgrade**: default `web` (250 millicores)
  is flagged in Recall's FAQ as typically insufficient for Output Media;
  `web_4_core` (+$0.10/hr) is the recommendation. `_recall_bot_create_json` must
  set it — either on all bots or behind a per-user "presenting enabled" flag.
- `output_media` is mutually exclusive with `automatic_video_output` /
  `automatic_audio_output` create params.
- Render surface: 1280x720 @ 15fps (set the sandbox display to match); WebSocket +
  canvas fine on all variants (WebGL only on `web_gpu` — noVNC doesn't need it).
- Host-settings gate: Zoom/Meet/Teams "who can share" can block the bot — build a
  fallback (post the view link in chat).
- The bot's screenshare is NOT captured in Recall's meeting recording (bot audio
  can be); the recording player won't show the presented screen.

## Step 0 — decisive spikes with GO/NO-GO GATES (do FIRST, ~1 day)

Nothing else gets built before spike 1 passes — it's the only thing that can
invalidate the architecture.

1. ~~E2B desktop torture test~~ — **PASSED (run 2026-07-13,
   `backend/spikes/spike1_report.json`)**: 20/20 cycles, all markers intact
   every cycle (disk file, IN-MEMORY process state — same PID, counter
   advanced — browser processes, stream endpoint, host stability); resume
   p95 **time-to-usable 0.75s** (connect p95 0.46s) vs the 3s gate; pause
   ~0.6–1.1s; zero #884/#1031-style corruption (SDK process table stable at 4
   across all cycles). VNC frame delivery confirmed via live noVNC RFB
   handshake against the stream URL. **E2B is locked as the v1 provider.**
   Two live observations that CONFIRM the wrapper-page design: (i) a PAUSED
   sandbox's URL serves "Sandbox Not Found" — a plain page load does NOT wake
   it without the create-time `lifecycle` auto-resume config, so the handler's
   explicit resume is load-bearing; (ii) after resume, stock noVNC shows a
   "Connect" button rather than reconnecting — the wrapper's auto-reconnect is
   mandatory, not nice-to-have. Remaining sub-item deferred to build: CU-model
   A/B (needs ANTHROPIC_API_KEY locally). Fallback chain (Blaxel → Daytona)
   retained in git history; no longer applicable.
2. **Recall spike**. PASS = pixels visible ≤ 10s after the `output_media` call,
   smooth noVNC playback on whichever variant that takes (decides the variant
   question), clean stop, host-permission-denied failure identified & catchable.
3. **End-to-end on-demand ask**: wrapper page + PAUSED sandbox + Recall → timed
   runs of the real flow (ask → ack → resume ∥ output_media → pixels). PASS =
   ≤10s total to pixels, resume portion ≤2s, LOW resume variance (high variance
   is the one finding that would justify reintroducing join-time pre-warm) +
   the solo self-narration check (zero self-triggered commands).

## Architecture

```
user utterance ("Prism, pull up the auth PR and walk us through it")
  → _process_command tool loop picks `computer_use` (presents=True)
  → handler spawns presentation manager as a BACKGROUND TASK and returns fast
      1. ensure_sandbox(user_id)             # get/create persistent per-user sandbox
      2. provider.resume(sandbox)
      3. recall start_screenshare(live_url)  # bot shares the sandbox desktop
      4. run_computer_use(goal, sandbox, cancel): screenshot → action → …
           - narration policy (grill Jul 2026): VOICE = milestones only (ack,
             arrival, walkthrough-on-request, errors) — never per-step; CHAT =
             start + final summary; STEP TRAIL = dashboard live commands[] log
             only. Walkthrough mode (CU model narrates the content it sees)
             keyed off walkthrough verbs in the ask ("walk us through",
             "explain"). Bot stays responsive to other commands mid-present.
           - cancel event checked every step
      5. recall stop_screenshare()           # on done / timeout / "stop sharing"
  → summary → chat + _record_bot_line (lands in the analyzed transcript)
```

> The handler MUST NOT run the loop inline — inline blocks `_process_command`,
> making the bot deaf to the kill-phrase. Background task + cancel event.

### New module: `backend/sandbox/`

**`provider.py`** — the protocol + env-selected singleton (`PRISM_SANDBOX_PROVIDER=e2b`,
mirroring `clients.py`):

```python
async def ensure_sandbox(user_id) -> Sandbox   # idempotent get-or-create, persistent
def live_view_url(sandbox) -> str              # VIEW-ONLY stream (what Recall shares)
def interactive_url(sandbox) -> str            # full-input desktop (setup / future takeover)
                                               # MUST stay distinct from view-only
async def screenshot(sandbox) -> bytes
async def act(sandbox, action) -> None         # click|type|key|scroll|navigate (CU schema)
async def pause(sandbox) / resume(sandbox)     # cost control between meetings
```

**`e2b_provider.py`** — first adapter (`E2B_API_KEY`), pending the Step-0 torture
test. Includes a runnable `demo()` self-check: ensure → live_view_url → screenshot
→ act(navigate) → screenshot, asserting the screenshots differ. Persist
`sandbox_id` + stream `authKey` + stream URL to `user_settings` at first
`stream.start()` (the key is client-generated and unrecoverable later).
`live_view_url()` returns OUR wrapper-page URL (see Wrapper page), not the raw
provider noVNC URL.

**`computer_use.py`** — the agent loop:

```python
async def run_computer_use(goal, sandbox, cancel: asyncio.Event,
                           max_steps=25, timeout_s=300) -> AsyncIterator[str]
```

Claude (Anthropic SDK computer-use tool schema): screenshot → model action →
`provider.act` → repeat. Yields short narration strings; final yield is the
summary. Stops on goal-done / max_steps / timeout / cancel. Constrained system
prompt: read/navigate/show; **refuses destructive actions outright in v1** (see
Safety — the confirm flag can't be reused mid-loop).

**CU model (grill Jul 2026): Haiku-first posture, spike-decided.** `PRISM_CU_MODEL`
env; Step-0 spike A/Bs `claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-4-8`
on the same 3 tasks (open PR / navigate dashboard / walkthrough) — success rate
first, step latency second (cost negligible at every tier: ~$0.05–0.35/present).
Haiku 4.5 supports computer use on the older `computer_20250124` tool version
(beta `computer-use-2025-01-24`; enhanced `computer_20251124` is Sonnet 5 /
Opus 4.5+) and beats Sonnet 4 on CU tasks — likely sufficient for v1's simple
navigation; escalate tier only if the spike shows fumbles. Sandbox display
1280×720 (= Recall's render surface AND the cost-efficient CU resolution;
~1.2–1.6k tokens/screenshot). Realistic feel: 3–8 steps ≈ 15–30s visible driving
for a pull-up; 10–15 steps ≈ 1–2 min for a walkthrough — bounds (25 steps/300s)
fit. Sweep `effort` low/medium in the spike. NOTE: this loop does NOT go through
`llm_call()` (text-only Groq path) — it uses the shared Anthropic client from
`clients.py` directly with the computer-use beta (sanctioned exception, precedent:
chat_routes → Groq). Future (not v1): tier by intent — Haiku for "pull up X"
navigation, bigger model for walkthroughs (narration quality is audible), keyed
off the same walkthrough-verb detection as narration mode.

### New tool: `backend/tools/computer_use.py`

- `register_tool("computer_use", ..., requires="sandbox_id", confirm=False, presents=True)`.
- Handler `async def handler(args, user_settings=None)`, `args={goal: str}` —
  delegates to the presentation manager (background), returns
  `{"success": True, "summary": "presenting: <goal>"}`.
- Visible in `get_available_tools` only when `user_settings["sandbox_id"]` exists.

### Registry change (`tools/registry.py`)

`presents: bool = False` param on `register_tool`, stored on the tool dict (exact
precedent: `taints_context`). The caller in `_process_command` reads
`tool["presents"]` to route through the presentation manager vs. plain dispatch.

### Trigger gate (decided, grill Jul 2026): deterministic verb pre-gate

`computer_use` is only ADDED to the tool list for an utterance when a
conservative visual-intent regex matches ("pull up", "put on screen",
"show us/everyone", "walk us through", "share your screen", …) — verb-only, no
audience check. No match → the model cannot choose the screen; informational
asks ("how did the presentation go?") answer from knowledge, and if the reply
offers "want it on screen?", the user's "yes, put it on screen" matches the gate
next turn — escalation closes deterministically. Precedents:
`ack_phrases._RULES`, `_STANDIN_QUERY_RE`. False-positives become structurally
impossible; false-negatives cost one rephrase; the phrase list is tunable.
Fallback if real phrasing outgrows regex: swap the gate function for a cheap
classifier (it's one function).

**Ask-gate (ADR 0002):** any workspace member may trigger in workspace-scope
meetings; owner-only in personal scope; ANYONE may stop. Sandbox is always the
bot owner's.

### Recall output (`recall_routes.py` / `realtime_routes.py`)

- `start_screenshare(bot_id, url)` / `stop_screenshare(bot_id)` helpers →
  `POST/DELETE /api/v1/bot/{id}/output_media/` with the `screenshare.webpage` body
  (NOT `/output_screenshare/`, which is JPEG-only).
- Only ONE presentation per bot at a time; a second `presents` call while one runs
  → "already presenting" via chat.
- Cleanup on bot teardown: cancel + stop_screenshare + provider.pause.

### Lifecycle: resume-on-demand (no pre-warm, no pause hooks)

- The sandbox is paused except during presents. The `computer_use` handler resumes
  it explicitly (SDK `connect()` resumes; E2B auto-resume also wakes on Recall
  loading the wrapper URL) — resume runs concurrent with Recall's own 2–10s
  screenshare startup.
- **Ask-time cover**: add a `present` category to `ack_phrases._RULES` ("Let me
  pull that up on screen—") — pre-synthesized automatically at warmup; the 1.2s
  race means it always plays while the share spins up.
- **Idle teardown is the provider's job**: create with
  `lifecycle: {onTimeout: 'pause'}` and a ~10 min timeout — the sandbox pauses
  itself after the present. Bump the timeout (`setTimeout`) when a present starts
  so it can't pause mid-share; on auto-resume wake, set the timeout explicitly
  (wakes with only a 5-min minimum otherwise).
- ponytail: no join-time pre-warm hooks, no `_sandbox_resumed` guard set, no
  pause-at-teardown wiring, no restart-recovery re-arm — add a join-time pre-warm
  later ONLY if the Step-0 spike shows resume variance the ack + Recall handshake
  can't cover.

### Credentials persistence

- New `user_settings.sandbox_id` (text, nullable). Migration in `supabase/` +
  `migrate.py` MIGRATION_ORDER; add to `backend/migrations.py` too if it must
  apply on boot (separate mechanism).
- The persistent sandbox IS the credential store: user logs into GitHub/Figma once
  inside their own sandbox (dashboard "Set up my AI workspace" opens
  `GET /sandbox/setup` → `interactive_url`); provider snapshots cookies; later
  meetings reuse the session. PrismAI never holds passwords.
- **Durability net**: memory snapshots are a cache (provider-disclaimed) — sync
  the browser profile dir to durable storage periodically so a corrupted/expired
  snapshot costs one cold boot, never a re-login-everything.

### Live-view mirroring (dashboard + share page)

- `screenshare: {active, view_url, goal}` added to `GET /live/{live_token}`
  (`recall_routes.py:2033`).
- `LiveMeetingView.jsx` + dashboard live area (`NewMeetingPanel` when
  `botStatus==='recording'`): iframe the `view_url` when active.
- **Decided (grill Jul 2026): mirror on BOTH surfaces** — the screenshare is
  meeting content (the pixels the room sees), so the live-share possession
  model applies; a link-holder can watch exactly what the meeting watches,
  exactly while it watches it. Hard rules: view-only is ENFORCED in the wrapper
  (noVNC `view_only`; the provider's interactive URL never appears in any
  payload — server-side only, for setup/future takeover), and the per-present
  token means the mirror dies the moment the present ends.

## Safety / scope (do NOT simplify away)

- **Sandbox isolation is the trust boundary** — untrusted model actions against
  logged-in sessions run only inside the provider's VM, never on app infra.
- **Bounded loop**: max steps + wall-clock timeout + "stop sharing" voice
  kill-phrase (detected in the transcript webhook path like the mute kill-switch,
  sets the cancel event).
- **Owner-gated**: same owner-gate as the confirm tools — a random participant
  can't drive the owner's logged-in browser.
- **Confirm-pattern caveat**: `get_available_tools(exclude_confirm=True)` strips
  confirm tools in live meetings, so mid-loop confirmation can't literally reuse
  the confirm flag. V1: the CU system prompt refuses destructive actions; a real
  mid-loop confirm flow is future work.

## Future: human takeover (fast-follow, not v1)

The interactive URL is already a full desktop. Later: a short-lived,
possession-gated takeover URL (reuse the `live_token` model) + a control lock
(human takeover pauses the agent loop; release resumes). The provider interface
keeps `interactive_url` distinct from `live_view_url` so this drops in cleanly.

## Out of scope (v1)

Human takeover · multi-bot simultaneous presenting · write-without-confirm flows ·
non-Recall platforms.

## Open questions

1. ~~Auto-provision vs explicit setup~~ — RESOLVED (grill Jul 2026): explicit
   one-time setup ("Set up my AI workspace" → interactive login → ends with a
   "test my screen" preview that shows exactly what meetings will see). An
   unprovisioned ask gets a chat-only nudge naming the owner ("Abhinav can
   enable it in the Prism dashboard"). The `computer_use` tool-gate keys off the
   BOT OWNER's `sandbox_id` (via `_get_settings_for_bot`), not the asker's.
2. ~~Idle cost~~ — RESOLVED (Jul 2026): full-state pause between meetings; E2B
   billing stops on pause, resume ~1s; see Persistence model.
3. ~~Recall create-time vs runtime screenshare~~ — RESOLVED (Jul 2026): ad-hoc
   start on a live bot is documented; but the bot VARIANT (`web_4_core`) is
   create-time-only — see Recall constraints.
4. **Variant cost policy** — SPIKE-CONTINGENT (grill Jul 2026): default `web`
   variant unless Spike 2 proves noVNC playback is choppy on it (Recall's
   "web_4_core recommended" FAQ targets video-heavy pages; a mostly-static
   noVNC desktop is unmeasured). IF the upgrade is needed: apply conditionally —
   `web_4_core` iff the BOT OWNER has a `sandbox_id` (needs one added
   `user_settings` read in `join_meeting`'s payload build; `user_id=None` demo
   joins correctly default to `web`). Accepted edges: mid-meeting sandbox setup
   → that bot can't present smoothly until the next meeting; the **dedup
   lottery** — whose bot won workspace dedup decides presenting availability,
   so a sandbox-holding teammate can be stuck in a meeting whose bot owner
   never set up (fix if users hit it: dedup-preference for sandbox-holders'
   bots).

## Verification

- **Step-0 spikes** (see above): E2B pause/resume ×20 torture test with a
  logged-in browser; Recall output_media latency on `web` vs `web_4_core`;
  end-to-end on-demand ask from a PAUSED sandbox (≤10s to pixels, resume ≤2s,
  low variance).
- **Provider adapter**: `python -m backend.sandbox.e2b_provider` demo passes.
- **Loop bounds**: scripted `run_computer_use` finishes within bounds; setting
  `cancel` mid-run stops it within one step.
- **Gating**: unit test — `get_available_tools` excludes `computer_use` without a
  sandbox; calendar (`presents=False`) never starts a share; `computer_use` does.
- **End-to-end**: in a real meeting, "Prism, open <PR url> and walk through it" →
  bot shares, narrates (voice condensed, chat full), stops on completion;
  "stop sharing" kills it; transcript has the narration lines; `/live` shows
  `screenshare.active` then clears.

## Build order (grill Jul 2026) — each phase independently testable

1. ✅ **DONE (2026-07-13)** — **Foundation**: `backend/sandbox/` (protocol +
   E2B adapter, live `demo()` PASS), `supabase/sandbox_migration.sql` +
   `schema.sql`/`migrations.py` boot path, `backend/sandbox_routes.py`
   (`POST /sandbox/setup`, `GET /sandbox/status`). Reviews caught+fixed shell
   injection in `act()`, a setup race, and a lost-auth-key path.
2. ✅ **DONE (2026-07-13)** — **Wrapper page**: `backend/present_tokens.py`
   (in-memory per-present bearer tokens: mint/resolve/revoke/revoke_for_bot) +
   `backend/present_routes.py` (`GET /present/{token}` wrapper HTML +
   `GET /present/{token}/vnc`, both public/token-gated, backend-authoritative
   reconnect). Live-verified in a real browser: iframe wired to the sandbox
   with `view_only=true`; pause→`/vnc` returns `resumed:true` + reachable URL
   in ~3s (the reconnect signal the client reloads on). Two documented v1
   residuals: **(1)** the VNC password reaches the browser inside the stream
   URL (real fix = websocket proxy, deferred); **(2)** `view_only` is a
   client-soft flag, not a hard boundary — safe for Recall (never sends input)
   and the owner's dashboard, but **the anonymous live-share mirror (Phase 4)
   cannot rely on it** — Phase 4 must decide: gate the mirror to authed
   members, or build the input-stripping proxy first.
3. ✅ **DONE (2026-07-14)** — **Meeting wiring**. Built + reviewed (full suite
   **761 passed, 0 regressions**; `import main` clean, no circular imports):
   - `tools/registry.py` `presents` flag + `tools/present_gate.py`
     (`presents_gate_matches` / `is_walkthrough_request` / `is_stop_sharing`),
     13 unit tests.
   - `backend/sandbox/computer_use.py` `run_computer_use()` — Claude computer
     use (`computer_20250124` + `computer-use-2025-01-24` beta, model
     `PRISM_CU_MODEL` default `claude-haiku-4-5`), action-map → `provider.act`,
     bounded (max_steps + wall-clock + cancel Event), yields milestone
     narration. Unit-tested with fake provider + stubbed Anthropic (7 checks).
   - `backend/tools/computer_use.py` (`presents=True`, `requires=sandbox_id`,
     background handoff), `backend/presentation.py` (manager: serialize, ADR-
     0002 gate, resume→mint token→`start_screenshare`→CU loop→narrate→
     `stop_screenshare` in a `finally`), Recall `start_screenshare` /
     `stop_screenshare` / `present_wrapper_url` in `recall_routes.py`, ack
     `present` category, surgical `realtime_routes.py` wiring (verb-gated tool
     offer, kill phrase, solo suspension, teardown).
   - **Live-verification DEFERRED** (code built, not run): the real CU loop
     needs `ANTHROPIC_API_KEY`; trigger→present→stop needs a live meeting.
   - **Review findings to resolve before/at Phase 5 (recorded, NOT bugs):**
     (i) **Ask-gate is broader than ADR 0002 says.** Code allows *any speaker*
     in a workspace-scope meeting to trigger — including a non-member external
     guest — because verifying "is a workspace member" needs the diarization
     name-match ADR 0002 explicitly rejected as a trust boundary. This matches
     the grill's collaboration posture + mitigations (owner present, anyone-
     stops, goal-pinned prompt), but the external-guest case is a real
     exposure — decide at Phase 5 whether to tighten to owner-only or accept.
     (ii) Typed-chat "stop sharing" doesn't cancel (kill phrase is on the
     spoken-transcript path only) — small gap, fix in polish. (iii) Per-step
     sandbox I/O isn't wall-clock-bounded (only the model call is) — a wedged
     `provider.act` could outlast the timeout and keep the screen up until it
     returns; harden for the live path.
4. ✅ **DONE (2026-07-14)** — **Surfaces**. Build gates green on final on-disk
   state (backend **766 passed**, `import main` clean; frontend `npm run build`
   ✓; review clean):
   - `recall_routes.py` `GET /live/{live_token}` gains
     `screenshare: {active, goal, view_url}`; `presentation.active_present_info`
     getter added. **Phase-2 residual (2) RESOLVED (members-only):** `view_url`
     (the password-bearing wrapper URL) is returned ONLY to an authenticated
     workspace member (reuses the `/ask` optional-Bearer-JWT member check via
     new `_caller_is_bot_member`); anonymous live-share holders get
     `active:true, view_url:null` — a "presenting in the meeting" indicator, not
     the interactive-capable stream. Unit-tested (5 cases: owner/member→url,
     anon/non-member→null, idle→inactive). This is a deliberate walk-back from
     the grill's Q9 "both surfaces" — justified by the Phase-2 finding that
     `view_only` is client-soft; anonymous mirror returns only if a real
     input-stripping proxy is built later.
   - Frontend `PresentationMirror.jsx` (member→responsive 16:9 iframe of the
     wrapper; anon→indicator card) in `LiveMeetingView` (poll switched to
     `apiFetch` so a member's Bearer unlocks `view_url`) + dashboard live area.
     `AIWorkspaceSetup.jsx` "Set up my AI workspace" in the account dropdown
     (POST `/sandbox/setup` → opens `interactive_url`, privacy note, 502/503
     handling). Theme-tokened, cyan, non-glass.
   - **Process note:** two frontend builders were parallelized on shared files
     and raced; they reconciled duplicates, and the final state was
     independently re-gated (both builds pass). Two non-blocking review nits
     logged (blank-tab edge on a 2xx-without-url, cosmetic "ready" when
     `running:null`).
   - **Live-verification DEFERRED:** the mirror needs a live present; the setup
     UI's happy path needs a logged-in session (the 503 path is the only one
     exercisable without login).
5. **E2E in a real meeting = the v1 demo milestone**: workspace standup on
   Meet, a teammate says "Prism, pull up ‹PR› and walk us through it" → bot
   shares its sandbox, drives, narrates, and "stop sharing" kills it.

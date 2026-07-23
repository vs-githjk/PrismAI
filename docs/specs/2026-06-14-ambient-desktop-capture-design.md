# Ambient Desktop Capture — A Granola-Style System-Level Companion for Prism

**Date:** 2026-06-14
**Branch:** `fixed-changes`
**Status:** Design / ideation — revised after pressure-test + Cluely research (see "Design updates")
**Author:** Session with Abhinav + Claude

---

## Context

PrismAI today acquires meeting transcripts through a **Recall.ai bot** that visibly
joins the call, streams transcript webhooks into [realtime_routes.py](../../backend/realtime_routes.py),
and runs the LangGraph agent pipeline. This works for remote calls but: it's
intrusive (a bot appears in the roster), it can't do in-person meetings, it costs
per-bot, and it requires the user to deliberately send a bot.

We want a **Granola-style** capability layered on top: a system-level desktop app
that *knows when a meeting is happening*, captures audio **ambiently** (no bot in
the call), and runs the full Prism feature set on the result — while the existing
web app stays exactly as it is.

The unlock is that **Prism's backend is transcript-in, results-out.** The 9-agent
graph, RAG, insights, and chat don't care how the transcript was acquired. So this
is not "rebuild Prism" — it's **add a new acquisition client** that speaks the
transcript protocol the backend already consumes.

### The core insight: the desktop app is a "local bot"

[`_handle_realtime_payload`](../../backend/realtime_routes.py#L2646) already consumes
a transcript wire protocol (the Recall webhook). If the desktop app POSTs the same
shape, the **entire** existing live machine runs unchanged — accumulator → three-layer
memory → command detection → ambient lane → live SSE → proactive RAG.

```
Recall bot  ──webhook──▶ realtime_routes ──▶ accumulator ─▶ memory ─▶ agents ─▶ live SSE / RAG
Desktop app ──POST─────▶      (same)            (same)        (same)    (same)      (same)
```

The only capability a local source lacks is **talking back into the call** — and per the
revised product split below, that capability stays with the *bot* (web app). The desktop
app deliberately **never speaks into the call**; it helps the user privately instead
(see "Design updates" and "Private Live Assist").

---

## Decisions settled (this session)

| Decision | Choice | Rationale |
|---|---|---|
| **Product split** | **Web app = Recall bot only** (visible participant). **Desktop = ambient no-bot + invisible private copilot.** | Bot keeps all persona/voice/talk-back; desktop never speaks into the call. Clean separation, no `if source==desktop` talk-back branching. |
| Differentiator | Desktop **actively helps the user live, privately** (not just notes) | Granola is passive post-meeting notes; our wedge is in-meeting private answers/coaching nobody else sees (see "Private Live Assist") |
| Capture build-vs-buy | **Leaning BUY — Recall Desktop SDK** (`@recallai/desktop-sdk`) | Already on Recall; SDK gives meeting-detect + `transcript.data` (our exact event) + `screenshare_on/off` + `speech_on/off`. Costs: $0.50/hr, audio→Recall cloud, deeper lock-in. **Open decision.** |
| Shell | **Electron** | Reuse the React frontend; overlay is a small window |
| MVP cadence | **Reconsidering live-first → batch-first** | Cost (batch 40–50% cheaper) + cognitive-load research (live suggestions hard to consume) argue batch-first for the notes value; layer live-assist after. **Open decision.** |
| Hot session state | **Redis + periodic durable checkpoint** (NOT per-utterance Postgres) | Corrects an earlier "move to Supabase" call — utterance-rate writes need in-memory; Supabase is the checkpoint tier |
| Overlay invisibility | **Tier-1: OS content-protection + `screenshare_on` auto-hide** | Confirmed to be *what Cluely actually uses*; the "GPU-hook below capture path" claim is unverified — do not build on it |
| Platforms | **Windows + macOS in parallel** | One `CaptureSource` (or Recall SDK) abstraction, two backends |

---

## Design updates (post-pressure-test & Cluely research)

These supersede earlier wording where they conflict:

- **Product split locked.** Web app = visible Recall bot. Desktop = ambient (no bot) **+ invisible private copilot**. The "hybrid with per-source talk-back branching" framing is dropped — delivery surfaces are cleanly separated (bot → in-call; desktop → private-to-user).
- **Capture: lean BUY (Recall Desktop SDK).** Emits `meeting-detected`, `transcript.data` (our exact ingestion event), `screenshare_on/off`, `speech_on/off`, participant + diarization — collapsing meeting-detection + most audio-capture risks into a vendor concern. Tradeoffs to accept: **$0.50/hr/user**, **audio uploads to Recall's cloud** (weakens "audio never leaves your device"), deeper Recall lock-in. Build-native stays the fallback if max privacy becomes the wedge.
- **Hot state = Redis, not Postgres.** Foundation #1 corrected: utterance-rate mutations stay in-memory/Redis; Supabase is the durable *checkpoint*, not the hot path.
- **MVP cadence under review → batch-first.** Streaming ASR is 40–50% pricier and live suggestions are hard to consume (cognitive load); ship the post-meeting notes value on batch first, add live-assist as a deliberate second stage.
- **Invisibility is Tier-1, and that's enough for our threat model.** Cluely's *own docs* describe the standard OS overlay-privacy mechanism (= our `setContentProtection` + `screenshare_on` auto-hide), not a magic GPU bypass. The "GPU-hook below the capture path" is unverified marketing — **do not build on it.** Tier-1 suffices for threat-model (A); we reject threat-model (B) (see "Private Live Assist").
- **Tool-path injection defense added.** Ambient capture ingests everyone's speech into a tool-calling path → indirect prompt injection ("Prism, forward this to the client"). Adopt least-privilege + human-confirm for destructive tools + a quarantined/privileged agent split for anything that reads raw transcript and holds tools.

---

## Goal

A signed, auto-detecting desktop app that captures meeting audio without a bot,
streams a Recall-compatible transcript into the existing backend (live or batch), and
surfaces Prism's outputs in both a local overlay and the web dashboard — with
correctness, privacy, and resilience that meets or beats Granola.

## Non-Goals

- **Replacing the Recall bot.** It remains the opt-in "active participant" mode.
- **Talking into the meeting from ambient mode.** Ambient cannot speak into the call;
  contributions/answers surface in the local overlay instead.
- **Mobile capture.** Desktop (Win/Mac) only for v1.
- **Perfect browser-tab audio scoping** and **perfect macOS overlay hiding** — see
  Residual Risks; we design around these, we don't claim to solve them.
- **Proctor / exam / interview-evasion (Cluely's "threat-model B").** We do *not* build
  anti-detection to defeat an adversary actively hunting for the assistant. Out of scope
  on ethics + arms-race grounds; the private copilot targets meetings the user is a
  legitimate participant in (see "Private Live Assist").

---

## Architecture

### The wire contract (what the desktop app must POST)

Matches the segment shape parsed at [realtime_routes.py:2682](../../backend/realtime_routes.py#L2682):

```jsonc
POST /realtime-events/{token}        // tokenized route, realtime_routes.py:2565
{
  "event": "transcript.data",
  "data": { "data": {
      "words": [{ "text": "...", "start_timestamp": { "absolute": "<iso8601>" } }],
      "participant": { "id": "spk_me", "name": "Abhinav" },  // id = stable speaker key
      "speaker": "Abhinav"
  }}
}
```

Two-stream capture maps onto `participant.id`: mic = `spk_me`, system = `spk_them`
(or provider-diarized `spk_them_1/2/3`). The *transcript ingestion path* then runs
unchanged; the edges still need code — see the caveat under Backend touchpoints.

### Backend touchpoints (additive, ~4)

1. **`POST /local-capture/start`** — like `/join-meeting` but **skips the Recall API
   call**: generate `bot_id`, write a `bot_sessions` row with `source='desktop'`,
   register in `meeting_bots` for dedup ([_find_shared_workspace_bot](../../backend/recall_routes.py#L134)),
   return `{bot_id, token}`. Skip [`_send_bot_intro`](../../backend/recall_routes.py)
   (no chat to post into).
2. **Stream** — desktop POSTs the contract above. **Near-zero new code** on the ingestion path.
3. **`POST /local-capture/stop`** — triggers the same finalization
   `_process_bot_transcript` does today (`run_full_analysis` + save). The desktop
   *detector* decides when the meeting ended; reuse the [`_processing_bots`](../../backend/recall_routes.py#L39)
   idempotency guard so detector-stop + manual-stop don't double-finalize.
4. **Talk-back redirect (desktop-only divergence)** — [`_send_chat_response`](../../backend/realtime_routes.py#L1264) /
   `_send_voice_response` branch on `source`: if `desktop`, push the reply to the
   **overlay over live SSE** instead of into the call.

> **"Near-zero" caveat (from pressure-test):** the *transcript ingestion* is reused as-is,
> but four edges still need code: (a) desktop session setup must seed `owner_name` /
> `user_id` / `workspace_id` like `join_meeting` does (for desktop the mic stream *is* the
> owner — deterministic, simpler); (b) the 3s fuzzy / partial-final dedup is tuned to
> Recall's emission pattern and needs re-tuning for a different ASR; (c) **egress** — the
> overlay must subscribe to its session's live SSE; (d) the user-facing `meetings` row is
> created by the frontend today, so `/local-capture/stop` should write it server-side
> rather than make the desktop client replay the frontend save.

### Desktop app anatomy (Electron)

```
Main process (Node)
├── Auth ............... reuse Supabase session → same Bearer token as web
├── Meeting Detector ... calendar + comms-process + audio-session fusion (detect → PROMPT)
├── Capture Controller . auto start/stop; supervises the streams
├── CaptureSource (iface)  ← ONLY platform-specific code
│     WindowsCapture → WASAPI process loopback (system) + built-in mic
│     MacCapture     → Core Audio process tap (14.4+) / ScreenCaptureKit + mic
│     emits 2 PCM streams { me, them } @ 16kHz
├── AEC (WebRTC AEC3) .. system stream = far-end reference, mic = near-end
├── VAD (Silero) ....... gates the pipeline; doubles as silence/end signal
├── StreamingASR ....... Deepgram/AssemblyAI WS, ephemeral key (audio bypasses our server)
├── Outbox (SQLite WAL)  durable buffer → uploader drains to /realtime-events
└── Uploader ........... formats utterances into the contract

Renderer (React)
├── Menubar/tray overlay  live notes + PRIVATE Prism suggestions (talk-back target)
└── Full dashboard ...... reuse the deployed web app in a BrowserWindow
```

> **This diagram is the *build-native* variant.** Per the lean-BUY decision, the Recall
> Desktop SDK **replaces `Meeting Detector` + `CaptureSource` + `StreamingASR`** (it emits
> `meeting-detected` + `transcript.data` + `speech_on/off` + `screenshare_on/off`
> directly), leaving us to own Auth, the Outbox, the Uploader, and the overlay. Keep the
> native stack as the fallback if max privacy (audio never leaving the device) becomes the wedge.

---

## Private Live Assist — the differentiator

**Positioning.** Granola is *passive*: notes you read after. The desktop app is *active*:
during the meeting, invisibly, it answers the questions the user can't — a number they
don't recall, an agenda item they missed, an objection to handle — surfaced so they can
**say it out loud without reading a wall of text**. This is the wedge Granola deliberately
doesn't touch.

### Threat model (choose A, reject B)

| | (A) Don't leak on a share *you* start — **CHOSEN** | (B) Evade an adversary hunting you — **REJECTED** |
|---|---|---|
| Scenario | Your own sales / customer / team / 1:1 meetings | Interviews, exams, proctored tests |
| Tech | `setContentProtection` + `screenshare_on` auto-hide (= Cluely's real mechanism) | anti-detection arms race; unverified GPU tricks |
| Risk | low, defensible | ethics + reputation + a losing detection race |

The whole promise is "without anyone knowing," so **overlay-leak prevention is P0**:
`screenshare_on` → blank the overlay instantly; `screenshare_off` → restore. On macOS,
where content-protection is only partial, the `screenshare_on` auto-hide is the real
defense.

### Core mechanism: prepare always, reveal only on hesitation

Cognitive-load research is unambiguous: pushing help while the user is engaged is missed
and/or overwhelming. So we surface at the **one moment load drops and need is proven** —
when the user *stalls* after a question aimed at them.

```
                  question aimed at user
   IDLE ───────────────────────────────────▶ PREPARING ── fire speculative grounded
    ▲    (diarization: not-the-user speaker      │          retrieval in parallel,
    │     + interrogative cue + user's name /     │          hold answer silently
    │     turn-yield)                             │
    │                              ┌──────────────┴─────────────┐
    │              user answers fluently            user hesitates (≤~1.5s:
    │              within window                     silence / "um" / "let me…")
    │                     │                                      │
    │                     ▼                                      ▼
    │                  DISCARD                            ┌──────────────┐  not grounded /
    │               (show nothing) ◀─────────────────────│ CONFIDENCE   │  low-confidence
    │                     │                               │   GATE       │──────────────┐
    │                     │                               └──────┬───────┘              ▼
    │                     │                      grounded +      │             SUPPRESS live →
    │                     │                      high-conf       ▼             drop into post-mtg note
    │                     │                              REVEAL Tier-1
    │                     │                        (headline, fixed spot, "ready" pulse)
    │                     │                                      │
    │                     │                    hotkey expand →   ▼
    │                     │                              REVEAL Tier-2 / Tier-3
    │                     │                                      │  used / goes stale
    └─────────────────────┴───────────────────────────────────  ┴──▶ fade → IDLE

  PULL (hotkey) : from ANY state → reveal the last prepared answer, else retrieve now.
  SHARE GUARD   : screenshare_on → blank overlay (P0); screenshare_off → restore.
```

Speculative retrieval fires on *question-detected*, **not** on hesitation — so by the
time the user stalls (~1–2s later) the answer is already in hand and reveal feels instant.
If they answer fluently, the prepared answer is discarded and nothing ever shows: **zero
interruption when help wasn't needed.**

### Confidence / grounding gate (non-negotiable)

A confident *wrong* answer is worse than none — the user will repeat it authoritatively.
Between PREPARING and REVEAL:

- **Strict grounding only.** Answer must come from the user's KB / past meetings / the
  live transcript. Reuse `knowledge_lookup`'s strict-grounding + `NO_GROUNDED_ANSWER`
  signal — if not grounded, **suppress the live reveal** and defer to the post-meeting
  note. Never surface a live guess.
- **Provenance tag** on every reveal (`from your Q1 SLA report`) so the user trust-
  calibrates before speaking it.
- **Conservative confidence threshold** — ambiguous → suppress. The PULL path covers
  misses, so silence is cheap.

### The surface: Tier-1 / 2 / 3 progressive disclosure

| Tier | When | Shows |
|---|---|---|
| **1** (default) | on REVEAL | The atomic, **speakable** answer + provenance, in a fixed glance-spot. e.g. `99.92% · 1 incident (Feb 12, 4h) · Q1 SLA report`. Formatted for a 200ms glance, not a read. |
| **2** | eyes linger / 1 expand | One supporting line (the caveat or surrounding fact) |
| **3** | hotkey expand only | Full source snippet + link. **Never live by default** (reading = load + the visible "eyes-reading" tell) |

Rules: **one candidate at a time** (never a stack), **silence is the default**, fixed
predictable position (no eye-searching), a subtle "answer ready" pulse so the user glances
on *their* terms instead of monitoring the overlay.

### Two-speed delivery

- **Live = minimal.** One speakable fact, on hesitation, Tier-1.
- **Post-meeting = deep.** "You were asked about X — here's the full answer + all sources"
  lands in the summary, where there's no cognitive load to spend. A missed live moment is
  therefore never a lost answer.

### Invocation

- **Proactive** (the state machine above), and
- **Pull** (hotkey / typed) — the highest-value path, because the user is actively seeking
  so attention is freely given. **No voice wake-word on desktop** — saying "Prism" aloud
  would be overheard. Pull also lets proactive surfacing stay conservatively quiet.

### Reuse map (mostly re-aimed existing machinery)

| Need | Existing Prism component |
|---|---|
| Speculative retrieval on question-detect | `_ambient_speculate` (ambient lane) |
| "Should I surface / when / how loud" | ambient-contribution-lane pricing + timing/yield engine |
| Strict grounding + no-guess | `knowledge_lookup` (`NO_GROUNDED_ANSWER`) |
| Retrieval sources | `knowledge_proactive`, KB/RAG, live transcript buffer |
| Question / hesitation / turn signals | Recall Desktop SDK `speech_on/off` + diarization |
| Delivery channel | private SSE → desktop overlay (desktop-only talk-back redirect) |

The ambient lane was built to decide *whether/when/how* to contribute and was going to
*speak in the meeting*; here the **decision engine transfers wholesale** and only the
**delivery channel** changes to the private overlay.

### Failure modes + instrumentation

- **Wrong-but-confident** → strict grounding + provenance + confidence gate (above).
- **Can't glance-and-speak / reading tell** → ultra-short Tier-1; the hesitation trigger
  means they're already paused. Some users still won't manage it live → that's why the
  post-meeting depth exists.
- **Over-surfacing** → conservative thresholds + one-at-a-time + the PULL safety valve.
- **Latency** → speculative pre-fetch; target <~1s hesitation→reveal (Cluely's bar ~300ms).
- **Instrument it:** measure *was a surfaced answer used within N seconds of reveal?* If
  live-assist doesn't earn its keep, the value is the post-meeting depth — let the data
  decide how much to invest in live.

### Open parameters to tune

- Hesitation window (start ~1.5s) and what counts as a "fluent" answer.
- Confidence threshold for live reveal vs defer-to-notes.
- "Directed at the user" detection precision (name cue / sole-other-participant / turn-yield).
- Tier-1 max length (the glance budget).

### Worked example

> Customer: *"What was our uptime last quarter — wasn't there an incident?"*
> → question detected, speculative KB retrieval fires, answer held silently.
> User: *"Uh… let me pull that up—"* (hesitation)
> → overlay, fixed corner: **`99.92% · 1 incident · Feb 12 (4h)`** · `Q1 SLA report`
> User glances: *"We were at 99.92% — one four-hour incident back in February."*
> → full incident timeline + report link land in the post-meeting notes.

---

## Edge cases: Granola precedent → our solution → the solution's own edge cases

Confidence: ✅ confirmed solved · ⚠️ partial / mitigation only · ❓ unverifiable.
Granola findings sourced from their docs + founder statements (see References).

> **Note:** the "Our fix" column describes the **build-native** path. Under the lean-BUY
> decision, the Recall Desktop SDK already handles several rows (meeting detection,
> per-process/system audio capture, `screenshare_on/off`, `speech_on/off`,
> `recording-ended`) — those become *vendor-managed*. The residual edge cases
> (device-change/Bluetooth, browser-tab bleed, macOS overlay, consent) stay ours either way.

### A. Audio capture

| Problem | Granola | Our fix | New edge cases introduced |
|---|---|---|---|
| **System-wide bleed** (music, notifications) | ⚠️ Not solved — "cannot isolate audio from individual applications" | ✅ Per-process capture: WASAPI `PROCESS_LOOPBACK` / macOS Core Audio tap | Meeting-PID identity is fragile (multi-process apps, Electron "Helper"); **browser meetings share one audio process** → bleed remains (mitigate: exclude-mode); `GetMixFormat`=E_NOTIMPL → must assume format; **no frames during silence** (poisons watchdog); mac 14.4 floor |
| **Speaker-mode echo** (mic re-hears "Them") | ❓ Not addressed | ✅ WebRTC AEC3 (system = reference, mic = near-end) | **Delay alignment** across two clocks is hard; **BT output adds 100–300ms variable latency**; clock drift over long meetings; **double-talk can suppress the user**; only needed on speakers → needs reliable output-type detection |
| **Bluetooth HFP collapse** | ⚠️ Punted to user device config | ✅ Capture "Them" via loopback (**digital, pre-codec → BT-immune**) + built-in mic for "Me" | Forcing built-in mic discards the user's good USB/BT mic; built-in mic + speakers = worst-case echo (→ AEC) |
| **4–5 min cutout / device change** | ⚠️ Documented bug, user-action fix | ✅ `IMMNotificationClient`/Core Audio listeners + invalidation re-bind + stall watchdog | Re-init = **audio gap**; flapping BT → restart storm (needs backoff); silence-vs-dead ambiguity; **partial failure silent** (mic dies, loopback lives); must follow *intentional* device switches |
| **Desktop multi-speaker diarization** | ⚠️ Desktop is "Me/Them" only | ✅ **2-channel** (mic + system) + provider streaming diarization → *better than Granola desktop* | ~2× ASR cost/bandwidth; not all providers diarize multichannel streaming; **labels unstable/relabel with lookahead** (live-view flicker); cross-talk within "Them" still degrades |

### B. Detection & lifecycle

| Problem | Granola | Our fix | New edge cases introduced |
|---|---|---|---|
| **False-positive recording** | ✅ Detect-then-**prompt**, never silent | ✅ Copy it: calendar + comms-process + audio-session fusion → **prompt**, human confirms | Process identity again; YouTube/podcast during a calendar block still prompts (annoying, not catastrophic) |
| **Runaway / end-of-meeting** | ⚠️ Partly manual ("click End") | ✅ SDK `recording-ended`; or build-native: audio-session inactive/expired ([`IAudioSessionEvents`](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nn-audiopolicy-iaudiosessionevents)) **OR** process exit **OR** VAD silence + calendar grace | **Unreliable both directions**: mute/silent-presentation → premature finalize; app holds device open after call → never finalizes; process rarely exits (tray); back-to-back merge; sleep looks like end |
| **Network loss mid-stream** | ⚠️ Founder *building* offline; sustained drops fail | ✅ SQLite **outbox/store-and-forward** + whisper.cpp local fallback | **Local audio at rest contradicts the privacy promise**; disk pressure; **model chicken-and-egg** (need whisper model on disk before going offline); offline loses diarization + burns battery; **replay idempotency** vs in-memory `bot_store`; stale-timestamp slotting; stitched-transcript seams |
| **Crash mid-meeting** | ⚠️ "restart your computer" | ✅ Same outbox persistence → relaunch detects unfinalized session, resumes/finalizes | Same replay-idempotency + ordering concerns as above |

### C. Privacy, UX, performance, distribution

| Problem | Granola | Our fix | New edge cases introduced |
|---|---|---|---|
| **Screen-share overlay leak** (private suggestions) | ❓ Unverifiable | ✅ Win: `setContentProtection` (`WDA_EXCLUDEFROMCAPTURE`). ⚠️ **mac: partial** — newer ScreenCaptureKit full-screen capture ignores `NSWindowSharingNone` | mac fallback needs "is a share active?" — **no clean API**; content-protection **blacks out the user's own legit screenshots/recordings**; restore-after-share detection |
| **Battery / CPU** | ❓ Unverifiable | ✅ Silero VAD gate (2MB, ~0.43% CPU realtime) | **Onset clipping** (needs pre-roll buffer); false neg drops soft speech; false pos on typing/music; **gating breaks provider diarization/endpointing** (continuous-audio assumption) |
| **Two-party consent** | ⚠️ Zoom-mac-only chat notice; legal punted to user | ⚠️ **Mitigation only**: pre-meeting email (calendar attendees) + platform disclaimer + per-contact/meeting exclusions + most-conservative default | **Spoken disclosure needs talking into the call — which ambient mode can't do**; calendar may hide external emails; chat injection per-platform/brittle; exclusions slip on renamed invites; mid-meeting revocation + purge |
| **Audio retention** | ✅ Cached then deleted | ✅ Match it: ephemeral, deleted on transcription; offline buffer encrypted + hard TTL | (covered under offline buffer) |
| **Same-user multi-device dup** | ❓ Unverifiable | ✅ Server-side **lease** keyed by calendar-event-id (fallback URL / time+participants), atomic conditional-insert | **Stale lease after crash** (needs TTL + heartbeat takeover); no calendar id for ad-hoc → fuzzy keys collide/miss; **wrong winner** (muted device wins); **lease must live in Supabase**, not in-memory |
| **Code signing / notarization** | ✅ (shipped app) | ✅ Apple notarization + Windows signing in CI | Cost + pipeline; auto-update must not fire mid-meeting |

---

## Emergent conflicts (where two fixes fight) — the real danger

These outrank any single edge case because resolving one re-breaks another:

1. **VAD gating ⟂ provider diarization/endpointing.** Speech-island audio starves the
   models that need continuous input. → *Gate cost/upload, but keep a continuous
   low-rate path for diarization, or use provider-side VAD instead of pre-gating.*
2. **Offline local buffer ⟂ privacy promise ⟂ battery.** Persisted audio betrays
   "deleted immediately"; local Whisper burns the battery VAD saved. → *Encrypted
   ephemeral buffer with hard TTL; treat offline as explicitly degraded mode.*
3. **Spoken consent ⟂ the no-bot architecture.** The strongest disclosure needs a
   capability we removed. → *Lean on pre-email + platform-native disclaimers + a
   visible local recording indicator; accept ambient can't self-announce aloud.*
4. **AEC ⟂ battery**, and AEC *depends on* output-type detection, which in turn
   *depends on* device-change events. Weak device detection → AEC misfires →
   diarization bleed.
5. **Meeting-process identity is a shared single point of failure** for per-process
   capture, which-session-to-watch (end detection), and PID-scoped routing. Get it
   wrong and three solutions fail together.
6. **Replay & multi-source ordering ⟂ the in-memory backend.** Outbox replay and
   multi-device leasing both need durable, idempotent, stably-ID'd ingestion — which
   today's in-memory [`bot_store`](../../backend/recall_routes.py) dedup undermines.

---

## Two foundations (MVP prerequisites)

Most second-order failures trace to one of these. Build them first.

1. **Durable, idempotent ingestion.** Move session state + **per-utterance event dedup**
   out of in-memory `bot_store` into a **Redis hot tier with periodic durable checkpoints
   to Supabase** (not per-utterance Postgres writes — see Decisions). The once-per-meeting
   **cross-device lease stays a durable Supabase row** (atomic conditional-insert, as in
   the Multi-device edge case). Give every utterance a stable end-to-end event id so
   outbox replay and multi-device leasing are safe across Render restarts.
2. **A robust meeting-process resolver.** A single component that answers "which
   process/audio-session *is* this meeting" — feeding capture scoping, end detection,
   and routing. Includes the browser-tab caveat as a known degraded path.

---

## Residual hard risks (design around — do not assume away)

- **Browser-tab audio scoping** — shared audio process; exclude-mode mitigates, doesn't solve.
- **macOS full-screen ScreenCaptureKit capturing the overlay** — no clean OS fix.
- **Robust meeting-process identity** — heuristic, will have misses.
- **Offline transcript quality vs the privacy/battery tradeoff.**
- **Legal consent in ambient mode** — mitigation only, never a guarantee.

---

## Phasing (both platforms)

> Cadence is an **open decision** (see Decisions). The phases below describe the
> **live-first** path; if **batch-first** is chosen, Phase 1 instead records the meeting
> and batch-transcribes on end into the existing `/analyze` flow (cheaper, simpler), and
> live streaming + Private Live Assist move to a later phase.

1. **Skeleton loop** — Electron menubar + Supabase auth + manual Start/Stop →
   **Windows capture** (Recall Desktop SDK, or WASAPI if building native) → transcript →
   POST the contract → watch it appear (live SSE view, or the dashboard for batch).
   No detector yet. Proves the contract on real audio fastest.
   *(Build the two foundations alongside this.)*
2. **macOS backend** — implement `MacCapture` behind the same `CaptureSource` interface.
3. **Resilience** — Silero VAD, AEC3, outbox + crash recovery, device watchdog.
4. **Auto-detect** — calendar + process + audio-session fusion driving start/stop (the
   Granola "you do nothing" magic), with detect-then-prompt.
5. **Overlay + Private Live Assist** — private suggestions + hotkey/proactive answers
   surfaced to *you*, not the room (**no voice wake-word** — see Invocation). Multi-device
   lease + consent tooling.

---

## References (technical claims)

- Windows per-process loopback — [ActivateAudioInterfaceAsync / PROCESS_LOOPBACK](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-activateaudiointerfaceasync), [sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)
- macOS Core Audio taps (14.4+) — [Apple docs](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps), [AudioCap](https://github.com/insidegui/AudioCap)
- WASAPI loopback is digital / pre-codec (BT-immune) — [Loopback Recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
- Device notifications — [IMMNotificationClient routing](https://learn.microsoft.com/en-us/windows/win32/coreaudio/relevant-device-notifications-for-stream-routing), [IAudioSessionEvents](https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nn-audiopolicy-iaudiosessionevents)
- Echo cancellation — [WebRTC AEC3](https://switchboard.audio/hub/how-webrtc-aec3-works/)
- VAD — [Silero VAD](https://github.com/snakers4/silero-vad)
- Streaming diarization — [AssemblyAI](https://www.assemblyai.com/blog/streaming-diarization-major-upgrade), [Deepgram](https://developers.deepgram.com/docs/diarization)
- Overlay exclusion — [Electron setContentProtection](https://www.electronjs.org/docs/latest/api/browser-window), [macOS limitation](https://github.com/electron/electron/issues/31787)
- Offline pattern — [transactional outbox](https://microservices.io/patterns/data/transactional-outbox.html), [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- Consent — [Circleback: recording consent](https://circleback.ai/blog/recording-consent-for-ai-meeting-notes)
- Granola precedent — [transcription docs](https://docs.granola.ai/help-center/taking-notes/transcription), [transcription issues](https://docs.granola.ai/help-center/troubleshooting/transcription-issues), [privacy FAQ](https://docs.granola.ai/help-center/consent-security-privacy/security-privacy-data-faqs), [getting consent](https://docs.granola.ai/help-center/consent-security-privacy/getting-consent), [founder on offline (X)](https://x.com/cjpedregal/status/1980322615815496107)

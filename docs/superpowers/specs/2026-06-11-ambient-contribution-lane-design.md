# Ambient Contribution Lane — Design Spec

**Date:** 2026-06-11
**Branch:** `fixed-changes`
**Status:** Proposed — pending user review
**Supersedes:**
- `2026-06-07-ambient-response-loop-design.md` (v1 — staged funnel + mode state machine)
- `2026-06-07-consent-interjection-design.md` (v2 — offer → consent → deliver)

The Utterance/Automatic join selector, mute, warmup, the wake-word fast-path, and
the `PRISM_AUTONOMOUS` / `PRISM_AUTONOMOUS_SHADOW` flags survive from v1/v2.
Everything else in the autonomous lane is replaced.

---

## Problem — why v1/v2 failed at autonomous talking

Diagnosed from the code, the v2 live test, and prod logs:

1. **The consent dance defeats the purpose.** A spoken offer ("I have info on X —
   want to hear it?") interrupts exactly as much as a contribution, but carries
   zero content. One payoff cost two interruptions, a forced human turn, and
   ~15–30s of latency. The bot never actually *talked* — it asked permission to talk.
2. **The deciders decided blind.** `offer_decider` judged "do I have valuable
   info?" with no KB access, no retrieval, no candidate. You cannot price a
   contribution you haven't seen. (Spec C12's "graceful empty payoff" was the
   written admission.)
3. **The mode state machine made autonomy unreachable or unbounded.** The lull
   entry (35s silence) almost never fires in a real meeting; auto-revert killed
   autonomy the moment conversation resumed; and the pre-join "Automatic"
   selector set `manual_mode`, which disabled every safety unconditionally.
4. **No timing model existed at speak time.** "Never speak while a participant is
   mid-utterance" was specced but never implemented — TTS fired blind after a
   2–4s decider chain.
5. **The recall gate was a metronome.** Its 8s pause-tick passed regardless of
   content, sending most utterances (with ~1.5K tokens of context each) to the
   8B, and every 8B-yes to the 70B — token burn with no judgment gain.
6. **Consent attribution was unsolvable.** The next utterance from *any* speaker
   was consent-classified; "yeah, let's do that" said to a human could trigger a
   full info dump.
7. **Three uncoordinated proactive systems** (Idea Engine, proactive-KB, ambient
   funnel) with separate gates and no shared dedup.

**Goal:** in Automatic mode the bot contributes the way a sharp colleague on a
slightly laggy line would — **says the thing directly**, briefly, grounded in
what it actually knows, at a real gap in conversation, through the cheapest
channel that does the job — and stays silent otherwise.

---

## The two modes (kept, simplified)

The Join-panel selector is unchanged:

| Mode | Behavior |
|------|----------|
| **Utterance** | Today's bot, byte-identical: wake word, Idea Engine, proactive-KB snippets. |
| **Automatic** | Everything in Utterance **plus** the ambient contribution lane, active the entire meeting. |

`state["mode"]` is seeded from the selector at join and changeable mid-meeting
via the existing `POST /bot/{id}/mode` endpoint (which now writes `mode`
directly — `manual_mode` is removed). **Deleted:** lull detection, handoff/stop
phrases, autonomy cap, auto-revert, `mode_entry_reason`. Mute (voice command +
button, both already built) blocks the entire ambient lane and is the in-meeting
kill switch; wake-word requests still work while muted.

---

## Pipeline

```
completed utterance / tick   (Automatic mode · not muted · past_warmup)
   │
   ├─ TRIGGERS (content-based; the 8s metronome is gone)
   │   Q  Unanswered question  → arm answer-wait window + SPECULATIVELY generate
   │   K  KB hit (existing ~20-line proactive search, score ≥ threshold)
   │   B  Blocker / decision moment (regex; chat-tier capped)
   │
   ├─ ② ONE grounded 70B call — the contribution generator
   │      input:  memory context + trigger evidence (question text, KB chunks,
   │              matched utterance) + subjects already contributed + persona name
   │      output: {"value": 0-10, "kind": "answer|fact|risk|none",
   │               "contribution": "≤2 sentences", "subject": "2-5 words"}
   │      Thin evidence ⇒ low value. Parse drift / API error / 429 ⇒ silent.
   │      No agentic tool loop in this lane — retrieval happens BEFORE the call.
   │
   └─ ③ DELIVERY POLICY
          value < CHAT_MIN (5)          → drop (logged)
          CHAT_MIN ≤ value < VOICE_MIN  → meeting-chat post (ℹ️ + citation)
          value ≥ VOICE_MIN (8)         → TIMING GATE → speak (preface +
                                          contribution) + mirror to chat;
                                          no gap within 8s → demote to chat
```

The generator declining (low value / `kind: none`) **is** the decider — one
model, holding the actual candidate, prices it. This replaces v2's 8B prefilter
+ 70B offer-decider + delivery generation (3+ calls → 1).

---

## Triggers

### Q — Unanswered question (the headline trigger)

- **Arm:** a flushed utterance qualifies as a question if it contains `?`
  (Deepgram smart_format punctuates) or starts with a question word and has ≥4
  words — and contains no wake word (the command path owns those). Arms
  `state["pending_question"] = {text, speaker_id, speaker_name, ts, window_s}`.
  One slot: a newer question replaces an older one (the room moved on).
- **Speculative generation (R1):** on arm, the lane runs **one** KB search on
  the question text, then fires the 70B generation *immediately*, in parallel
  with the answer-wait window — not after it. That single search serves double
  duty: its chunks are the generator's evidence, and its top score drives the
  addressee window-scaling below. If the window clears, the candidate is
  discarded (a few K tokens, question-triggers only). If the window expires,
  the contribution is already in hand and delivery starts instantly.
- **Clear:** a subsequent utterance from a **different** speaker with ≥4 words
  clears the slot (the humans handled it) and discards/cancels the candidate.
  The asker continuing does *not* clear ("What was Q3 revenue? I can't find it
  anywhere" is still open); rhetorical questions are the value-scorer's job —
  it sees the recent transcript.
- **Addressee heuristics (R3)** set the window:
  - default: `PRISM_ANSWER_WAIT_S` (6s)
  - question names a human participant ("Vidyut, what do you think?"):
    window × 1.5 — it's explicitly not ours; only enter if they don't.
  - bot-only-answerable (the arm-time KB search's top score ≥ 0.80, or the
    question matches past-decision/action patterns): window × 0.7 — no human
    is the addressee of record.
- **Fire:** on tick, window expired + candidate ready → delivery policy.

### K — Knowledge-base hit

`maybe_proactive_knowledge_check` (already runs every ~20 transcript lines,
already gated by dedupe window, per-doc cooldown, and sensitivity) changes
behavior **only in Automatic mode**: instead of posting a raw 200-char snippet,
the matches become evidence for the contribution generator — same search, same
cost, but the output is a generated, cited contribution routed through the
value tiers. Utterance mode keeps today's snippet behavior exactly.

### B — Blocker / decision moment

`looks_like_blocker()` or `DECISION_PATTERN` match on a flushed utterance →
trigger with the matched utterance as evidence. **Capped at the chat tier in
v1** (a risk flag is rarely worth taking the floor for; revisit with data).

**Concurrency:** one in-flight generation per bot (`_ambient_busy`); triggers
arriving while busy are dropped and logged (generations take ~1–2s, collisions
are rare). Bot-self transcript chunks (existing `bot_self_speaker_id` filter)
never arm triggers or stamp activity.

---

## The contribution generator

- **Model:** `PRISM_AMBIENT_MODEL` (default `llama-3.3-70b-versatile`), direct
  Groq, temperature 0.2, max_tokens ≈ 220. On Groq 429/5xx the lane stays
  silent — **no Haiku fallback**; ambient is optional behavior and the
  fallback budget stays reserved for user-facing paths.
- **Input:** compact dedicated system prompt (persona name injected) +
  `build_memory_context(state)` + a `[TRIGGER]` block (the question / KB chunks
  with doc names / matched utterance) + `[ALREADY CONTRIBUTED]` subject list.
- **Output contract (strict JSON):**
  `{"value": 0-10, "kind": "answer"|"fact"|"risk"|"none", "contribution": "...", "subject": "..."}`
- **Prompt rules:** ≤2 sentences; cite the doc name when evidence is from the
  KB ("Per the Q3 forecast doc, …"); use only facts present in the evidence or
  meeting memory; thin/absent evidence ⇒ value ≤ 4; already-contributed or
  room-already-covered subjects ⇒ value ≤ 4. Value rubric: 8–10 = directly
  answers an open question with grounded info, or corrects a material error;
  5–7 = relevant, helpful, not urgent; 0–4 = tangential/obvious/ungrounded.
- **Fail-safes:** `strip_fences` + brace-extraction + `json.loads`; any drift
  (missing/invalid fields, non-bool/numeric types) ⇒ silent. Same parser shape
  as v2's `parse_decider_output` (rewritten for the new contract). Exceptions
  never propagate to the ingest path.

---

## Delivery

### Chat tier (5 ≤ value < 8)

`_send_chat_response` with an `ℹ️` prefix and the citation inline. Cooldown
`PRISM_AMBIENT_CHAT_COOLDOWN_S` (25s). Zero interruption — deliberately generous.

### Voice tier (value ≥ 8, `PRISM_AMBIENT_VOICE=1`)

1. **Timing gate (R2)** — all three must hold, polled every 200ms for up to
   `PRISM_GAP_WAIT_S` (8s); on timeout, demote to chat (the contribution still
   lands, just non-interruptively):
   - audio-quiet: `now − state["last_audio_ts"] ≥ PRISM_QUIET_GAP_S` (1.5s) —
     `last_audio_ts` is stamped on every *human* transcript-chunk arrival
     (webhook ingest), not on utterance flush, so it tracks speech in
     near-real-time at webhook latency;
   - no pending partial: `not accumulator.pending`;
   - semantic completeness: the last flushed utterance ends with terminal
     punctuation and its final word is not a trailing connective
     (`and / but / so / or / because / um / uh / like`) — the text-level
     approximation of end-of-turn detection ("I went to the store and…" is
     not a gap, even after 2s of silence).
2. **Graceful entry preface (R5):** the spoken audio opens with a short
   floor-taking beat from a small rotation ("One thing worth adding —",
   "Quick note —", …) before the contribution. Voice only — the chat mirror
   gets the bare contribution.
3. **Speak + mirror:** streamed TTS (existing `voice_pipeline` path) speaks
   the contribution; the bare contribution is always posted to chat too, so
   the content survives any audio failure or yield.
4. **Yield rule (R4):** ambient speech records `ambient_speaking_since`; the
   sequential chunk-upload loop checks before each upload whether a human
   transcript chunk arrived after that timestamp → abort remaining uploads,
   log `ambient_yielded`, **never re-take the floor** for this contribution
   (the chat mirror already carries it). Stop latency is webhook-bound
   (~1–2s); ≤2-sentence contributions bound the overlap either way.
5. Cooldown `PRISM_AMBIENT_VOICE_COOLDOWN_S` (60s) between unsolicited speaks.

### Shared guards

- `past_warmup(state)` gates the whole lane (no contributions during intros).
- Mute blocks the whole lane (both tiers); wake word unaffected.
- Subject dedup: normalized-subject ledger `contributed_subjects` (last 25),
  checked post-generation and fed into the prompt; shared with the Idea Engine
  so the two lanes never post about the same subject.
- Shadow (`PRISM_AUTONOMOUS_SHADOW=1`): full pipeline runs and logs every
  trigger, generation, value, and would-be delivery — posts and speaks nothing.

---

## Coordination with existing proactive systems

| System | Change |
|--------|--------|
| Proactive-KB | Utterance mode: unchanged. Automatic mode: its chat-posting is absorbed by trigger K (same search; better output). |
| Idea Engine | Untouched (meeting-*process* insights are a different content class). Shares the `contributed_subjects` ledger. |
| Wake word | Unchanged fast-path in both modes, including the persona-alias punctuation hardening from main. |

---

## Latency budget (honest)

| Stage | This design | Full-duplex ideal |
|-------|-------------|-------------------|
| Hearing the room (Recall webhook ASR) | ~1–2s | ~100ms |
| Candidate ready at gap time | ~0s (speculative, R1) | ~0s |
| Speaking starts (streamed TTS) | ~0.5–1.5s | ~200ms |
| **Gap → bot voice** | **~1.5–3s** | ~300ms |

The floor is Recall's perception delay — we don't own the audio path. The
tiered design is the adaptation: when you can't win on timing, bias voice
toward fewer, higher-value entries and route the rest to the channel where
latency doesn't matter. **Documented upgrade path (out of scope here):**
subscribe to Recall's real-time raw-audio websocket purely as a *timing*
signal (local VAD, no ASR) — upgrades the gap detector and yield rule to
~100–300ms without changing this architecture.

---

## Cost

Triggers are content-based; expected volume in an active Automatic-mode hour:
~5–15 generations (incl. discarded speculative ones) × ~2.5K tokens ≈
**15–40K tokens/hour on the 70B, zero 8B calls** — versus v2's metronome
(8B on most utterances + 70B per 8B-yes). KB trigger embedding cost is
unchanged (it's the existing proactive search). On 429 the lane goes silent.

---

## State & flags

**State fields added:** `pending_question`, `last_audio_ts`,
`ambient_voice_last_ts`, `ambient_chat_last_ts`, `contributed_subjects`,
`_ambient_busy`, `ambient_speaking_since`.
**Removed:** `interjection_state`, `pending_offer`, `offered_subjects`,
`offer_last_ts`, `_ambient_last_gate_ts`, `mode_entry_reason`,
`mode_since_ts`, `recent_utterance_ts`, `manual_mode`. (`muted` stays.)

**Env vars added:** `PRISM_AMBIENT_VOICE` (1; set 0 for chat-only rollout),
`PRISM_AMBIENT_VOICE_MIN` (8), `PRISM_AMBIENT_CHAT_MIN` (5),
`PRISM_ANSWER_WAIT_S` (6), `PRISM_QUIET_GAP_S` (1.5), `PRISM_GAP_WAIT_S` (8),
`PRISM_AMBIENT_VOICE_COOLDOWN_S` (60), `PRISM_AMBIENT_CHAT_COOLDOWN_S` (25),
`PRISM_AMBIENT_MODEL` (llama-3.3-70b-versatile).
**Kept:** `PRISM_AUTONOMOUS`, `PRISM_AUTONOMOUS_SHADOW`.
**Removed:** `PRISM_OFFER_*` (4), `PRISM_LULL_THRESHOLD_S`,
`PRISM_AUTONOMY_CAP_S`, `PRISM_PAUSE_DEBOUNCE_S`, `PRISM_DECIDER_MODEL`.

**Observability counters (perception_state):** `ambient_q_triggers`,
`ambient_kb_triggers`, `ambient_b_triggers`, `ambient_generations`,
`ambient_discarded_answered`, `ambient_low_value`, `ambient_chat_posted`,
`ambient_spoken`, `ambient_demoted_no_gap`, `ambient_yielded`,
`ambient_parse_fail`, `mutes` (kept).

---

## Files touched

| File | Change |
|------|--------|
| `backend/ambient_loop.py` | Rewrite. **Delete** `update_mode`, `check_lull`, `_HANDOFF_RE`/`_STOP_RE`, `decide` + decider prompt/parser, `offer_decider` + prompt/parser, `classify_consent` + prompt/parser, `interject`, `_handle_pending_offer`, `make_offer`, offer-subject helpers (~350 lines). **Keep** `detect_mute_command`, `past_warmup`, flag helpers. **Add** trigger detection (Q/K/B), the contribution generator + parser, the delivery policy, the timing gate, cooldown/dedup helpers. |
| `backend/realtime_routes.py` | Rewrite `_ambient_on_utterance` (trigger arming/clearing). **Delete** `_run_interject`, `_ambient_speak_offer`, `_ambient_run_delivery`, `_AMBIENT_PREAMBLE`, `_is_ambient_silent`, the `ambient=` kwarg on `_process_command`, the `check_lull` tick call. **Add** `last_audio_ts` stamping at chunk ingest, pending-question expiry in the tick loop, ambient voice delivery (gate → preface → streamed TTS → yield check) + chat mirror; `_maybe_generate_idea` consults/records the shared `contributed_subjects` ledger. |
| `backend/knowledge_proactive.py` | Automatic-mode branch: hand matches to the ambient lane instead of posting the snippet. |
| `backend/meeting_memory.py` | State-field changes per above. |
| `backend/perception_state.py` | Counter changes per above. |
| `backend/recall_routes.py` | `initial_mode` now seeds `state["mode"]` directly (no `manual_mode`). |
| `backend/tests/` | `test_consent_interjection.py` **deleted**; `test_ambient_loop.py` + `test_ambient_wiring.py` rewritten for the new pipeline. |
| `frontend/src/components/DashboardPage.jsx` | Selector kept; Automatic hint text updated ("Chimes in with relevant info — speaks only for high-value moments"). |

No schema changes. No new dependencies.

---

## Edge cases

- **Rhetorical / self-answered questions** — asker continuation doesn't clear
  the trigger; the value scorer sees the recent transcript and prices
  rhetorical openings low. Backstop: chat-tier delivery is non-interruptive.
- **Question addressed to a named human** — longer window (R3); if they answer,
  the different-speaker rule clears the trigger.
- **Two questions back-to-back** — single slot, newest wins.
- **Groq 429 / parse drift / any exception** — lane silent; never blocks
  ingest, never falls back to a louder behavior.
- **Bot hears itself** — existing `bot_self_speaker_id` filter excludes its own
  TTS from triggers, `last_audio_ts`, and the clear rule.
- **Human talks over the bot** — yield rule (R4); chat mirror preserves content.
- **Room never goes quiet** — gate timeout → chat demotion; nothing is lost.
- **Server restart mid-meeting** — lane state is per-bot ephemeral; resets to
  the join-time mode, same as the rest of live state.

---

## Rollout

1. **Shadow** — `PRISM_AUTONOMOUS=1` + `PRISM_AUTONOMOUS_SHADOW=1` on real
   meetings; tune `CHAT_MIN`/`VOICE_MIN` from logged values.
2. **Chat-only** — shadow off, `PRISM_AMBIENT_VOICE=0`; the lane is live but
   non-interruptive.
3. **Voice on** — flip `PRISM_AMBIENT_VOICE=1` once chat-tier quality is right.

---

## Acceptance criteria

1. `PRISM_AUTONOMOUS` off ⇒ byte-identical to current behavior.
2. Utterance mode ⇒ byte-identical to current behavior (including proactive-KB
   snippets) even with the flag on.
3. In Automatic mode, an unanswered KB-answerable question yields a spoken,
   cited, ≤2-sentence answer within ~3s of the answer-window expiring into a
   gap — with no consent round-trip.
4. A question a human answers in-window produces **no** bot output and a
   discarded-candidate log entry.
5. The bot never starts speaking while `accumulator.pending` is non-empty or
   within 1.5s of the last human audio; if the room never quiets, the
   contribution arrives in chat instead.
6. A human speaking over ambient bot audio halts further audio within one
   chunk boundary; the contribution remains in chat.
7. Small talk and intros produce no contributions (warmup + value scoring).
8. Mute silences the lane in both tiers; wake-word requests still work muted.
9. Shadow mode emits nothing while logging every pipeline decision.
10. Backend suite green; consent-interjection tests removed with the feature.

## Tests (headline)

Trigger Q arms / clears on different-speaker answer / survives asker
continuation / addressee window scaling; speculative candidate discarded on
clear; trigger K routes through the generator only in Automatic mode; trigger B
caps at chat tier; generator parse-drift ⇒ silent; value tiers route
drop/chat/voice; timing gate blocks on pending partial, trailing connective,
and recent audio; gate timeout demotes to chat; yield aborts remaining chunk
uploads; per-channel cooldowns; subject dedup incl. the shared Idea Engine
ledger; mute blocks lane / wake word still works; shadow emits nothing; flag
off ⇒ no ambient code paths reachable; mode endpoint switches the lane
mid-meeting.

---

## Out of scope

- **Backchanneling** ("mm-hm") — a TTS bot's acknowledgment arriving 1.5s late
  through meeting audio is noise, not presence.
- **Raw-audio VAD timing upgrade** — documented above as the next latency step;
  separate spec when scheduled.
- **Full-duplex / owning the audio path** — a product-scale decision (replacing
  Recall with a native meeting participant), not a patch.
- **Web search / agentic tools in the ambient lane** — wake-word path only;
  unprompted tool use adds latency and injection surface.
- **Distilled local decider** — moot; the lane no longer has a standalone
  decider stage.

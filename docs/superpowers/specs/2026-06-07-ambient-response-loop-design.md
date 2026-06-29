# Ambient Response Loop — Design Spec

**Date:** 2026-06-07
**Branch:** `fixed-changes`
**Status:** SUPERSEDED by `2026-06-11-ambient-contribution-lane-design.md` — do not build on the funnel/mode machine described here
**Roadmap phase:** Realtime live-bot — proactive/ambient response (relates to Phase 7, context-aware conversation)
**Scope of this spec:** backend live-meeting loop only (`realtime_routes.py` + a new `ambient_loop.py`). No frontend beyond a mode indicator + toggle (deferred to the plan).

---

## Problem

Today the live bot only speaks when **explicitly addressed** — the wake word
`prism`/`prismai` (`TRIGGER_PATTERN`, `realtime_routes.py:68`). Nothing fires
unless a participant says the magic word. The product thesis is the opposite:
the bot should **understand the room and decide on its own when it has something
worth saying** — "it just knew when to jump in" — without a wake word.

The naïve version of that ("run an LLM on every utterance to decide respond /
stay silent") is a cost and rate-limit disaster (≈150–250 utterances/meeting,
~95% of which should be silent) and a barge-in risk (a wrong interjection in a
real meeting is the single worst failure mode). This spec designs the version
that is **cheap, low-latency, non-embarrassing, and ~90% reuse** of machinery
that already exists.

**Goal:** a no-wake-word "ambient" response capability, expressed as a second
**mode** the bot can shift into, that decides when to speak via a staged cost
funnel, keeps irreversible actions human-gated, and ships safely behind a flag
with a shadow-soak.

---

## Two modes

The capability is framed as two operating **modes** with a state machine in
front. Critically, they are **not two pipelines** — utterance mode is a *subset*
of the autonomous funnel (the ambient branch switched off). There is exactly one
internal design to build.

| Mode | What it is | Ambient branch | Trigger to speak |
|------|-----------|----------------|------------------|
| **UTTERANCE** (default) | **Today's system, unchanged.** Explicit-only: you address it, it responds. | **OFF** | Wake word `prism …` only |
| **AUTONOMOUS** (new) | The full ambient funnel — the bot decides on its own when to contribute. Explicit fast-path still works. | **ON** | Recall gate → decider → generator, *plus* the wake-word fast-path |

### Mode state machine

```
        ┌──────────── MODE STATE MACHINE (per bot; current mode shown on dashboard) ───────────┐
        │   UTTERANCE  ⇄  AUTONOMOUS                                                             │
        │   → AUTONOMOUS when:  explicit handoff ("prism, run with this / take it from here")    │
        │                       OR auto lull detection (sustained low activity after activity,   │
        │                       or cue phrases "let me pull that up" / "give me a sec")          │
        │   → UTTERANCE when:   revert rule depends on WHY it entered (see below)                 │
        │                       always: "prism, stop"  OR  autonomy cap  OR  manual toggle        │
        └───────────────────────────────────────────────────────────────────────────────────────┘
```

**Revert depends on the entry reason** (tracked as `mode_entry_reason ∈
{lull, handoff, manual}`):

- **Lull-entered** → revert to utterance **as soon as active cross-talk resumes**
  (the lull is over). The decider therefore never runs during active discussion
  in this path — a structural **barge-in guarantee**.
- **Handoff-entered** → the owner explicitly delegated, so the bot **stays
  autonomous through active discussion** until "prism, stop", the autonomy cap,
  or a manual toggle. This path trades the structural guarantee for the
  participation the owner asked for — but it is still protected by the cooldown,
  the "never speak while a participant is mid-utterance" rule, and the decider
  confidence threshold.

**Why this is the right default.** Most of the time the bot is in utterance mode
or lull-entered autonomous, where it *cannot* barge into a heated exchange. It
only contributes during active cross-talk when a human has explicitly handed off
to it. The trade in the conservative (lull) path: it won't auto-answer a question
thrown mid-active-discussion *unless* addressed by name.

---

## The funnel (autonomous mode internals)

Event-driven, **per completed utterance** from `utterance_accumulator` — there is
**no timer/batch tick**. Decider-first and serial: we decide *before* generating,
so there is no speculative generation or pre-synthesized-audio buffer to discard.

```
                         each completed utterance (utterance_accumulator)
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │ explicit "prism …" present?      │ no wake word (ambient branch —   │
        ▼ YES                              ▼ AUTONOMOUS mode only)            
  ┌───────────────┐              ① RECALL GATE  (FREE — heuristics only)      
  │ FAST-PATH     │                 fires on every utterance + a speaker-pause
  │ bypass gates  │                 tick (debounced ~8–10s).                  
  │ → generator   │                 reuses _QUESTION_WORDS, update_structured_
  └──────┬────────┘                 state, looks_like_blocker, knowledge_     
         │                          proactive KB-hits. Tuned for RECALL.      
         │                                  │ triggers the decider            
         │                                  ▼                                 
         │                      ② DECIDER  (8B → 70B on drift; PLUGGABLE)      
         │                         "should I speak now?" → {respond, conf}     
         │                         strict JSON; parse-fail → SILENT;           
         │                         conf < threshold → SILENT; cooldown-aware.  
         │                         fed cheap signals (KB hits, live_decisions, 
         │                         unanswered-question flag) — not a candidate.
         │                         ┌────────┴─────────┐                        
         │                    yes  │                  │ no-but-moderate signal 
         │                         ▼                  ▼                        
         └──────────────▶ ③ GENERATOR (70B)    ④ IDEA ENGINE (side panel)     
                            EXISTING agentic       silent surfacing —          
                            tool loop + verb-gate  "don't speak" ≠ "no value"  
                            READ tools: auto                                   
                            WRITE tools: draft + confirm (verb_gate)           
                            may DECLINE (NO_GROUNDED_ANSWER) → suppress         
                                  │                                            
                                  ▼                                            
                            ⑤ STREAM TTS (StreamingSegmenter / TtsDispatcher) → speak
```

Runs as an `asyncio.create_task` off the transcript-ingest path (same pattern as
`maybe_compress` / `_maybe_generate_idea`) with a per-bot `_ambient_evaluating`
mutex, so it never blocks ingestion and only one evaluation runs at a time.

---

## Decisions locked in this session

| ID | Decision | Rationale |
|----|----------|-----------|
| A1 | **Staged cost funnel:** free recall gate → 8B decider → 70B generator → TTS. Each cheap stage gates the expensive next. | Canonical pattern for deciding cheaply on a stream. Keeps 70B + TTS off the ~95% of moments that should be silent. |
| A2 | **Decider-first, serial** (no speculative parallel generate-then-gate, no pre-generated/buffer-release audio). | The "instant audio" win of speculation is ≈0.3–0.5s (generation is the long pole either way); not worth generating on every "no". A short human-like beat reads as natural. Also removes the buffer/release machinery entirely. |
| A3 | **Recall gate (Stage 1) is FREE** — heuristics on every utterance + a debounced speaker-pause tick. No 8B at Stage 1; the only 8B is the decider. | Stage 1 exists to bound decider volume at ~$0. The pause tick gives the decider a shot at *implicit* openings ("not sure what our Q3 number was") even when heuristics are silent. |
| A4 | **Decider = Llama 3.1-8b on Groq to start; pluggable stage.** Shadow-soak vs 70B; **escalate to 70B on Groq** if soak shows drift. | A binary classifier can't *hallucinate facts* — it can only misclassify, which is tunable/measurable/fail-safe. Match model size to error tolerance; stay in the existing Groq→Anthropic stack. Escalation target is 70B (already in stack), not a new provider. |
| A5 | **Decider fails safe to SILENT** + confidence threshold (start 0.7) biased toward silence. | Missed opening = forgivable/invisible; barge-in = the one embarrassing error. Asymmetric cost ⇒ asymmetric bias. |
| A6 | **Generator is the EXISTING agentic tool loop** (70B, `_process_command` machinery + `think_loop` verb-gate). Unchanged. | ~90% reuse. The verb-gate already implements read-auto / write-confirm. The generator can still DECLINE (`NO_GROUNDED_ANSWER`) — a third backstop on a wrong decider "yes". |
| A7 | **Autonomy boundary: READ tools auto, WRITE tools require confirm** (existing `verb_gate` / `confirm_and_execute`). | The bot can research/prep on its own; anything irreversible (send/post/schedule/file) gets a human yes. |
| A8 | **Borderline "no" feeds the existing Idea Engine** (side panel), not TTS. | Reuse; "don't speak" ≠ "no value". |
| A9 | **Explicit `prism` fast-path kept** as a bypass in both modes. | Guaranteed-respond escape hatch + power-user shortcut; does not dilute the ambient thesis (additional path, not a requirement). |
| A10 | **Mode shift = explicit handoff OR auto lull; revert depends on entry reason** (lull → revert on activity; handoff → persist until stop/cap); manual toggle; dashboard shows mode. | Predictable + safe; visible state is non-negotiable for trust. Lull-entered autonomous doubles as a structural barge-in guarantee; handoff is an explicit opt-in to participate. |
| A11 | **Memory stays async** (`meeting_memory.maybe_compress` untouched; **not** folded into a per-turn structured output). | Never couple latency-critical response to slow summarization. |
| A12 | **Kimi 2.5 / DeepSeek V3.2 are NOT the decider.** Parked as a future *generator* A/B behind its own flag. | Their strengths (tools/reasoning/long-ctx) are exactly what a binary gate discards; the decider wants latency + ops-simplicity. The generator is where a cheap-but-capable model could earn its place — later, mindful of tool-call-shape regressions (`think_loop.py:399`). |
| A13 | **Ship behind `PRISM_AUTONOMOUS`; validate with `PRISM_AUTONOMOUS_SHADOW` first.** | Utterance mode = current prod (no flag). Shadow runs the full funnel + mode transitions, logs decisions + would-be responses, **never speaks** — the `PRISM_ACC_COMPARE` discipline applied here. |

---

## Approaches considered (at each fork)

### Trigger model — what fires the expensive pipeline
- **Cheap recall-gate first ✅ (A1/A3).** Free pre-filter; only survivors reach the decider.
- *Judge on every utterance, generate only on yes* — rejected: a per-utterance LLM call is the rate-limit pressure we're avoiding.
- *Full speculation every utterance* (generate + TTS + judge, release on yes) — rejected: discarded TTS dominates cost; viable only for a throwaway demo.

### Stage ordering — decide vs generate
- **Decider-first, serial ✅ (A2).** Cheapest; no speculative TTS waste.
- *Parallel generate ∥ decide, release on yes* — rejected: ≈0.5s latency win not worth generating on every "no"; adds buffer/release complexity.
- *One structured 70B call `{respond, response, tools}`* — rejected: re-couples decision + generation (kills the calibration win) and re-opens the malformed-tool-call class documented in `think_loop.py:399`.

### Decider model
- **8B start, soak, escalate to 70B on drift ✅ (A4).** Data-driven; stays in stack.
- *Frontier model (Kimi/DeepSeek) on the decider* — rejected (A12): capability mismatch; latency + a third provider for one bit.
- *Heuristics-only decider* — rejected: hard recall ceiling; misses the implicit openings that make it feel magical.

---

## Architecture & data flow

```
realtime webhook (transcript segment)
  → utterance_accumulator → completed utterance
  → update_structured_state(...)            # Layer-3 regex (unchanged)
  → maybe_compress(...) via create_task     # Layer-2 async summary (unchanged)
  → mode = ambient_loop.update_mode(state, utterance)   # handoff/lull/revert detection
  → if explicit "prism ..."  → existing _process_command (fast-path; both modes)
  → elif mode == AUTONOMOUS  → create_task(ambient_loop.evaluate(bot_id, state))
        ├─ ① recall_gate(state, utterance)            # free heuristics + pause tick
        │     └─ miss → return                         # nothing to do
        ├─ ② decide(state)                             # 8B (or 70B); strict JSON; fail-safe SILENT
        │     ├─ respond=False, moderate → idea_engine.surface(...)   # side panel
        │     └─ respond=False, low      → return
        ├─ cooldown / someone-actively-talking guard → return if blocked
        ├─ ③ generator = existing _process_command path (70B agentic loop + verb_gate)
        │     └─ READ auto · WRITE → confirm · may DECLINE → suppress
        └─ ⑤ stream TTS (StreamingSegmenter/TtsDispatcher) → upload to call
```

Shared substrate (all reused, unchanged): `meeting_memory` (context),
`knowledge_proactive` (signals), `think_loop` (verb-gate + artifact handoff),
`voice_pipeline` (streaming TTS), the Idea Engine, `perception_state`
(observability).

---

## New module: `backend/ambient_loop.py`

Pure-ish logic + the two new model touch points. Illustrative surface (final
signatures land in the plan):

```python
# Mode state machine ----------------------------------------------------------
def update_mode(state: dict, utterance: str, speaker: str, now: float) -> str:
    """Detect handoff / lull / revert; mutate + return state['mode']
    ('utterance' | 'autonomous'). Records state['mode_entry_reason']
    ('lull' | 'handoff' | 'manual') — lull reverts on activity resume,
    handoff persists until stop/cap. Honors a manual override flag."""

# Stage 1 — recall gate (FREE) ------------------------------------------------
def recall_gate(state: dict, utterance: str, now: float) -> bool:
    """True if this utterance (or a debounced pause tick) is worth waking the
    decider. High recall: questions, request verbs, disagreement/uncertainty,
    knowledge_proactive KB-hits, fresh live_decision/action_item."""

# Stage 2 — decider (PLUGGABLE) -----------------------------------------------
async def decide(state: dict) -> dict:
    """{'respond': bool, 'confidence': float, 'reason': str}.
    Strict-JSON parse; ANY drift → {'respond': False}. Model chosen by
    PRISM_DECIDER_MODEL. Fed build_memory_context + cheap signals."""

# Orchestration ---------------------------------------------------------------
async def evaluate(bot_id: str, state: dict) -> None:
    """Runs the funnel off the ingest path under the _ambient_evaluating mutex:
    recall_gate → decide → guards → existing generator path → stream TTS.
    Moderate 'no' → idea engine. Shadow mode logs but never speaks."""
```

`realtime_routes.py` changes are thin: call `update_mode` + branch to
`ambient_loop.evaluate` on the no-wake-word path when `mode == autonomous` and
`PRISM_AUTONOMOUS` is on; keep the existing wake-word path as the fast-path.

---

## Safety / control parameters (all env-tunable)

| Param (env) | Default | Purpose |
|-------------|---------|---------|
| `PRISM_AUTONOMOUS` | off | Master flag — makes autonomous mode reachable. Off ⇒ pure current behavior. |
| `PRISM_AUTONOMOUS_SHADOW` | off | Run the funnel + mode transitions, log everything, **never speak**. |
| `PRISM_DECIDER_MODEL` | `llama-3.1-8b-instant` | Decider model; flip to 70B if soak shows drift. |
| `PRISM_DECIDER_THRESHOLD` | `0.7` | Min confidence to speak; biased toward silence. |
| `PRISM_AMBIENT_COOLDOWN_S` | `40` | Min gap between *unsolicited* spoken responses (silent work uncapped; explicit `prism` bypasses). |
| `PRISM_PAUSE_DEBOUNCE_S` | `8` | Min gap between pause-triggered decider evaluations (volume knob). |
| `PRISM_LULL_THRESHOLD_S` | `35` | Low-activity span that triggers utterance→autonomous. |
| `PRISM_AUTONOMY_CAP_S` | `300` | Max autonomous span before auto-revert; a fresh handoff/lull renews it. |

Hard rules independent of tuning: never speak while a participant is actively
mid-utterance; honor `PRISM_BARGE_IN`; writes always confirm.

---

## Efficiency & cost

- **Cascade:** free heuristics → 8B (survivors only) → 70B (decider-"yes" only) →
  TTS (generated text only). Nothing expensive runs until something cheaper
  approved it.
- **Mode-gating compounds it:** the ambient branch is live only during
  lulls/handoffs, so the decider runs on a *fraction* of the meeting — the
  per-utterance volume worry is largely dissolved by the lull gate itself.
- **Decider-first** eliminates speculative TTS spend entirely.
- **Prompt caching:** the generator reuses the existing **cached static system
  prefix** (`_build_static_prefix`, see `2026-06-02-live-bot-persona-wiring`), so
  the ~2800-token context rides the cache across the agentic loop's iterations.
- **Streaming TTS** (already built in `voice_pipeline`) lands first audio while
  the rest generates.
- **Reuse:** the only net-new code is `ambient_loop.py` (recall gate + decider +
  mode machine) and thin wiring; the generator, tools, verb-gate, TTS, memory,
  and Idea Engine are untouched.

### Is this the most efficient design? (honest answer)

Yes — *to build first*. It is the textbook cost cascade with ~90% reuse, and
mode-gating makes it cheaper still. The **only** strictly-cheaper decider is a
**distilled classifier**, which cannot be the starting point (no labeled data
exists yet). The decider is therefore built as a **pluggable stage** (A4) so it
can be swapped later if — and only if — decider cost becomes a real bottleneck at
scale.

---

## Shadow-soak: what it can and cannot harvest (honest framing)

The soak's **primary, certain** value is operational, not ML: tune
`PRISM_DECIDER_THRESHOLD`, measure 8B-vs-70B agreement, catch false-positives via
generator declines, and confirm no barge-ins — **before any of it is audible.**

On the *secondary, speculative* "harvest labels to distill a cheaper decider
later" idea, the precise truth:

- **Harvestable from shadow:**
  - **Distillation pairs** `(context → decision)` — train a cheap student to
    *mimic* a teacher (run the 70B decider as the shadow teacher; it's offline so
    its latency doesn't matter). Gives a cheaper decider of **comparable, not
    better,** quality — a student can't exceed its teacher.
  - **Automatic false-positive labels** — `decider said YES → generator DECLINED
    (NO_GROUNDED_ANSWER)` is a free "shouldn't have spoken" signal.
- **NOT harvestable from shadow:**
  - **Ground-truth false negatives** — when the decider says "silent," shadow
    never speaks, so a *missed* opportunity is never observed. Recovering those
    needs **human review** of the logged contexts (the soak makes this efficient
    by handing the labeler the exact context + candidate) or **live feedback**
    once speaking.

So the soak log is *reusable* for a future distillation, but it is **not** a path
to a *smarter* decider on its own, and the distilled-classifier v2 is an
explicit "only if cost hurts at scale" project — **not promised** by this spec.

Note on training distribution: the decider only ever sees recall-gate survivors
in both training and serving, so there is **no train/serve skew** — but the
"respond" class is rare, so any future classifier must handle heavy class
imbalance (resampling / threshold tuning).

---

## Edge cases & how the design handles them

- **EDGE A — barge-in during active talk.** Lull-*entered* autonomous reverts the
  moment cross-talk resumes, so the decider isn't running then (structural
  guarantee). Handoff-*entered* autonomous deliberately stays — but is still held
  by the "never speak while someone is mid-utterance" rule, the
  `PRISM_AMBIENT_COOLDOWN_S` gap, and the decider confidence threshold.
- **EDGE B — wrong decider "yes".** The 70B generator can still DECLINE
  (`NO_GROUNDED_ANSWER` / "nothing to add") → suppressed before TTS.
- **EDGE C — decider JSON drift (8B instruction-following).** Strict parse;
  any malformed output → `respond=False` (fail-safe silent).
- **EDGE D — autonomous mode runs away.** `PRISM_AUTONOMY_CAP_S` auto-reverts to
  utterance mode; a fresh handoff/lull is required to continue.
- **EDGE E — owner wants control.** Manual toggle (UI + voice) overrides the
  state machine either direction; current mode is always shown on the dashboard.
- **EDGE F — autonomous write action.** Routed through the existing `verb_gate` /
  `confirm_and_execute` — drafts + asks; never sends/posts/schedules unprompted.
- **EDGE G — server restart mid-meeting.** Mode + ambient counters live in the
  per-bot state dict; reset to `utterance` (safe default) on cold reload, like
  the rest of the live state.
- **EDGE H — Groq rate limit on the decider.** `llm_call`'s Groq→Haiku fallback
  applies; on any decider error the fail-safe is SILENT, so a throttled decider
  degrades to "say nothing", never to a wrong interjection.
- **EDGE I — explicit `prism` during autonomous mode.** Fast-path bypass fires
  the generator directly, ignoring gates/cooldown (the user asked).

---

## Rollout plan

1. **Phase 0 — utterance mode unchanged.** No flag, current production behavior.
2. **Phase 1 — `PRISM_AUTONOMOUS_SHADOW`.** Funnel + mode machine run, log
   decisions / would-be responses / would-be mode shifts, never speak. Tune
   threshold; measure 8B-vs-70B agreement + generator-decline rate; confirm zero
   barge-in candidates during cross-talk.
3. **Phase 2 — `PRISM_AUTONOMOUS` live** for internal/opt-in bots once shadow
   metrics are clean. Manual toggle + dashboard indicator required before live.
4. **Phase 3 (conditional) — decider escalation** to 70B if soak drift demands;
   distillation only if decider cost becomes a scale bottleneck.

---

## Files touched (anticipated)

| File | Change |
|------|--------|
| `backend/ambient_loop.py` | **New.** Mode state machine, free recall gate, decider (pluggable model), funnel orchestration, shadow-soak logging. |
| `backend/realtime_routes.py` | Call `update_mode`; branch no-wake-word path to `ambient_loop.evaluate` when autonomous + flag on; keep wake-word fast-path; add `_ambient_evaluating` mutex + mode fields to bot state. |
| `backend/meeting_memory.py` | Add mode/ambient bookkeeping fields to `get_initial_memory_state` (counters, `mode`, `mode_entry_reason`, `mode_since_ts`, last-spoke ts, `_ambient_evaluating`). No change to compression. |
| `backend/perception_state.py` | New observability counters (gate fires, decisions, declines, suppressions, mode shifts). |
| `frontend/` (mode indicator + toggle) | Deferred to the plan; small dashboard surface showing/limiting current mode. |

No schema changes anticipated (mode is per-meeting ephemeral state). New env vars
per the table above. No change to the 8-agent analysis graph.

---

## Out of scope (deferred)

- **Distilled-classifier decider (v2)** — conditional on cost-at-scale; soak logs
  are kept reusable for it but it is not promised here.
- **Kimi 2.5 / DeepSeek V3.2 generator A/B** — separate flag + spec; watch
  tool-call-shape regressions.
- **Periodic/deliberate self-driven "agent tick"** — explicitly *not* part of
  autonomous mode (which is event-driven per utterance). Considered and dropped.
- **Frontend mode UX polish** beyond a minimal indicator + toggle.
- **Per-meeting cost cap / provider budget** — separate, pre-existing concern.

---

## Acceptance criteria

1. With `PRISM_AUTONOMOUS` **off**, behavior is byte-identical to today
   (utterance mode only; wake-word path unchanged).
2. In `PRISM_AUTONOMOUS_SHADOW`, the funnel + mode transitions are logged on real
   meetings and the bot **never** emits audio.
3. In autonomous mode (live), the bot speaks unprompted only when: mode is
   autonomous, recall gate fired, decider `respond=True` above threshold, no one
   is mid-utterance, and cooldown is clear.
4. A wrong/over-eager decision is caught by at least one backstop (generator
   decline, cooldown, or fail-safe-silent) rather than producing a barge-in.
5. Autonomous **write** actions always route through `verb_gate`/confirm — no
   unprompted send/post/schedule/file.
6. The explicit `prism …` fast-path responds in both modes.
7. Current mode is visible on the dashboard and manually overridable.
8. Backend test suite stays green and gains the tests below.

---

## Tests (anticipated — finalized in the plan)

| Test | Verifies |
|------|----------|
| `test_update_mode_handoff_to_autonomous` | "prism, run with this" → mode = autonomous |
| `test_update_mode_lull_to_autonomous` | sustained low activity → autonomous (reason=lull) |
| `test_update_mode_lull_reverts_on_activity` | lull-entered + cross-talk resumes → utterance |
| `test_update_mode_handoff_persists_through_activity` | handoff-entered + cross-talk → stays autonomous |
| `test_update_mode_autonomy_cap_reverts` | span > cap → utterance (either entry reason) |
| `test_update_mode_manual_override_wins` | manual toggle beats auto detection |
| `test_recall_gate_question_fires` / `_silence_misses` | heuristic recall behavior |
| `test_recall_gate_pause_tick_debounced` | pause tick respects `PRISM_PAUSE_DEBOUNCE_S` |
| `test_decide_parse_failure_is_silent` | malformed JSON → `respond=False` |
| `test_decide_below_threshold_silent` | low confidence → silent |
| `test_decide_moderate_no_routes_to_idea_engine` | borderline "no" → side panel |
| `test_evaluate_blocked_by_cooldown` | within cooldown → no speak |
| `test_evaluate_blocked_while_speaker_active` | mid-utterance → no speak |
| `test_evaluate_generator_decline_suppresses` | NO_GROUNDED_ANSWER → no audio |
| `test_evaluate_write_tool_requires_confirm` | autonomous write → verb_gate refusal/confirm |
| `test_shadow_mode_never_speaks` | shadow flag → logs only, zero TTS |
| `test_autonomous_off_is_byte_identical` | flag off → current behavior unchanged |
| `test_explicit_prism_fast_path_both_modes` | wake-word bypass works in both modes |

Frontend has no test framework (project convention) — none added.

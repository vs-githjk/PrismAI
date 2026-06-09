# Live-Bot Perf Defaults + Dead-Code Cleanup — Design Spec

**Date:** 2026-06-07
**Branch:** `fixed-changes`
**Status:** Approved — ready for implementation
**Scope:** edge/leaf changes only. The consent-interjection v2 architecture
(`interject` state machine, recall gate, offer-decider, consent classifier, mute,
warmup) is **untouched**.

---

## Problem

Live-bot replies are slow even excluding TTS. Live log on "Prism, am I on
automatic mode": the model called `web_search` (Tavily, ~2-3s) **and**
`knowledge_lookup` for a meta question needing neither, hit a malformed-tool-call
recovery, then a second 70B pass — and only *then* did TTS start, because
streaming is off. Two root causes: **streaming is gated off**, and the model
**over-calls slow tools**. Separately, rollout flags + a superseded function are
now cruft.

**Goal:** make the performance wins permanent (no manual flag), and delete the
genuinely-dead code — without altering the system design.

---

## Changes

### 1. Streaming on by default
The four `getenv` checks for `PRISM_STREAMED_TTS` / `PRISM_STREAMED_LLM` in
`realtime_routes.py` currently mean "off unless `=1`". Flip to **"on unless
`=0`"**: `os.getenv("PRISM_STREAMED_TTS", "1") != "0"` (and the same for
`PRISM_STREAMED_LLM`). Audio then streams as the model generates — first audio
~1s in instead of after the full response + all tool rounds.

**Keep the buffered path** as the `=0` fallback. It is *not* dead code — it is the
safety net if streaming misbehaves in production, and the instant escape hatch.
(Fully deleting buffered is explicitly out of scope: more aggressive, removes the
fallback.)

### 2. Tool-conservatism (permanent, no flag)
Add a tool-policy clause to the **cached static prefix** (`_build_static_prefix`,
via a new `_STATIC_TOOL_POLICY` appended to `base`). Intent:

> Answer directly from the conversation and your own knowledge whenever you can.
> Use `web_search` ONLY for current external facts you genuinely do not know, and
> `knowledge_lookup` ONLY for the user's uploaded documents. Do NOT call any tool
> for questions about yourself/your state or for simple conversational replies.

It rides the prompt cache (≈0 cost per call). This is the actual-latency fix —
it removes the gratuitous tool round-trips. Kept deliberately short and free of
`<thinking>`-style directives (a prior directive destabilised Groq+Llama tool-call
syntax — see the note already in `_build_static_prefix`).

### 3. `web_search` timeout cap (permanent)
Bound the Tavily request (~4s, env-overridable `PRISM_WEB_SEARCH_TIMEOUT_S`) so a
slow search can't dominate when a tool *is* used. On timeout, return the existing
graceful "no results" shape so the loop continues.

### 4. Delete dead / inert code
- `ambient_loop.evaluate()` — superseded by `interject()`, now unreachable (wiring
  calls `interject`). Delete it.
- `EvaluateTests` in `test_ambient_loop.py` — target deleted; remove the class.
- `ambient_loop.decider_threshold()` and `cooldown_s()` — only `evaluate` used
  them. Delete + their `PRISM_DECIDER_THRESHOLD` / `PRISM_AMBIENT_COOLDOWN_S`
  defaults.
- The inert `PRISM_DECIDER_THRESHOLD=0.85` / `PRISM_AMBIENT_COOLDOWN_S=120` lines
  in `backend/.env` (they tuned v1's path; v2 ignores them).

**Kept** (still live, do NOT remove): `decide()` (now the 8B substance prefilter),
`recall_gate`, `_signal_summary`, `decider_model`, `pause_debounce_s`,
`lull_threshold_s`, `autonomy_cap_s`, and all offer-side params.

---

## Files touched

| File | Change |
|------|--------|
| `backend/realtime_routes.py` | Flip 4 streaming `getenv` defaults to on; add `_STATIC_TOOL_POLICY` to `_build_static_prefix`. |
| `backend/tools/web_search.py` | Timeout cap on the Tavily request. |
| `backend/ambient_loop.py` | Delete `evaluate`, `decider_threshold`, `cooldown_s`. |
| `backend/tests/test_ambient_loop.py` | Remove `EvaluateTests`. |
| `backend/.env` | Remove the 2 inert tuning lines. |
| `backend/tests/test_consent_interjection.py` (or a small new test) | Tiny test that the streaming default helper reports on-by-default. |

No schema, no frontend, no change to the interjection state machine.

---

## Testing
- New: streaming-default helper returns True when the env var is unset; False when `=0`.
- `test_streamed_voice` already covers the streaming path.
- Remove `EvaluateTests`; the rest of the ambient/consent suites stay green.
- Import smoke + targeted regression after the deletions.

## Out of scope (deferred)
- Graduating the other rollout flags (accumulator/think_loop/barge-in/owner-id-
  lock/injection-guard/prompt-cache) and removing the legacy chunk path.
- Fully deleting the buffered-TTS fallback.

## Acceptance criteria
1. With no env flags set, the bot streams audio (first audio well before the full
   reply); `PRISM_STREAMED_TTS=0` restores buffered.
2. A meta/simple question is answered without calling `web_search`/`knowledge_lookup`.
3. A `web_search` that stalls returns within the cap, loop continues.
4. `evaluate` and its tests/helpers/env are gone; all remaining suites pass.
5. No behavior change to the consent-interjection flow.

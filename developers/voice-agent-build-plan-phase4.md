# Phase 4 — One engagement gate (Auto / Manual)

Goal: collapse wake-word/solo-freeflow/ambient/proactive into a single decision point with one user-facing toggle. After this phase there are exactly two behaviors: **Auto** (bot speaks directly when it judges a contribution is warranted) and **Manual** (wake-word only). (KRC items 6–9, 11; fork ①; Q3; core decision #6.)

## 1. New module

```
backend/voice/gate.py   # the ONLY place that decides "does the bot speak now?"
```

`voice_channel.py` calls the gate on every finished turn (and for every proposer nudge). Everything else feeds it signals.

## 2. Gate inputs → decision

| Signal | Source | Effect |
|---|---|---|
| `mode` (auto/manual) | settings (item 11's `/bot/{id}/mode`) | Manual: only wake-word turns pass. Auto: everything below applies |
| Wake-word hit | item 6's patterns (persona names + Prism aliases) | Always passes the gate, both modes — an addressed bot answers |
| Headcount | item 5 roster (webhooks) | Auto + 1 human → every substantive utterance passes (absorbed solo free-flow, item 7). Auto + N humans → ambient judge decides |
| Ambient judge verdict | Q3: reused judgment prompt (minus consent), run on the voice channel's model | "Worth saying" → speak directly (fork ①: no offer, no "want it?") |
| Proposer nudges | item 9: drifting-commitment checker + idea generator post *candidates* to the gate | Gate decides whether/when to voice them — the watchers never speak on their own |
| Mute | item 11 kill-switch | Hard stop, all paths |
| Speaking state / gap | politeness gate | Timing, not permission — a "yes" waits for the lull |

Mode is user intent and **never auto-switches** (item 7's clarification): Manual in a 1-on-1 stays wake-word-only. Auto is the default, so solo meetings behave like today out of the box.

## 3. Wake-word machinery slimming (item 6)

Keep: trigger patterns, persona aliases (`_BOT_WAKE_ALIAS`, `_WAKE_PATTERN_CACHE`), bare-name case ("Prism." → pause → next utterance from same speaker is the command — human behavior, survives).
Delete: fragment-gluing (`_looks_command_complete`, `_COMMAND_MIN_WORDS_FOR_DISPATCH`, pending-parts accumulation) — Flux hands us complete turns; guessing completeness from punctuation is dead. The bare-name window shrinks to a simple "armed for next turn from speaker X within 8s" state.

## 4. Consent funnel removal (item 8)

`_ambient_speak_offer` / `_ambient_run_delivery` / the offer→confirm state machine die. The judge's prompt is reused (Q3) with the offer framing stripped: output is now *the contribution itself or silence*, not an offer. `_is_ambient_silent`-style "stay quiet" detection survives as the gate's no-op branch. Future judge tuning: `docs/future-ideas.md`.

## 5. Proactive/idea rewiring (item 9)

`_run_proactive_checker` + `_maybe_generate_idea` keep their schedules and detection logic, lose their mouths: output becomes `gate.propose(candidate)`. The gate applies mode/mute/room-state and speaks at most one nudge per quiet window (no proposer pile-ups).

## 6. Frontend

The dashboard bot-mode control (NewMeetingPanel / settings surface) becomes a two-value toggle: **Auto** (default) / **Manual**, wired to the existing `/bot/{id}/mode` endpoint with new semantics. Old mode values migrate (`ambient`→auto, anything else→manual) server-side; no DB migration needed if mode lives in settings JSON — verified at build time.

## 7. Demolition (final commit)

- `_solo_mode_active`, `_solo_freeflow_*`, `PRISM_SOLO_FREEFLOW` (absorbed — item 7).
- `_ambient_on_utterance` funnel path, `_ambient_speak_offer`, `_ambient_run_delivery` (item 8).
- Direct-speak paths inside proactive checker + idea generator (item 9).
- Fragment-gluing wake-word code (item 6's dead half).
- Flags obsoleted this phase (Q6).

## Exit criteria

Exactly one decision function answers "speak now?"; flipping the dashboard toggle changes behavior live; Manual = only wake words (even solo); Auto solo = free conversation; Auto group = selective interjection with no consent question; a drifting-commitment nudge arrives *through the gate*.

# Phase 5 — Feel tuning

Goal: make it feel like a participant, not a system that technically responds. This phase is a knob-turning loop with the owner, not a feature build: implement the knobs, seed them with Curio's proven values, then iterate on real-meeting feel. (KRC item 22; fork ④'s Silero half; the item-22 reporting promise.)

## 1. Real-audio barge-in (item 22's rebuild)

- Silero VAD speech-start during bot playback → Pipecat interruption → TTS + speaker-page buffer flushed within ~100ms. The old transcript-final-based supersede/cancel (`SpeakingSession` semantics) re-homes onto this signal.
- **Backchannel tolerance:** short affirmations while the bot talks ("yeah", "mm-hm", "right") must NOT kill the reply. Gate the interrupt on sustained speech: VAD speech-start + duration ≥ `BARGE_MIN_SPEECH_MS` (start ~500ms) before firing; sub-threshold bursts are ignored. If a transcript for the burst arrives later and is substantive, treat as a late interrupt.
- Mute / "stop" spoken command stays an instant kill (deterministic, pre-gate).

## 2. Politeness gap on real audio (item 22 report-back)

Replace transcript-timestamp silence with PCM-level silence from VAD state: speak when the room has been acoustically quiet ≥ `GAP_SILENCE_S`, cap `GAP_MAX_WAIT_S`. Same knobs as today (1.2s / 4.0s defaults carry over), now measured on truth instead of lagged transcripts. **Owner gets a report:** observed silence-wait distributions before/after, so the defaults can be re-picked on data.

## 3. Latency polish

- Flux **EagerEndOfTurn** → start the Groq call speculatively; `TurnResumed` → cancel. (The events Phase 2 wired but the shim ignored.) Expected win: 200–400ms.
- Review the stopwatch medians (t0–t4) per segment; attack the fattest segment; re-report. The t3→t4 Recall mix number gets a final verdict here: fine / tolerable / escalate-to-vendor-question.

## 4. Voice & delivery

- Cartesia voice selection (owner picks from 2–3 candidates), speed/pause defaults.
- Spoken-condense limits (`_spoken_condense`: 3 sentences / 340 chars) re-tuned for streaming — a streaming voice can afford slightly longer before it feels laggy, since it starts immediately.
- Future (ledger, not this phase): emotion/expressiveness via Cartesia per-utterance controls.

## 5. Knob table (all env-tunable, seeded from Curio `tuning.py` where it has an equivalent)

| Knob | Default (seed) | What it changes |
|---|---|---|
| `BARGE_MIN_SPEECH_MS` | ~500 | backchannel vs real interruption |
| `GAP_SILENCE_S` | 1.2 | how long a lull before speaking |
| `GAP_MAX_WAIT_S` | 4.0 | never-hang cap |
| `EAGER_EOT_THRESHOLD` | Flux default | speculative-LLM aggressiveness |
| `EOT_THRESHOLD` | Flux default | end-of-turn confidence |
| spoken-condense limits | 3 sent / 340 ch | speak-short cutoff |
| ack timer | 1.5s | chat-ack threshold (fork ③) |
| dedup similarity / window | 0.85 / 3s | queue tier-1 (item 10) |

Curio's `tuning.py` is read at build time and any additional knobs it proved useful (gap/overlap pacing, interruption grace) get ported with their values as seeds.

## 6. The loop

Owner joins real meetings, reports feel ("interrupts me when I think out loud", "too slow to jump in") → agent maps each report to a knob or a judge-prompt tweak → adjust → next meeting. No exit criteria beyond the owner saying it feels right; the phase ends by decree, not checklist.

## 7. Demolition (final commit)

- Transcript-timestamp gap implementation (replaced by PCM version).
- Any remaining obsoleted experiment flags — final Q6 sweep; after this phase the only flags left are operational (mute, mode default, barge-in kill-switch, knob overrides).

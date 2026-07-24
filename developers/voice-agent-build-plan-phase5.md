# Phase 5 — Feel tuning

> **STATUS — dry build COMPLETE (2026-07-22).** §1–§5 built; §6 is the owner's loop (needs
> real meetings); §7 demolition **deliberately not done — awaiting the owner's ruling**
> (see "Demolition: held" below). New: `backend/voice/tuning.py` (the §5 knob table) +
> `backend/voice/barge.py` (Silero room state, the duration-gated interrupt, the VAD
> politeness gap + its report). Changed: `pipeline.py` (VAD + gate + Cartesia knobs +
> eager-EOT wiring), `speaker_page.py` (`stop` kills scheduled buffers), `voice_channel.py`
> (speculative call, gap before the first chunk), `bridge.py`/`stopwatch.py` (real t0–t4
> threading), `gate.py` (`might_engage`), `bus.py` + `realtime_routes.py` (knobs), plus
> `requirements.txt` (`[silero]`) and `.env.example`.
>
> **Not run against real audio** — same key-stop as phases 2–4. Verified offline: every
> module imports clean, all voice self-checks pass (tuning parsing, room/playout math, the
> backchannel-vs-interrupt gate, late interrupt, gap wait + fallback, speculation
> start/adopt/miss/cancel, stopwatch turn slot, gate `might_engage` not consuming the arm
> window), and the 741-test backend suite passes.
>
> **Degradation is deliberate:** if Silero can't load (no onnxruntime wheel), the pipeline
> reverts to Flux's built-in interruption and the gap falls back to transcript timestamps.
> Prod pins Python 3.11 in `render.yaml`, so prod gets Silero.

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

### Demolition: held (2026-07-22) — owner ruling needed

Nothing was deleted. The tension the plan didn't anticipate: phases 2–4 each deferred their
own demolition pending a live test that still hasn't happened, so the "legacy" code this
phase would delete is currently the **only path that has ever been the live path**, and it
is about to be the safety net on prod.

Specifically:

- **The transcript-timestamp gap is not purely legacy.** It is the fallback inside
  `barge.wait_for_gap` for (a) bots with no voice pipeline attached — the entire
  non-voice-agent fleet, which still runs the webhook transcript path — and (b) any
  environment where Silero fails to load. Deleting it removes the politeness gate for
  those, it doesn't just remove dead code. Recommendation: keep permanently, reframed as
  "the estimate used when there's no acoustic truth" rather than as legacy.
- **`PRISM_TWO_CHANNEL` / `PRISM_ENGAGEMENT_GATE` / `_process_command` / `bridge.py` /
  the MP3 path** are phases 3–4's deferred demolitions, gated on one real meeting. They
  are not Phase 5's to delete, and deleting them before that meeting removes the rollback.

Flags this phase added are all operational per Q6 and stay: `PRISM_VOICE_BARGE_IN`
(kill-switch), `PRISM_GAP_WAIT`, and the knob overrides in `voice/tuning.py`.

## 8. What the build actually does (implementation notes)

- **Barge-in** is a duration gate, not a word count. `VADProcessor(SileroVADAnalyzer)` sits
  between the transport and Flux; `BargeInGate` arms a timer on `VADUserStartedSpeakingFrame`
  and fires only if the burst is still running `BARGE_MIN_SPEECH_MS` after it began (VAD's
  own `start_secs` counts toward that, not on top of it). Firing = `broadcast_interruption()`
  (kills the Cartesia turn) + `{"type":"stop"}` to the speaker page (kills buffers already
  scheduled on its Web Audio cursor — the audio that is otherwise already past the point of
  no return). Flux's `should_interrupt` is switched OFF whenever Silero loaded, since it
  interrupts on *any* turn start, which is the behaviour §1 exists to fix.
- **Stopping the reply, not just the audio.** Killing the TTS turn is only half of it: a
  streamed reply is still generating, and every later sentence would be queued straight
  back into the mouth the human just talked over. `RoomAudio.interrupt_seq` is bumped per
  interrupt; the streaming loop snapshots it and bails when it moves (chat still gets the
  full text). Without this, barge-in would have looked like it worked for ~1 sentence.
- **Late interrupt**: `TranscriptCapture` calls `barge.late_interrupt()` on every final
  transcript. A sub-threshold burst whose words number ≥ `LATE_INTERRUPT_MIN_WORDS` (3,
  Curio's proven backchannel boundary — its value, not its mechanism) interrupts after the
  fact. One interrupt per burst, latched.
- **Mute and spoken "stop"** call `barge.hard_stop()` — no threshold, no gap. Fixing this
  turned up a live bug: the stop-command detector read `segment["words"]`, which Flux always
  leaves empty, so "stop" was undetectable on the voice-agent path. It now falls back to
  `segment["text"]`.
- **The gap** reads `RoomAudio.quiet_seconds()` (Silero) and polls at 50ms instead of 200ms,
  since VAD state is local and free. `_wait_for_speech_gap` is now a two-line delegation.
  Every wait is recorded; `[voice-gap] SUMMARY` logs median/p90/max plus the reason and the
  `source=vad|transcript` split every 10 waits — that split IS the before/after report §2
  asks for. A `note_speak_queued` grace covers Cartesia's time-to-first-byte so chunk 2 of
  a streamed reply doesn't stall in the gap waiting for chunk 1's own audio.
- **Speculation (§3)** is a cache of an in-flight LLM stream keyed by the eager transcript.
  `on_eager_turn` → `gate.might_engage` (a deliberately read-only sibling of `decide()`, so
  a speculation can never consume the bare-name arm window) → start the streaming call with
  deltas buffered into a queue. It **never speaks on its own**: only the real post-EndOfTurn
  path can adopt it, and only on an exact normalized text match. `TurnResumed`, a mismatch,
  or a TTL abandons it. Dormant until `PRISM_FLUX_EAGER_EOT_THRESHOLD` is set (Flux's
  default, and Curio's, is off) — **the owner has to set it to get the 200–400ms.**
- **The stopwatch is now real end-to-end.** Previously only t3/t4 were populated, which made
  §3's "review the t0–t4 medians per segment" impossible. A per-bot open-turn slot joins the
  three places that stamp markers: the ears open the turn at EndOfTurn (t0 and t1 are the
  same instant on Flux — the semantic decision *is* the transcript), the voice channel marks
  t2 on its first token, the mouth claims the turn for t3/t4. An interrupted utterance drops
  its turn so the next one can't inherit a poisoned t3.
- **Not done, needs real audio:** the §6 loop itself; re-picking `_spoken_condense`'s
  3 sentences / 340 chars for a streaming mouth (§4 — the pacing constraint that set those
  numbers is gone, but there is no data to re-pick on, so they ship as knobs at the old
  value); picking the Cartesia voice; and the t3→t4 verdict.

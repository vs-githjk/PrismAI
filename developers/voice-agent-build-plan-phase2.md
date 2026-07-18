# Phase 2 — Transport swap (ears + mouth + stopwatch)

Goal: replace the webhook-transcript ears and MP3-blob mouth with the Pipecat-run realtime loop. The **old brain stays** this phase — Flux end-of-turn feeds the existing `_process_command`, so the bot remains fully functional while only the transport changes. (KRC items 1–5, 19, 20; core decisions #3, #4, #9; Q1 hybrid, Q2, Q5.)

## 1. New package layout

```
backend/voice/
  __init__.py
  pipeline.py        # builds one Pipecat pipeline per bot (transport→VAD/Flux→bridge→Cartesia→sink)
  serializer.py      # RecallFrameSerializer: Recall audio WS frames ⇄ Pipecat frames
  audio_routes.py    # FastAPI WS endpoints: /voice/audio-in/{token} (Recall→us), /voice/speaker/{token} (page↔us)
  speaker_page.py    # serves the thin Output Media page (GET /voice/speaker-page/{token})
  stopwatch.py       # per-turn t0–t4 markers → JSONL log + loud t3→t4 reporting
  bridge.py          # Phase-2 shim: Flux EndOfTurn → existing _process_command; replaced by channels in Phase 3
```

## 2. Recall bot-create changes (`recall_routes._recall_bot_create_json`)

Current payload (line ~713 after the 2026-07-18 main merge; the doc's original "~294" predates it): webhook `realtime_endpoints` carrying `transcript.data` + chat + participant events; `deepgram_streaming` transcript provider; recording (mp4/mp3) config. NOTE: main since added nova-3 tuning + flag-gated live keyterm (`_LIVE_KEYTERM_ENABLED`, default OFF) + async re-transcription (Lever B) — the async/recording path is KEPT; only the live `transcript.data` subscription moves to Flux. **[DONE 2026-07-18]**

Changes:
- **Add** a websocket realtime endpoint streaming raw per-participant audio to `wss://…/voice/audio-in/{token}` ⚠ (exact event name — `audio_separate_raw.data` vs mixed — and endpoint shape verified against current Recall docs; separate-per-participant is preferred: it carries speaker identity, which replaces webhook diarization).
- **Add** Output Media config pointing Recall's renderer at `https://…/voice/speaker-page/{token}` ⚠ (exact field: `output_media.camera.kind=webpage` shape per current docs). Mutually exclusive with `output_audio` uploads — which we're deleting anyway.
- **Drop** `transcript.data` from the webhook events list. **Keep** `participant_events.chat_message`, `.join`, `.leave` (Q2: chat + roster stay webhooks).
- **Keep** the recording config (mp4/mp3) and the async `deepgram_streaming` transcript provider — recording playback and the post-meeting fallback transcript (`_process_bot_transcript`) still use them. Only the *realtime* speech path moves.
- Token: reuse the existing per-bot realtime token (`register_realtime_token`) for both new WS endpoints.

## 3. The ears

- `serializer.py`: parse Recall's audio WS frames (16kHz mono s16le + participant metadata) → Pipecat `InputAudioRawFrame` tagged with speaker. Filter the bot's own participant (item 5's `_looks_like_bot_participant` logic reused) so it never hears itself.
- `pipeline.py`: Pipecat pipeline per bot — input transport (FastAPI WS + our serializer) → Silero VAD (interruption) + Deepgram **Flux** service (STT + semantic end-of-turn; enable eager end-of-turn events for the Phase 3 latency win, unused by the Phase 2 shim).
- Flux transcript lines feed the existing state: `transcript_buffer`, `_append_realtime_line`, memory compression — same consumers, new producer.
- New ingress guard (replaces `_ingress_rate_ok`): max concurrent audio sockets per token = 1, drop + log on protocol garbage.

## 4. The mouth

- `speaker_page.py`: ONE static HTML page (~100 lines, inline JS): opens `wss://…/voice/speaker/{token}`, receives PCM/opus audio frames ⚠ (format per Pipecat output + browser AudioWorklet appetite — decided at build time), plays them gaplessly, reports playout-start pings back on the same socket. No logic beyond play + ping.
- Output sink in `pipeline.py`: Cartesia streaming TTS service → frames forwarded to the speaker WS.
- **Faithfulness rule (item 20, owner's condition):** every behavior of the old mouth carries over — speak-short/chat-full condensation, URL/citation stripping, leak scrubbing, politeness gap, mute/cancel honoring. Only genuinely blob-specific machinery dies (play-seconds estimation — a streaming socket with real playout feedback doesn't guess). Destination changes; skeleton behavior doesn't.
- Politeness gap: Phase 2 keeps the transcript-timestamp implementation as-is (item 22's real-audio rebuild is Phase 5 — it needs the tuning loop). Same knobs.

## 5. The bridge (temporary brain glue)

`bridge.py`: on Flux `EndOfTurn` → hand the finished utterance to today's dispatch path (`_detect_command` / solo / ambient logic untouched this phase). Replies route to the new mouth instead of `_send_voice_response`. This shim is explicitly Phase-3 fodder — it exists so Phase 2 ships a working bot.

## 6. The stopwatch (absorbed Phase 0)

`stopwatch.py` — per turn:

| Marker | Where captured |
|---|---|
| t0 | Flux EndOfTurn event timestamp |
| t1 | final transcript in hand |
| t2 | first LLM token |
| t3 | first TTS audio byte from Cartesia |
| t4 | first audio frame sent to speaker page + measured WS RTT/2 (send-side proxy — one clock, no browser clock trust) |

JSONL per turn (`voice_timings.jsonl` or log line), plus a rolling median/p90 summary logged every N turns. **t3→t4 + the page's playout pings get logged LOUDLY** — that's Recall's mix-hop floor, the one number that could ever send us to MeetingBaaS (master doc §5).

## 7. Env & flags — and the KEY STOP

New env vars: `DEEPGRAM_API_KEY` (Flux), `CARTESIA_API_KEY`, `CARTESIA_VOICE_ID`. Operational (kept): mute, `PRISM_GAP_*`. No "use old path" flag — Q5.

**Build order around the stop:** steps 1–6 are implemented WITHOUT live keys (code, page, payload, stopwatch — all writable and lint-checkable dry). Then the build **halts at the KEY STOP**: the agent posts the checklist (overview doc), the owner creates the keys with proper configuration and confirms Output Media is enabled on the Recall account, keys land in `backend/.env` + Render env. On the owner's "keys are in", the build resumes: live wiring, first real join, stopwatch readout — and continues into Phase 3 without further planned stops.

## 8. Demolition (final commit of the phase)

- `_upload_audio_to_recall`, `_estimate_play_seconds`, `_send_voice_response` (MP3 path) — item 19.
- Utterance accumulator + tick loop + compare mode + `_legacy_buffer_append_simulation` — item 2.
- `perception_state` integration + `PRISM_PRE_PERCEPTION` — item 3.
- `_ingress_rate_ok` webhook limiter — item 4 (replaced).
- Flags obsoleted: `PRISM_STREAMED_TTS`/`PRISM_STREAMED_LLM` (streaming is now the only path), accumulator flags — item 28/Q6 (this phase's share).
- `transcript.data` branch of `_handle_realtime_payload` (the dispatcher keeps chat + participant branches).

## Exit criteria

Bot joins a real meeting; hears through Flux (transcript lines appear in state/memory); speaks through the Output Media page; wake-word commands answered by the old brain; timings JSONL populating with a visible t3→t4 readout; MP3/accumulator code gone.

## Build status (2026-07-18)

**Dry build DONE — halted at the KEY STOP.** Delivered keyless: all six `backend/voice/` files, bot-create re-target, router registration, `pipecat-ai[deepgram,cartesia,silero]==1.4.0` in requirements. Import-clean against pipecat 1.4.0 (validated via Curio's venv); serializer end-to-end + stopwatch self-checks pass. All ⚠ field names verified against live Recall API + installed pipecat 1.4.0 source (NOT 1.3.0 — Curio's docstring was stale).

**Still open (resume after "keys are in"):**
1. **Mouth re-point** — `realtime_routes` reply emission (`_send_voice_response` / streamed-TTS paths) → try `voice.bridge.speak(bot_id, text)` first, fall back to the old path. Deferred because it's untestable without `CARTESIA_*` and is the riskiest edit to the 3.6k-line file — the plan sequences live wiring after the stop.
2. **Ears activation** — code is wired (audio-in WS → pipeline → `bridge` → old brain); needs `DEEPGRAM_API_KEY` (Flux) + a `wss://`-reachable host to actually flow.
3. **Demolition commit** (§8) — after live wiring proves the new paths: delete MP3 upload / accumulator / perception_state integration / `transcript.data` branch.

Known non-blockers: pipeline.py uses the still-supported-but-deprecated Flux `params=`/`model=` and Cartesia `voice_id=` kwargs (removed in pipecat 2.0) — modernize to `settings=` during Phase 5 cleanup.

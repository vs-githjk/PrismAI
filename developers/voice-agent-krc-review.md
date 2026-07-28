# KRC review — realtime_routes.py inventory

Phase 1 of the voice-agent rebuild: every piece of the ~3,600-line live-meeting surface, with a verdict and the owner's ruling. Companion to [voice-agent-master.md](voice-agent-master.md) (which holds the compact table); this file keeps the full per-item notes and clarifications. HTML version: `claude.ai/code/artifact/80e5d0e6-26fa-44fa-a114-2aa1ef6341f1`.

**Verdicts:** keep = survives as-is (may re-home) · change = concept survives, implementation reworked · replace = new component takes the job · remove = deleted, nothing takes the job.
**Status:** ✓ approved · ⏳ awaiting ruling.

---

## A · Ingress — the ears today (1–5)

Today: Recall webhooks post transcript chunks, chat messages, and participant events to `/realtime-events`. Tomorrow: audio arrives as raw PCM over our WebSocket → Flux.

### 1 · Webhook endpoints + token auth — change ✓
The HTTP doors Recall knocks on, with a per-bot token check. Audio stops coming this way — but chat messages and participant join/leave events still arrive as webhooks. The door stays; it just stops receiving speech.
`/realtime-events`, `/realtime-events/{token}`, `register_realtime_token`, `_extract_bot_id_from_payload`, `_handle_realtime_payload` (~415 lines — the giant dispatcher)

### 2 · Utterance accumulator + plumbing — replace ✓
Rebuilds sentences from Recall's wire chunks (speaker change / pause / punctuation / max-length) with a tick loop for timeouts. Flux does this job semantically. The A/B compare mode and legacy-buffer simulation are experiment scaffolding — delete with it.
`_emit_utterance`, `_accumulator_tick_loop`, `_ensure_accumulator_tick_task`, `_accumulator_on`, `_accumulator_compare_on`, `_legacy_buffer_append_simulation`

### 3 · Pre-perception observability — remove ✓
Event-id dedup + partial-drop-ratio metrics for the *webhook* stream (`PRISM_PRE_PERCEPTION`). Measures a transport we're retiring. New PCM path gets simpler counters (frames received / gaps).

### 4 · Ingress rate limiter — change ✓
Caps webhook events at 50/sec per bot. A PCM WebSocket has a fixed byte rate — the guard becomes connection sanity + max concurrent sockets.
`_ingress_rate_ok`, `_INGRESS_MAX_PER_SEC`

### 5 · Participant roster + speaker hygiene — keep ✓
Who's in the room, how many are human, is this speaker the bot itself, name scrubbing. Feeds solo detection and the no-self-feedback guard. Source stays the participant webhooks.
`_human_participant_count`, `_note_human_count`, `_looks_like_bot_participant`, `_safe_speaker_name`, `_BOT_SELF_NAMES`

**Q1 ✓ DECIDED — HYBRID.** Pipecat owns the realtime audio loop (input transport + `RecallFrameSerializer` ~150–300 lines, Silero interruption, Flux + Cartesia services, output WS sink ~100–200 lines). The agent channel stays entirely outside — plain Python bridged by a queue; the visibility bus never touches the framework. Rationale: the currency is live-meeting debug iterations; hand-rolled realtime concurrency (barge-in cancellation, backpressure, races) is where those iterations concentrate, and Pipecat has them pre-debugged. Customizability that matters lives in our code either way. Blast radius if Pipecat must go: the audio loop only.

**Q2 ✓ DECIDED — yes.** Webhook ingress stays alive for chat + participant events; only speech moves to the PCM socket.

---

## B · Wake & engagement gating (6–11)

Everything deciding *whether the bot engages*. Destination: the one Auto/Manual gate (Phase 4).

### 6 · Wake-word machinery — change ✓
Regex patterns for "Prism…" + per-persona names (Flash, Echo…), command extraction, completeness heuristics. Survives as **Manual mode's trigger**.
**The 8s pending window explained:** patches "wake word and command arrive in separate fragments". Case 1 — bare *"Prism."* + pause: 8s window opens, same speaker's next utterance becomes the command. Case 2 — *"Prism, what do you think about—"* looks unfinished (no end punctuation, <6 words): stash, glue follow-up fragments until complete, or flush best-effort at 8s. Case 2 guesses "are they done?" from punctuation — exactly Flux's job, so it dies. Case 1 (name, pause, then ask) is real human behavior and survives.
`TRIGGER_PATTERN`, `_wake_patterns_for_alias/_bot`, `_detect_command`, `_has_trigger_word`, `_normalize_cmd`, `PENDING_TRIGGER_WINDOW`, `_looks_command_complete`

### 7 · Solo free-flow — change ✓
Today: a separate code path (own flag, own eligibility rules) bypassing the wake word when 1 human is detected. **"Absorbed" means:** it stops being a mechanism and becomes a *headcount signal into the Auto gate* — Auto + 1 human → every substantive utterance treated as addressed to the bot; Auto + several → the gate stays selective. **It does NOT switch modes:** Manual stays wake-word-only even in a 1-on-1. Auto is the default, so solo meetings behave like today out of the box.
`_solo_mode_active`, `_solo_freeflow_on/_eligible/_text_eligible`, `PRISM_SOLO_FREEFLOW`

### 8 · Ambient loop (consent funnel) — change ✓
The "want it?" question is the part that dies. Old: judge finds something → bot offers → waits for a yes → delivers. New: judge says "worth saying" → bot just says it. Judge survives, permission-middleman deleted.
`_ambient_on_utterance`, `_run_interject`, `_ambient_speak_offer`, `_ambient_run_delivery`, `_AMBIENT_PREAMBLE`, `_is_ambient_silent`

### 9 · Proactive checker + idea generation — change ✓
Today these watchers speak on their own authority. New: demoted to **proposers** — they drop candidates into the Auto gate ("commitment X is drifting", "idea: …") and the gate decides whether/when to voice them, respecting mode, mute, room state. One mouth, one decision-maker.
`_run_proactive_checker`, `_find_drifting_commitment`, `_fetch_historical_blockers`, `_maybe_generate_idea`, `_IDEA_SYSTEM_PROMPT`

### 10 · Command debounce → command queue — replace ✓ (owner's redesign)
The blind 3s window dies — it dropped legitimate rapid-fire commands ("make a design spec in Notion… and send the email to…"). New: commands **queue** on the agent channel, with a **tiered dedup** deciding "same command re-heard" vs "new command, same tool": exact/near-duplicate text within a couple seconds → string similarity, free; ambiguous cases → a small fast model referees. Flux end-of-turn removes the original double-fire cause.
`_COMMAND_DEBOUNCE_S` (deleted) → agent-channel queue + tiered dedup

### 11 · Mode + mute endpoints — keep ✓
`/bot/{id}/mode` becomes the Auto↔Manual toggle surface; `/bot/{id}/mute` stays the kill-switch, honored by both channels.

**Q3 ✓ DECIDED — reuse the ambient judge, tune later.** The judgment prompt already knows the shape of the problem (silence default, speak only when adding value). Future tuning/redesign logged in `docs/future-ideas.md`.

---

## C · The brain (12–18)

Today one fused LLM call picks tools AND writes the spoken reply. Phase 3 splits it: voice channel (talk, no tools) + agent channel (all tools) + visibility bus.

### 12 · `_process_command` — the 640-line core — change ✓
The fused brain: builds messages, calls the LLM with tools, loops on tool calls, finalizes, speaks + chats. Phase 3's whole job is splitting this into the two channels. Nothing deleted blindly — pieces re-home per the rows below.
`_process_command`, `_dispatch_command`, `_dispatch_slow_path_command`

### 13 · Prompt assembly + injection guard — change ✓ (with owner's condition)
Cached static prefix (persona, owner email, tool policy, style), participant-utterance wrapping against prompt injection, recent-turn history shaping. Splits in two: slim conversational prompt for voice, tool policy for agent.
**Owner's condition — zero ambiguity about which channel gets what.** Every prompt feature gets an *explicit documented home* in the build plan: voice, agent, or deliberately both. Duplication is fine; silent dropping or vague placement is not. A full dissection table is a required part of the Phase 3 build plan.
`_build_static_prefix`, `_STATIC_*`, `_wrap_participant_utterance`, `_build_command_messages`, `_recent_turn_messages`, `_owner_email_for_bot`, `_prompt_cache_on`, `_injection_guard_on`

### 14 · Tool-call recovery + leak scrubbing — keep ✓
Salvages malformed `<function=…>` tags, strips tools on tainted responses, scans streamed deltas so tag garbage never gets spoken. Recovery → agent channel; delta leak-scanner → voice channel.
`_parse_function_tags`, `_recover_tool_calls`, `_strip_tools_if_tainted`, `_extract_failed_generation`, `_find_matching_brace`, `_scan_delta_for_leak`

### 15 · Capability-block memory — keep ✓
Remembers "Gmail isn't connected" so dead tools aren't retried; terse repeats + cooldown. Agent channel; the bus surfaces blocks so the voice can *say* "Gmail's not connected" naturally.
`_CAP_*`, `_blocked_capability_for_command`, `_is_auth_failure`, `_capability_of`

### 16 · Owner-gate + owner-id lock — keep ✓
Side-effectful tools only obey the bot's owner; identity pinned by participant id. Safety-critical, re-homed untouched.

### 17 · Stand-in spoken updates — keep ✓
"Any updates from people who couldn't make it?" → deterministic regex → reads stand-in updates aloud, no LLM. Re-homes onto the voice channel's pre-LLM fast path.
`_STANDIN_QUERY_RE`, `_STANDIN_PERSON_RE`, `_updates_for_named`, `_standin_spoken_summary`

### 18 · Three-layer live memory — keep ✓
Rolling compressed summary + entity slots + recent window (`meeting_memory.py`), refreshed by `_compress_and_persist`. Transport-independent; both channels read it.

**Q4 ✓ DECIDED — Groq for the voice channel.** Tool-less conversational speed is Groq's strength and the provider is already in the stack; agent channel stays gpt-4o-mini (battle-tested tool calling). If Groq misbehaves, the owner flags it and we revisit.

---

## D · The mouth (19–23)

Today: TTS → MP3 → upload to Recall as a blob. Tomorrow: streaming Cartesia → Output Media web app.

### 19 · MP3 upload path + playback pacing — remove ✓
Discrete-blob audio with estimated-seconds pacing so overlapping blobs don't mix. Output Media makes the category obsolete.
`_upload_audio_to_recall`, `_estimate_play_seconds`, `_send_voice_response`

### 20 · Streaming voice groundwork — change ✓
The already-built streaming skeleton: LLM deltas → sentence segmenter → TTS dispatcher (`voice_pipeline.py`), flag-gated. Re-target output from MP3-upload to the Output Media WS and it becomes the production mouth.
**Owner's condition:** the re-target must be *faithful* — every feature of the original path carries over unless genuinely redundant/irrelevant for a streaming socket (e.g. play-time estimation). Change the destination, not the skeleton's behavior.
`_stream_llm_to_voice`, `_send_voice_response_streamed`, `_chunk_reply`, `StreamingSegmenter`, `TtsDispatcher`

### 21 · Speak-short / chat-full — keep ✓
Spoken copy condensed (~3 sentences; lists → "full breakdown in the chat"), full text to chat, URL/citation stripping. Stays as designed.
`_spoken_condense`, `_spoken_version`

### 22 · Politeness gate + barge-in — change ✓
1.2s transcript-silence wait before speaking (max 4s); SpeakingSession supersede/cancel on talk-over. Both re-implement against **real audio**: Silero speech-start for barge-in, PCM-level silence for the gap.
`_wait_for_speech_gap`, `_GAP_SILENCE_S`, `_GAP_MAX_WAIT_S`, `SpeakingSession`, `_barge_in_on`
**Current timing (reported):** polls every 200ms; speaks once >=1.2s since the last transcript segment (`PRISM_GAP_SILENCE_S`), hard cap 4.0s (`PRISM_GAP_MAX_WAIT_S`), instant bail on cancel, kill-switch `PRISM_GAP_WAIT=0`. Weakness: silence judged on lagged transcript timestamps — the PCM version measures real audio silence. Same knobs carry over; observed timings to be reported after the rebuild.

### 23 · Chat responder — keep ✓
Posts into meeting chat via Recall. More important now: the ack surface ("on it…") + full-reply surface.
`_send_chat_response`

**Q5 ✓ DECIDED — delete the MP3 path outright in Phase 2.** The work lives on the `voice-agent` branch; git is the fallback (revert / switch branch), no runtime flag.

---

## E · Side surfaces & lifecycle (24–28)

### 24 · Transcript recording — keep ✓
Append-only durable transcript: human utterances, human chat lines, bot replies, interleaved, throttle-persisted. Only the human-speech source changes (Flux instead of webhooks).
`_append_realtime_line`, `_record_bot_line`, `_record_human_chat_line`, `_maybe_persist_transcript`

### 25 · Live catch-up ("Ask Prism, just you") — keep ✓
Private SSE catch-up/QA from memory + last 30 lines, token-gated, rate-limited. Untouched.
`stream_catchup_answer`, `_build_catchup_context`, `_catchup_rate_ok`

### 26 · Settings + persona cache — keep ✓
Per-bot settings with TTL cache, persona/wake-alias population, invalidation. The gate reads the same settings.
`_get_settings_for_bot`, `_invalidate_bot_settings_cache`

### 27 · Bot state lifecycle — change ✓
The big per-bot state dict + init/teardown. Restructure deliberately: accumulator fields out; Flux session + channel/bus state in.
`_get_bot_state`, `init_bot_realtime`, `cleanup_bot_state`

### 28 · Experiment feature flags — remove ✓
Flags that gated experiments now becoming the architecture (streamed-TTS/LLM, accumulator, compare, pre-perception). Keep only operational switches (mute, mode defaults, barge-in kill-switch).

**Q6 ✓ DECIDED — per-phase deletion.** A flag whose "off" branch no longer works is worse than no flag.

---

## Scoreboard

**REVIEW COMPLETE (2026-07-15).** All 28 items approved (11 keep · 12 change · 2 replace · 3 remove), all 6 questions decided. The rewrite is ears and mouth, not brain and memory. Next: the phase-wise build plan.

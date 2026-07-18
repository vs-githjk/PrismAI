# Phase 3 — The two-channel brain

Goal: kill the fused `_process_command` shape. Voice channel (Groq, streaming, ZERO tools) talks; agent channel (gpt-4o-mini, ALL tools) works; a queue + visibility bus connects them. Chat acks replace spoken filler. (KRC items 10, 12–18, 23; forks ②③; Q3, Q4.)

## 1. New modules

```
backend/voice/
  voice_channel.py   # Pipecat processor: Flux turns → gate check (Phase-2 legacy logic until Phase 4) → streaming Groq reply → TTS
  agent_channel.py   # plain asyncio worker OUTSIDE Pipecat: consumes the command queue, runs the tool loop
  bus.py             # command queue (tiered dedup) + status events (dispatched/running/done/blocked) + results
  prompts.py         # BOTH channels' prompt assembly — the single home for the dissection table below
```

`bridge.py` from Phase 2 is deleted; `voice_channel.py` takes its place inside the pipeline. The agent channel is a plain task — it never enters Pipecat (Q1 hybrid, the load-bearing property).

## 2. Channel contracts

**Voice channel** (Groq — start `llama-3.3-70b-versatile` for parity with the rest of the repo; drop to a smaller/faster Groq model if TTFT disappoints — Q4):
- Streams conversational replies sentence-by-sentence into TTS.
- Detects "this needs a tool" → posts a command to the bus, keeps talking or yields. NEVER calls tools itself.
- Pre-LLM deterministic fast path: stand-in updates query (item 17) answered without any model.
- Narrates bus events: on `done` → speak/condense the result; on `blocked` (capability-block, item 15) → say "Gmail isn't connected" naturally.
- Leak scanner (`_scan_delta_for_leak`) runs on its stream.

**Agent channel** (gpt-4o-mini, today's tool loop re-homed — item 12):
- Consumes the queue serially (or small worker pool later — start serial, simplest correct thing).
- Owner-gate + owner-id lock enforced here (item 16) — side-effect tools only obey the owner.
- Tool-call recovery (`_parse_function_tags`, `_recover_tool_calls`, `_strip_tools_if_tainted`) — item 14.
- Capability-block memory (item 15) lives here; emits `blocked` events to the bus.
- Emits `dispatched` / `running` / `done(result)` / `error` events.

**Bus** (`bus.py`):
- Command queue with **tiered dedup** (item 10, owner's design): tier 1 — normalized string similarity (difflib ratio ≥ ~0.85) within a ~3s window = same command re-heard, drop; tier 2 — ambiguous cases go to a small fast model (Groq 8B-class, one yes/no: "same request or a new request?"). Distinct requests both run, in order.
- Status events consumed by: voice channel (narration), chat-ack logic, live-share payload (later).

**Chat acks** (item 23, fork ③): on `dispatched`, start a 1.5s timer; if not `done` by then, post "⏳ on it — ‹short command echo›" via `_send_chat_response`. `done` always posts the full result to chat (speak-short/chat-full unchanged). No spoken filler ever.

## 3. Prompt dissection table (item 13 — owner's required condition)

Every prompt feature gets an explicit home. **Both** = deliberately duplicated, possibly in different form. Nothing is silently dropped.

| Feature (today) | Voice channel | Agent channel | Notes |
|---|---|---|---|
| `_STATIC_PERSONA` (identity, persona name/tone) | ✅ full | ✅ slim | Voice needs the character; agent needs name/owner facts for artifacts (emails sign as owner, not bot) |
| `_STATIC_STYLE` ("spoken aloud, ≤3 sentences") | ✅ (relaxed — speak-short/chat-full handles length) | ❌ | Style is a mouth concern |
| `_STATIC_TOOL_POLICY` | ❌ (replaced by "you have NO tools; to act, dispatch — describe the request") | ✅ full | The core of the split |
| `_STATIC_GMAIL_ON/OFF`, `_STATIC_CALENDAR_ON/OFF` (capability availability) | ✅ one-line awareness summary (answer "can you email?" without dispatching) | ✅ authoritative | Both, deliberately — different fidelity |
| Owner email injection (`_owner_email_for_bot`) | ✅ (can say it) | ✅ (tool args; placeholder-domain rejection stays in `tools/gmail.py`) | Both |
| `_wrap_participant_utterance` (injection guard) | ✅ | ✅ | EVERY LLM that sees participant text wraps it. Non-negotiable |
| `_recent_turn_messages` (history shaping) | ✅ full conversational window | ✅ slimmer: the triggering command + minimal context | Voice is a conversation; agent is a job runner |
| Memory snapshot (`meeting_memory`) | ✅ | ✅ | Shared read, item 18 |
| Static-prefix caching (`_build_static_prefix`) | ✅ per-channel prefix, cached | ✅ per-channel prefix, cached | Two prefixes, same caching pattern |
| Solo/ambient preamble text | migrates into the gate prompt (Phase 4) | ❌ | Interim: carried in voice prefix |
| Capability-block terse responses (`_CAP_TERSE`) | ✅ (narration source) | ✅ (block detection) | Split roles |

Build order enforces this: `prompts.py` is written first, reviewed against this table, then the channels consume it.

## 4. What `_process_command` becomes

Its ~640 lines dissolve: message-building → `prompts.py`; tool loop + recovery + owner-gate + capability-block → `agent_channel.py`; reply finalization + speak/chat delivery → `voice_channel.py` + bus consumers; stand-in regex path → voice pre-LLM. `_dispatch_command` / `_dispatch_slow_path_command` are replaced by bus posts. Nothing else in the repo calls `_process_command` when this lands (grep-verified at build time).

## 5. Demolition (final commit)

- `_process_command`, `_dispatch_command`, `_dispatch_slow_path_command`, `bridge.py`.
- `_COMMAND_DEBOUNCE_S` (item 10 — the queue replaced it).
- Any Phase-2 shim config. Flags obsoleted this phase die here (Q6).

## Exit criteria

Voice replies stream via Groq with no tools in that call path; a spoken "send the summary to X" produces: chat ack (if >1.5s) → background tool run → chat full result → spoken narration. Dedup drops a re-heard command but runs two distinct rapid-fire commands. Owner-gate + capability-block behavior identical to today. Prompt table verified feature-by-feature against `prompts.py`.

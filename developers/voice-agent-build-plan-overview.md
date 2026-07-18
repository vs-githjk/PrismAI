# Build plan — overview

Companion docs: [phase 2](voice-agent-build-plan-phase2.md) · [phase 3](voice-agent-build-plan-phase3.md) · [phase 4](voice-agent-build-plan-phase4.md) · [phase 5](voice-agent-build-plan-phase5.md). Decisions backing every step: [voice-agent-master.md](voice-agent-master.md) + [voice-agent-krc-review.md](voice-agent-krc-review.md).

## Workflow (owner's rule)

Continuous build, not test-gated: the agent implements phase N end-to-end, the owner fixes/flags errors, then feeds phase N+1. Real testing happens on the whole system after Phase 5 — there is no meaningful midway test point (Phase 2 alone produces a bot with new ears/mouth but the old brain glued in; it runs, but the product moment is the full stack). Each phase ends with its own demolition commit (Q6: flags/paths obsoleted by that phase die in that phase).

## Phase map

| Phase | Doc | One-liner | Exit criteria |
|---|---|---|---|
| 2 | [phase2](voice-agent-build-plan-phase2.md) | Transport swap: PCM in → Flux, Output Media page out, MP3 path deleted, stopwatch t0–t4 | Bot joins a meeting, hears via Flux, speaks via Output Media, old brain still answers; timings logged per turn |
| 3 | [phase3](voice-agent-build-plan-phase3.md) | Split the brain: voice channel (Groq, tool-less) ∥ agent channel (tools) + queue/bus + chat acks. Includes the required prompt-dissection table | Voice replies stream; tools run queued in background; acks in chat; results narrated |
| 4 | [phase4](voice-agent-build-plan-phase4.md) | One engagement gate: Auto/Manual toggle; ambient/solo/proactive collapse into it | Two modes only; watchers propose, the gate speaks; consent funnel gone |
| 5 | [phase5](voice-agent-build-plan-phase5.md) | Feel tuning: real-audio barge-in, gaps, backchannel tolerance, voice | Knobs exposed + Curio-seeded defaults; owner-driven iteration |

## The key stop (the one planned pause in the continuous build)

The build does NOT block on keys up front. Phase 2 starts immediately and builds everything that doesn't need live credentials (package layout, serializer, pipeline code, speaker page, stopwatch, payload changes). Then it hits the **KEY STOP** — a deliberate halt where the agent posts the exact checklist below and waits for the owner to create the keys with proper configuration. Once the owner says "keys are in", the build resumes and runs continuously through Phase 5 with no further planned stops (errors excepted).

At the stop, the owner supplies (into `backend/.env`, names exactly as listed):

- [ ] `DEEPGRAM_API_KEY` — **with Flux access confirmed enabled** on the key (dashboard check; the ears design depends on it).
- [ ] `CARTESIA_API_KEY` + `CARTESIA_VOICE_ID` (any voice to start — final voice is picked in Phase 5).
- [ ] **Recall account: Output Media enabled** (can be plan-gated — confirm in the Recall dashboard; no key, just confirmation).
- [ ] Backend host reachable via **wss://** (Render provides TLS; local dev needs a tunnel for Recall→us WS).
- [ ] Render region noted vs Recall's `us-west-2` — colocate when possible (core decision #8).

## New dependencies (Phase 2 installs)

`pipecat-ai` with Deepgram + Cartesia + Silero extras (exact extras syntax confirmed against current Pipecat docs at build time via context7). Silero VAD weights vendor via pipecat. No frontend deps.

## Conventions

- All work on the `voice-agent` branch; git is the rollback story (Q5) — no legacy runtime flags.
- New code lives in `backend/voice/` (new package) — `realtime_routes.py` shrinks each phase rather than growing.
- Exact Recall/Pipecat field names marked ⚠ in the phase docs are verified against live docs (context7 / Recall API reference) at build time, not trusted from memory.
- Every phase doc ends with its demolition list. Deletions happen in that phase's final commit.

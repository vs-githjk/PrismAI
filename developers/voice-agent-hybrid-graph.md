# Hybrid architecture — who owns what

One conversational turn through the hybrid design (Q1 decision). Boundaries = ownership. HTML/SVG version: `claude.ai/code/artifact/49ac712d-64e6-494d-8c4f-06ae1a16e55d`.

```mermaid
flowchart TB
    subgraph MEETING["THE MEETING — Google Meet / Zoom"]
        HS[Human speaks]
        BV[Bot's voice heard]
    end

    subgraph RECALL["RECALL'S INFRA — vendor, untouched"]
        RB["Bot in the call<br/>(headless Chrome, WebRTC leg)"]
        OM["Output Media renderer<br/>(renders OUR web page,<br/>mixes its audio into the call)"]
        WH["Webhooks: chat messages +<br/>participant join/leave"]
    end

    subgraph PIPECAT["PIPECAT — framework runs the realtime loop"]
        IT["Input transport<br/>(+ RecallFrameSerializer — OURS)"]
        VAD["Silero VAD (local, ms)<br/>'someone started talking'"]
        FLUX["Deepgram Flux ☁<br/>STT + semantic end-of-turn"]
        VC["VOICE CHANNEL — OURS, hosted here<br/>Auto/Manual gate · ambient judge ·<br/>Groq LLM ☁ · zero tools"]
        TTS["Cartesia TTS ☁ (streaming)"]
        OS["Output WS sink — OURS"]
    end

    subgraph BACKEND["MY BACKEND — plain Python, outside the framework"]
        QB["Command queue + visibility bus<br/>(dispatched/running/done · tiered dedup)"]
        AC["AGENT CHANNEL — all tools ☁<br/>(today's tool loop, re-homed)"]
        TM["Tools · memory · RAG · personas"]
        CH["Chat acks + full replies → Recall chat API"]
        RS["Roster + state<br/>(headcount · owner-gate · mute · settings)"]
    end

    HS -->|WebRTC| RB
    RB -->|WS raw PCM 16kHz| IT
    IT --> VAD & FLUX
    FLUX -->|complete turns| VC
    VAD -.->|interrupt!| VC
    VC -->|sentences| TTS --> OS
    OS -->|WS audio frames| OM
    OM -->|WebRTC| BV
    WH -->|HTTPS| RS
    RS -.->|feeds gate| VC
    VC <-.->|dispatch / status| QB
    QB --> AC --> TM
    AC --> CH
```

## Legend

| Marker | Meaning |
|---|---|
| MEETING | The call itself (Google Meet / Zoom) |
| RECALL | Vendor infra — untouched by us |
| PIPECAT | Framework — runs the realtime loop only |
| BACKEND | Ours — plain Python, outside the framework |
| "OURS, hosted here" | Our Python files that Pipecat merely schedules (serializer, voice-channel processor, output sink) |
| ☁ | External cloud service (Deepgram, Cartesia, Groq/OpenAI) |
| dashed arrows | Control/state signals (interrupt, gate inputs, queue/bus) — not audio |

## How to read it

- **Pipecat owns the loop, not the logic.** Its box is plumbing: moving audio frames, running VAD, calling Flux/Cartesia, killing TTS on barge-in. Zero product decisions live there.
- **Everything "OURS" is editable without touching the framework** — the gate, the channels, the tools, plus the thin web page Recall's Output Media renders (~100 lines: WS + audio element).
- **The agent channel never enters the framework.** Voice ↔ agent talk only through the queue/visibility bus. If Pipecat ever has to go, the blast radius is its box only.
- **WebRTC is entirely inside the meeting + Recall** — we never touch it. Our two hops (PCM in, audio frames out) are plain WebSockets.

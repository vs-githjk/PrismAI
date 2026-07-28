"""Voice agent (Phase 2+): the real-time audio loop.

Ears (raw PCM from Recall → Deepgram Flux) and mouth (Cartesia → Recall Output
Media) run inside a per-bot Pipecat pipeline. The agent/tool brain stays outside
this package (plain Python in realtime_routes) and is bridged in by `bridge.py`.

See developers/voice-agent-build-plan-phase2.md for the file-by-file spec and
developers/voice-agent-master.md for the locked decisions.
"""

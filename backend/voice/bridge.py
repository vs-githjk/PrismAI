"""Phase-2 brain glue: the new ears/mouth talk to the OLD brain, unchanged.

Two directions, both intentionally thin — this shim exists only so Phase 2 ships a
working bot while the transport is swapped. Phase 3 replaces it with the two-channel
split (voice channel + agent channel + command queue/visibility bus).

  ears → brain
    Flux `EndOfTurn` gives a finished, semantically-complete utterance. `make_on_final`
    reshapes it into the SAME `transcript.data`-shaped payload the live dispatcher
    (`realtime_routes._handle_realtime_payload`) already parses, with `verified_bot_id`
    set. Every existing behaviour runs untouched — dedup, three-layer memory, wake-word
    detection, solo free-flow, command dispatch. Flux is simply a new PRODUCER of
    finished utterances, replacing the retired `transcript.data` webhook + utterance
    accumulator. (words=[] → the handler uses `segment["text"]` verbatim, so Flux's full
    turn text flows through unmodified; participant.name carries the speaker for
    transcript attribution + the name-based owner gate.)

  brain → mouth
    `speak(bot_id, text)` renders a reply through the bot's live voice pipeline
    (Cartesia → speaker page). Defined here so the live-wiring step in `realtime_routes`
    (re-pointing its reply emission off the MP3 path) is a one-line call. Returns False
    when no pipeline is attached, so the caller can fall back to its existing path.

See developers/voice-agent-build-plan-phase2.md §5 (the bridge) and §8 (demolition).
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

# ponytail: Flux only gives us a speaker NAME (serializer.last_speaker /
# transport_source), not Recall's stable participant id. The name-based owner gate
# (_is_owner_speaker) still works; the id-based owner LOCK (PRISM_OWNER_ID_LOCK, a
# flag-gated hardening, default off) degrades to no-op. Thread an id through
# OnFinalTranscript only if that lock is turned on for voice-agent bots.


def make_on_final(bot_id: str) -> Callable[[str, str, str], Awaitable[None]]:
    """Build the per-bot EndOfTurn callback the pipeline's TranscriptCapture fires."""

    async def on_final(text: str, speaker: str, ts: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        speaker = (speaker or "").strip() or "Speaker"
        payload = {
            "event": "transcript.data",
            "data": {
                "data": {
                    "speaker": speaker,
                    "text": text,
                    "words": [],  # empty → handler falls back to segment["text"]
                    "participant": {"name": speaker, "id": None},
                    "_flux": True,  # provenance marker (debug/log only)
                }
            },
        }
        # Lazy import: realtime_routes pulls in the whole live stack; keep it out of
        # module import so `voice` stays lightweight to import (and cycle-free).
        from realtime_routes import _handle_realtime_payload

        await _handle_realtime_payload(payload, verified_bot_id=bot_id)

    return on_final


async def speak(bot_id: str, text: str, turn=None) -> bool:
    """Render `text` through the bot's live voice pipeline (mouth). Returns False if
    no pipeline is attached — the caller then uses its own reply path."""
    text = (text or "").strip()
    if not text:
        return False
    from voice.audio_routes import get_session

    session = get_session(bot_id)
    if session is None or session.pipeline is None:
        return False
    if turn is None:
        # Claim the turn the ears opened at EndOfTurn, so t0→t4 is one real timeline.
        # Nothing to claim + an utterance already rendering ⇒ this is a later chunk of a
        # streamed reply: leave the running stopwatch alone. Nothing to claim and nothing
        # rendering ⇒ an unprompted utterance (a nudge): mint one so the mix-hop line,
        # the number the owner watches, still fires.
        from voice import stopwatch as _sw
        turn = _sw.take_turn(bot_id)
        if turn is None and not session.pipeline.has_open_turn:
            import time
            turn = _sw.TurnStopwatch(bot_id, f"t{int(time.time() * 1000)}")
    # The mouth is committed from here, not from the first audio byte — see
    # RoomAudio.note_speak_queued (Phase 5 §2).
    session.pipeline.room.note_speak_queued()
    await session.pipeline.speak(text, turn=turn)
    return True

"""RecallFrameSerializer — Recall audio WS frames → Pipecat audio frames.

Recall streams **separate raw audio per participant** to our `/voice/audio-in/{token}`
WebSocket (config: `recording_config.audio_separate_raw = {}` +
`realtime_endpoints[type=websocket, events=["audio_separate_raw.data"]]`). Each frame
is a JSON text message:

    {
      "event": "audio_separate_raw.data",
      "data": {
        "data": {
          "buffer": "<base64 16kHz mono s16le PCM>",
          "timestamp": {"absolute": "<iso>", "relative": <float>},
          "participant": {"id": <int>, "name": <str|null>, "is_host": <bool>, ...}
        },
        ...
      }
    }

We decode `buffer` → PCM bytes → `InputAudioRawFrame` and tag it with the speaking
participant so downstream (bridge/transcript) can attribute Flux's output. Separate
(not mixed) audio is chosen precisely for this speaker identity — it replaces the
diarization the retired `transcript.data` webhook used to give us.

The bot's own audio (its Output-Media TTS, re-captured as a participant) is filtered
here so Flux never transcribes the bot talking to itself — reusing the same
`_looks_like_bot_participant` heuristic the rest of the app trusts.

Direction: this socket is INPUT ONLY. Recall does not consume audio from us here
(output goes out via the Output-Media speaker page), so `serialize()` is a no-op.
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from pipecat.frames.frames import Frame, InputAudioRawFrame, StartFrame
from pipecat.serializers.base_serializer import FrameSerializer

# Recall separate-raw audio format (documented, fixed).
_SAMPLE_RATE = 16000
_NUM_CHANNELS = 1
_AUDIO_EVENT = "audio_separate_raw.data"


class RecallFrameSerializer(FrameSerializer):
    """One instance per bot pipeline. Stateless except for the last-seen speaker,
    which the bridge reads to attribute a finished Flux turn."""

    def __init__(self, bot_id: str):
        super().__init__()
        self._bot_id = bot_id
        # Name of the participant whose audio we most recently admitted. The bridge
        # reads this when Flux emits EndOfTurn to attribute the utterance. In a
        # turn-based meeting one person speaks at a time, so "last admitted speaker"
        # is a faithful proxy; overlapping speech is a Phase-5 tuning concern.
        self.last_speaker: str = ""

    async def setup(self, frame: StartFrame) -> None:
        # No handshake with Recall — the socket is already open when frames arrive.
        return None

    async def serialize(self, frame: Frame) -> str | bytes | None:
        # Input-only socket: nothing is ever sent back to Recall here.
        return None

    async def deserialize(self, data: str | bytes) -> Optional[Frame]:
        try:
            msg = json.loads(data)
        except (ValueError, TypeError):
            return None  # protocol garbage — drop silently (guard logs the count)

        if msg.get("event") != _AUDIO_EVENT:
            return None

        inner = ((msg.get("data") or {}).get("data")) or {}
        b64 = inner.get("buffer")
        if not b64:
            return None

        participant = inner.get("participant") or {}
        speaker = (participant.get("name") or "").strip()

        # Never hear ourselves: the bot's Output-Media audio can come back as a
        # participant stream. Same heuristic the rest of the app uses.
        if _is_bot_participant(speaker, participant):
            return None

        try:
            pcm = base64.b64decode(b64)
        except (ValueError, TypeError):
            return None
        if not pcm:
            return None

        if speaker:
            self.last_speaker = speaker

        frame = InputAudioRawFrame(
            audio=pcm,
            sample_rate=_SAMPLE_RATE,
            num_channels=_NUM_CHANNELS,
        )
        # Attach speaker identity for downstream attribution. `transport_source` is
        # Pipecat's per-frame source tag; if the field name drifts across versions
        # the bridge falls back to serializer.last_speaker.  ⚠ verify at wire time.
        try:
            frame.transport_source = speaker or None
        except Exception:
            pass
        return frame


def _is_bot_participant(name: str, raw: dict) -> bool:
    """Reuse realtime_routes' bot-self detection so this stays in lockstep with the
    persona names / is_bot flags the rest of the app already knows about. Imported
    lazily to avoid a heavy import at module load (realtime_routes pulls in the
    whole live stack)."""
    try:
        from realtime_routes import _looks_like_bot_participant
        return _looks_like_bot_participant(name, raw)
    except Exception:
        # Conservative fallback: only obvious self-names, never over-filter humans.
        n = (name or "").lower()
        return n in ("prism", "prismai") or "(prismai stand-in)" in n

"""One Pipecat pipeline per live bot — the realtime audio loop.

    Recall audio WS ──▶ transport.input() ──▶ Flux STT ──▶ TranscriptCapture ──▶ …
                        (RecallFrameSerializer)   (EndOfTurn)   (→ bridge → brain)
    … ──▶ Cartesia TTS ──▶ SpeakerSink ──▶ speaker WS ──▶ Recall Output Media ──▶ call

Two sockets, not one: input is the Recall audio WS (handled by
`FastAPIWebsocketTransport` + our serializer); output is the *separate* speaker-page
WS, driven by a custom `SpeakerSink` (NOT `transport.output()`, which would write back
to Recall's input socket). `audio_out_enabled=False` on the transport keeps it silent.

Phase 2 keeps the OLD brain: `TranscriptCapture` hands each finished turn to
`voice.bridge`, which runs today's dispatch path. Replies come back as
`TTSSpeakFrame`s queued onto the task (`VoicePipeline.speak`) → Cartesia → speaker.
There is no LLM/aggregator inside this pipeline in Phase 2 — the brain split is Phase 3.

⚠ Barge-in: Phase 2 relies on Flux's built-in interruption (`should_interrupt`).
Dedicated Silero speech-start barge-in + politeness-gap re-tuning is Phase 5 (item 22).
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Optional

from starlette.websockets import WebSocket

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice.serializer import RecallFrameSerializer
from voice.speaker_page import SPEAKER_SAMPLE_RATE

# Recall separate-raw audio is 16kHz mono s16le.
_INPUT_SAMPLE_RATE = 16000

# Flux tuning (ported from Curio's tuning.py; env-overridable). Semantic end-of-turn
# is the difference between "cuts you off" and "snappy" — see the master doc §5.
_FLUX_MODEL = os.getenv("PRISM_FLUX_MODEL", "flux-general-en")
_FLUX_EOT_THRESHOLD = float(os.getenv("PRISM_FLUX_EOT_THRESHOLD", "0.7"))
_FLUX_EOT_TIMEOUT_MS = int(os.getenv("PRISM_FLUX_EOT_TIMEOUT_MS", "5000"))
_FLUX_EAGER_EOT = os.getenv("PRISM_FLUX_EAGER_EOT_THRESHOLD")  # None disables

# Cartesia TTS (voice id is a KEY-STOP item — no default; empty until the owner sets it).
_TTS_MODEL = os.getenv("PRISM_TTS_MODEL", "sonic-3")
_TTS_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")

# Callback the bridge registers: (bot_id, text, speaker, timestamp) on each finished turn.
OnFinalTranscript = Callable[[str, str, str, str], Awaitable[None]]


class SpeakerConnection:
    """Late-bindable holder for the speaker-page WebSocket. The audio-in socket and
    the speaker socket connect independently and in any order, so the pipeline is
    built when audio-in arrives and the speaker WS attaches whenever it shows up.
    Audio sent while no speaker is attached is dropped (the page reconnects and the
    next utterance plays) — never buffered unbounded."""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._ws: Optional[WebSocket] = None
        # Last control pings from the page — consumed by the stopwatch RTT loop at
        # live time (t4 send-side proxy + real-playout close). Stashed, not acted on.
        self.last_playout: Optional[dict] = None
        self.last_pong: Optional[dict] = None

    def attach(self, ws: WebSocket) -> None:
        self._ws = ws

    def on_control(self, msg: dict) -> None:
        """Handle a JSON control frame from the speaker page ({"type": ...})."""
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "playout":
            self.last_playout = msg
        elif kind == "pong":
            self.last_pong = msg

    def detach(self, ws: WebSocket) -> None:
        if self._ws is ws:
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def send_pcm(self, pcm: bytes) -> None:
        ws = self._ws
        if ws is None or not pcm:
            return
        try:
            await ws.send_bytes(pcm)
        except Exception:
            # Page went away mid-utterance; drop and let it reconnect.
            self._ws = None

    async def send_json(self, obj: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send_json(obj)
        except Exception:
            self._ws = None


class TranscriptCapture(FrameProcessor):
    """Observer at the STT tail: every finalized Flux turn (EndOfTurn) is handed to
    the bridge. Passes all frames through untouched — it's a tap, not a gate."""

    def __init__(self, bot_id: str, serializer: RecallFrameSerializer,
                 on_final: OnFinalTranscript):
        super().__init__()
        self._bot_id = bot_id
        self._serializer = serializer
        self._on_final = on_final

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            # Flux emits interim + final; act only on finalized turns.
            if text and getattr(frame, "finalized", True):
                speaker = (getattr(frame, "transport_source", None)
                           or getattr(frame, "user_id", None)
                           or self._serializer.last_speaker or "")
                ts = getattr(frame, "timestamp", "") or ""
                # Fire-and-forget: the brain must never stall the audio pipeline.
                asyncio.create_task(self._on_final(text, speaker, ts))
        await self.push_frame(frame, direction)


class SpeakerSink(FrameProcessor):
    """Pipeline tail: forwards Cartesia's raw PCM out the speaker WS and stamps the
    mix-hop stopwatch markers (t3 first TTS byte, t4 first frame sent)."""

    def __init__(self, connection: SpeakerConnection):
        super().__init__()
        self._conn = connection
        self._turn = None  # current TurnStopwatch, set by VoicePipeline.speak

    def set_turn(self, turn) -> None:
        self._turn = turn

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            turn = self._turn
            if turn is not None:
                turn.mark("t3")  # first TTS byte in hand (idempotent — first wins)
            await self._conn.send_pcm(frame.audio)
            if turn is not None:
                turn.mark("t4")  # first frame handed to the speaker page
        elif isinstance(frame, TTSStoppedFrame):
            # Utterance finished: close the stopwatch (logs JSONL + the LOUD t3→t4
            # mix-hop line) and tell the page to reset its utterance state.
            turn = self._turn
            if turn is not None:
                turn.finish()
                self._turn = None
            await self._conn.send_json({"type": "flush"})
        await self.push_frame(frame, direction)


class VoicePipeline:
    """Owns the per-bot transport + services + task lifecycle."""

    def __init__(self, bot_id: str, recall_ws: WebSocket,
                 connection: SpeakerConnection, on_final: OnFinalTranscript,
                 keyterms: Optional[list[str]] = None):
        self.bot_id = bot_id
        self._connection = connection
        self._serializer = RecallFrameSerializer(bot_id)

        transport = FastAPIWebsocketTransport(
            websocket=recall_ws,
            params=FastAPIWebsocketParams(
                serializer=self._serializer,
                audio_in_enabled=True,
                audio_in_sample_rate=_INPUT_SAMPLE_RATE,
                audio_out_enabled=False,   # output goes out the separate speaker WS
                add_wav_header=False,
            ),
        )

        stt = DeepgramFluxSTTService(
            api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            sample_rate=_INPUT_SAMPLE_RATE,
            should_interrupt=True,  # basic barge-in; Silero refinement is Phase 5
            settings=DeepgramFluxSTTService.Settings(
                model=_FLUX_MODEL,
                eot_threshold=_FLUX_EOT_THRESHOLD,
                eot_timeout_ms=_FLUX_EOT_TIMEOUT_MS,
                eager_eot_threshold=(float(_FLUX_EAGER_EOT) if _FLUX_EAGER_EOT else None),
                # Flux DOES support keyterm prompting — thread the app's grounding list in.
                keyterm=list(keyterms or []),
            ),
        )

        tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY", ""),
            sample_rate=SPEAKER_SAMPLE_RATE,  # so the sink can forward PCM as-is
            encoding="pcm_s16le",
            container="raw",
            settings=CartesiaTTSService.Settings(
                voice=_TTS_VOICE_ID or None,
                model=_TTS_MODEL,
            ),
        )

        self._sink = SpeakerSink(connection)
        self._capture = TranscriptCapture(bot_id, self._serializer, on_final)

        pipeline = Pipeline([
            transport.input(),   # Recall audio WS → InputAudioRawFrame
            stt,                 # Deepgram Flux (STT + semantic EOT)
            self._capture,       # EndOfTurn → bridge (old brain)
            tts,                 # Cartesia (fed by queued TTSSpeakFrame)
            self._sink,          # → speaker WS
        ])
        self._task = PipelineTask(pipeline)
        self._runner = PipelineRunner(handle_sigint=False)

    async def run(self) -> None:
        """Drive the pipeline until the Recall audio socket closes. Awaited by the
        /voice/audio-in route so the WS handler stays open for the socket's lifetime."""
        await self._runner.run(self._task)

    async def speak(self, text: str, turn=None) -> None:
        """Render `text` out the mouth. `turn` (a TurnStopwatch) receives t3/t4."""
        if turn is not None:
            self._sink.set_turn(turn)
        await self._task.queue_frame(TTSSpeakFrame(text))

    async def stop(self) -> None:
        # run() awaits the runner directly, so cancelling the task ends the pipeline
        # and unblocks run() — no separate run-task handle to tear down.
        try:
            await self._task.cancel()
        except Exception:
            pass

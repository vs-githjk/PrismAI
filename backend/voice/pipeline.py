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

Phase 5 adds the feel layer (see `voice/tuning.py` for every knob):
  · Silero VAD + `BargeInGate` between the transport and Flux — duration-gated barge-in
    (fork ④: Silero owns "someone started talking over us", Flux owns "did they finish?").
    Flux's own `should_interrupt` is therefore OFF whenever Silero is available; it stays
    on as the fallback when onnxruntime is missing, so nothing regresses.
  · Cartesia speed/volume/emotion knobs.
  · EagerEndOfTurn / TurnResumed wired to the voice channel's speculative call (§3) —
    dormant until `PRISM_FLUX_EAGER_EOT_THRESHOLD` is set, which is Flux's own default.
"""

from __future__ import annotations

import asyncio
import os
from typing import Awaitable, Callable, Optional

from starlette.websockets import WebSocket

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from voice import barge, stopwatch, tuning
from voice.barge import BargeInGate, RoomAudio
from voice.serializer import RecallFrameSerializer
from voice.speaker_page import SPEAKER_SAMPLE_RATE

# Recall separate-raw audio is 16kHz mono s16le (also one of Silero's two supported rates).
_INPUT_SAMPLE_RATE = 16000

# Callback the bridge registers: (bot_id, text, speaker, timestamp) on each finished turn.
OnFinalTranscript = Callable[[str, str, str, str], Awaitable[None]]


def _make_vad():
    """Silero VAD analyzer, or None when it can't load. onnxruntime has no wheels on some
    Python versions (3.14 dev boxes); prod pins 3.11 in render.yaml. Returning None is a
    real degradation path, not an error: the pipeline falls back to Flux interruption and
    the politeness gap falls back to transcript timestamps."""
    if not tuning.BARGE_IN_ENABLED:
        return None
    try:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.audio.vad.vad_analyzer import VADParams

        return SileroVADAnalyzer(
            sample_rate=_INPUT_SAMPLE_RATE,
            params=VADParams(
                confidence=tuning.VAD_CONFIDENCE,
                start_secs=tuning.VAD_START_SECS,
                stop_secs=tuning.VAD_STOP_SECS,
                min_volume=tuning.VAD_MIN_VOLUME,
            ),
        )
    except Exception as exc:
        print(f"[voice-barge] Silero VAD unavailable ({exc}) — falling back to Flux "
              f"interruption; barge-in has no backchannel tolerance and the politeness "
              f"gap reads transcript timestamps")
        return None


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
                # Start this turn's stopwatch here: t0/t1 (speech end + transcript) are
                # the same instant on Flux, and the mouth claims the turn when it speaks.
                stopwatch.open_turn(self._bot_id, {"speaker": speaker[:24]})
                # Late interrupt (§1): a burst too short to trip the duration gate, whose
                # words turn out to be substantive, is a real interjection after all.
                asyncio.create_task(barge.late_interrupt(self._bot_id, text))
                # Fire-and-forget: the brain must never stall the audio pipeline.
                asyncio.create_task(self._on_final(text, speaker, ts))
        await self.push_frame(frame, direction)


class SpeakerSink(FrameProcessor):
    """Pipeline tail: forwards Cartesia's raw PCM out the speaker WS and stamps the
    mix-hop stopwatch markers (t3 first TTS byte, t4 first frame sent)."""

    def __init__(self, connection: SpeakerConnection, room: RoomAudio):
        super().__init__()
        self._conn = connection
        self._room = room
        self._turn = None  # current TurnStopwatch, set by VoicePipeline.speak

    def set_turn(self, turn) -> None:
        self._turn = turn

    @property
    def has_turn(self) -> bool:
        return self._turn is not None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            turn = self._turn
            if turn is not None:
                turn.mark("t3")  # first TTS byte in hand (idempotent — first wins)
            await self._conn.send_pcm(frame.audio)
            # Every byte sent extends the playout tail — this is what "the bot is
            # currently speaking" means for barge-in and for the politeness gap.
            self._room.note_tts_audio(len(frame.audio), frame.sample_rate)
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
        elif isinstance(frame, InterruptionFrame):
            # Barge-in (from our VAD gate, or Flux's own when Silero is unavailable).
            # An interrupted turn may never see TTSStopped, so drop the stopwatch here or
            # the NEXT utterance's first audio would stamp t3/t4 onto this dead turn and
            # poison the one measurement this phase is judged on. The page-side `stop` is
            # idempotent — the gate already sent one on the fast path.
            self._turn = None
            self._room.note_playout_stopped()
            await self._conn.send_json({"type": "stop"})
        await self.push_frame(frame, direction)


class VoicePipeline:
    """Owns the per-bot transport + services + task lifecycle."""

    def __init__(self, bot_id: str, recall_ws: WebSocket,
                 connection: SpeakerConnection, on_final: OnFinalTranscript,
                 keyterms: Optional[list[str]] = None):
        self.bot_id = bot_id
        self._connection = connection
        self._serializer = RecallFrameSerializer(bot_id)
        self.room = RoomAudio(bot_id)
        print(f"[voice] pipeline bot={bot_id[:8]} tuning: {tuning.summary()}")

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

        vad_analyzer = _make_vad()

        stt = DeepgramFluxSTTService(
            api_key=os.getenv("DEEPGRAM_API_KEY", ""),
            sample_rate=_INPUT_SAMPLE_RATE,
            # Silero owns barge-in when it loaded (fork ④): Flux's StartOfTurn kills the
            # reply on ANY turn start, which is exactly the backchannel intolerance §1
            # exists to fix. Without Silero, Flux's crude version is better than none.
            should_interrupt=vad_analyzer is None,
            settings=DeepgramFluxSTTService.Settings(
                model=tuning.FLUX_MODEL,
                eot_threshold=tuning.FLUX_EOT_THRESHOLD,
                eot_timeout_ms=tuning.FLUX_EOT_TIMEOUT_MS,
                eager_eot_threshold=tuning.FLUX_EAGER_EOT_THRESHOLD,
                # Flux DOES support keyterm prompting — thread the app's grounding list in.
                keyterm=list(keyterms or []),
            ),
        )

        # §3 — speculative voice-channel call. Flux fires EagerEndOfTurn once end-of-turn
        # confidence crosses the eager threshold, a beat before it is certain; we start the
        # talk brain then and hold its audio until EndOfTurn confirms the same text.
        # TurnResumed means the human kept going → throw the speculation away.
        if tuning.FLUX_EAGER_EOT_THRESHOLD is not None:
            @stt.event_handler("on_eager_end_of_turn")
            async def _on_eager(service, transcript: str):
                from voice import voice_channel
                await voice_channel.on_eager_turn(bot_id, transcript,
                                                  self._serializer.last_speaker)

            @stt.event_handler("on_turn_resumed")
            async def _on_resumed(service):
                from voice import voice_channel
                voice_channel.cancel_speculation(bot_id, "turn_resumed")

        tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY", ""),
            sample_rate=SPEAKER_SAMPLE_RATE,  # so the sink can forward PCM as-is
            encoding="pcm_s16le",
            container="raw",
            settings=CartesiaTTSService.Settings(
                voice=tuning.TTS_VOICE_ID or None,
                model=tuning.TTS_MODEL,
                generation_config=GenerationConfig(
                    speed=tuning.TTS_SPEED,
                    volume=tuning.TTS_VOLUME,
                    emotion=tuning.TTS_EMOTION,
                ),
            ),
        )

        self._sink = SpeakerSink(connection, self.room)
        self._capture = TranscriptCapture(bot_id, self._serializer, on_final)
        self._gate = BargeInGate(bot_id, self.room, connection) if vad_analyzer else None

        stages = [transport.input()]         # Recall audio WS → InputAudioRawFrame
        if vad_analyzer is not None:
            stages.append(VADProcessor(vad_analyzer=vad_analyzer))  # Silero, local, ms
            stages.append(self._gate)        # duration-gated barge-in (§1)
        stages += [
            stt,                             # Deepgram Flux (STT + semantic EOT)
            self._capture,                   # EndOfTurn → bridge (old brain)
            tts,                             # Cartesia (fed by queued TTSSpeakFrame)
            self._sink,                      # → speaker WS
        ]
        self._task = PipelineTask(Pipeline(stages))
        self._runner = PipelineRunner(handle_sigint=False)
        if self._gate is not None:
            barge.register(bot_id, self._gate, self.room)

    async def run(self) -> None:
        """Drive the pipeline until the Recall audio socket closes. Awaited by the
        /voice/audio-in route so the WS handler stays open for the socket's lifetime."""
        await self._runner.run(self._task)

    @property
    def has_open_turn(self) -> bool:
        """True while an utterance is still being rendered — a streamed reply's later
        chunks belong to the stopwatch already running, not to a new one."""
        return self._sink.has_turn

    async def speak(self, text: str, turn=None) -> None:
        """Render `text` out the mouth. `turn` (a TurnStopwatch) receives t3/t4."""
        if turn is not None:
            self._sink.set_turn(turn)
        await self._task.queue_frame(TTSSpeakFrame(text))

    async def stop(self) -> None:
        # run() awaits the runner directly, so cancelling the task ends the pipeline
        # and unblocks run() — no separate run-task handle to tear down.
        barge.cleanup_bot(self.bot_id)
        stopwatch.cleanup_bot(self.bot_id)
        try:
            await self._task.cancel()
        except Exception:
            pass

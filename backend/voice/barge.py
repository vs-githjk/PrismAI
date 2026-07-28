"""Phase 5 §1 + §2 — real-audio barge-in and the politeness gap, both off Silero VAD.

Silero is the local, millisecond-latency answer to ONE question: *is a human making
sound right now?* (fork ④ — Flux answers "did they finish?", Silero answers "did someone
start talking over us?"). Two features fall out of that one signal:

  §1 barge-in   VAD speech-start while the bot is playing out → wait until the burst has
                lasted `BARGE_MIN_SPEECH_MS` → interrupt: Pipecat's `InterruptionFrame`
                (kills the Cartesia turn) + a `stop` control message that drops the
                speaker page's already-scheduled buffers. Sub-threshold bursts are
                ignored, so "yeah" / "mm-hm" don't kill the reply. If that short burst
                later transcribes to something substantive, `late_interrupt()` fires.
                Mute and the spoken "stop" command bypass the gate entirely (`hard_stop`).

  §2 gap        The room's acoustic silence, not the transcript's. `wait_for_gap()` holds
                an utterance until the room has been quiet for `GAP_SILENCE_S`, capped at
                `GAP_MAX_WAIT_S`. Observed waits are recorded and a median/p90 is logged
                every N waits — the report §2 promises, so the defaults get re-picked on
                data instead of taste.

Everything degrades: without Silero (no onnxruntime — e.g. a Python 3.14 dev box) there is
no room, `wait_for_gap` falls back to transcript timestamps, and the pipeline reverts to
Flux's built-in interruption. Nothing here can take the bot's voice out.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Optional

from pipecat.frames.frames import (
    Frame,
    UserSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice import tuning


class RoomAudio:
    """Per-bot acoustic state: who is making noise, and how long the bot's own audio
    still has to play. One monotonic clock throughout — wall-clock jumps must never be
    read as silence."""

    __slots__ = ("bot_id", "human_speaking", "speech_started_at", "last_speech_ts",
                 "bot_playing_until", "interrupted_burst", "interrupt_seq")

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.human_speaking = False
        self.speech_started_at = 0.0
        self.last_speech_ts = 0.0        # monotonic of the last speech evidence
        self.bot_playing_until = 0.0     # monotonic estimate of playout tail
        self.interrupted_burst = False   # this burst already fired an interrupt
        self.interrupt_seq = 0           # bumped per interrupt; see interrupted_since()

    # — human side (fed by Silero via BargeInGate) —
    def note_speech_start(self) -> None:
        now = time.monotonic()
        self.human_speaking = True
        self.speech_started_at = now
        self.last_speech_ts = now
        self.interrupted_burst = False

    def note_speech_activity(self) -> None:
        self.last_speech_ts = time.monotonic()

    def note_speech_stop(self) -> None:
        self.human_speaking = False
        self.last_speech_ts = time.monotonic()

    def quiet_seconds(self) -> float:
        """How long the room has been acoustically quiet. 0 while someone is talking."""
        if self.human_speaking:
            return 0.0
        if not self.last_speech_ts:
            return tuning.GAP_MAX_WAIT_S  # nobody has spoken yet → treat as quiet
        return time.monotonic() - self.last_speech_ts

    # — bot side (fed by the pipeline's SpeakerSink) —
    def note_speak_queued(self, grace_s: float = 2.0) -> None:
        """Text handed to TTS but no audio back yet. Without this, the ~100–300ms of
        Cartesia time-to-first-byte reads as "the bot is silent", so the SECOND chunk of a
        streamed reply would sit in the politeness gap waiting for a lull that the bot's
        own first chunk is about to fill — a stutter mid-sentence. The grace expires on
        its own if TTS never produces anything, so a dead mouth can't wedge the gap."""
        now = time.monotonic()
        self.bot_playing_until = max(self.bot_playing_until, now + grace_s)

    def note_tts_audio(self, num_bytes: int, sample_rate: int) -> None:
        """Extend the playout estimate by this chunk's real duration. The speaker page
        schedules buffers back-to-back on a running cursor, so the tail is just the sum
        of what we've sent — no browser clock to trust.
        # ponytail: 16-bit mono assumed (what Cartesia is configured to emit here)."""
        if num_bytes <= 0 or sample_rate <= 0:
            return
        now = time.monotonic()
        base = self.bot_playing_until if self.bot_playing_until > now else now
        self.bot_playing_until = base + num_bytes / float(sample_rate * 2)

    def note_playout_stopped(self) -> None:
        self.bot_playing_until = 0.0

    def note_interrupted(self) -> None:
        """The reply was cut off. Bumping the sequence is what lets a still-generating
        streamed reply notice and stop feeding the mouth."""
        self.note_playout_stopped()
        self.interrupt_seq += 1

    def bot_is_speaking(self) -> bool:
        return time.monotonic() < self.bot_playing_until


class BargeInGate(FrameProcessor):
    """Sits right after the VAD processor. Watches VAD frames; when a burst crosses the
    duration threshold while the bot is playing out, it interrupts. Passes every frame
    through untouched — a tap with a timer, not a gate on the audio."""

    def __init__(self, bot_id: str, room: RoomAudio, connection):
        super().__init__()
        self._bot_id = bot_id
        self._room = room
        self._conn = connection
        self._timer: Optional[asyncio.Task] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._room.note_speech_start()
            self._arm(getattr(frame, "start_secs", tuning.VAD_START_SECS) or 0.0)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._room.note_speech_stop()
            self._disarm()
        elif isinstance(frame, UserSpeakingFrame):
            self._room.note_speech_activity()
        await self.push_frame(frame, direction)

    def _arm(self, already_elapsed_s: float) -> None:
        """VAD only reports a start after `start_secs` of confirmed speech, so that much
        of the threshold is already spent by the time we get here."""
        self._disarm()
        if not tuning.BARGE_IN_ENABLED or not self._room.bot_is_speaking():
            return
        remaining = max(0.0, tuning.BARGE_MIN_SPEECH_MS / 1000.0 - already_elapsed_s)
        self._timer = asyncio.create_task(self._fire_after(remaining))

    def _disarm(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None

    async def _fire_after(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        # Re-check both halves: the burst may have stopped, or the bot may have finished
        # on its own while we waited. Either way there is nothing to interrupt.
        if not self._room.human_speaking or not self._room.bot_is_speaking():
            return
        self._room.interrupted_burst = True
        await self.interrupt("sustained_speech")

    async def interrupt(self, reason: str) -> None:
        """Kill the in-flight reply: cancel the TTS turn AND drop what the speaker page
        has already scheduled (Cartesia audio we sent is buffered ahead of the ear)."""
        try:
            await self.broadcast_interruption()
        except Exception as exc:
            print(f"[voice-barge] interruption broadcast failed: {exc}")
        try:
            await self._conn.send_json({"type": "stop"})
        except Exception as exc:
            print(f"[voice-barge] speaker stop failed: {exc}")
        self._room.note_interrupted()
        print(f"[voice-barge] INTERRUPT bot={self._bot_id[:8]} reason={reason}")


# ── per-bot registry ──────────────────────────────────────────────────────────
# The gate lives inside the Pipecat pipeline, but mute / the spoken "stop" command / the
# politeness gap all reach it from plain request-handler code, keyed by bot_id.

_GATES: dict[str, BargeInGate] = {}
_ROOMS: dict[str, RoomAudio] = {}


def register(bot_id: str, gate: BargeInGate, room: RoomAudio) -> None:
    _GATES[bot_id] = gate
    _ROOMS[bot_id] = room
    # Also hang the room on the bot's state dict so `_wait_for_speech_gap(state)` — which
    # only ever receives the state — can find it without a signature change.
    try:
        from realtime_routes import _get_bot_state
        _get_bot_state(bot_id)["voice_room"] = room
    except Exception:
        pass


def cleanup_bot(bot_id: str) -> None:
    gate = _GATES.pop(bot_id, None)
    _ROOMS.pop(bot_id, None)
    if gate is not None:
        gate._disarm()
    # Drop the state-dict handle too — a dead room reads as permanently quiet, which
    # would silently disable the politeness gap for the rest of the bot's life.
    try:
        from realtime_routes import _bot_state
        st = _bot_state.get(bot_id)
        if st is not None:
            st.pop("voice_room", None)
    except Exception:
        pass


def room_for(bot_id: str) -> Optional[RoomAudio]:
    return _ROOMS.get(bot_id)


def interrupt_seq(bot_id: str) -> int:
    room = _ROOMS.get(bot_id)
    return room.interrupt_seq if room is not None else 0


def interrupted_since(bot_id: str, seq: int) -> bool:
    """Has a barge-in fired since `seq` was taken? Killing the in-flight TTS turn is only
    half of stopping the bot: a STREAMED reply is still generating, and every later
    sentence would be queued straight back into the mouth the human just talked over. The
    streaming loop snapshots the sequence and stops when it moves."""
    return interrupt_seq(bot_id) != seq


async def hard_stop(bot_id: str, reason: str = "stop") -> bool:
    """Instant kill — mute, or the spoken "stop" command. Pre-gate by design: no duration
    threshold, no politeness, no waiting for a lull (§1). Returns False when this bot has
    no live pipeline (the caller's own cancel path still applies)."""
    gate = _GATES.get(bot_id)
    if gate is None:
        return False
    await gate.interrupt(reason)
    return True


async def late_interrupt(bot_id: str, text: str) -> bool:
    """A burst that stayed under the duration gate but transcribed to something
    substantive: the human really did interject, just briefly. Interrupt after the fact
    rather than talking on over an actual question."""
    room = _ROOMS.get(bot_id)
    gate = _GATES.get(bot_id)
    if room is None or gate is None or not tuning.BARGE_IN_ENABLED:
        return False
    if room.interrupted_burst or not room.bot_is_speaking():
        return False
    if len((text or "").split()) < tuning.LATE_INTERRUPT_MIN_WORDS:
        return False
    room.interrupted_burst = True
    await gate.interrupt("late_transcript")
    return True


# ── the politeness gap (§2) ───────────────────────────────────────────────────

async def wait_for_gap(bot_id: str = "", state: Optional[dict] = None) -> None:
    """Hold until the room has been quiet for `GAP_SILENCE_S`, or `GAP_MAX_WAIT_S` passes.

    Prefers Silero's acoustic silence; falls back to the transcript-timestamp estimate
    (`state["last_segment_ts"]`) when no pipeline is attached. Returns immediately if the
    bot is already mid-utterance — the gap gates the START of speech, not every chunk of
    a reply already in flight — or if the speaking session was cancelled (mute / "stop").
    """
    if not tuning.GAP_ENABLED:
        return
    if state is None and bot_id:
        try:
            from realtime_routes import _get_bot_state
            state = _get_bot_state(bot_id)
        except Exception:
            state = None
    room = (state or {}).get("voice_room") or (_ROOMS.get(bot_id) if bot_id else None)

    if room is not None and room.bot_is_speaking():
        return  # already talking — this is a continuation, not a new utterance

    started = time.monotonic()
    deadline = started + tuning.GAP_MAX_WAIT_S
    poll = tuning.GAP_POLL_VAD_S if room is not None else tuning.GAP_POLL_FALLBACK_S
    source = "vad" if room is not None else "transcript"
    while time.monotonic() < deadline:
        if _session_cancelled(state):
            _record_wait(time.monotonic() - started, "cancelled", source)
            return
        if room is not None:
            quiet = room.quiet_seconds()
        else:
            last = (state or {}).get("last_segment_ts", 0.0) or 0.0
            quiet = time.time() - last if last else tuning.GAP_MAX_WAIT_S
        if quiet >= tuning.GAP_SILENCE_S:
            _record_wait(time.monotonic() - started, "quiet", source)
            return
        await asyncio.sleep(poll)
    _record_wait(time.monotonic() - started, "cap", source)


def _session_cancelled(state: Optional[dict]) -> bool:
    if not state:
        return False
    try:
        import perception_state
        sess = perception_state.get_session(state)
        return sess is not None and sess.is_cancelled
    except Exception:
        return False


class _GapReport:
    """The §2 report-back: a bounded window of observed waits, logged as median/p90 every
    N waits so the owner can re-pick GAP_SILENCE_S on data rather than on feel."""

    def __init__(self, window: int = 200):
        self._waits: list[float] = []
        self._reasons: dict[str, int] = {}
        self._sources: dict[str, int] = {}
        self._window = window
        self._n = 0

    def record(self, waited_s: float, reason: str, source: str) -> None:
        self._waits.append(waited_s * 1000.0)
        if len(self._waits) > self._window:
            del self._waits[: len(self._waits) - self._window]
        self._reasons[reason] = self._reasons.get(reason, 0) + 1
        self._sources[source] = self._sources.get(source, 0) + 1
        self._n += 1
        if tuning.GAP_REPORT_EVERY > 0 and self._n % tuning.GAP_REPORT_EVERY == 0:
            self.log()

    def log(self) -> None:
        if not self._waits:
            return
        from voice.stopwatch import _pctl  # same percentile math as the latency report
        med = statistics.median(self._waits)
        print(f"[voice-gap] SUMMARY n={self._n} med={med:.0f}ms p90={_pctl(self._waits, 90):.0f}ms "
              f"max={max(self._waits):.0f}ms reasons={self._reasons} source={self._sources} "
              f"(silence={tuning.GAP_SILENCE_S}s cap={tuning.GAP_MAX_WAIT_S}s)")


_REPORT = _GapReport()


def _record_wait(waited_s: float, reason: str, source: str) -> None:
    _REPORT.record(waited_s, reason, source)


# ── self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    def _demo() -> None:
        room = RoomAudio("botxxxxxxxx")

        # Playout estimate: 24kHz 16-bit mono, 48000 bytes = 1.0s of audio.
        assert not room.bot_is_speaking()
        room.note_tts_audio(48000, 24000)
        assert room.bot_is_speaking()
        assert 0.9 < room.bot_playing_until - time.monotonic() <= 1.0
        # Chunks queue back to back rather than resetting the tail.
        room.note_tts_audio(48000, 24000)
        assert 1.9 < room.bot_playing_until - time.monotonic() <= 2.0
        room.note_playout_stopped()
        assert not room.bot_is_speaking()

        # Silence tracking: zero while talking, growing once stopped.
        assert room.quiet_seconds() > 0            # nobody has spoken yet
        room.note_speech_start()
        assert room.quiet_seconds() == 0.0
        room.note_speech_stop()
        assert room.quiet_seconds() < 0.1

        # A fresh burst clears the "already interrupted" latch.
        room.interrupted_burst = True
        room.note_speech_start()
        assert room.interrupted_burst is False

        # Gap wait with no room + no transcript history → returns on the first poll.
        state: dict = {}
        t0 = time.monotonic()
        asyncio.run(wait_for_gap(state=state))
        assert time.monotonic() - t0 < 0.5, "empty state should not burn the cap"

        # Gap wait honours a recent transcript timestamp, then the cap.
        state = {"last_segment_ts": time.time()}
        t0 = time.monotonic()
        asyncio.run(wait_for_gap(state=state))
        waited = time.monotonic() - t0
        assert tuning.GAP_SILENCE_S - 0.3 < waited < tuning.GAP_SILENCE_S + 0.5, waited

        # Queue grace: a chunk handed to TTS counts as speaking before any audio returns,
        # so the next chunk of a streamed reply doesn't stall in the gap.
        room3 = RoomAudio("b3")
        room3.note_speak_queued(0.5)
        assert room3.bot_is_speaking()
        room3.note_tts_audio(48000 * 4, 24000)   # real audio extends past the grace
        assert room3.bot_playing_until - time.monotonic() > 3.5

        # Gap wait skips entirely while the bot is mid-utterance.
        room2 = RoomAudio("b2")
        room2.note_tts_audio(48000, 24000)
        room2.note_speech_start()  # room is NOT quiet, yet we must not block
        t0 = time.monotonic()
        asyncio.run(wait_for_gap(state={"voice_room": room2}))
        assert time.monotonic() - t0 < 0.1

        # late_interrupt is a no-op without a registered pipeline, whatever the text.
        assert asyncio.run(late_interrupt("nosuchbot", "this is a real question")) is False
        assert asyncio.run(hard_stop("nosuchbot")) is False

        _REPORT.log()

    class _SpyGate(BargeInGate):
        """Exercises the duration gate without the pipeline around it: records interrupts
        instead of broadcasting frames."""

        def __init__(self, room):
            super().__init__("botxxxxxxxx", room, connection=None)
            self.fired: list[str] = []

        async def interrupt(self, reason: str) -> None:
            self.fired.append(reason)
            self._room.note_interrupted()   # same state effect as the real interrupt

    async def _gate_demo() -> None:
        # Backchannel: a burst shorter than the threshold must NOT kill the reply.
        room = RoomAudio("botxxxxxxxx")
        room.note_tts_audio(48000 * 5, 24000)  # bot has 5s of audio queued
        gate = _SpyGate(room)
        room.note_speech_start()
        gate._arm(tuning.VAD_START_SECS)
        await asyncio.sleep(tuning.BARGE_MIN_SPEECH_MS / 1000.0 * 0.4)
        room.note_speech_stop()
        gate._disarm()                                   # "yeah" — speaker stopped
        await asyncio.sleep(tuning.BARGE_MIN_SPEECH_MS / 1000.0)
        assert gate.fired == [], gate.fired

        # Sustained speech over the bot: interrupts once the threshold elapses.
        room.note_speech_start()
        gate._arm(tuning.VAD_START_SECS)
        await asyncio.sleep(tuning.BARGE_MIN_SPEECH_MS / 1000.0 + 0.15)
        assert gate.fired == ["sustained_speech"], gate.fired
        assert not room.bot_is_speaking(), "interrupt must clear the playout estimate"

        # Nothing to interrupt (bot silent) → the timer never even arms.
        gate.fired.clear()
        room.note_speech_start()
        gate._arm(0.0)
        await asyncio.sleep(tuning.BARGE_MIN_SPEECH_MS / 1000.0 + 0.15)
        assert gate.fired == [], gate.fired

        # Late interrupt: sub-threshold burst, substantive words → fire; "yeah" → don't.
        room2 = RoomAudio("late")
        gate2 = _SpyGate(room2)
        _GATES["late"], _ROOMS["late"] = gate2, room2
        room2.note_tts_audio(48000 * 5, 24000)
        assert await late_interrupt("late", "yeah") is False
        assert await late_interrupt("late", "wait what about the deadline") is True
        assert await late_interrupt("late", "and another thing entirely") is False  # latched

        # A streamed reply in flight must be able to see that it was cut off.
        seq = interrupt_seq("late")
        assert not interrupted_since("late", seq)
        room2.note_tts_audio(48000 * 5, 24000)   # bot speaks again
        room2.interrupted_burst = False
        assert await late_interrupt("late", "no I meant the other one") is True
        assert interrupted_since("late", seq)
        cleanup_bot("late")
        assert interrupt_seq("late") == 0        # unknown bot → never "interrupted"

    _demo()
    asyncio.run(_gate_demo())
    print("barge self-check OK")

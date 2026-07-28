"""A whole reply must ride in ONE Cartesia context.

Pipecat mints a fresh context per TTSSpeakFrame but reuses one across an LLM response,
and Cartesia caps concurrent contexts per account (2 on the free tier). Sending each
chunk as its own speak-frame therefore made chunks-per-reply == concurrent contexts, and
multi-sentence replies died mid-reply on a 429. These assert the frame shape that fixes
it: one open, N texts, one close — and a fresh open after an interruption.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice.pipeline import SpeakerSink, VoicePipeline


class _StubConn:
    async def send_json(self, _payload):
        pass


class _StubRoom:
    def note_playout_stopped(self):
        pass


class _FakeTask:
    def __init__(self):
        self.frames = []

    async def queue_frame(self, frame):
        self.frames.append(frame)

    @property
    def shape(self):
        """Frame types as short letters: S=open, T=text, E=close."""
        letter = {LLMFullResponseStartFrame: "S", TextFrame: "T", LLMFullResponseEndFrame: "E"}
        return "".join(letter.get(type(f), "?") for f in self.frames)


def _pipeline():
    """A VoicePipeline with only the two collaborators speak() touches — building the
    real one needs a Recall websocket, Deepgram and Cartesia."""
    p = object.__new__(VoicePipeline)
    p._task = _FakeTask()
    p._sink = object.__new__(SpeakerSink)
    p._sink._turn = None
    p._sink.speaking = False
    return p


class UtteranceGroupingTests(unittest.TestCase):
    def test_one_shot_reply_opens_and_closes(self):
        p = _pipeline()
        asyncio.run(p.speak("Just the one line."))
        asyncio.run(p.end_utterance())
        self.assertEqual(p._task.shape, "STE")

    def test_streamed_chunks_share_one_context(self):
        p = _pipeline()

        async def _run():
            for chunk in ("First bit.", "Second bit.", "Third bit."):
                await p.speak(chunk)
            await p.end_utterance()

        asyncio.run(_run())
        # The point of the fix: ONE open and ONE close around three chunks, not three
        # standalone utterances (which would be three concurrent Cartesia contexts).
        self.assertEqual(p._task.shape, "STTTE")

    def test_close_is_idempotent(self):
        p = _pipeline()
        asyncio.run(p.speak("One."))
        asyncio.run(p.end_utterance())
        asyncio.run(p.end_utterance())  # the streamed path closes from a finally
        self.assertEqual(p._task.shape, "STE")

    def test_close_without_speaking_emits_nothing(self):
        p = _pipeline()
        asyncio.run(p.end_utterance())
        self.assertEqual(p._task.shape, "")

    def test_next_reply_reopens_after_interruption(self):
        p = _pipeline()
        p._sink._conn = _StubConn()
        p._sink._room = _StubRoom()

        async def _run():
            await p.speak("Interrupted mid-")
            # Barge-in. Drive the real sink branch: pipecat drops its TTS turn context
            # here, so the sink must drop ours. Only the base-class plumbing is faked.
            with patch.object(FrameProcessor, "process_frame", AsyncMock()), \
                 patch.object(SpeakerSink, "push_frame", AsyncMock()):
                await p._sink.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            await p.speak("Fresh reply.")
            await p.end_utterance()

        asyncio.run(_run())
        # Second S: without the reset the new reply would append to a context pipecat
        # has already thrown away, and every later chunk would open its own again.
        self.assertEqual(p._task.shape, "STSTE")


if __name__ == "__main__":
    unittest.main()

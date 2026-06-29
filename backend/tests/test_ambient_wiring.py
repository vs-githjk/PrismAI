"""Wiring tests for the ambient loop in realtime_routes."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import realtime_routes  # noqa: E402


class StreamingDefaultTests(unittest.TestCase):
    def test_streaming_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(realtime_routes._streamed_tts_on())
            self.assertTrue(realtime_routes._streamed_llm_on())

    def test_streaming_off_when_zero(self):
        with mock.patch.dict(os.environ, {"PRISM_STREAMED_TTS": "0", "PRISM_STREAMED_LLM": "0"}):
            self.assertFalse(realtime_routes._streamed_tts_on())
            self.assertFalse(realtime_routes._streamed_llm_on())


class FakeUtterance:
    def __init__(self, text, speaker_name="Abhinav"):
        self.text = text
        self.speaker_name = speaker_name
        self.speaker_id = "sid"
        self.utterance_id = "uid"
        self.word_count = len(text.split())
        self.chunk_count = 1
        self.duration_ms = 1000
        self.flush_reason = "pause"


class AmbientOnUtteranceRoutingTests(unittest.IsolatedAsyncioTestCase):
    def _auto_state(self):
        s = realtime_routes.meeting_memory.get_initial_memory_state()
        s["mode"] = "autonomous"
        s["meeting_start_ts"] = time.time() - 600
        s["live_decisions"] = [{"text": "d", "speaker": "A", "ts": 1.0}]  # past_warmup
        s["transcript_buffer"] = ["A: hello."]
        return s

    async def test_explicit_command_skips_ambient(self):
        state = self._auto_state()
        with mock.patch.object(realtime_routes, "_detect_command", return_value="summarize"), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance(
                "bot1", state, FakeUtterance("Prism, summarize?"))
        spec.assert_not_awaited()

    async def test_utterance_mode_skips_ambient(self):
        state = self._auto_state()
        state["mode"] = "utterance"
        with mock.patch.object(realtime_routes, "_detect_command", return_value=None), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance(
                "bot1", state, FakeUtterance("What is the SLA, again?"))
        spec.assert_not_awaited()

    async def test_autonomous_mode_arms_question(self):
        state = self._auto_state()
        with mock.patch.object(realtime_routes, "_detect_command", return_value=None), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance(
                "bot1", state, FakeUtterance("What is the SLA, again?"))
            # Speculation now runs as a background task (latest-wins) — await it.
            await state["_ambient_spec_task"]
            spec.assert_awaited()
        self.assertIsNotNone(state["pending_question"])

    async def test_mute_command_routes_to_lane(self):
        state = self._auto_state()
        await realtime_routes._ambient_on_utterance(
            "bot1", state, FakeUtterance("Prism, stay quiet"))
        self.assertTrue(state["muted"])


class ModeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_mode(self):
        bot_id = "bot-mode-test"
        state = realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "autonomous"})
            self.assertEqual(res, {"mode": "autonomous"})
            self.assertEqual(state["mode"], "autonomous")

            state["pending_question"] = {"text": "q?"}
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "utterance"})
            self.assertEqual(state["mode"], "utterance")
            self.assertIsNone(state["pending_question"])  # slot cleared on switch away
        finally:
            realtime_routes.cleanup_bot_state(bot_id)

    async def test_invalid_or_null_mode_rejected(self):
        bot_id = "bot-mode-test-2"
        realtime_routes._get_bot_state(bot_id)
        try:
            self.assertIn("error", await realtime_routes.set_bot_mode(bot_id, {"mode": "bogus"}))
            self.assertIn("error", await realtime_routes.set_bot_mode(bot_id, {"mode": None}))
        finally:
            realtime_routes.cleanup_bot_state(bot_id)


class MuteEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_mute_toggle(self):
        bot_id = "bot-mute-test"
        state = realtime_routes._get_bot_state(bot_id)
        try:
            state["pending_question"] = {"text": "q?"}
            res = await realtime_routes.set_bot_mute(bot_id, {"muted": True})
            self.assertTrue(res["muted"])
            self.assertTrue(state["muted"])
            self.assertIsNone(state["pending_question"])

            res = await realtime_routes.set_bot_mute(bot_id, {"muted": False})
            self.assertFalse(state["muted"])
        finally:
            realtime_routes.cleanup_bot_state(bot_id)


class PreJoinModeSeedTests(unittest.TestCase):
    def test_initial_mode_seeds_mode(self):
        bot_id = "bot-prejoin-test"
        realtime_routes.bot_store[bot_id] = {"initial_mode": "autonomous"}
        try:
            state = realtime_routes._get_bot_state(bot_id)
            self.assertEqual(state["mode"], "autonomous")
            self.assertNotIn("manual_mode", state)
        finally:
            realtime_routes.cleanup_bot_state(bot_id)
            realtime_routes.bot_store.pop(bot_id, None)

    def test_no_initial_mode_leaves_default(self):
        bot_id = "bot-prejoin-test-2"
        realtime_routes.bot_store[bot_id] = {}
        try:
            state = realtime_routes._get_bot_state(bot_id)
            self.assertEqual(state["mode"], "utterance")
        finally:
            realtime_routes.cleanup_bot_state(bot_id)
            realtime_routes.bot_store.pop(bot_id, None)


if __name__ == "__main__":
    unittest.main()

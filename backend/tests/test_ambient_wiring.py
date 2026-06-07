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


class AmbientSilentHelperTests(unittest.TestCase):
    def test_silent_detection(self):
        self.assertTrue(realtime_routes._is_ambient_silent("SILENT"))
        self.assertTrue(realtime_routes._is_ambient_silent("  silent.  "))
        self.assertFalse(realtime_routes._is_ambient_silent("Our Q3 number was 4.2M."))
        self.assertFalse(realtime_routes._is_ambient_silent(""))

    def test_preamble_nonempty(self):
        self.assertIn("SILENT", realtime_routes._AMBIENT_PREAMBLE)


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
    def setUp(self):
        self.state = realtime_routes.meeting_memory.get_initial_memory_state()
        self.state["transcript_buffer"] = []
        self.state["meeting_start_ts"] = 1000.0

    async def test_explicit_command_skips_ambient(self):
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        self.state["mode"] = "autonomous"
        self.state["mode_since_ts"] = time.time()
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("Prism, send the email")
            )
        self.assertEqual(called, [])

    async def test_utterance_mode_skips_ambient(self):
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("the numbers look fine to me")
            )
        self.assertEqual(called, [])

    async def test_autonomous_mode_runs_ambient(self):
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        self.state["mode"] = "autonomous"
        self.state["mode_entry_reason"] = "handoff"
        self.state["mode_since_ts"] = time.time()
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("what was our Q3 number")
            )
        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()

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
        async def fake_interject(*a, **k):
            called.append(a[2])
            return {"action": "offered"}
        self.state["mode"] = "autonomous"
        self.state["mode_since_ts"] = time.time()
        with mock.patch.object(realtime_routes.ambient_loop, "interject", fake_interject):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("Prism, send the email")
            )
        self.assertEqual(called, [])

    async def test_utterance_mode_skips_ambient(self):
        called = []
        async def fake_interject(*a, **k):
            called.append(a[2])
            return {"action": "offered"}
        with mock.patch.object(realtime_routes.ambient_loop, "interject", fake_interject):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("the numbers look fine to me")
            )
        self.assertEqual(called, [])

    async def test_autonomous_mode_runs_ambient(self):
        called = []
        async def fake_interject(*a, **k):
            called.append(a[2])
            return {"action": "offered"}
        self.state["mode"] = "autonomous"
        self.state["mode_entry_reason"] = "handoff"
        self.state["mode_since_ts"] = time.time()
        with mock.patch.object(realtime_routes.ambient_loop, "interject", fake_interject):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("what was our Q3 number")
            )
        self.assertEqual(called, ["what was our Q3 number"])

    async def test_mute_command_routes_to_interject(self):
        # "Prism, stay quiet" contains the wake word but must reach the
        # interjection layer (to set muted), not the generic command path.
        called = []
        async def fake_interject(*a, **k):
            called.append(a[2])
            return {"action": "muted"}
        with mock.patch.object(realtime_routes.ambient_loop, "interject", fake_interject):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("Prism, stay quiet")
            )
        self.assertEqual(called, ["Prism, stay quiet"])


class ModeOverrideEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_manual_mode(self):
        bot_id = "bot-override-test"
        state = realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "autonomous"})
            self.assertEqual(res["mode"], "autonomous")
            self.assertEqual(state["manual_mode"], "autonomous")

            res = await realtime_routes.set_bot_mode(bot_id, {"mode": None})
            self.assertIsNone(state["manual_mode"])
        finally:
            realtime_routes.cleanup_bot_state(bot_id)

    async def test_invalid_mode_rejected(self):
        bot_id = "bot-override-test-2"
        realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "bogus"})
            self.assertIn("error", res)
        finally:
            realtime_routes.cleanup_bot_state(bot_id)


class MuteEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_mute_toggle(self):
        bot_id = "bot-mute-test"
        state = realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mute(bot_id, {"muted": True})
            self.assertTrue(res["muted"])
            self.assertTrue(state["muted"])
            self.assertIsNone(state["pending_offer"])

            res = await realtime_routes.set_bot_mute(bot_id, {"muted": False})
            self.assertFalse(state["muted"])
        finally:
            realtime_routes.cleanup_bot_state(bot_id)


class PreJoinModeSeedTests(unittest.TestCase):
    def test_initial_mode_seeds_manual_override(self):
        bot_id = "bot-prejoin-test"
        realtime_routes.bot_store[bot_id] = {"initial_mode": "autonomous"}
        try:
            state = realtime_routes._get_bot_state(bot_id)
            self.assertEqual(state["manual_mode"], "autonomous")
            self.assertEqual(state["mode"], "autonomous")
        finally:
            realtime_routes.cleanup_bot_state(bot_id)
            realtime_routes.bot_store.pop(bot_id, None)

    def test_no_initial_mode_leaves_default(self):
        bot_id = "bot-prejoin-test-2"
        realtime_routes.bot_store[bot_id] = {}
        try:
            state = realtime_routes._get_bot_state(bot_id)
            self.assertIsNone(state["manual_mode"])
            self.assertEqual(state["mode"], "utterance")
        finally:
            realtime_routes.cleanup_bot_state(bot_id)
            realtime_routes.bot_store.pop(bot_id, None)


if __name__ == "__main__":
    unittest.main()

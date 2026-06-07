"""Unit tests for ambient_loop: state, mode machine, recall gate, decider, orchestration."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import meeting_memory  # noqa: E402
import perception_state  # noqa: E402


class StateFieldTests(unittest.TestCase):
    def test_initial_state_has_ambient_fields(self):
        s = meeting_memory.get_initial_memory_state()
        self.assertEqual(s["mode"], "utterance")
        self.assertEqual(s["mode_entry_reason"], "")
        self.assertEqual(s["mode_since_ts"], 0.0)
        self.assertIsNone(s["manual_mode"])
        self.assertEqual(s["last_activity_ts"], 0.0)
        self.assertEqual(s["recent_utterance_ts"], [])
        self.assertEqual(s["ambient_last_spoke_ts"], 0.0)
        self.assertFalse(s["_ambient_evaluating"])

    def test_counters_include_ambient_keys(self):
        s = {}
        c = perception_state.ensure_counters(s)
        for key in (
            "ambient_gate_fires", "ambient_decider_yes", "ambient_decider_no",
            "ambient_spoke", "ambient_suppressed_decline", "ambient_mode_shifts",
            "ambient_shadow_would_speak", "ambient_idea_handoff",
        ):
            self.assertEqual(c[key], 0)
        ops = perception_state.operational_counters(s)
        self.assertIn("ambient_gate_fires", ops)

    def test_snapshot_surfaces_mode(self):
        s = meeting_memory.get_initial_memory_state()
        s["transcript_buffer"] = []
        s["mode"] = "autonomous"
        s["mode_entry_reason"] = "handoff"
        snap = meeting_memory.get_memory_snapshot(s)
        self.assertEqual(snap["mode"], "autonomous")
        self.assertEqual(snap["mode_entry_reason"], "handoff")


class FlagTests(unittest.TestCase):
    def test_flags_default_off(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ambient_loop.autonomous_enabled())
            self.assertFalse(ambient_loop.shadow_mode())

    def test_flags_on(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS": "1", "PRISM_AUTONOMOUS_SHADOW": "1"}):
            self.assertTrue(ambient_loop.autonomous_enabled())
            self.assertTrue(ambient_loop.shadow_mode())

    def test_param_defaults(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ambient_loop.decider_model(), "llama-3.1-8b-instant")
            self.assertEqual(ambient_loop.decider_threshold(), 0.7)
            self.assertEqual(ambient_loop.cooldown_s(), 40.0)
            self.assertEqual(ambient_loop.pause_debounce_s(), 8.0)
            self.assertEqual(ambient_loop.lull_threshold_s(), 35.0)
            self.assertEqual(ambient_loop.autonomy_cap_s(), 300.0)

    def test_param_override(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {"PRISM_DECIDER_THRESHOLD": "0.55"}):
            self.assertEqual(ambient_loop.decider_threshold(), 0.55)


if __name__ == "__main__":
    unittest.main()

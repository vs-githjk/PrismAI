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


class UpdateModeTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["meeting_start_ts"] = 1000.0

    def test_handoff_enters_autonomous(self):
        import ambient_loop
        mode = ambient_loop.update_mode(self.s, "Prism, take it from here", "Abhinav", 1100.0)
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "handoff")

    def test_plain_utterance_stays_utterance(self):
        import ambient_loop
        mode = ambient_loop.update_mode(self.s, "I think the numbers look fine", "Abhinav", 1100.0)
        self.assertEqual(mode, "utterance")

    def test_stop_reverts_to_utterance(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, run with this", "Abhinav", 1100.0)
        mode = ambient_loop.update_mode(self.s, "Prism, stop", "Abhinav", 1110.0)
        self.assertEqual(mode, "utterance")

    def test_manual_override_wins(self):
        import ambient_loop
        self.s["manual_mode"] = "autonomous"
        mode = ambient_loop.update_mode(self.s, "just a normal sentence", "Abhinav", 1100.0)
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "manual")

    def test_autonomy_cap_reverts(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, run with this", "Abhinav", 1100.0)
        mode = ambient_loop.update_mode(self.s, "still going", "Abhinav", 1100.0 + 400.0)
        self.assertEqual(mode, "utterance")

    def test_lull_entered_reverts_on_active_crosstalk(self):
        import ambient_loop
        self.s["mode"] = "autonomous"
        self.s["mode_entry_reason"] = "lull"
        self.s["mode_since_ts"] = 1100.0
        ambient_loop.update_mode(self.s, "a", "X", 1101.0)
        ambient_loop.update_mode(self.s, "b", "Y", 1102.0)
        mode = ambient_loop.update_mode(self.s, "c", "Z", 1103.0)
        self.assertEqual(mode, "utterance")

    def test_handoff_entered_persists_through_activity(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, take it from here", "Abhinav", 1100.0)
        ambient_loop.update_mode(self.s, "a", "X", 1101.0)
        ambient_loop.update_mode(self.s, "b", "Y", 1102.0)
        mode = ambient_loop.update_mode(self.s, "c", "Z", 1103.0)
        self.assertEqual(mode, "autonomous")


class CheckLullTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["meeting_start_ts"] = 1000.0
        self.s["last_activity_ts"] = 1000.0

    def test_lull_shifts_to_autonomous(self):
        import ambient_loop
        mode = ambient_loop.check_lull(self.s, 1000.0 + 40.0)
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "lull")

    def test_no_lull_when_recent_activity(self):
        import ambient_loop
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 10.0))

    def test_no_lull_when_already_autonomous(self):
        import ambient_loop
        self.s["mode"] = "autonomous"
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))

    def test_no_lull_before_meeting_start(self):
        import ambient_loop
        self.s["meeting_start_ts"] = None
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))

    def test_manual_override_blocks_lull(self):
        import ambient_loop
        self.s["manual_mode"] = "utterance"
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))


class RecallGateTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()

    def test_question_mark_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "What was our Q3 revenue?", 100.0))

    def test_question_word_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "who owns the migration", 100.0))

    def test_request_phrase_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "can you pull up the doc", 100.0))

    def test_decision_pattern_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "we decided to ship Friday", 100.0))

    def test_plain_statement_misses_within_debounce(self):
        import ambient_loop
        self.s["_ambient_last_gate_ts"] = 100.0
        self.assertFalse(ambient_loop.recall_gate(self.s, "the weather is nice today", 101.0))

    def test_plain_statement_fires_after_debounce(self):
        import ambient_loop
        self.s["_ambient_last_gate_ts"] = 100.0
        self.assertTrue(ambient_loop.recall_gate(self.s, "the weather is nice today", 100.0 + 9.0))


class ParseDeciderTests(unittest.TestCase):
    def test_clean_json(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('{"respond": true, "confidence": 0.82, "reason": "open question"}')
        self.assertTrue(out["respond"])
        self.assertEqual(out["confidence"], 0.82)
        self.assertEqual(out["reason"], "open question")

    def test_fenced_json(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('```json\n{"respond": false, "confidence": 0.1, "reason": "chit-chat"}\n```')
        self.assertFalse(out["respond"])

    def test_json_with_prose_around_it(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('Sure! {"respond": true, "confidence": 0.9, "reason": "x"} hope that helps')
        self.assertTrue(out["respond"])

    def test_garbage_fails_safe_silent(self):
        import ambient_loop
        for bad in ["", None, "respond yes", "{not json", "{}", '{"confidence": 0.9}']:
            out = ambient_loop.parse_decider_output(bad)
            self.assertFalse(out["respond"])
            self.assertEqual(out["confidence"], 0.0)

    def test_confidence_clamped(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('{"respond": true, "confidence": 5, "reason": "x"}')
        self.assertEqual(out["confidence"], 1.0)


class DecideTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["transcript_buffer"] = ["Abhinav: what's our Q3 number?"]

    async def test_decide_parses_model_output(self):
        import ambient_loop
        async def fake_call(system, user):
            return '{"respond": true, "confidence": 0.8, "reason": "open question"}'
        with mock.patch.object(ambient_loop, "_call_decider_model", fake_call):
            out = await ambient_loop.decide(self.s)
        self.assertTrue(out["respond"])
        self.assertEqual(out["confidence"], 0.8)

    async def test_decide_model_error_fails_safe(self):
        import ambient_loop
        async def boom(system, user):
            raise RuntimeError("groq down")
        with mock.patch.object(ambient_loop, "_call_decider_model", boom):
            out = await ambient_loop.decide(self.s)
        self.assertFalse(out["respond"])
        self.assertEqual(out["reason"], "decider_error")


if __name__ == "__main__":
    unittest.main()

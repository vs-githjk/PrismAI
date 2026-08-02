"""Repro for the stand-in solo free-flow bug (2026-08-01 demo).

A scheduled stand-in bot registers with initial_mode=None, so its state is
seeded only by meeting_memory.get_initial_memory_state() — which pre-sets
"mode": "utterance" for the ambient lane. gate.get_mode() read that seed as
an explicit legacy choice and migrated every fresh bot to MANUAL, silently
disabling solo free-flow (log: speak=False wake=none despite solo=True).
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import meeting_memory  # noqa: E402
from voice import gate  # noqa: E402


def _fresh_state():
    """State exactly as realtime_routes builds it for a bot with no explicit
    initial_mode (the stand-in path): the memory seed, nothing else."""
    return {**meeting_memory.get_initial_memory_state()}


class GateModeDefaultTests(unittest.TestCase):
    def test_fresh_bot_defaults_to_auto(self):
        # The bug: the ambient-lane seed "mode": "utterance" was migrated to manual.
        self.assertEqual(gate.get_mode(_fresh_state()), "auto")

    def test_explicit_utterance_choice_still_manual(self):
        # manual_mode is only ever set by the join selector / mode endpoint —
        # a real user choice, which must keep winning.
        state = {**_fresh_state(), "manual_mode": "utterance"}
        self.assertEqual(gate.get_mode(state), "manual")

    def test_explicit_autonomous_choice_still_auto(self):
        state = {**_fresh_state(), "manual_mode": "autonomous"}
        self.assertEqual(gate.get_mode(state), "auto")

    def test_phase4_engagement_mode_wins(self):
        state = {**_fresh_state(), "engagement_mode": "manual"}
        self.assertEqual(gate.get_mode(state), "manual")
        state = {**_fresh_state(), "engagement_mode": "auto", "manual_mode": "utterance"}
        self.assertEqual(gate.get_mode(state), "auto")


class GateDecideSoloReplayTests(unittest.TestCase):
    """End-to-end replay of the logged utterance through the real gate +
    realtime_routes signals: one human in the roster, no wake word."""

    def _solo_state(self):
        state = _fresh_state()
        state["participants"] = {"100": {"name": "Devajsinh Ajitsinh Solanki", "is_bot": False}}
        state["participants_seen"] = True
        return state

    def test_solo_wakeless_request_engages(self):
        import asyncio
        state = self._solo_state()
        speak, cmd = asyncio.run(gate.decide(
            "bot-test", state,
            "Okay. Okay. Okay. Fine now. Can you tell us an update of how "
            "two plus two is equal to four?",
            "Devajsinh Ajitsinh Solanki",
        ))
        self.assertTrue(speak)
        self.assertIn("two plus two", cmd)


if __name__ == "__main__":
    unittest.main()

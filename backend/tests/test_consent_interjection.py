"""Unit tests for consent-based interjection (autonomous v2)."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import meeting_memory  # noqa: E402
import perception_state  # noqa: E402


class StateFieldTests(unittest.TestCase):
    def test_initial_state_has_interjection_fields(self):
        s = meeting_memory.get_initial_memory_state()
        self.assertEqual(s["interjection_state"], "idle")
        self.assertIsNone(s["pending_offer"])
        self.assertEqual(s["offered_subjects"], [])
        self.assertEqual(s["offer_last_ts"], 0.0)
        self.assertFalse(s["muted"])

    def test_counters_include_offer_keys(self):
        c = perception_state.ensure_counters({})
        for key in (
            "offers_made", "offers_accepted", "offers_declined",
            "offers_expired", "offers_talked_over", "mutes",
        ):
            self.assertEqual(c[key], 0)
        self.assertIn("offers_made", perception_state.operational_counters({}))

    def test_snapshot_surfaces_muted_and_interjection_state(self):
        s = meeting_memory.get_initial_memory_state()
        s["transcript_buffer"] = []
        s["muted"] = True
        s["interjection_state"] = "offer_pending"
        snap = meeting_memory.get_memory_snapshot(s)
        self.assertTrue(snap["muted"])
        self.assertEqual(snap["interjection_state"], "offer_pending")


if __name__ == "__main__":
    unittest.main()

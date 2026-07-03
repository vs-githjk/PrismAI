import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents import action_executor as ae


class CleanTests(unittest.TestCase):
    def test_drops_invalid_and_non_executable(self):
        rows = [
            {"task": "email Jane the deck", "action_type": "email", "title": "Deck",
             "body": "Hi Jane", "recipients": ["Jane"], "confidence": 0.9},
            {"task": "think about strategy", "action_type": "none"},   # not executable
            {"task": "", "action_type": "email"},                       # no task
            {"action_type": "task", "title": "Bug"},                    # no task text
            "garbage",                                                   # not a dict
        ]
        out = ae._clean(rows, owner="Vidyut")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action_type"], "email")
        self.assertEqual(out[0]["task"], "email Jane the deck")
        self.assertTrue(out[0]["owned"])

    def test_sorted_by_confidence_desc(self):
        rows = [
            {"task": "a", "action_type": "task", "confidence": 0.3},
            {"task": "b", "action_type": "email", "confidence": 0.95},
            {"task": "c", "action_type": "chat", "confidence": 0.6},
        ]
        out = ae._clean(rows, owner="")
        self.assertEqual([r["task"] for r in out], ["b", "c", "a"])

    def test_confidence_clamped_and_recipients_coerced(self):
        rows = [{"task": "x", "action_type": "calendar", "confidence": 5,
                 "recipients": "Bob"}]
        out = ae._clean(rows, owner="")
        self.assertEqual(out[0]["confidence"], 1.0)
        self.assertEqual(out[0]["recipients"], ["Bob"])

    def test_owner_falls_back_to_meeting_owner(self):
        rows = [{"task": "x", "action_type": "email"}]
        out = ae._clean(rows, owner="Vidyut")
        self.assertEqual(out[0]["owner"], "Vidyut")


class RunTests(unittest.TestCase):
    def test_no_open_items_short_circuits(self):
        # No LLM call should happen when there are no open action items.
        out = asyncio.run(ae.run("transcript", {"action_items": []}))
        self.assertEqual(out, {"suggested_actions": []})

    def test_completed_items_are_not_candidates(self):
        out = asyncio.run(ae.run("t", {"action_items": [{"task": "done", "completed": True}]}))
        self.assertEqual(out, {"suggested_actions": []})


class BuildContentTests(unittest.TestCase):
    def test_owner_header_and_items_included(self):
        content = ae._build_user_content("the transcript", {
            "owner_name": "Vidyut",
            "summary": "we shipped",
            "action_items": [{"task": "email Jane", "owner": "Vidyut"}],
        })
        self.assertIn("[Meeting owner: Vidyut]", content)
        self.assertIn("email Jane", content)
        self.assertIn("the transcript", content)


if __name__ == "__main__":
    unittest.main()

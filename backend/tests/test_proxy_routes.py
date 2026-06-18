"""Stand-in proxy (Feature A) — A1/A2 pure-logic tests."""
import os
import unittest
from datetime import datetime, timezone, timedelta

import proxy_routes as pr


class OwnerMatchTests(unittest.TestCase):
    def test_matches_first_or_full_name(self):
        names = ["Alice Smith", "Alice", "alice"]
        self.assertTrue(pr._user_owns_item("Alice", names))
        self.assertTrue(pr._user_owns_item("alice smith", names))
        self.assertTrue(pr._user_owns_item("Alice S.", names))  # 'alice' in 'alice s.'

    def test_rejects_others_and_placeholders(self):
        names = ["Alice"]
        self.assertFalse(pr._user_owns_item("Bob", names))
        self.assertFalse(pr._user_owns_item("Unassigned", names))
        self.assertFalse(pr._user_owns_item("TBD", names))
        self.assertFalse(pr._user_owns_item("", names))
        self.assertFalse(pr._user_owns_item("team", names))


class AuthorNamesTests(unittest.TestCase):
    def test_builds_name_variants(self):
        names = pr._author_names("u1", "Alice Smith", "alice.smith@acme.com")
        self.assertIn("Alice Smith", names)
        self.assertIn("Alice", names)           # first name
        self.assertIn("alice.smith", names)      # email local part

    def test_empty_inputs(self):
        self.assertEqual(pr._author_names("u1", "", ""), [])


class BlockFormattingTests(unittest.TestCase):
    def test_items_block_open_and_done(self):
        items = {
            "open": [{"task": "Finish auth flow", "due": "Friday", "meeting": "Sync"}],
            "done": [{"task": "Ship API", "due": "", "meeting": "Sync"}],
        }
        block = pr._items_block(items)
        self.assertIn("Finish auth flow", block)
        self.assertIn("due Friday", block)
        self.assertIn("Ship API", block)

    def test_items_block_empty(self):
        block = pr._items_block({"open": [], "done": []})
        self.assertIn("no recent action items", block)

    def test_profile_context(self):
        ctx = pr._profile_context({"role_focus": "Backend lead", "standing_notes": "owns payments"})
        self.assertIn("Backend lead", ctx)
        self.assertIn("owns payments", ctx)
        self.assertEqual(pr._profile_context({}), "")


class ScheduleGatingTests(unittest.TestCase):
    def _iso(self, **delta):
        return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()

    def test_join_at_ok_far_future(self):
        self.assertTrue(pr._join_at_ok(self._iso(minutes=30)))

    def test_join_at_too_soon(self):
        self.assertFalse(pr._join_at_ok(self._iso(minutes=5)))

    def test_join_at_past(self):
        self.assertFalse(pr._join_at_ok(self._iso(minutes=-30)))

    def test_join_at_missing_or_bad(self):
        self.assertFalse(pr._join_at_ok(None))
        self.assertFalse(pr._join_at_ok(""))
        self.assertFalse(pr._join_at_ok("not-a-date"))

    def test_join_at_handles_z_suffix(self):
        z = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(pr._join_at_ok(z))

    def test_schedule_flag(self):
        old = os.environ.get("PRISM_STANDIN_SCHEDULE")
        try:
            os.environ["PRISM_STANDIN_SCHEDULE"] = "0"
            self.assertFalse(pr._standin_schedule_on())
            os.environ["PRISM_STANDIN_SCHEDULE"] = "1"
            self.assertTrue(pr._standin_schedule_on())
            del os.environ["PRISM_STANDIN_SCHEDULE"]
            self.assertTrue(pr._standin_schedule_on())  # default ON
        finally:
            if old is not None:
                os.environ["PRISM_STANDIN_SCHEDULE"] = old


if __name__ == "__main__":
    unittest.main()

"""Stand-in proxy (Feature A) — A1 pure-logic tests (owner matching, synthesis)."""
import unittest

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


if __name__ == "__main__":
    unittest.main()

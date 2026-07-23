"""Unit tests for the on-screen presentation verb pre-gate + registry `presents` flag.

Pure logic — no network, no Anthropic key. Covers the deterministic trigger gate,
walkthrough-narration detection, the stop kill-phrase (incl. persona aliases), and
the registry `presents` flag / `is_presents` helper.
"""

import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# registry imports are stdlib-only, but keep parity with the other registry tests.
fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

from tools.present_gate import (
    presents_gate_matches,
    is_walkthrough_request,
    is_stop_sharing,
)


class PresentsGateTests(unittest.TestCase):
    POSITIVES = [
        "Prism, pull up the auth PR",
        "put the dashboard on screen",
        "put the dashboard on the screen",
        "walk us through it",
        "share your screen",
        "share screen",
        "can you screen share the roadmap",
        "bring up the staging dashboard",
        "open the figma file on screen",
        "show us the latest mockups",
        "show everyone the burndown chart",
        "get that up on screen",
        "take everyone through the deploy flow",
    ]

    NEGATIVES = [
        "how did the presentation go",
        "what did we decide",
        "pull up a chair",
        "pull up a seat for the new hire",
        "show me some respect",
        "walk me through your reasoning",  # pure explanation, no audience -> not a trigger
        "let's talk about the roadmap",
        "can you summarize the last meeting",
        "email a recap to the team",
        "",
    ]

    def test_positives_match(self):
        for u in self.POSITIVES:
            with self.subTest(utterance=u):
                self.assertTrue(presents_gate_matches(u), f"should trigger: {u!r}")

    def test_negatives_do_not_match(self):
        for u in self.NEGATIVES:
            with self.subTest(utterance=u):
                self.assertFalse(presents_gate_matches(u), f"should NOT trigger: {u!r}")

    def test_none_is_safe(self):
        self.assertFalse(presents_gate_matches(None))  # type: ignore[arg-type]


class WalkthroughDetectionTests(unittest.TestCase):
    def test_walkthrough_positives(self):
        for u in [
            "walk us through it",
            "take us through the deploy flow",
            "explain what's on the screen",
            "can you explain this diagram",
            "give everyone a rundown",
            "walk me through the PR",  # permissive here (narration mode only)
        ]:
            with self.subTest(utterance=u):
                self.assertTrue(is_walkthrough_request(u), f"should be walkthrough: {u!r}")

    def test_walkthrough_negatives(self):
        for u in [
            "pull up the auth PR",
            "put the dashboard on screen",
            "share your screen",
            "",
        ]:
            with self.subTest(utterance=u):
                self.assertFalse(is_walkthrough_request(u), f"not a walkthrough: {u!r}")


class StopSharingTests(unittest.TestCase):
    def test_stop_positives(self):
        for u in [
            "stop sharing",
            "Prism, stop sharing",
            "you can stop sharing now",
            "stop the screen share",
            "stop screensharing",
            "stop presenting",
            "stop the presentation",
            "that's enough sharing",
            "cut the screen share",
        ]:
            with self.subTest(utterance=u):
                self.assertTrue(is_stop_sharing(u), f"should stop: {u!r}")

    def test_stop_negatives(self):
        for u in [
            "pull up the auth PR",
            "keep sharing that",
            "don't stop, this is great",  # no share/present object near "stop"
            "let's stop for a coffee break",
            "",
        ]:
            with self.subTest(utterance=u):
                self.assertFalse(is_stop_sharing(u), f"should NOT stop: {u!r}")

    def test_persona_alias_stop(self):
        aliases = ["Flash", "Prism", "PrismAI"]
        self.assertTrue(is_stop_sharing("Flash, stop", aliases))
        self.assertTrue(is_stop_sharing("stop Flash", aliases))
        self.assertTrue(is_stop_sharing("Prism stop it", aliases))
        # Without the alias list, a bare "<name>, stop" is not a recognized kill phrase.
        self.assertFalse(is_stop_sharing("Flash, stop"))
        # An alias mention with no stop verb is not a kill phrase.
        self.assertFalse(is_stop_sharing("Flash, pull up the PR", aliases))

    def test_empty_aliases_safe(self):
        self.assertTrue(is_stop_sharing("stop sharing", []))
        self.assertFalse(is_stop_sharing("what's next", ["Flash"]))


class RegistryPresentsFlagTests(unittest.TestCase):
    def setUp(self):
        from tools.registry import register_tool, _TOOLS
        self._TOOLS = _TOOLS

        async def _noop(_args, user_settings=None):
            return {"ok": True}

        register_tool(
            name="mock_presents",
            description="presents",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
            requires="sandbox_id",
            presents=True,
        )
        register_tool(
            name="mock_plain",
            description="plain",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
        )
        self._added = ["mock_presents", "mock_plain"]

    def tearDown(self):
        for name in self._added:
            self._TOOLS.pop(name, None)

    def test_presents_flag_stored(self):
        self.assertTrue(self._TOOLS["mock_presents"]["presents"])
        self.assertFalse(self._TOOLS["mock_plain"]["presents"])

    def test_is_presents_helper(self):
        from tools.registry import is_presents
        self.assertTrue(is_presents("mock_presents"))
        self.assertFalse(is_presents("mock_plain"))
        self.assertFalse(is_presents("does_not_exist"))

    def test_default_is_false_for_existing_tools(self):
        # Pre-existing tools registered without the flag must default to False,
        # so get_available_tools filtering semantics are unchanged.
        from tools.registry import is_presents
        self.assertFalse(is_presents("mock_plain"))

    def test_get_available_tools_semantics_unchanged(self):
        # The presents flag must not alter existing availability filtering:
        # requires-gated tool stays hidden without the credential, shown with it.
        from tools.registry import get_available_tools
        names_no_cred = {t["function"]["name"] for t in get_available_tools({})}
        self.assertNotIn("mock_presents", names_no_cred)
        self.assertIn("mock_plain", names_no_cred)

        names_with_cred = {
            t["function"]["name"]
            for t in get_available_tools({"sandbox_id": "sb_123"})
        }
        self.assertIn("mock_presents", names_with_cred)


if __name__ == "__main__":
    unittest.main()

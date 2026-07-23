# backend/tests/test_personas_dispatch.py
"""Whitelist + per-agent dispatch wrapper."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules.setdefault("supabase", fake)


_stub_supabase()


class WhitelistTests(unittest.TestCase):
    def setUp(self):
        # Reload analysis_service to defeat any test-ordering interaction
        # (some test earlier in the suite imports it before our edits land
        # in the in-memory module — the reload re-reads the source on disk).
        import importlib
        import analysis_service
        importlib.reload(analysis_service)

    def test_whitelist_has_all_agents(self):
        import analysis_service
        expected = {"summarizer", "decisions", "action_items", "sentiment",
                    "speaker_coach", "email_drafter", "health_score", "calendar_suggester",
                    "action_executor", "meeting_classifier", "content_analyst"}
        self.assertEqual(set(analysis_service.AGENT_PERSONA_WHITELIST), expected)

    def test_structured_agents_exclude_cheeky_and_socratic(self):
        import analysis_service
        for agent in ("decisions", "action_items", "sentiment", "speaker_coach",
                      "health_score", "calendar_suggester"):
            allowed = analysis_service.AGENT_PERSONA_WHITELIST[agent]
            self.assertNotIn("cheeky", allowed, f"{agent} should not allow cheeky")
            self.assertNotIn("socratic", allowed, f"{agent} should not allow socratic")
            self.assertNotIn("custom", allowed, f"{agent} should not allow custom")

    def test_freetext_agents_allow_everything(self):
        import analysis_service
        for agent in ("summarizer", "email_drafter"):
            allowed = analysis_service.AGENT_PERSONA_WHITELIST[agent]
            self.assertEqual(allowed, {"default", "concise", "formal", "cheeky", "socratic", "custom"})


class DispatchSetsContextvarPerAgent(unittest.TestCase):
    def test_tier1_node_sets_persona_for_allowed_agent(self):
        """summarizer is in AGENT_PERSONA_WHITELIST['cheeky'] → contextvar gets PRESETS['cheeky']."""
        import importlib
        import analysis_service
        importlib.reload(analysis_service)
        from agents import utils as agent_utils

        captured = {"persona_in_agent": None}

        async def fake_summarizer(transcript, meeting_type=""):
            captured["persona_in_agent"] = agent_utils._PERSONA_TEXT.get()
            return {"summary": "ok"}

        node = analysis_service._make_tier1_node("summarizer")
        state = {
            "transcript": "hi",
            "agents_to_run": ["summarizer"],
            "results": {},
            "context": {},
            "persona_preset": "cheeky",
            "persona_custom_prompt": None,
        }
        with patch.dict(analysis_service.AGENT_MAP,
                        {"summarizer": fake_summarizer}):
            asyncio.run(node(state))

        self.assertIn("dry wit", captured["persona_in_agent"])

    def test_tier1_node_falls_back_when_whitelist_denies(self):
        """action_items + cheeky → contextvar empty (fall back to default)."""
        import importlib
        import analysis_service
        importlib.reload(analysis_service)
        from agents import utils as agent_utils

        captured = {"persona_in_agent": None}

        async def fake_action_items(transcript):
            captured["persona_in_agent"] = agent_utils._PERSONA_TEXT.get()
            return {"action_items": []}

        node = analysis_service._make_tier1_node("action_items")
        state = {
            "transcript": "hi",
            "agents_to_run": ["action_items"],
            "results": {},
            "context": {},
            "persona_preset": "cheeky",
            "persona_custom_prompt": None,
        }
        with patch.dict(analysis_service.AGENT_MAP,
                        {"action_items": fake_action_items}):
            asyncio.run(node(state))

        self.assertEqual(captured["persona_in_agent"], "")

    def test_tier1_node_uses_custom_prompt_for_allowed_agent(self):
        """summarizer + custom → contextvar = custom prompt text."""
        import importlib
        import analysis_service
        importlib.reload(analysis_service)
        from agents import utils as agent_utils

        captured = {"persona_in_agent": None}

        async def fake_summarizer(transcript, meeting_type=""):
            captured["persona_in_agent"] = agent_utils._PERSONA_TEXT.get()
            return {"summary": "ok"}

        node = analysis_service._make_tier1_node("summarizer")
        state = {
            "transcript": "hi",
            "agents_to_run": ["summarizer"],
            "results": {},
            "context": {},
            "persona_preset": "custom",
            "persona_custom_prompt": "Talk like a pirate.",
        }
        with patch.dict(analysis_service.AGENT_MAP,
                        {"summarizer": fake_summarizer}):
            asyncio.run(node(state))

        self.assertEqual(captured["persona_in_agent"], "Talk like a pirate.")

    def test_tier2_node_also_applies_whitelist(self):
        """email_drafter (tier 2) + cheeky → contextvar gets cheeky text."""
        import importlib
        import analysis_service
        importlib.reload(analysis_service)
        from agents import utils as agent_utils

        captured = {"persona_in_agent": None}

        async def fake_email(transcript, ctx):
            captured["persona_in_agent"] = agent_utils._PERSONA_TEXT.get()
            return {"email": "ok"}

        node = analysis_service._make_tier2_node("email_drafter")
        state = {
            "transcript": "hi",
            "agents_to_run": ["email_drafter"],
            "results": {},
            "context": {"summary": ""},
            "persona_preset": "cheeky",
            "persona_custom_prompt": None,
        }
        with patch.dict(analysis_service.AGENT_MAP,
                        {"email_drafter": fake_email}):
            asyncio.run(node(state))

        self.assertIn("dry wit", captured["persona_in_agent"])

    def test_concurrent_agents_see_their_own_persona(self):
        """The production fan-out runs multiple agents in parallel via
        LangGraph's Send mechanism. Each dispatch node sets/resets the
        contextvar in its own task. If LangGraph ever stops creating a
        per-Send task and shares context across the fan-out, this test
        would fail — the agents would observe each other's persona values.

        Verifies the production isolation claim, not the lower-level
        contextvar-by-asyncio.gather property (covered in test_personas_contextvar)."""
        import importlib
        import analysis_service
        importlib.reload(analysis_service)
        from agents import utils as agent_utils

        captured: dict[str, str] = {}

        async def fake_summarizer(transcript, meeting_type=""):
            # Read AFTER awaiting a sleep so the scheduler has a chance to
            # interleave with the other agent's coroutine.
            await asyncio.sleep(0.005)
            captured["summarizer"] = agent_utils._PERSONA_TEXT.get()
            return {"summary": "ok"}

        async def fake_action_items(transcript):
            await asyncio.sleep(0.005)
            captured["action_items"] = agent_utils._PERSONA_TEXT.get()
            return {"action_items": []}

        # summarizer + cheeky → dry-wit text; action_items + cheeky →
        # falls back to "" via the whitelist. If the contextvar leaks
        # between the two parallel nodes, action_items will see "dry wit"
        # or summarizer will see "".
        n_sum = analysis_service._make_tier1_node("summarizer")
        n_ai = analysis_service._make_tier1_node("action_items")
        state = {
            "transcript": "hi",
            "agents_to_run": ["summarizer", "action_items"],
            "results": {},
            "context": {},
            "persona_preset": "cheeky",
            "persona_custom_prompt": None,
        }

        async def run_both():
            await asyncio.gather(n_sum(state), n_ai(state))

        with patch.dict(analysis_service.AGENT_MAP,
                        {"summarizer": fake_summarizer,
                         "action_items": fake_action_items}):
            asyncio.run(run_both())

        self.assertIn("dry wit", captured["summarizer"])
        self.assertEqual(captured["action_items"], "")


if __name__ == "__main__":
    unittest.main()

"""Tests for the LangGraph analysis pipeline efficiency knobs:
  - orchestrator fast-path: skip LLM call for transcripts ≥ N words
  - tier-2 context-only: email_drafter receives "" transcript when the flag
    is on, so it works from summary+decisions+action_items (context) alone

Both behaviors are flag-gated so the legacy path stays the rollback target.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import analysis_service  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────────────

def _state(transcript: str = "", context: dict = None, results: dict = None) -> dict:
    return {
        "transcript": transcript,
        "agents_to_run": [],
        "results": results or {},
        "context": context or {},
    }


# ── Orchestrator fast-path (#5) ─────────────────────────────────────────────

class OrchestratorSkipTests(unittest.TestCase):
    def setUp(self):
        self.prior_threshold = os.environ.get("PRISM_SKIP_ORCH_WORDS")
        os.environ["PRISM_SKIP_ORCH_WORDS"] = "10"  # tiny threshold for tests

    def tearDown(self):
        if self.prior_threshold is None:
            os.environ.pop("PRISM_SKIP_ORCH_WORDS", None)
        else:
            os.environ["PRISM_SKIP_ORCH_WORDS"] = self.prior_threshold

    def test_long_transcript_skips_orchestrator_llm_call(self):
        long_transcript = "word " * 20  # 20 words, above threshold
        with patch.object(analysis_service.orchestrator, "run_orchestrator",
                          new=AsyncMock(return_value=["summarizer"])) as mocked:
            out = asyncio.run(analysis_service._orchestrator_node(_state(long_transcript)))

        mocked.assert_not_called()
        # All agents queued — no orchestrator filtering happened.
        self.assertEqual(set(out["agents_to_run"]), set(analysis_service.AGENT_MAP.keys()))

    def test_short_transcript_invokes_orchestrator(self):
        short_transcript = "tiny meeting"  # 2 words, below threshold
        with patch.object(analysis_service.orchestrator, "run_orchestrator",
                          new=AsyncMock(return_value=["summarizer", "decisions"])) as mocked:
            out = asyncio.run(analysis_service._orchestrator_node(_state(short_transcript)))

        mocked.assert_called_once()
        self.assertEqual(out["agents_to_run"], ["summarizer", "decisions"])

    def test_empty_transcript_invokes_orchestrator(self):
        # An empty transcript has 0 words — below any positive threshold,
        # so the orchestrator runs (or rather, the orchestrator gets a chance
        # to decide on the empty case).
        with patch.object(analysis_service.orchestrator, "run_orchestrator",
                          new=AsyncMock(return_value=["summarizer"])) as mocked:
            asyncio.run(analysis_service._orchestrator_node(_state("")))
        mocked.assert_called_once()

    def test_threshold_zero_always_skips(self):
        os.environ["PRISM_SKIP_ORCH_WORDS"] = "0"
        with patch.object(analysis_service.orchestrator, "run_orchestrator",
                          new=AsyncMock(return_value=[])) as mocked:
            out = asyncio.run(analysis_service._orchestrator_node(_state("anything")))
        mocked.assert_not_called()
        self.assertEqual(set(out["agents_to_run"]), set(analysis_service.AGENT_MAP.keys()))

    def test_orchestrator_filters_to_known_agents(self):
        # Sanity: orchestrator returning a bogus name doesn't leak into the run list.
        with patch.object(analysis_service.orchestrator, "run_orchestrator",
                          new=AsyncMock(return_value=["summarizer", "made_up_agent"])):
            out = asyncio.run(analysis_service._orchestrator_node(_state("short")))
        self.assertIn("summarizer", out["agents_to_run"])
        self.assertNotIn("made_up_agent", out["agents_to_run"])


# ── Tier-2 context-only (#4) ────────────────────────────────────────────────

class Tier2ContextOnlyTests(unittest.TestCase):
    def setUp(self):
        self.prior_flag = os.environ.get("PRISM_EMAIL_FROM_CONTEXT")
        os.environ["PRISM_EMAIL_FROM_CONTEXT"] = "1"

    def tearDown(self):
        if self.prior_flag is None:
            os.environ.pop("PRISM_EMAIL_FROM_CONTEXT", None)
        else:
            os.environ["PRISM_EMAIL_FROM_CONTEXT"] = self.prior_flag

    def test_email_drafter_node_passes_empty_transcript_when_flag_on(self):
        node = analysis_service._make_tier2_node("email_drafter")
        ctx = {"summary": "We aligned on Q4.", "decisions": [], "action_items": []}
        captured = {}

        async def fake_email(transcript, context):
            captured["transcript"] = transcript
            captured["context"] = context
            return {"follow_up_email": {"subject": "Q4 sync", "body": "..."}}

        with patch.dict(analysis_service.AGENT_MAP, {"email_drafter": fake_email}):
            asyncio.run(node(_state(transcript="full 5000-token transcript", context=ctx)))

        self.assertEqual(captured["transcript"], "", "email_drafter must receive empty transcript")
        self.assertEqual(captured["context"], ctx)

    def test_email_drafter_receives_transcript_when_flag_off(self):
        os.environ["PRISM_EMAIL_FROM_CONTEXT"] = "0"
        node = analysis_service._make_tier2_node("email_drafter")
        captured = {}

        async def fake_email(transcript, context):
            captured["transcript"] = transcript
            return {"follow_up_email": {"subject": "", "body": ""}}

        with patch.dict(analysis_service.AGENT_MAP, {"email_drafter": fake_email}):
            asyncio.run(node(_state(transcript="meaningful transcript", context={})))

        self.assertEqual(captured["transcript"], "meaningful transcript")

    def test_health_score_always_receives_full_transcript(self):
        node = analysis_service._make_tier2_node("health_score")
        captured = {}

        async def fake_health(transcript, context):
            captured["transcript"] = transcript
            return {"health_score": {"score": 80}}

        with patch.dict(analysis_service.AGENT_MAP, {"health_score": fake_health}):
            asyncio.run(node(_state(transcript="full transcript", context={"summary": "x"})))

        self.assertEqual(captured["transcript"], "full transcript",
                         "health_score reads behavioural signal from raw transcript — must NOT be stripped")

    def test_calendar_suggester_always_receives_full_transcript(self):
        node = analysis_service._make_tier2_node("calendar_suggester")
        captured = {}

        async def fake_cal(transcript, context):
            captured["transcript"] = transcript
            return {"calendar_suggestion": {"recommended": False}}

        with patch.dict(analysis_service.AGENT_MAP, {"calendar_suggester": fake_cal}):
            asyncio.run(node(_state(transcript="let's meet Tuesday at 3pm", context={})))

        self.assertEqual(captured["transcript"], "let's meet Tuesday at 3pm",
                         "calendar_suggester needs raw transcript for date extraction — must NOT be stripped")

    def test_tier2_node_swallows_agent_exception(self):
        # If a tier-2 agent raises, the node must return {} for that agent so
        # the rest of the pipeline doesn't crash. Pre-existing contract — kept.
        node = analysis_service._make_tier2_node("email_drafter")

        async def boom(*_a, **_k):
            raise RuntimeError("agent crashed")

        with patch.dict(analysis_service.AGENT_MAP, {"email_drafter": boom}):
            out = asyncio.run(node(_state(transcript="x")))

        self.assertEqual(out, {"results": {"email_drafter": {}}})


# ── Email drafter input-construction regression tests ──────────────────────

class EmailDrafterInputTests(unittest.TestCase):
    """email_drafter is called with both shapes:
      - analysis pipeline: transcript="" + populated context
      - chat_routes re-run: transcript=full + context={}
    Both must produce a useful user_content string. Regression-test by
    inspecting what llm_call gets handed."""

    def _run(self, transcript: str, context: dict):
        from agents import email_drafter

        captured = {}

        async def fake_llm(system, user, temperature=0.7):
            captured["user"] = user
            return '{"follow_up_email": {"subject": "ok", "body": "ok"}}'

        with patch.object(email_drafter, "llm_call", new=fake_llm):
            asyncio.run(email_drafter.run(transcript, context))
        return captured.get("user", "")

    def test_context_only_input_omits_transcript_header(self):
        user_content = self._run(
            "",
            {
                "summary": "Aligned on Q4 plan.",
                "decisions": [{"decision": "Ship Friday"}],
                "action_items": [{"task": "Draft RFC", "owner": "Sam"}],
            },
        )
        self.assertIn("Meeting summary", user_content)
        self.assertIn("Ship Friday", user_content)
        self.assertNotIn("Transcript:\n", user_content,
                         "empty transcript must NOT produce a dangling 'Transcript:' section")

    def test_transcript_only_input_preserves_chat_routes_path(self):
        # chat_routes flow: full transcript + [User instruction: ...] suffix,
        # empty context. The current behaviour must be unchanged.
        user_content = self._run(
            "Alice: hi\nBob: hey\n\n[User instruction: make it formal]",
            {},
        )
        self.assertIn("Transcript:", user_content)
        self.assertIn("[User instruction: make it formal]", user_content)
        self.assertNotIn("Meeting summary", user_content)

    def test_both_inputs_produce_combined_content(self):
        user_content = self._run("Alice: hi\nBob: hey", {"summary": "Greetings."})
        self.assertIn("Meeting summary: Greetings.", user_content)
        self.assertIn("Transcript:", user_content)
        # Order matters: context first, then transcript (current behaviour).
        self.assertLess(user_content.index("Meeting summary"), user_content.index("Transcript:"))

    def test_empty_input_fallback_does_not_explode(self):
        # Defensive: empty transcript AND empty context → still produces a
        # non-empty user message (so the LLM call doesn't 400).
        user_content = self._run("", {})
        self.assertTrue(user_content.strip())


if __name__ == "__main__":
    unittest.main()

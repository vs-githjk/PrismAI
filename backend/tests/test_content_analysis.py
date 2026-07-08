"""Tests for the meeting-type content-analysis feature:
  - meeting_classifier: parses/clamps type, safe fallback
  - content_analyst: NO LLM for standard; deep-dive + score clamping for pitch/interview
  - orchestrator: classifier only when auto; content_analyst always routed
  - barrier: resolves explicit vs detected type into context
  - _state_to_result: keeps content_analysis only for a specialized type with a rubric
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import analysis_service  # noqa: E402
from agents import content_analyst, meeting_classifier  # noqa: E402
from agents.orchestrator import run_orchestrator  # noqa: E402


def _fake_llm(payload):
    async def _f(system, user):
        return json.dumps(payload)
    return _f


# ── meeting_classifier ───────────────────────────────────────────────────────

class ClassifierTests(unittest.TestCase):
    def test_parses_valid_type(self):
        with patch.object(meeting_classifier, "llm_call",
                          new=_fake_llm({"meeting_type": "pitch", "confidence": 0.9, "reason": "demo"})):
            out = asyncio.run(meeting_classifier.run("A: we're building X"))
        self.assertEqual(out["meeting_type"], "pitch")
        # Only the resolved type is returned — diagnostics (confidence/reason) are
        # logged, not surfaced, so the streamed result stays clean.
        self.assertEqual(set(out.keys()), {"meeting_type"})

    def test_unknown_type_falls_back_to_standard(self):
        with patch.object(meeting_classifier, "llm_call",
                          new=_fake_llm({"meeting_type": "wedding_toast", "confidence": 1})):
            out = asyncio.run(meeting_classifier.run("A: hi"))
        self.assertEqual(out["meeting_type"], "standard")

    def test_bad_json_returns_default(self):
        async def _boom(system, user):
            return "not json at all"
        with patch.object(meeting_classifier, "llm_call", new=_boom):
            out = asyncio.run(meeting_classifier.run("A: hi"))
        self.assertEqual(out, {"meeting_type": "standard"})


# ── content_analyst ──────────────────────────────────────────────────────────

class ContentAnalystTests(unittest.TestCase):
    def test_standard_makes_no_llm_call(self):
        called = {"n": 0}
        async def _tripwire(system, user):
            called["n"] += 1
            return "{}"
        with patch.object(content_analyst, "llm_call", new=_tripwire):
            out = asyncio.run(content_analyst.run("A: routine sync", {"meeting_type": "standard"}))
        self.assertEqual(called["n"], 0, "standard meetings must not invoke the LLM")
        self.assertEqual(out["content_analysis"], {"type": "standard"})

    def test_missing_type_treated_as_standard(self):
        called = {"n": 0}
        async def _tripwire(system, user):
            called["n"] += 1
            return "{}"
        with patch.object(content_analyst, "llm_call", new=_tripwire):
            out = asyncio.run(content_analyst.run("A: hi", {}))
        self.assertEqual(called["n"], 0)
        self.assertEqual(out["content_analysis"]["type"], "standard")

    def test_pitch_builds_analysis_and_clamps_scores(self):
        payload = {
            "headline_score": 250,  # out of range → clamp to 100
            "verdict": "Strong.",
            "rubric": [{"dimension": "Value prop", "score": -5, "notes": "clear", "evidence": "q"}],
            "strengths": ["clarity"], "weaknesses": ["no ask"],
            "key_moments": [{"label": "The ask", "quote": "buy now", "note": "weak"}],
        }
        with patch.object(content_analyst, "llm_call", new=_fake_llm(payload)):
            out = asyncio.run(content_analyst.run("A: pitch", {"meeting_type": "pitch"}))
        ca = out["content_analysis"]
        self.assertEqual(ca["type"], "pitch")
        self.assertEqual(ca["headline_score"], 100)
        self.assertEqual(ca["rubric"][0]["score"], 0)  # clamped up from -5
        self.assertEqual(ca["score_label"], "Pitch strength")
        self.assertEqual(len(ca["key_moments"]), 1)

    def test_job_interview_uses_readiness_label(self):
        payload = {"headline_score": 70, "rubric": [{"dimension": "STAR", "score": 60}]}
        with patch.object(content_analyst, "llm_call", new=_fake_llm(payload)):
            out = asyncio.run(content_analyst.run("A: interview", {"meeting_type": "interview_job"}))
        self.assertEqual(out["content_analysis"]["score_label"], "Candidate readiness")

    def test_parses_json_with_trailing_prose(self):
        # The model sometimes returns valid JSON then keeps writing markdown
        # commentary → json.loads 'Extra data'. _parse_json must recover it.
        async def _prose(system, user):
            return ('```json\n{"headline_score": 70, "verdict": "ok",'
                    ' "rubric": [{"dimension": "Clarity", "score": 70}]}\n```\n\n'
                    '**Strengths to keep:** the model rambled on after the JSON.')
        with patch.object(content_analyst, "llm_call", new=_prose):
            out = asyncio.run(content_analyst.run("A: pitch", {"meeting_type": "pitch"}))
        ca = out["content_analysis"]
        self.assertEqual(ca["type"], "pitch")
        self.assertEqual(ca["headline_score"], 70)
        self.assertEqual(len(ca["rubric"]), 1)

    def test_bad_json_returns_shell_with_type(self):
        async def _boom(system, user):
            return "}{ broken"
        with patch.object(content_analyst, "llm_call", new=_boom):
            out = asyncio.run(content_analyst.run("A: pitch", {"meeting_type": "pitch"}))
        ca = out["content_analysis"]
        self.assertEqual(ca["type"], "pitch")
        self.assertEqual(ca["rubric"], [])


# ── orchestrator routing ─────────────────────────────────────────────────────

class RoutingTests(unittest.TestCase):
    TWO_SPEAKER = "Alice: hi\nBob: hey"

    def test_auto_adds_classifier(self):
        self.assertIn("meeting_classifier", run_orchestrator(self.TWO_SPEAKER))
        self.assertIn("meeting_classifier", run_orchestrator(self.TWO_SPEAKER, "auto"))

    def test_explicit_type_skips_classifier(self):
        for t in ("standard", "pitch", "interview_content", "interview_job"):
            self.assertNotIn("meeting_classifier", run_orchestrator(self.TWO_SPEAKER, t),
                             f"explicit '{t}' should not run the classifier")

    def test_content_analyst_always_routed(self):
        self.assertIn("content_analyst", run_orchestrator(self.TWO_SPEAKER))
        self.assertIn("content_analyst", run_orchestrator(self.TWO_SPEAKER, "standard"))
        self.assertIn("content_analyst", run_orchestrator(self.TWO_SPEAKER, "pitch"))

    def test_content_analyst_not_context_only(self):
        # It needs the full transcript for evidence quotes.
        self.assertNotIn("content_analyst", analysis_service.TIER2_CONTEXT_ONLY)


# ── barrier type resolution ──────────────────────────────────────────────────

def _barrier(state):
    return asyncio.run(analysis_service._tier1_barrier(state))


class BarrierTypeResolutionTests(unittest.TestCase):
    def test_explicit_type_wins(self):
        state = {"transcript": "x", "meeting_type": "pitch", "results": {
            "meeting_classifier": {"meeting_type": "interview_job"}}}
        out = _barrier(state)
        self.assertEqual(out["context"]["meeting_type"], "pitch")

    def test_auto_uses_classifier(self):
        state = {"transcript": "x", "meeting_type": "auto", "results": {
            "meeting_classifier": {"meeting_type": "interview_content"}}}
        out = _barrier(state)
        self.assertEqual(out["context"]["meeting_type"], "interview_content")

    def test_invalid_resolves_to_standard(self):
        state = {"transcript": "x", "meeting_type": "", "results": {
            "meeting_classifier": {"meeting_type": "nonsense"}}}
        out = _barrier(state)
        self.assertEqual(out["context"]["meeting_type"], "standard")

    def test_no_classifier_defaults_standard(self):
        out = _barrier({"transcript": "x", "meeting_type": "", "results": {}})
        self.assertEqual(out["context"]["meeting_type"], "standard")


# ── result assembly ──────────────────────────────────────────────────────────

class StateToResultTests(unittest.TestCase):
    def _state(self, ctx_type, ca):
        return {"context": {"meeting_type": ctx_type},
                "results": {"content_analyst": {"content_analysis": ca}} if ca is not None else {}}

    def test_pitch_with_rubric_is_kept(self):
        ca = {"type": "pitch", "headline_score": 80, "rubric": [{"dimension": "d", "score": 80}]}
        res = analysis_service._state_to_result(self._state("pitch", ca))
        self.assertEqual(res["meeting_type"], "pitch")
        self.assertEqual(res["content_analysis"]["headline_score"], 80)
        self.assertIn("content_analyst", res["agents_run"])

    def test_standard_type_marker_is_dropped(self):
        res = analysis_service._state_to_result(self._state("standard", {"type": "standard"}))
        self.assertEqual(res["meeting_type"], "standard")
        self.assertIsNone(res["content_analysis"])
        self.assertNotIn("content_analyst", res["agents_run"])

    def test_specialized_type_without_rubric_is_dropped(self):
        # Fallback shell (LLM failed) → no misleading empty card.
        res = analysis_service._state_to_result(self._state("pitch", {"type": "pitch", "rubric": []}))
        self.assertIsNone(res["content_analysis"])
        self.assertEqual(res["meeting_type"], "pitch")  # type still surfaced for badging


# ── /agent override re-run path ──────────────────────────────────────────────

class AgentReRunTests(unittest.TestCase):
    """The type-override feature re-runs content_analyst via POST /agent; the
    route must thread meeting_type into the Tier-2 context or the deep-dive
    would treat the meeting as standard and return no card."""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import chat_routes
        app = FastAPI()
        app.include_router(chat_routes.create_chat_router(openai_client=object()))
        return TestClient(app)

    def test_agent_threads_meeting_type_to_content_analyst(self):
        # Patch the names chat_routes actually uses (other suites stub the whole
        # analysis_service module into sys.modules, so bind at the chat_routes
        # namespace to stay order-independent). No AGENT_MAP spy: we prove the
        # threading by the RESULT — a pitch card only appears if context.meeting_type
        # reached content_analyst; otherwise it early-returns {type: standard}.
        import chat_routes
        captured = {}
        async def _fake(system, user):
            return json.dumps({"headline_score": 66, "rubric": [{"dimension": "d", "score": 66}]})

        async def _spy_run(transcript, context=None):
            captured["meeting_type"] = (context or {}).get("meeting_type")
            return await content_analyst.run(transcript, context)

        with patch.object(content_analyst, "llm_call", new=_fake), \
             patch.dict(chat_routes.AGENT_MAP, {"content_analyst": _spy_run}, clear=False), \
             patch.object(chat_routes, "TIER2_AGENTS", frozenset({"content_analyst"})), \
             patch.object(chat_routes, "_persona_text_for_agent", lambda *a, **k: ""):
            client = self._client()
            resp = client.post("/agent", json={
                "agent": "content_analyst",
                "transcript": "Alice: our pitch deck",
                "meeting_type": "pitch",
                "result": {"summary": "s"},
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured["meeting_type"], "pitch")
        body = resp.json()
        self.assertEqual(body["content_analysis"]["type"], "pitch")
        self.assertEqual(body["content_analysis"]["headline_score"], 66)


if __name__ == "__main__":
    unittest.main()

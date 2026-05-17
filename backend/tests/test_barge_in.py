import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

# pysbd is an optional runtime dep; stub it for the test runner. Real behavior
# of StreamingSegmenter/TtsDispatcher is exercised by test_voice_pipeline.
if "pysbd" not in sys.modules:
    _fake_pysbd = types.ModuleType("pysbd")
    class _FakeSegmenter:
        def __init__(self, *_a, **_k): pass
        def segment(self, text): return [text]
    _fake_pysbd.Segmenter = _FakeSegmenter
    sys.modules["pysbd"] = _fake_pysbd

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")


import perception_state


def _run(coro):
    return asyncio.run(coro)


class CousinAndStopRecognitionTests(unittest.TestCase):
    def test_cousins_recognized_across_phonetic_variants(self):
        for variant in ("prism", "Prism", "PRISM", "prism ai", "prison",
                        "brism", "prisma", "prasim"):
            text = f"Hey {variant}, can you check the weather?"
            self.assertTrue(
                perception_state.has_cousin(text),
                f"failed to recognize cousin in: {text!r}",
            )

    def test_non_cousin_text_does_not_match(self):
        for text in ("Bob and Alice talked about Q3.",
                     "How is everyone today?",
                     "The presentation is on Tuesday."):
            self.assertFalse(perception_state.has_cousin(text), text)

    def test_stop_command_recognized(self):
        for variant in (
            "Prism, stop.",
            "prism stop",
            "Prism, cancel that.",
            "Prism, nevermind.",
            "Prism, never mind.",
            "Prism, shut up.",
            "Prism, quiet.",
            "Prison, stop.",       # phonetic cousin still cancels
            "Brism, cancel that.",
        ):
            self.assertTrue(
                perception_state.is_stop_command(variant),
                f"failed to recognize stop command: {variant!r}",
            )

    def test_wait_and_hold_on_are_not_stop_commands(self):
        # "wait" / "hold on" are turn-taking signals, not interrupts.
        # Phase B spec deliberately excludes them.
        for variant in (
            "Prism, wait, can you also check the calendar?",
            "Prism, hold on a second.",
            "Prism, hold that thought.",
        ):
            self.assertFalse(
                perception_state.is_stop_command(variant),
                f"should NOT trigger stop: {variant!r}",
            )

    def test_normal_commands_are_not_stop_commands(self):
        for variant in (
            "Prism, what's the weather?",
            "Prism, send an email to John.",
        ):
            self.assertFalse(perception_state.is_stop_command(variant), variant)


class StableSamplingTests(unittest.TestCase):
    def test_same_text_always_samples_or_not(self):
        # Determinism: bucket only depends on content.
        for text in ("hello world", "foo bar baz", "another text"):
            v1 = perception_state.should_sample(text, fraction_pct=10)
            v2 = perception_state.should_sample(text, fraction_pct=10)
            self.assertEqual(v1, v2)

    def test_100_percent_always_samples(self):
        self.assertTrue(perception_state.should_sample("x", fraction_pct=100))

    def test_0_percent_never_samples(self):
        self.assertFalse(perception_state.should_sample("x", fraction_pct=0))

    def test_empty_text_never_samples(self):
        self.assertFalse(perception_state.should_sample("", fraction_pct=50))


class SpeakingSessionLifecycleTests(unittest.TestCase):
    def test_supersede_cancels_old_session(self):
        async def go():
            state: dict = {}
            old = perception_state.SpeakingSession()
            await perception_state.supersede_session(state, old)
            self.assertFalse(old.is_cancelled)

            new = perception_state.SpeakingSession()
            returned = await perception_state.supersede_session(state, new)
            self.assertIs(returned, old)
            self.assertTrue(old.is_cancelled)
            self.assertFalse(new.is_cancelled)
            self.assertIs(state["speaking_session"], new)
        _run(go())

    def test_clear_session_only_clears_if_unchanged(self):
        async def go():
            state: dict = {}
            s1 = perception_state.SpeakingSession()
            await perception_state.supersede_session(state, s1)
            # A second session takes over; clearing s1 should be a no-op.
            s2 = perception_state.SpeakingSession()
            await perception_state.supersede_session(state, s2)
            await perception_state.clear_session(state, s1)
            self.assertIs(state["speaking_session"], s2)
            # Clearing s2 succeeds.
            await perception_state.clear_session(state, s2)
            self.assertIsNone(state.get("speaking_session"))
        _run(go())

    def test_cancel_is_idempotent(self):
        s = perception_state.SpeakingSession()
        s.chunks_generated = 5
        s.cancel()
        self.assertTrue(s.is_cancelled)
        self.assertEqual(s.cancelled_at_chunk, 5)
        s.cancel()  # no-op
        self.assertEqual(s.cancelled_at_chunk, 5)


class CounterScaffoldingTests(unittest.TestCase):
    def test_cancel_site_counters_in_operational_split(self):
        state: dict = {}
        for site in ("llm_read", "segmenter", "upload", "dispatch"):
            perception_state.bump(state, f"cancel_at_{site}")
        op = perception_state.operational_counters(state)
        for site in ("llm_read", "segmenter", "upload", "dispatch"):
            self.assertEqual(op[f"cancel_at_{site}"], 1)

    def test_tts_chunks_wasted_counter_present(self):
        state: dict = {}
        perception_state.bump(state, "tts_chunks_generated_but_cancelled", 7)
        op = perception_state.operational_counters(state)
        self.assertEqual(op["tts_chunks_generated_but_cancelled"], 7)


class PartialDropCousinCarveoutTests(unittest.TestCase):
    """A.2 partial-drop must NOT swallow cousin-bearing partials. Stop
    commands arrive as partials ~300-1000ms before the final; dropping
    them at A.2 bakes in unfixable cancellation latency."""

    def test_partial_with_cousin_is_kept(self):
        # We test the perception_state predicate composition the way the
        # handler does: is_partial says drop, has_cousin says keep.
        text = "Prism, stop."
        seg_partial = {"is_final": False, "words": [{"text": w} for w in text.split()]}
        self.assertTrue(perception_state.is_partial(seg_partial, None))
        self.assertTrue(perception_state.has_cousin(text))

    def test_partial_without_cousin_is_dropped(self):
        text = "yeah sounds good to me let me check that doc real quick"
        seg_partial = {"is_final": False, "words": [{"text": w} for w in text.split()]}
        self.assertTrue(perception_state.is_partial(seg_partial, None))
        self.assertFalse(perception_state.has_cousin(text))

    def test_final_with_cousin_is_not_partial(self):
        seg_final = {"is_final": True, "words": [{"text": "Prism"}]}
        self.assertFalse(perception_state.is_partial(seg_final, None))


class StopCommandRouteIntegrationTests(unittest.TestCase):
    """Tighter integration: confirm _session_cancelled() + supersede
    interact correctly when a stop command arrives during an active session."""

    def test_stop_cancels_existing_session_and_records_waste(self):
        async def go():
            import realtime_routes
            state: dict = {}
            session = perception_state.SpeakingSession()
            session.chunks_generated = 3
            session.chunks_uploaded = 1
            await perception_state.supersede_session(state, session)

            # Mimic the stop-command-detection path.
            session.cancel()
            perception_state.bump(state, "stop_command_fired")

            # First cancel-site detection records the waste.
            self.assertTrue(realtime_routes._session_cancelled(state, "upload"))
            op = perception_state.operational_counters(state)
            self.assertEqual(op["cancel_at_upload"], 1)
            self.assertEqual(op["cancel_count"], 1)
            self.assertEqual(op["tts_chunks_generated_but_cancelled"], 2)  # 3-1

            # A second site detecting the same cancellation must NOT double-count waste.
            self.assertTrue(realtime_routes._session_cancelled(state, "llm_read"))
            op2 = perception_state.operational_counters(state)
            self.assertEqual(op2["cancel_at_llm_read"], 1)
            self.assertEqual(op2["cancel_count"], 2)
            self.assertEqual(op2["tts_chunks_generated_but_cancelled"], 2)  # unchanged
        _run(go())

    def test_upload_site_stamps_last_upload_aborted_mono(self):
        # The latency timeline's third timestamp closes when the upload site
        # is the one detecting the cancellation.
        async def go():
            import realtime_routes
            state: dict = {"last_cancel_timeline": {
                "detected_mono": 100.0,
                "session_cancelled_mono": 100.0,
                "last_upload_aborted_mono": None,
                "reason": "stop_command",
            }}
            session = perception_state.SpeakingSession()
            session.chunks_generated = 2
            await perception_state.supersede_session(state, session)
            session.cancel()
            self.assertTrue(realtime_routes._session_cancelled(state, "upload"))
            tl = state["last_cancel_timeline"]
            self.assertIsNotNone(tl["last_upload_aborted_mono"])
            self.assertGreaterEqual(tl["last_upload_aborted_mono"], 100.0)

            # A non-upload site that fires LATER must not overwrite the stamp.
            stamp = tl["last_upload_aborted_mono"]
            self.assertTrue(realtime_routes._session_cancelled(state, "segmenter"))
            self.assertEqual(tl["last_upload_aborted_mono"], stamp)
        _run(go())


if __name__ == "__main__":
    unittest.main()

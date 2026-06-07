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


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()

    def test_no_warmup_before_meeting_start(self):
        import ambient_loop
        self.assertFalse(ambient_loop.past_warmup(self.s))

    def test_no_warmup_without_substance(self):
        import ambient_loop
        self.s["meeting_start_ts"] = 1000.0
        self.assertFalse(ambient_loop.past_warmup(self.s))

    def test_warmup_with_a_decision(self):
        import ambient_loop
        self.s["meeting_start_ts"] = 1000.0
        self.s["live_decisions"] = [{"text": "ship friday", "speaker": "A", "ts": 1.0}]
        self.assertTrue(ambient_loop.past_warmup(self.s))

    def test_warmup_with_enough_entities(self):
        import ambient_loop
        from collections import Counter
        self.s["meeting_start_ts"] = 1000.0
        self.s["live_entities"] = Counter({"Q3": 2, "Migration": 1, "Budget": 1, "Vendor": 1, "Roadmap": 1})
        self.assertTrue(ambient_loop.past_warmup(self.s))


class MuteCommandTests(unittest.TestCase):
    def test_mute_phrases(self):
        import ambient_loop
        for t in ["Prism, stay quiet", "prism be quiet", "Prism, mute yourself", "prism stop talking"]:
            self.assertEqual(ambient_loop.detect_mute_command(t), "mute", t)

    def test_unmute_phrases(self):
        import ambient_loop
        for t in ["Prism, you can chime in", "prism chime in again", "Prism, you can talk", "prism unmute"]:
            self.assertEqual(ambient_loop.detect_mute_command(t), "unmute", t)

    def test_non_mute(self):
        import ambient_loop
        for t in ["let's discuss the budget", "what time is it", ""]:
            self.assertIsNone(ambient_loop.detect_mute_command(t))


class OfferGenTests(unittest.TestCase):
    def test_make_offer_includes_subject(self):
        import ambient_loop
        line = ambient_loop.make_offer("the vendor forecast")
        self.assertIn("vendor forecast", line)
        self.assertIn("?", line)

    def test_make_offer_empty_subject_is_generic(self):
        import ambient_loop
        line = ambient_loop.make_offer("")
        self.assertTrue(line.strip().endswith("?"))
        self.assertGreater(len(line), 10)

    def test_subject_dedup(self):
        import ambient_loop
        s = meeting_memory.get_initial_memory_state()
        self.assertFalse(ambient_loop.subject_already_offered(s, "Vendor Forecast"))
        ambient_loop.record_offered_subject(s, "Vendor Forecast")
        self.assertTrue(ambient_loop.subject_already_offered(s, "vendor forecast"))
        self.assertFalse(ambient_loop.subject_already_offered(s, "meteor timing"))


class ParseConsentTests(unittest.TestCase):
    def test_yes(self):
        import ambient_loop
        for r in ["YES", "yes", "Answer: YES", '{"consent":"yes"}', "yes, go ahead"]:
            self.assertEqual(ambient_loop.parse_consent(r), "yes", r)

    def test_no(self):
        import ambient_loop
        for r in ["NO", "no", "Answer: NO", '{"consent":"no"}']:
            self.assertEqual(ambient_loop.parse_consent(r), "no", r)

    def test_unclear_failsafe(self):
        import ambient_loop
        for r in ["", None, "unclear", "maybe", "I don't know", "banana"]:
            self.assertEqual(ambient_loop.parse_consent(r), "unclear", r)


class ClassifyConsentTests(unittest.IsolatedAsyncioTestCase):
    async def test_classify_yes(self):
        import ambient_loop
        async def fake(system, user):
            return "YES"
        with mock.patch.object(ambient_loop, "_call_consent_model", fake):
            self.assertEqual(await ambient_loop.classify_consent("vendor forecast", "yeah go ahead"), "yes")

    async def test_classify_error_is_unclear(self):
        import ambient_loop
        async def boom(system, user):
            raise RuntimeError("down")
        with mock.patch.object(ambient_loop, "_call_consent_model", boom):
            self.assertEqual(await ambient_loop.classify_consent("x", "sure"), "unclear")


class ParseOfferTests(unittest.TestCase):
    def test_clean(self):
        import ambient_loop
        out = ambient_loop.parse_offer_output('{"offer": true, "subject": "vendor forecast", "confidence": 0.8, "reason": "x"}')
        self.assertTrue(out["offer"])
        self.assertEqual(out["subject"], "vendor forecast")
        self.assertEqual(out["confidence"], 0.8)

    def test_fenced_and_prose(self):
        import ambient_loop
        out = ambient_loop.parse_offer_output('```json\n{"offer": false, "subject": "", "confidence": 0.1, "reason": "small talk"}\n```')
        self.assertFalse(out["offer"])

    def test_garbage_failsafe(self):
        import ambient_loop
        for bad in ["", None, "{nope", "{}", '{"subject":"x"}']:
            out = ambient_loop.parse_offer_output(bad)
            self.assertFalse(out["offer"])

    def test_confidence_clamped(self):
        import ambient_loop
        out = ambient_loop.parse_offer_output('{"offer": true, "subject": "x", "confidence": 9}')
        self.assertEqual(out["confidence"], 1.0)


class OfferDeciderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["transcript_buffer"] = ["Abhinav: do you wanna check the vendor forecast?"]

    async def test_offer_decider_parses(self):
        import ambient_loop
        async def fake(system, user):
            return '{"offer": true, "subject": "vendor forecast", "confidence": 0.82, "reason": "open topic"}'
        with mock.patch.object(ambient_loop, "_call_offer_model", fake):
            out = await ambient_loop.offer_decider(self.s)
        self.assertTrue(out["offer"])
        self.assertEqual(out["subject"], "vendor forecast")

    async def test_offer_decider_error_failsafe(self):
        import ambient_loop
        async def boom(system, user):
            raise RuntimeError("down")
        with mock.patch.object(ambient_loop, "_call_offer_model", boom):
            out = await ambient_loop.offer_decider(self.s)
        self.assertFalse(out["offer"])

    def test_offer_decider_model_default(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ambient_loop.offer_decider_model(), "llama-3.3-70b-versatile")


if __name__ == "__main__":
    unittest.main()

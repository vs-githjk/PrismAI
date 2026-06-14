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
            self.assertEqual(ambient_loop.offer_decider_model(), "gpt-4o-mini")


class InterjectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["transcript_buffer"] = ["Abhinav: do you wanna check the vendor forecast?"]
        self.s["meeting_start_ts"] = 1000.0
        self.s["live_decisions"] = [{"text": "ship friday", "speaker": "A", "ts": 1.0}]  # past warmup
        self.offered = []
        self.delivered = []

    async def _speak_offer(self, bot_id, text):
        self.offered.append(text)
        return True

    async def _speak_offer_talkedover(self, bot_id, text):
        self.offered.append(text)
        return False

    async def _run_delivery(self, bot_id, subject, speaker):
        self.delivered.append(subject)
        return f"Here's what I found about {subject}."

    def _patch(self, *, pre=True, offer=True, subject="vendor forecast", conf=0.8, consent="unclear"):
        import ambient_loop
        async def fake_decide(state):
            return {"respond": pre, "confidence": 0.9, "reason": ""}
        async def fake_offer(state):
            return {"offer": offer, "subject": subject, "confidence": conf, "reason": ""}
        async def fake_consent(subj, utt):
            return consent
        return (
            mock.patch.object(ambient_loop, "decide", fake_decide),
            mock.patch.object(ambient_loop, "offer_decider", fake_offer),
            mock.patch.object(ambient_loop, "classify_consent", fake_consent),
        )

    async def _interject(self, text, speaker="Abhinav", now=5000.0, speak=None):
        import ambient_loop
        return await ambient_loop.interject(
            "bot1", self.s, text, speaker,
            speak_offer=speak or self._speak_offer, run_delivery=self._run_delivery, now=now,
        )

    # ── mute ──
    async def test_mute_command(self):
        out = await self._interject("Prism, stay quiet")
        self.assertEqual(out["action"], "muted")
        self.assertTrue(self.s["muted"])

    async def test_unmute_command(self):
        self.s["muted"] = True
        out = await self._interject("Prism, chime in again")
        self.assertEqual(out["action"], "unmuted")
        self.assertFalse(self.s["muted"])

    async def test_muted_skips(self):
        self.s["muted"] = True
        with mock.patch.dict(os.environ, {}, clear=True):
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "muted_skip")
        self.assertEqual(self.offered, [])

    # ── warmup / cooldown ──
    async def test_warmup_blocks(self):
        self.s["live_decisions"] = []
        self.s["live_action_items"] = []
        with mock.patch.dict(os.environ, {}, clear=True):
            out = await self._interject("anything substantive?")
        self.assertEqual(out["action"], "warmup")

    async def test_cooldown_blocks(self):
        self.s["offer_last_ts"] = 4950.0  # 50s ago < 90s
        with mock.patch.dict(os.environ, {}, clear=True):
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "cooldown")

    # ── offer path ──
    async def test_happy_offer(self):
        p = self._patch(offer=True, subject="vendor forecast", conf=0.8)
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "offered")
        self.assertEqual(self.s["interjection_state"], "offer_pending")
        self.assertEqual(self.s["pending_offer"]["subject"], "vendor forecast")
        self.assertEqual(len(self.offered), 1)
        self.assertIn("vendor forecast", self.offered[0])

    async def test_no_offer(self):
        p = self._patch(offer=False)
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "no_offer")
        self.assertEqual(self.offered, [])

    async def test_dup_subject_suppressed(self):
        self.s["offered_subjects"] = ["vendor forecast"]
        p = self._patch(offer=True, subject="Vendor Forecast", conf=0.9)
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "dup_subject")

    async def test_offer_talked_over(self):
        p = self._patch(offer=True, conf=0.9)
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("do you wanna check the vendor forecast?", speak=self._speak_offer_talkedover)
        self.assertEqual(out["action"], "offer_talked_over")
        self.assertNotEqual(self.s["interjection_state"], "offer_pending")

    async def test_shadow_offer_never_speaks(self):
        p = self._patch(offer=True, conf=0.9)
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS_SHADOW": "1"}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "shadow_offer")
        self.assertEqual(self.offered, [])

    # ── consent path ──
    def _set_pending(self, ts=5000.0, turns=0, subject="vendor forecast"):
        self.s["interjection_state"] = "offer_pending"
        self.s["pending_offer"] = {"subject": subject, "ts": ts, "turns": turns}

    async def test_consent_yes_delivers(self):
        self._set_pending()
        p = self._patch(consent="yes")
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("yeah go ahead", now=5005.0)
        self.assertEqual(out["action"], "delivered")
        self.assertEqual(self.delivered, ["vendor forecast"])
        self.assertEqual(self.s["interjection_state"], "idle")

    async def test_consent_no_drops(self):
        self._set_pending()
        p = self._patch(consent="no")
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("no we're good", now=5005.0)
        self.assertEqual(out["action"], "declined")
        self.assertEqual(self.delivered, [])
        self.assertEqual(self.s["interjection_state"], "idle")

    async def test_consent_unclear_waits(self):
        self._set_pending(ts=5000.0, turns=0)
        p = self._patch(consent="unclear")
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("so anyway about the roadmap", now=5005.0)
        self.assertEqual(out["action"], "awaiting_consent")
        self.assertEqual(self.s["interjection_state"], "offer_pending")

    async def test_consent_unclear_expires_by_turns(self):
        self._set_pending(ts=5000.0, turns=1)
        p = self._patch(consent="unclear")
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("and another thing", now=5005.0)
        self.assertEqual(out["action"], "expired")
        self.assertEqual(self.s["interjection_state"], "idle")

    async def test_consent_unclear_expires_by_time(self):
        self._set_pending(ts=5000.0, turns=0)
        p = self._patch(consent="unclear")
        with mock.patch.dict(os.environ, {}, clear=True), p[0], p[1], p[2]:
            out = await self._interject("much later", now=5050.0)  # >25s
        self.assertEqual(out["action"], "expired")

    async def test_mutex_busy(self):
        self.s["_ambient_evaluating"] = True
        out = await self._interject("do you wanna check the vendor forecast?")
        self.assertEqual(out["action"], "busy")


if __name__ == "__main__":
    unittest.main()

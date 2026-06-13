"""Tests for instant acknowledgments (classifier, audio cache, wiring)."""

import asyncio
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ack_phrases  # noqa: E402


class ClassifierTests(unittest.TestCase):
    def _c(self, text):
        return ack_phrases.classify_command(text)

    def test_email_write(self):
        self.assertEqual(self._c("send an email to the team about the launch"), "email_write")
        self.assertEqual(self._c("draft a reply to that mail from finance"), "email_write")

    def test_email_read(self):
        self.assertEqual(self._c("can you check my inbox for anything urgent"), "email_read")

    def test_calendar_write(self):
        self.assertEqual(self._c("schedule a meeting with Vidyut next Tuesday"), "calendar_write")
        self.assertEqual(self._c("set up a calendar event for the review"), "calendar_write")

    def test_calendar_read(self):
        self.assertEqual(self._c("do I have any meetings tomorrow"), "calendar_read")
        self.assertEqual(self._c("what's on my calendar"), "calendar_read")

    def test_bare_meeting_is_not_calendar(self):
        # "this meeting" in live-meeting speech must not trigger calendar.
        self.assertEqual(self._c("what do you think about this meeting"), "generic")

    def test_meeting_recall_beats_web_and_knowledge(self):
        self.assertEqual(self._c("check the documents about what we discussed in the last meeting"),
                         "meeting_recall")

    def test_knowledge(self):
        self.assertEqual(self._c("look in the knowledge base for the vendor SLA"), "knowledge")

    def test_summary(self):
        self.assertEqual(self._c("summarize the meeting so far"), "summary")

    def test_actions(self):
        self.assertEqual(self._c("list the action items please"), "actions")

    def test_web(self):
        self.assertEqual(self._c("what's the weather tomorrow"), "web")
        self.assertEqual(self._c("look up the latest on the chip shortage"), "web")

    def test_generic_fallback(self):
        self.assertEqual(self._c("can you help us settle this"), "generic")
        self.assertEqual(self._c(""), "generic")


class PhraseTests(unittest.TestCase):
    def test_every_category_has_phrases(self):
        for cat in ack_phrases.CATEGORIES:
            self.assertTrue(ack_phrases.PHRASES[cat], cat)

    def test_pick_phrase_rotates_per_bot(self):
        state = {}
        seen = {ack_phrases.pick_phrase("generic", state) for _ in range(4)}
        self.assertEqual(len(seen), len(ack_phrases.PHRASES["generic"]))

    def test_all_phrases_iterable_for_presynthesis(self):
        phrases = ack_phrases.all_phrases()
        self.assertGreaterEqual(len(phrases), 10)
        self.assertEqual(len(phrases), len(set(phrases)))  # no duplicates

    def test_flags(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(ack_phrases.ack_on())
            self.assertAlmostEqual(ack_phrases.ack_delay_s(), 1.2)
        with mock.patch.dict(os.environ, {"PRISM_ACK": "0", "PRISM_ACK_DELAY_S": "2"}):
            self.assertFalse(ack_phrases.ack_on())
            self.assertAlmostEqual(ack_phrases.ack_delay_s(), 2.0)


import ack_audio  # noqa: E402


class AckAudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ack_audio._CACHE.clear()

    async def test_ensure_synthesizes_all_phrases(self):
        synthesized = []

        async def fake_tts(text):
            synthesized.append(text)
            return b"audio:" + text.encode()

        with mock.patch.object(ack_audio, "text_to_speech", new=fake_tts):
            await ack_audio.ensure_ack_audio()
        self.assertEqual(sorted(synthesized), sorted(ack_phrases.all_phrases()))
        phrase = ack_phrases.PHRASES["generic"][0]
        self.assertEqual(ack_audio.get_ack_audio(phrase), b"audio:" + phrase.encode())

    async def test_ensure_is_idempotent(self):
        calls = []

        async def fake_tts(text):
            calls.append(text)
            return b"a"

        with mock.patch.object(ack_audio, "text_to_speech", new=fake_tts):
            await ack_audio.ensure_ack_audio()
            await ack_audio.ensure_ack_audio()
        self.assertEqual(len(calls), len(ack_phrases.all_phrases()))  # no re-synthesis

    async def test_failures_skipped_not_raised(self):
        async def flaky_tts(text):
            if "inbox" in text:
                raise RuntimeError("tts down")
            return b"a"

        with mock.patch.object(ack_audio, "text_to_speech", new=flaky_tts):
            await ack_audio.ensure_ack_audio()  # must not raise
        self.assertIsNone(ack_audio.get_ack_audio("Let me check your inbox—"))
        self.assertIsNotNone(ack_audio.get_ack_audio("On it — one moment."))


if __name__ == "__main__":
    unittest.main()

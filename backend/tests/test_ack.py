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

    def test_present_tense_recall_beats_email(self):
        # Review fix: "what did we decide about the budget email" must ack as
        # recall, not "Let me check your inbox—" (a confidently-wrong ack).
        self.assertEqual(self._c("what did we decide about the budget email"), "meeting_recall")
        self.assertEqual(self._c("did we agree on the vendor in the email thread"), "meeting_recall")

    def test_set_up_call_is_calendar_write(self):
        self.assertEqual(self._c("set up a call with the vendor"), "calendar_write")
        self.assertEqual(self._c("schedule a sync for the review"), "calendar_write")


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


import meeting_memory  # noqa: E402
import perception_state  # noqa: E402
import realtime_routes as rt  # noqa: E402


class AckWiringTests(unittest.IsolatedAsyncioTestCase):
    def _state(self):
        return meeting_memory.get_initial_memory_state()

    async def test_ack_fires_after_delay_when_no_real_audio(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.05"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=b"ack-bytes"), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox please")
            await asyncio.sleep(0.15)
        self.assertEqual(uploaded, [b"ack-bytes"])
        self.assertEqual(perception_state.ensure_counters(state)["ack_played"], 1)

    async def test_cancel_before_delay_suppresses_ack(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.2"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=b"ack-bytes"), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox please")
            await asyncio.sleep(0.02)
            rt._cancel_ack(state)
            await asyncio.sleep(0.3)
        self.assertEqual(uploaded, [])
        self.assertEqual(perception_state.ensure_counters(state)["ack_cancelled_fast"], 1)

    async def test_flag_off_never_arms(self):
        state = self._state()
        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK": "0"}):
            rt._arm_ack("b1", state, "check my inbox")
        self.assertIsNone(state.get("_ack_task"))

    async def test_missing_audio_is_silent_noop(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.05"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=None), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox")
            await asyncio.sleep(0.15)
        self.assertEqual(uploaded, [])

    async def test_new_command_replaces_pending_ack(self):
        state = self._state()
        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "5"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"):
            rt._arm_ack("b1", state, "first command")
            first_task = state["_ack_task"]
            rt._arm_ack("b1", state, "second command")
            await asyncio.sleep(0.01)
            self.assertTrue(first_task.cancelled() or first_task.done())
            state["_ack_task"].cancel()

    async def test_process_command_finally_suppresses_ack_on_no_voice_exit(self):
        # Review fix #2: a command that exits without producing voice (here the
        # no-API-key early return) must not leave the ack to fire into silence —
        # the _process_command finally cancels the still-pending ack.
        bot_id = "bot-ack-novoice"
        rt._get_bot_state(bot_id)  # reset debounce/processing
        uploaded = []

        async def fake_upload(b, audio):
            uploaded.append(audio)
            return True

        try:
            with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "5"}), \
                 mock.patch.object(rt, "RECALL_API_KEY", "k"), \
                 mock.patch.object(rt, "OPENAI_API_KEY", ""), \
                 mock.patch.object(rt, "_barge_in_on", return_value=False), \
                 mock.patch.object(rt, "_get_settings_for_bot",
                                   new=mock.AsyncMock(return_value={"persona_text": "", "bot_name": "Prism"})), \
                 mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()), \
                 mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=b"ack-bytes"), \
                 mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
                await rt._process_command(bot_id, "check my inbox please")
                await asyncio.sleep(0.05)  # give a cancelled ack a chance to (not) fire
            self.assertEqual(uploaded, [])  # ack suppressed, never uploaded
            self.assertIsNone(rt._get_bot_state(bot_id).get("_ack_task"))
        finally:
            rt.cleanup_bot_state(bot_id)

    async def test_cleanup_cancels_pending_ack(self):
        # Review fix #3: a bot torn down within the ack window must not leave a
        # task that wakes and uploads to a dead bot.
        bot_id = "bot-ack-cleanup"
        state = rt._get_bot_state(bot_id)
        try:
            with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "5"}), \
                 mock.patch.object(rt, "RECALL_API_KEY", "k"):
                rt._arm_ack(bot_id, state, "check my inbox")
                task = state["_ack_task"]
                rt.cleanup_bot_state(bot_id)
                await asyncio.sleep(0)
                self.assertTrue(task.cancelled() or task.done())
        finally:
            rt.cleanup_bot_state(bot_id)


if __name__ == "__main__":
    unittest.main()

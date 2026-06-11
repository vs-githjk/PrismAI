"""Tests for the ambient contribution lane (spec 2026-06-11)."""

import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ambient_loop  # noqa: E402
import meeting_memory  # noqa: E402
import perception_state  # noqa: E402


class IsQuestionTests(unittest.TestCase):
    def test_question_mark_fires(self):
        self.assertTrue(ambient_loop.is_question("What was Q3 revenue?"))

    def test_question_word_start_fires_with_length(self):
        self.assertTrue(ambient_loop.is_question("does anyone know the vendor deadline"))

    def test_short_question_word_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question("what now"))

    def test_statement_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question("We shipped the build yesterday."))

    def test_empty_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question(""))


class QuestionWindowTests(unittest.TestCase):
    def test_default_window(self):
        self.assertAlmostEqual(
            ambient_loop.question_window_s("What was Q3 revenue?", [], None), 6.0
        )

    def test_named_participant_lengthens(self):
        w = ambient_loop.question_window_s(
            "Vidyut, what do you think?", ["Vidyut Sriram", "Abhinav Dasari"], None
        )
        self.assertAlmostEqual(w, 9.0)

    def test_strong_kb_hit_shortens(self):
        w = ambient_loop.question_window_s("What was Q3 revenue?", [], 0.86)
        self.assertAlmostEqual(w, 4.2, places=1)

    def test_named_participant_wins_over_kb(self):
        w = ambient_loop.question_window_s(
            "Vidyut, what was Q3 revenue?", ["Vidyut Sriram"], 0.9
        )
        self.assertAlmostEqual(w, 9.0)


class ParseContributionTests(unittest.TestCase):
    def test_valid_payload(self):
        raw = '{"value": 8.5, "kind": "answer", "contribution": "Per the Q3 doc, revenue was 1.2M.", "subject": "Q3 revenue"}'
        out = ambient_loop.parse_contribution_output(raw)
        self.assertEqual(out["kind"], "answer")
        self.assertAlmostEqual(out["value"], 8.5)
        self.assertEqual(out["subject"], "Q3 revenue")

    def test_fenced_payload(self):
        raw = '```json\n{"value": 6, "kind": "fact", "contribution": "X.", "subject": "x"}\n```'
        out = ambient_loop.parse_contribution_output(raw)
        self.assertEqual(out["kind"], "fact")

    def test_kind_none_returns_silent_shape(self):
        out = ambient_loop.parse_contribution_output('{"value": 9, "kind": "none", "contribution": "", "subject": ""}')
        self.assertEqual(out, {"value": 0.0, "kind": "none", "contribution": "", "subject": ""})

    def test_drift_cases_return_none(self):
        for raw in (None, "", "no json here", '{"value": "high"}',
                    '{"value": 8, "kind": "poem", "contribution": "x", "subject": "s"}',
                    '{"value": 8, "kind": "answer", "contribution": "", "subject": "s"}'):
            self.assertIsNone(ambient_loop.parse_contribution_output(raw), raw)

    def test_value_clamped(self):
        out = ambient_loop.parse_contribution_output(
            '{"value": 99, "kind": "answer", "contribution": "x", "subject": "s"}'
        )
        self.assertEqual(out["value"], 10.0)


class DeliveryTierTests(unittest.TestCase):
    def test_high_value_is_voice(self):
        with mock.patch.dict(os.environ, {"PRISM_AMBIENT_VOICE": "1"}):
            self.assertEqual(ambient_loop.delivery_tier(8.5), "voice")

    def test_mid_value_is_chat(self):
        self.assertEqual(ambient_loop.delivery_tier(6.0), "chat")

    def test_low_value_is_drop(self):
        self.assertEqual(ambient_loop.delivery_tier(3.0), "drop")

    def test_chat_cap_demotes_high_value(self):
        self.assertEqual(ambient_loop.delivery_tier(9.0, max_tier="chat"), "chat")

    def test_voice_flag_off_demotes_to_chat(self):
        with mock.patch.dict(os.environ, {"PRISM_AMBIENT_VOICE": "0"}):
            self.assertEqual(ambient_loop.delivery_tier(9.0), "chat")


class CooldownAndLedgerTests(unittest.TestCase):
    def test_voice_cooldown(self):
        state = {"ambient_voice_last_ts": time.time()}
        self.assertFalse(ambient_loop.voice_cooldown_clear(state, time.time()))
        state["ambient_voice_last_ts"] = time.time() - 61
        self.assertTrue(ambient_loop.voice_cooldown_clear(state, time.time()))

    def test_chat_cooldown(self):
        state = {"ambient_chat_last_ts": time.time()}
        self.assertFalse(ambient_loop.chat_cooldown_clear(state, time.time()))
        state["ambient_chat_last_ts"] = time.time() - 26
        self.assertTrue(ambient_loop.chat_cooldown_clear(state, time.time()))

    def test_ledger_dedup_and_cap(self):
        state = {}
        ambient_loop.record_contributed_subject(state, "Q3 Revenue")
        self.assertTrue(ambient_loop.subject_already_contributed(state, "q3 revenue"))
        self.assertFalse(ambient_loop.subject_already_contributed(state, "vendor sla"))
        for i in range(30):
            ambient_loop.record_contributed_subject(state, f"subject {i}")
        self.assertLessEqual(len(state["contributed_subjects"]), 25)


class TimingGateTests(unittest.TestCase):
    def _state(self, last_line="Abhinav: We shipped it.", audio_age=5.0, pending=False):
        acc = types.SimpleNamespace(pending={"s1": object()} if pending else {})
        return {
            "transcript_buffer": [last_line] if last_line else [],
            "last_audio_ts": time.time() - audio_age,
            "accumulator": acc,
        }

    def test_clear_when_quiet_and_terminal(self):
        self.assertTrue(ambient_loop.gate_clear(self._state(), time.time()))

    def test_blocked_by_recent_audio(self):
        self.assertFalse(ambient_loop.gate_clear(self._state(audio_age=0.3), time.time()))

    def test_blocked_by_pending_partial(self):
        self.assertFalse(ambient_loop.gate_clear(self._state(pending=True), time.time()))

    def test_blocked_by_no_terminal_punct(self):
        s = self._state(last_line="Abhinav: I went to the store and")
        self.assertFalse(ambient_loop.gate_clear(s, time.time()))

    def test_blocked_by_trailing_connective(self):
        s = self._state(last_line="Abhinav: We could do that because.")
        self.assertFalse(ambient_loop.gate_clear(s, time.time()))

    def test_clear_with_no_accumulator(self):
        s = self._state()
        s["accumulator"] = None
        self.assertTrue(ambient_loop.gate_clear(s, time.time()))


class GenerateContributionTests(unittest.IsolatedAsyncioTestCase):
    def _state(self):
        s = meeting_memory.get_initial_memory_state()
        s["transcript_buffer"] = ["Abhinav: What was Q3 revenue?"]
        return s

    async def test_good_json_passes_through(self):
        raw = '{"value": 8, "kind": "answer", "contribution": "Per the Q3 doc, 1.2M.", "subject": "Q3 revenue"}'
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(return_value=raw)):
            out = await ambient_loop.generate_contribution(self._state(), "unanswered_question", "evidence", "Flash")
        self.assertEqual(out["kind"], "answer")

    async def test_drift_returns_none_and_counts(self):
        state = self._state()
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(return_value="garbage")):
            out = await ambient_loop.generate_contribution(state, "unanswered_question", "e", "Prism")
        self.assertIsNone(out)
        self.assertEqual(perception_state.ensure_counters(state)["ambient_parse_fail"], 1)

    async def test_model_exception_returns_none(self):
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(side_effect=RuntimeError("429"))):
            out = await ambient_loop.generate_contribution(self._state(), "knowledge_match", "e", "Prism")
        self.assertIsNone(out)

    async def test_prompt_includes_evidence_and_ledger(self):
        state = self._state()
        ambient_loop.record_contributed_subject(state, "vendor sla")
        state["previous_idea_summaries"] = ["(idea) ownership gap"]
        captured = {}

        async def fake_call(system, user):
            captured["system"] = system
            captured["user"] = user
            return '{"value": 2, "kind": "none", "contribution": "", "subject": ""}'

        with mock.patch.object(ambient_loop, "_call_ambient_model", new=fake_call):
            await ambient_loop.generate_contribution(state, "unanswered_question", "EVIDENCE-XYZ", "Flash")
        self.assertIn("EVIDENCE-XYZ", captured["user"])
        self.assertIn("vendor sla", captured["user"])
        self.assertIn("ownership gap", captured["user"])
        self.assertIn("Flash", captured["system"])


class LaneStateFieldTests(unittest.TestCase):
    def test_initial_state_has_lane_fields(self):
        s = meeting_memory.get_initial_memory_state()
        self.assertIsNone(s["pending_question"])
        self.assertEqual(s["last_audio_ts"], 0.0)
        self.assertEqual(s["ambient_voice_last_ts"], 0.0)
        self.assertEqual(s["ambient_chat_last_ts"], 0.0)
        self.assertEqual(s["contributed_subjects"], [])
        self.assertFalse(s["_ambient_busy"])
        self.assertEqual(s["ambient_speaking_since"], 0.0)

    def test_lane_counters_exist(self):
        s = meeting_memory.get_initial_memory_state()
        counters = perception_state.ensure_counters(s)
        for key in ("ambient_q_triggers", "ambient_kb_triggers", "ambient_b_triggers",
                    "ambient_generations", "ambient_discarded_answered",
                    "ambient_low_value", "ambient_chat_posted", "ambient_spoken",
                    "ambient_demoted_no_gap", "ambient_yielded", "ambient_parse_fail"):
            self.assertIn(key, counters, key)


import realtime_routes as rt  # noqa: E402


class StreamedSenderAbortTests(unittest.IsolatedAsyncioTestCase):
    async def test_abort_check_stops_uploads(self):
        uploads = []

        async def fake_tts(text):
            return b"audio"

        async def fake_upload(bot_id, audio):
            uploads.append(audio)
            return True

        def abort_check():
            return len(uploads) >= 1  # talk-over detected after the first chunk

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_chunk_reply", return_value=["One.", "Two.", "Three."]), \
             mock.patch.object(rt, "_get_bot_state", return_value=meeting_memory.get_initial_memory_state()):
            await rt._send_voice_response_streamed("bot-1", "One. Two. Three.",
                                                   cmd_detected_ts=time.time(),
                                                   abort_check=abort_check)
        self.assertEqual(len(uploads), 1)  # second/third chunk never uploaded

    async def test_no_abort_check_uploads_all(self):
        uploads = []

        async def fake_tts(text):
            return b"audio"

        async def fake_upload(bot_id, audio):
            uploads.append(audio)
            return True

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_chunk_reply", return_value=["One.", "Two."]), \
             mock.patch.object(rt, "_get_bot_state", return_value=meeting_memory.get_initial_memory_state()):
            await rt._send_voice_response_streamed("bot-1", "One. Two.",
                                                   cmd_detected_ts=time.time())
        self.assertEqual(len(uploads), 2)


class FakeUtt:
    def __init__(self, text, speaker_name="Abhinav", speaker_id="sid-a"):
        self.text = text
        self.speaker_name = speaker_name
        self.speaker_id = speaker_id
        self.utterance_id = "u1"


def _auto_state(**over):
    s = meeting_memory.get_initial_memory_state()
    s["mode"] = "autonomous"
    s["meeting_start_ts"] = time.time() - 600
    s["live_decisions"] = [{"text": "ship it", "speaker": "A", "ts": 1.0}]  # past_warmup
    s["transcript_buffer"] = ["Abhinav: hello."]
    s.update(over)
    return s


class TriggerArmingTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_arms_pending_slot_and_speculates(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        self.assertIsNotNone(state["pending_question"])
        self.assertEqual(state["pending_question"]["text"], "What was Q3 revenue?")
        spec.assert_awaited()
        self.assertEqual(perception_state.ensure_counters(state)["ambient_q_triggers"], 1)

    async def test_different_speaker_substantive_reply_clears(self):
        state = _auto_state()
        state["pending_question"] = {"text": "q?", "speaker_id": "sid-a",
                                     "speaker_name": "Abhinav", "ts": time.time(),
                                     "window_s": 6.0, "candidate": None,
                                     "candidate_done": False, "delivered": False}
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("it was one point two million", "Vidyut", "sid-v"))
        self.assertIsNone(state["pending_question"])
        self.assertEqual(perception_state.ensure_counters(state)["ambient_discarded_answered"], 1)

    async def test_asker_continuation_does_not_clear(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "sid-a", "speaker_name": "Abhinav",
              "ts": time.time(), "window_s": 6.0, "candidate": None,
              "candidate_done": False, "delivered": False}
        state["pending_question"] = pq
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("I really cannot find it anywhere", "Abhinav", "sid-a"))
        self.assertIs(state["pending_question"], pq)

    async def test_short_reply_does_not_clear(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "sid-a", "speaker_name": "Abhinav",
              "ts": time.time(), "window_s": 6.0, "candidate": None,
              "candidate_done": False, "delivered": False}
        state["pending_question"] = pq
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("yeah", "Vidyut", "sid-v"))
        self.assertIs(state["pending_question"], pq)

    async def test_blocker_fires_chat_capped(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_fire", new=mock.AsyncMock()) as fire:
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("we are blocked on the vendor SLA"))
        fire.assert_awaited()
        self.assertEqual(fire.await_args.kwargs.get("max_tier"), "chat")

    async def test_mute_command_sets_muted_and_clears_slot(self):
        state = _auto_state()
        state["pending_question"] = {"text": "q?", "speaker_id": "x", "speaker_name": "X",
                                     "ts": 0, "window_s": 6.0, "candidate": None,
                                     "candidate_done": False, "delivered": False}
        await rt._ambient_on_utterance("bot-1", state, FakeUtt("Prism, stay quiet"))
        self.assertTrue(state["muted"])
        self.assertIsNone(state["pending_question"])

    async def test_muted_state_blocks_triggers(self):
        state = _auto_state(muted=True)
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        self.assertIsNone(state["pending_question"])
        spec.assert_not_awaited()

    async def test_utterance_mode_blocks_triggers(self):
        state = _auto_state(mode="utterance")
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        spec.assert_not_awaited()

    async def test_explicit_command_skips_lane(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value="summarize"), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("Prism, summarize?"))
        spec.assert_not_awaited()


class SpeculateTests(unittest.IsolatedAsyncioTestCase):
    async def test_speculate_attaches_candidate_and_window(self):
        state = _auto_state()
        pq = {"text": "What is the vendor SLA?", "speaker_id": "sid-a",
              "speaker_name": "Abhinav", "ts": time.time(), "window_s": 6.0,
              "candidate": None, "candidate_done": False, "delivered": False}
        matches = [{"doc_name": "Vendor contract", "content": "SLA is 99.9%",
                    "score": 0.91, "sensitivity": "public", "doc_id": "d1", "meeting_id": None}]
        good = {"value": 8.0, "kind": "answer",
                "contribution": "Per the Vendor contract, SLA is 99.9%.", "subject": "vendor SLA"}
        with mock.patch.dict(rt.bot_store, {"bot-1": {"user_id": "u-1", "meeting_id": None}}, clear=False), \
             mock.patch.object(rt, "_ambient_kb_search", new=mock.AsyncMock(return_value=matches)), \
             mock.patch.object(rt.ambient_loop, "generate_contribution",
                               new=mock.AsyncMock(return_value=good)):
            await rt._ambient_speculate("bot-1", state, pq)
        self.assertTrue(pq["candidate_done"])
        self.assertEqual(pq["candidate"]["subject"], "vendor SLA")
        self.assertAlmostEqual(pq["window_s"], 4.2, places=1)  # strong KB hit shortened

    async def test_speculate_marks_done_on_failure(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "a", "speaker_name": "A", "ts": time.time(),
              "window_s": 6.0, "candidate": None, "candidate_done": False, "delivered": False}
        with mock.patch.dict(rt.bot_store, {"bot-1": {"user_id": None}}, clear=False), \
             mock.patch.object(rt.ambient_loop, "generate_contribution",
                               new=mock.AsyncMock(return_value=None)):
            await rt._ambient_speculate("bot-1", state, pq)
        self.assertTrue(pq["candidate_done"])
        self.assertIsNone(pq["candidate"])


if __name__ == "__main__":
    unittest.main()

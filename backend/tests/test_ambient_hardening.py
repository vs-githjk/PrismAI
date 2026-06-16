# backend/tests/test_ambient_hardening.py
"""Hardening fixes for the ambient contribution lane — edge cases surfaced in
review (timeout wedge, self-audio, mute-during-gate, lost-on-demote, newest-wins).
Each test reproduces the bug; the fix makes it pass."""
import asyncio
import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()

import ambient_loop
import realtime_routes as rt


class GeneratorTimeoutTests(unittest.TestCase):
    """Bug 1: a hung generator call must not wedge the lane (_ambient_busy)."""

    def test_hung_generator_returns_none_within_timeout(self):
        async def _hang(system, user):
            await asyncio.sleep(30)  # far longer than the timeout
            return '{"value": 9, "kind": "answer", "contribution": "x", "subject": "y"}'

        async def _run():
            with patch.dict(os.environ, {"PRISM_AMBIENT_TIMEOUT_S": "0.1"}), \
                 patch.object(ambient_loop, "_call_ambient_model", new=_hang), \
                 patch.object(ambient_loop.meeting_memory, "build_memory_context",
                              new=lambda _s: ""):
                start = time.monotonic()
                out = await ambient_loop.generate_contribution({}, "q", "ev", "Prism")
                return out, time.monotonic() - start

        out, elapsed = asyncio.run(_run())
        self.assertIsNone(out)                 # silent on timeout
        self.assertLess(elapsed, 5.0)          # bounded, not the 30s hang


class SelfAudioGuardTests(unittest.TestCase):
    """Bug 2: the bot's own transcribed TTS must not stamp last_audio_ts (which
    drives the gate + yield) — but human speech always must."""

    def test_human_speech_stamps_last_audio_ts(self):
        state = {}
        rt._ambient_note_audio(state, "Vidyut", "spk-1", 100.0)
        self.assertEqual(state["last_audio_ts"], 100.0)

    def test_bot_audio_by_name_does_not_stamp_and_learns_id(self):
        state = {}
        rt._ambient_note_audio(state, "PrismAI", "bot-spk", 100.0)
        self.assertNotIn("last_audio_ts", state)            # excluded
        self.assertEqual(state["bot_self_speaker_id"], "bot-spk")  # learned

    def test_bot_audio_with_empty_speaker_id_still_excluded(self):
        state = {}
        rt._ambient_note_audio(state, "prismai", "", 100.0)  # case-insensitive
        self.assertNotIn("last_audio_ts", state)
        self.assertIsNone(state.get("bot_self_speaker_id"))  # nothing to learn

    def test_learned_id_excludes_even_when_name_changes(self):
        # Recall sometimes mislabels; once we've learned the id, trust it.
        state = {"bot_self_speaker_id": "bot-spk"}
        rt._ambient_note_audio(state, "Speaker 3", "bot-spk", 100.0)
        self.assertNotIn("last_audio_ts", state)

    def test_human_still_stamps_after_bot_id_learned(self):
        state = {"bot_self_speaker_id": "bot-spk"}
        rt._ambient_note_audio(state, "Alice", "spk-2", 100.0)
        self.assertEqual(state["last_audio_ts"], 100.0)      # yield/gate still works


class MuteAndDemotionTests(unittest.TestCase):
    """Bug 3 (mute during the gate-wait blocks both tiers) +
    Bug 4 (a no-gap voice demotion still lands in chat, nothing lost)."""

    _ENV = {"PRISM_AMBIENT_VOICE": "1", "PRISM_AMBIENT_VOICE_MIN": "8",
            "PRISM_AMBIENT_CHAT_MIN": "5", "PRISM_AMBIENT_CHAT_COOLDOWN_S": "25"}

    @staticmethod
    def _out(value=9.0):
        return {"value": value, "kind": "answer",
                "contribution": "Q3 was $3M.", "subject": "q3 revenue"}

    def test_mute_during_gate_wait_speaks_nothing_and_skips_chat(self):
        state = {"mode": "autonomous", "muted": False, "ambient_voice_last_ts": 0.0}
        chat = AsyncMock()

        async def _voice_muted(bot_id, st, out):
            st["muted"] = True            # user muted mid-wait
            return False

        async def _run():
            with patch.object(rt, "_ambient_deliver_voice", new=_voice_muted), \
                 patch.object(rt, "_send_chat_response", new=chat), \
                 patch.object(rt.ambient_loop, "shadow_mode", return_value=False), \
                 patch.object(rt.ambient_loop, "subject_already_contributed", return_value=False), \
                 patch.dict(os.environ, self._ENV):
                await rt._ambient_deliver("bot-1", state, self._out(), max_tier="voice")

        asyncio.run(_run())
        chat.assert_not_called()          # mute blocked the chat fallback too

    def test_no_gap_demotion_posts_to_chat_bypassing_cooldown(self):
        state = {"mode": "autonomous", "muted": False,
                 "ambient_voice_last_ts": 0.0,
                 "ambient_chat_last_ts": time.time()}   # chat cooldown NOT clear
        chat = AsyncMock()

        async def _voice_nogap(bot_id, st, out):
            return False                  # no gap appeared, not muted

        async def _run():
            with patch.object(rt, "_ambient_deliver_voice", new=_voice_nogap), \
                 patch.object(rt, "_send_chat_response", new=chat), \
                 patch.object(rt.ambient_loop, "shadow_mode", return_value=False), \
                 patch.object(rt.ambient_loop, "subject_already_contributed", return_value=False), \
                 patch.dict(os.environ, self._ENV):
                await rt._ambient_deliver("bot-1", state, self._out(9.0), max_tier="voice")

        asyncio.run(_run())
        chat.assert_called_once()         # demotion bypassed the chat cooldown

    def test_organic_chat_still_respects_cooldown(self):
        state = {"mode": "autonomous", "muted": False,
                 "ambient_chat_last_ts": time.time()}   # cooldown NOT clear
        chat = AsyncMock()

        async def _run():
            with patch.object(rt, "_send_chat_response", new=chat), \
                 patch.object(rt.ambient_loop, "shadow_mode", return_value=False), \
                 patch.object(rt.ambient_loop, "subject_already_contributed", return_value=False), \
                 patch.dict(os.environ, self._ENV):
                # value 6 → chat tier (no voice attempt); cooldown active → dropped
                await rt._ambient_deliver("bot-1", state, self._out(6.0), max_tier="voice")

        asyncio.run(_run())
        chat.assert_not_called()          # organic chat respects its cooldown

    def test_voice_poll_bails_immediately_when_muted(self):
        state = {"mode": "autonomous", "muted": True}
        voice = AsyncMock()

        async def _run():
            with patch.object(rt, "_send_voice_response", new=voice), \
                 patch.object(rt, "_send_voice_response_streamed", new=AsyncMock()), \
                 patch.object(rt.ambient_loop, "gate_clear", return_value=True), \
                 patch.dict(os.environ, {"PRISM_GAP_WAIT_S": "8"}):
                return await rt._ambient_deliver_voice("bot-1", state, self._out())

        result = asyncio.run(_run())
        self.assertFalse(result)          # bailed without speaking
        voice.assert_not_called()


class LatestWinsTests(unittest.TestCase):
    """Bug 5: a newer question cancels the older in-flight speculation (freeing
    _ambient_busy) instead of being dropped as a collision."""

    def test_cancel_ambient_spec_cancels_and_pops(self):
        async def _run():
            running = asyncio.Event()

            async def _long():
                running.set()
                await asyncio.sleep(30)

            task = asyncio.create_task(_long())
            state = {"_ambient_spec_task": task}
            await running.wait()
            await rt._cancel_ambient_spec(state)
            return task.cancelled(), "_ambient_spec_task" in state

        cancelled, still_present = asyncio.run(_run())
        self.assertTrue(cancelled)
        self.assertFalse(still_present)

    def test_newer_question_supersedes_older_speculation(self):
        cancelled = []

        async def _run():
            running = asyncio.Event()

            async def _spec(bot_id, st, slot):
                if slot["text"].startswith("Q1"):
                    running.set()
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    cancelled.append(slot["text"][:2])
                    raise

            def _u(text, sid):
                return types.SimpleNamespace(text=text, speaker_id=sid, speaker_name=sid)

            state = {"mode": "autonomous", "muted": False, "meeting_start_ts": 1.0,
                     "live_decisions": [{"text": "d"}]}   # past_warmup via a decision
            with patch.object(rt, "_ambient_speculate", new=_spec), \
                 patch.object(rt, "_detect_command", return_value=False):
                await rt._ambient_on_utterance("bot-1", state, _u("Q1 what is revenue?", "s1"))
                t1 = state["_ambient_spec_task"]
                await running.wait()                       # Q1 speculation in-flight
                await rt._ambient_on_utterance("bot-1", state, _u("Q2 what is profit?", "s2"))
                t2 = state["_ambient_spec_task"]
            await asyncio.sleep(0)                          # let cancellation settle
            result = (t1.cancelled(), t1 is not t2, not t2.done())
            t2.cancel()                                    # clean up the dangling task
            try:
                await t2
            except asyncio.CancelledError:
                pass
            return result

        t1_cancelled, distinct_tasks, t2_alive = asyncio.run(_run())
        self.assertTrue(t1_cancelled)        # Q1 superseded
        self.assertIn("Q1", cancelled)       # Q1's spec saw the cancel (busy freed)
        self.assertTrue(distinct_tasks)      # Q2 got its own task
        self.assertTrue(t2_alive)            # Q2 is generating, not dropped


class SharedGapTests(unittest.TestCase):
    """Consolidation: the wake-word command path and the autonomous lane share ONE
    gap detector (ambient_loop.speech_gap_clear) on ONE bot-excluded timestamp
    (last_audio_ts), instead of two that can drift."""

    def test_speech_gap_clear_honors_custom_quiet_s(self):
        now = 1000.0
        state = {"last_audio_ts": now - 1.0}             # quiet for 1.0s
        self.assertFalse(ambient_loop.speech_gap_clear(state, now, quiet_s=1.5))
        self.assertTrue(ambient_loop.speech_gap_clear(state, now, quiet_s=0.5))

    def test_gate_clear_delegates_to_speech_gap_clear(self):
        now = 1000.0
        loud = {"last_audio_ts": now}
        quiet = {"last_audio_ts": now - 100.0}
        self.assertEqual(ambient_loop.gate_clear(quiet, now),
                         ambient_loop.speech_gap_clear(quiet, now))
        self.assertEqual(ambient_loop.gate_clear(loud, now),
                         ambient_loop.speech_gap_clear(loud, now))

    def test_command_gap_keys_off_last_audio_ts_not_last_segment_ts(self):
        # The command path now ignores last_segment_ts (which was stamped for the
        # bot's own audio too) and uses the bot-excluded last_audio_ts.
        async def _run():
            state = {"last_audio_ts": time.time() - 10,   # quiet for 10s
                     "last_segment_ts": time.time()}       # stale signal, now ignored
            with patch.dict(os.environ, {"PRISM_GAP_WAIT": "1"}):
                start = time.monotonic()
                await rt._wait_for_speech_gap(state)
                return time.monotonic() - start

        self.assertLess(asyncio.run(_run()), 0.5)          # cleared fast, didn't wait

    def test_command_gap_blocks_while_room_is_loud(self):
        async def _run():
            state = {"last_audio_ts": time.time()}         # someone speaking right now
            with patch.dict(os.environ, {"PRISM_GAP_WAIT": "1"}), \
                 patch.object(rt, "_GAP_MAX_WAIT_S", 0.4):
                start = time.monotonic()
                await rt._wait_for_speech_gap(state)
                return time.monotonic() - start

        self.assertGreaterEqual(asyncio.run(_run()), 0.35)  # blocked → waited to max

    def test_terminal_check_is_optional(self):
        # buf[-1] is the bot's own pre-appended reply with no terminal punctuation.
        # The command path (require_terminal=False) must not block on it; the lane
        # (require_terminal=True) enforces a complete thought.
        now = 1000.0
        state = {"last_audio_ts": now - 10, "transcript_buffer": ["Prism: Done"]}
        self.assertTrue(ambient_loop.speech_gap_clear(state, now, require_terminal=False))
        self.assertFalse(ambient_loop.speech_gap_clear(state, now, require_terminal=True))

    def test_command_gap_does_not_block_on_unterminated_bot_reply(self):
        # Regression: pre-fix, the command path inherited the terminal check and
        # waited the full _GAP_MAX_WAIT_S on a short, unpunctuated bot reply.
        async def _run():
            state = {"last_audio_ts": time.time() - 10,
                     "transcript_buffer": ["Prism: Done"]}
            with patch.dict(os.environ, {"PRISM_GAP_WAIT": "1"}), \
                 patch.object(rt, "_GAP_MAX_WAIT_S", 4.0):
                start = time.monotonic()
                await rt._wait_for_speech_gap(state)
                return time.monotonic() - start

        self.assertLess(asyncio.run(_run()), 0.5)          # clears fast, not 4s


class CancelDuringGapTests(unittest.TestCase):
    """A mute / 'stop' that lands DURING the pre-speak gap cancels the speaking
    session. The streamed send self-checks mid-pipeline, but the buffered send
    does not — so _process_command re-checks the cancel right after the gap and
    stays silent. Chat still posts (it fired in parallel before the gap)."""

    def _fake_openai(self, content="Done"):
        msg = types.SimpleNamespace(content=content, tool_calls=None)
        choice = types.SimpleNamespace(message=msg, finish_reason="stop")
        resp = types.SimpleNamespace(choices=[choice])
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=AsyncMock(return_value=resp))
            )
        )

    def _drive(self, cancel_during_gap):
        bot_id = "bot-cancel-gap-" + ("c" if cancel_during_gap else "n")
        rt._get_bot_state(bot_id)  # fresh state (resets debounce/processing)
        voice = AsyncMock()
        voice_streamed = AsyncMock()
        chat = AsyncMock()

        async def fake_gap(state):
            # Model the mute/"stop" landing during the lull wait: the active
            # speaking session gets cancelled before we emit any audio.
            if cancel_during_gap:
                sess = rt.perception_state.get_session(state)
                if sess is not None:
                    sess.cancel()

        async def _run():
            with mock.patch.object(rt, "OPENAI_API_KEY", "k"), \
                 mock.patch.object(rt, "RECALL_API_KEY", "k"), \
                 mock.patch.object(rt, "get_openai", return_value=self._fake_openai()), \
                 mock.patch.object(rt, "_barge_in_on", return_value=True), \
                 mock.patch.object(rt, "_streamed_tts_on", return_value=False), \
                 mock.patch.object(rt, "_streamed_llm_on", return_value=False), \
                 mock.patch.object(rt, "get_available_tools", return_value=[]), \
                 mock.patch.object(rt.meeting_memory, "build_memory_context",
                                   return_value=""), \
                 mock.patch.object(rt, "_get_settings_for_bot",
                                   new=AsyncMock(return_value={"persona_text": "", "bot_name": "Prism"})), \
                 mock.patch.object(rt, "_arm_ack", return_value=None), \
                 mock.patch.object(rt, "_cancel_ack", return_value=None), \
                 mock.patch.object(rt, "_db_append_command", return_value=None), \
                 mock.patch.object(rt, "_wait_for_speech_gap", new=fake_gap), \
                 mock.patch.object(rt, "_send_voice_response", new=voice), \
                 mock.patch.object(rt, "_send_voice_response_streamed", new=voice_streamed), \
                 mock.patch.object(rt, "_send_chat_response", new=chat):
                await rt._process_command(bot_id, "what's on my calendar today")

        try:
            asyncio.run(_run())
        finally:
            rt.cleanup_bot_state(bot_id)
        return voice, voice_streamed, chat

    def test_cancel_during_gap_suppresses_buffered_voice(self):
        voice, voice_streamed, chat = self._drive(cancel_during_gap=True)
        voice.assert_not_awaited()           # buffered send skipped on cancel
        voice_streamed.assert_not_awaited()
        chat.assert_awaited()                # chat still posted (fired before the gap)

    def test_clear_gap_still_speaks(self):
        # Guard against over-suppression: no cancel during the gap → the buffered
        # voice send still fires. (Proves the new re-check doesn't silence normal replies.)
        voice, voice_streamed, chat = self._drive(cancel_during_gap=False)
        voice.assert_awaited()
        voice_streamed.assert_not_awaited()
        chat.assert_awaited()


if __name__ == "__main__":
    unittest.main()

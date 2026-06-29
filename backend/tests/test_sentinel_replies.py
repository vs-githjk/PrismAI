"""Regression: internal fallback sentinels (NO_WEB_ANSWER / NO_GROUNDED_ANSWER)
must never reach meeting chat or TTS verbatim.

From the 2026-06-11 live test: knowledge_lookup found nothing → web_search
found nothing → the synthesis turn replied exactly `NO_WEB_ANSWER` (per the
tool's own instruction) and the bot SPOKE the sentinel into the meeting
(streamed_llm_done chars=13)."""

import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import meeting_memory  # noqa: E402
import realtime_routes as rt  # noqa: E402


class SentinelDegradeTests(unittest.TestCase):
    def test_exact_sentinels_degraded(self):
        for raw in ("NO_WEB_ANSWER", "NO_GROUNDED_ANSWER", "no_web_answer",
                    " NO_WEB_ANSWER. ", "NO_WEB_ANSWER!", "`NO_GROUNDED_ANSWER`"):
            out = rt._degrade_sentinel_reply(raw)
            self.assertNotIn("NO_WEB_ANSWER", out.upper(), raw)
            self.assertNotIn("NO_GROUNDED_ANSWER", out.upper(), raw)
            self.assertGreater(len(out), 10, raw)  # graceful text, not empty

    def test_real_replies_untouched(self):
        for raw in ("The Q3 revenue was 1.2M.",
                    "Tomorrow will be sunny with highs near 27°C.",
                    "You have no meetings scheduled for tomorrow."):
            self.assertEqual(rt._degrade_sentinel_reply(raw), raw)

    def test_embedded_sentinel_not_degraded(self):
        raw = "The tool returned NO_WEB_ANSWER for this query."
        self.assertEqual(rt._degrade_sentinel_reply(raw), raw)

    def test_empty_passthrough(self):
        self.assertEqual(rt._degrade_sentinel_reply(""), "")
        self.assertIsNone(rt._degrade_sentinel_reply(None))


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeEvent:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeStream:
    def __init__(self, parts):
        self._parts = list(parts)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._parts:
            raise StopAsyncIteration
        return _FakeEvent(self._parts.pop(0))


class StreamedSentinelTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_sentinel_not_spoken(self):
        """The dispatcher flushes 'NO_WEB_ANSWER' as one chunk at stream end —
        the TTS text must be the graceful fallback, never the sentinel."""
        spoken = []

        async def fake_tts(text):
            spoken.append(text)
            return b"audio"

        async def fake_upload(bot_id, audio):
            return True

        class _FakeCompletions:
            async def create(self, **kwargs):
                return _FakeStream(["NO_WEB", "_ANSWER"])

        groq = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=_FakeCompletions())
        )
        call_kwargs = {"model": "m", "messages": []}

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_get_bot_state",
                               return_value=meeting_memory.get_initial_memory_state()):
            await rt._stream_llm_to_voice(groq, call_kwargs, "bot-1", time.time())

        self.assertTrue(spoken)
        joined = " ".join(spoken).upper()
        self.assertNotIn("NO_WEB_ANSWER", joined)

    async def test_streamed_real_reply_spoken_verbatim(self):
        spoken = []

        async def fake_tts(text):
            spoken.append(text)
            return b"audio"

        async def fake_upload(bot_id, audio):
            return True

        class _FakeCompletions:
            async def create(self, **kwargs):
                return _FakeStream(["The Q3 revenue ", "was 1.2M."])

        groq = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=_FakeCompletions())
        )

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_get_bot_state",
                               return_value=meeting_memory.get_initial_memory_state()):
            reply = await rt._stream_llm_to_voice(
                groq, {"model": "m", "messages": []}, "bot-1", time.time())

        self.assertIn("Q3 revenue", " ".join(spoken))
        self.assertEqual(reply, "The Q3 revenue was 1.2M.")


class ToolPolicyFormatTests(unittest.TestCase):
    def test_tool_policy_forbids_function_tag_text(self):
        """F4: every live command was emitting <function=...> as text (Groq 400
        + recovery round-trip each turn). The static policy must name the
        failure mode explicitly."""
        self.assertIn("<function=", rt._STATIC_TOOL_POLICY)


if __name__ == "__main__":
    unittest.main()

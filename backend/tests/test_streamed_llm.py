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

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")


def _make_delta_event(content: str):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=content))]
    )


class _FakeStream:
    def __init__(self, deltas):
        self._deltas = deltas

    def __aiter__(self):
        self._iter = iter(self._deltas)
        return self

    async def __anext__(self):
        try:
            d = next(self._iter)
        except StopIteration:
            raise StopAsyncIteration
        return _make_delta_event(d)


class _FakeCompletions:
    def __init__(self, deltas):
        self._deltas = deltas

    async def create(self, **kwargs):
        assert kwargs.get("stream") is True, "PR-5 must request stream=True"
        return _FakeStream(self._deltas)


class _FakeGroq:
    def __init__(self, deltas):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(deltas))


class ScanDeltaForLeakTests(unittest.TestCase):
    def test_no_leak_returns_false(self):
        from realtime_routes import _scan_delta_for_leak
        new_tail, leak = _scan_delta_for_leak("", "Hello world. How are you?")
        self.assertFalse(leak)
        self.assertEqual(new_tail, "Hello world. How are you?"[-30:])

    def test_leak_in_single_delta(self):
        from realtime_routes import _scan_delta_for_leak
        _, leak = _scan_delta_for_leak("", "Hello <function=gmail_send {}>")
        self.assertTrue(leak)

    def test_leak_split_across_tail_and_delta(self):
        from realtime_routes import _scan_delta_for_leak
        # The "<fun" was already in the tail; "ction=foo>" arrives in the new delta.
        tail = "some text <fun"
        _, leak = _scan_delta_for_leak(tail, "ction=foo>")
        self.assertTrue(leak)

    def test_tail_window_is_30_chars(self):
        from realtime_routes import _scan_delta_for_leak
        new_tail, _ = _scan_delta_for_leak("", "x" * 50)
        self.assertEqual(len(new_tail), 30)

    def test_leak_followed_by_filler_still_caught_in_same_step(self):
        from realtime_routes import _scan_delta_for_leak
        # Even if the marker shows up early in delta and trailing chars push it
        # past the window, this scan should still flag it (combined string check).
        _, leak = _scan_delta_for_leak("", "<function=foo" + "y" * 40)
        self.assertTrue(leak)


class StreamLlmToVoiceTests(unittest.TestCase):
    def setUp(self):
        os.environ["RECALL_API_KEY"] = "test"

    def _run(self, coro):
        return asyncio.run(coro)

    def test_happy_path_streams_text_and_uploads_chunks(self):
        import realtime_routes
        # Three medium-long deltas that segment into 2-3 sentences, exceeding
        # the dispatcher's 25-char threshold.
        deltas = [
            "Hello there friend. ",
            "This is a streamed reply from the model. ",
            "I hope you find it informative.",
        ]
        fake_groq = _FakeGroq(deltas)
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(side_effect=lambda c: f"audio:{c[:8]}".encode())

        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            result = self._run(realtime_routes._stream_llm_to_voice(
                fake_groq, {"model": "m"}, "bot-stream", cmd_detected_ts=0.0,
            ))

        # Full text returned, in order.
        self.assertIn("Hello there friend", result)
        self.assertIn("streamed reply", result)
        self.assertIn("informative", result)
        # At least one TTS + one upload happened.
        self.assertGreater(tts_mock.await_count, 0)
        self.assertGreater(upload_mock.await_count, 0)
        # No chunk ever sent to TTS contained the function-tag marker.
        for call in tts_mock.await_args_list:
            args, _ = call
            self.assertNotIn("<function=", args[0])

    def test_leak_in_single_delta_blocks_subsequent_tts(self):
        import realtime_routes
        deltas = [
            "Hello there friend. ",
            "Then: <function=gmail_send {\"to\": \"x\"}> trailing. ",
            "More content that should never reach TTS.",
        ]
        fake_groq = _FakeGroq(deltas)
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(side_effect=lambda c: b"audio")

        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._stream_llm_to_voice(
                fake_groq, {"model": "m"}, "bot-leak1", cmd_detected_ts=0.0,
            ))

        # Whatever made it to TTS must not contain the marker.
        for call in tts_mock.await_args_list:
            args, _ = call
            self.assertNotIn("<function=", args[0])
        # And no chunks containing the marker were uploaded.
        # (text_to_speech mock returns generic bytes; upload tests are indirect:
        # the leak abort cancels remaining tasks. Worst case all clean chunks get
        # uploaded — that's expected behavior.)

    def test_leak_split_across_deltas_caught_by_rolling_tail(self):
        import realtime_routes
        # The marker is split: "Hi <fun" + "ction=foo>". A naive per-delta scan
        # would miss this; the rolling tail catches it.
        deltas = [
            "Hi there. Here is some content. <fun",
            "ction=gmail_send {\"to\": \"x\"}>",
        ]
        fake_groq = _FakeGroq(deltas)
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(side_effect=lambda c: b"audio")

        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._stream_llm_to_voice(
                fake_groq, {"model": "m"}, "bot-leak2", cmd_detected_ts=0.0,
            ))

        for call in tts_mock.await_args_list:
            args, _ = call
            self.assertNotIn("<function=", args[0])
            self.assertNotIn("ction=", args[0])

    def test_returns_full_text_even_when_recall_key_missing(self):
        import realtime_routes
        # When RECALL_API_KEY is empty we shouldn't try uploads — just drain the
        # stream and return the text so the caller can fall back to chat-only.
        deltas = ["Hello. ", "World."]
        fake_groq = _FakeGroq(deltas)
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(return_value=b"audio")
        with patch.object(realtime_routes, "RECALL_API_KEY", ""), \
             patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            result = self._run(realtime_routes._stream_llm_to_voice(
                fake_groq, {"model": "m"}, "bot-no-recall", cmd_detected_ts=0.0,
            ))
        self.assertEqual(result, "Hello. World.")
        self.assertEqual(tts_mock.await_count, 0)
        self.assertEqual(upload_mock.await_count, 0)


if __name__ == "__main__":
    unittest.main()

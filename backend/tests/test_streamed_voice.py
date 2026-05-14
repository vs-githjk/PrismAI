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


class ChunkReplyTests(unittest.TestCase):
    def test_chunks_under_min_concatenate(self):
        import realtime_routes
        chunks = realtime_routes._chunk_reply("Hi. Bye.")
        # Both sentences together (8 chars) are under min_chars=25, so on flush
        # the dispatcher concatenates them.
        self.assertEqual(len(chunks), 1)
        self.assertIn("Hi.", chunks[0])
        self.assertIn("Bye.", chunks[0])

    def test_long_reply_chunks_at_sentence_boundaries(self):
        import realtime_routes
        text = (
            "First sentence is comfortably long enough on its own. "
            "Second sentence is also long enough to dispatch on its own. "
            "Third sentence is also long enough independently."
        )
        chunks = realtime_routes._chunk_reply(text)
        self.assertEqual(len(chunks), 3)


class StreamedVoiceTests(unittest.TestCase):
    """Exercises the streamed-TTS orchestrator. Patches the real TTS and
    Recall upload so the test stays in-process."""

    def setUp(self):
        os.environ["RECALL_API_KEY"] = "test"

    def _make_audio(self, marker: bytes = b"audio"):
        return marker

    def _run(self, coro):
        return asyncio.run(coro)

    def test_happy_path_all_chunks_uploaded(self):
        import realtime_routes
        reply = (
            "First sentence is comfortably long enough on its own. "
            "Second sentence is also long enough to dispatch on its own. "
            "Third sentence is also long enough independently."
        )
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(side_effect=lambda chunk: f"audio:{chunk[:10]}".encode())
        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._send_voice_response_streamed(
                "bot-1", reply, cmd_detected_ts=0.0,
            ))
        # All three chunks produced TTS → uploaded.
        self.assertEqual(upload_mock.await_count, 3)
        self.assertEqual(tts_mock.await_count, 3)

    def test_function_tag_leak_aborts_before_tts(self):
        import realtime_routes
        # The reply contains a leaked tool tag. The leak scanner must block
        # all TTS + uploads.
        leaky = "Sure thing. <function=gmail_send {\"to\": \"x\"}> Done."
        upload_mock = AsyncMock(return_value=True)
        tts_mock = AsyncMock(return_value=b"audio")
        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._send_voice_response_streamed(
                "bot-1", leaky, cmd_detected_ts=0.0,
            ))
        self.assertEqual(tts_mock.await_count, 0)
        self.assertEqual(upload_mock.await_count, 0)

    def test_salvage_on_first_upload_failure(self):
        import realtime_routes
        reply = (
            "First sentence is comfortably long enough on its own. "
            "Second sentence is also long enough to dispatch on its own. "
            "Third sentence is also long enough independently."
        )
        # Fail chunk 1 (second upload), salvage upload succeeds.
        results = iter([True, False, True])
        upload_mock = AsyncMock(side_effect=lambda *_a, **_k: next(results))
        tts_mock = AsyncMock(side_effect=lambda chunk: f"audio:{chunk[:10]}".encode())

        # Reset bot state so we can assert the salvage debounce reset.
        state = realtime_routes._get_bot_state("bot-salvage")
        state["last_command_ts"] = 99999.0

        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._send_voice_response_streamed(
                "bot-salvage", reply, cmd_detected_ts=0.0,
            ))

        # Upload calls: chunk-0 (success), chunk-1 (fail), then ONE consolidated salvage upload.
        self.assertEqual(upload_mock.await_count, 3)
        # Debounce reset is the load-bearing side effect — verifies the principle
        # that follow-up commands are not blocked while salvage runs.
        self.assertEqual(state["last_command_ts"], 0)

    def test_hard_abort_on_two_upload_failures(self):
        import realtime_routes
        reply = (
            "First sentence is comfortably long enough on its own. "
            "Second sentence is also long enough to dispatch on its own. "
            "Third sentence is also long enough independently."
        )
        # First upload fails (count=1, salvage). Salvage upload also fails (count=2, hard abort).
        results = iter([False, False])
        upload_mock = AsyncMock(side_effect=lambda *_a, **_k: next(results))
        tts_mock = AsyncMock(side_effect=lambda chunk: f"audio:{chunk[:10]}".encode())
        with patch.object(realtime_routes, "text_to_speech", new=tts_mock), \
             patch.object(realtime_routes, "_upload_audio_to_recall", new=upload_mock):
            self._run(realtime_routes._send_voice_response_streamed(
                "bot-2failed", reply, cmd_detected_ts=0.0,
            ))
        # Exactly two upload attempts: chunk-0 (fail) + salvage (fail). No more attempts.
        self.assertEqual(upload_mock.await_count, 2)


if __name__ == "__main__":
    unittest.main()

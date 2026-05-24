import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase/groq so recall_routes imports cleanly in tests
fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

fake_groq_module = types.ModuleType("groq")
class _FakeAsyncGroq:
    def __init__(self, *a, **k): pass
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

from recall_routes import _segments_from_recall_data


class TestSegmentsFromRecallData(unittest.TestCase):
    def test_streaming_provider_shape_with_words(self):
        raw = [
            {
                "speaker": "Alice",
                "words": [
                    {"text": "Hello", "start_time": 0.5, "end_time": 1.0},
                    {"text": "world", "start_time": 1.1, "end_time": 1.6},
                ],
            },
            {
                "speaker": "Bob",
                "words": [
                    {"text": "Hi", "start_time": 2.0, "end_time": 2.3},
                ],
            },
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [
            {"speaker": "Alice", "start": 0.5, "end": 1.6, "text": "Hello world"},
            {"speaker": "Bob", "start": 2.0, "end": 2.3, "text": "Hi"},
        ])

    def test_skips_segments_with_no_words(self):
        raw = [
            {"speaker": "Alice", "words": []},
            {"speaker": "Bob", "words": [{"text": "ok", "start_time": 1.0, "end_time": 1.2}]},
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [{"speaker": "Bob", "start": 1.0, "end": 1.2, "text": "ok"}])

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(_segments_from_recall_data([]))

    def test_returns_none_for_non_list_input(self):
        self.assertIsNone(_segments_from_recall_data({"transcript": "blob"}))
        self.assertIsNone(_segments_from_recall_data("plain string"))
        self.assertIsNone(_segments_from_recall_data(None))

    def test_uses_participant_name_when_speaker_missing(self):
        raw = [{
            "participant": {"name": "Carol"},
            "words": [{"text": "yo", "start_time": 0.1, "end_time": 0.3}],
        }]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Carol", "start": 0.1, "end": 0.3, "text": "yo"},
        ])

    def test_falls_back_to_unknown_speaker_label(self):
        raw = [{"words": [{"text": "hi", "start_time": 0.0, "end_time": 0.2}]}]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Speaker", "start": 0.0, "end": 0.2, "text": "hi"},
        ])


import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


class TestProcessBotTranscriptSavesSegments(unittest.TestCase):
    def test_saves_segments_to_bot_sessions_on_success(self):
        import recall_routes
        recall_routes.bot_store["bot-xyz"] = {
            "status": "processing", "result": None, "error": None,
            "commands": [], "user_id": "user-1",
        }

        # Mock _fetch_transcript to return a response with structured segments
        fake_response = MagicMock()
        fake_response.json.return_value = [
            {"speaker": "Alice", "words": [
                {"text": "hi", "start_time": 0.0, "end_time": 0.3},
            ]},
        ]

        # Capture _db_save calls
        saved_fields: list[dict] = []
        def fake_db_save(bot_id, fields):
            saved_fields.append(fields)

        async def fake_run_full_analysis(_t):
            return {"summary": "ok"}

        with patch.object(recall_routes, "_fetch_transcript", AsyncMock(return_value=fake_response)), \
             patch.object(recall_routes, "_db_save", side_effect=fake_db_save), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "run_full_analysis", side_effect=fake_run_full_analysis), \
             patch.object(recall_routes, "build_analysis_transcript", side_effect=lambda t, owner_name=None: t), \
             patch("realtime_routes.cleanup_bot_state"):
            asyncio.run(recall_routes._process_bot_transcript("bot-xyz"))

        # Find the final "done" save and confirm segments were included
        done_save = next((f for f in saved_fields if f.get("status") == "done"), None)
        self.assertIsNotNone(done_save, "expected a status=done _db_save call")
        self.assertIn("transcript_segments", done_save)
        self.assertEqual(done_save["transcript_segments"], [
            {"speaker": "Alice", "start": 0.0, "end": 0.3, "text": "hi"},
        ])

    def test_segments_null_when_realtime_buffer_fallback_used(self):
        import recall_routes
        recall_routes.bot_store["bot-fb"] = {
            "status": "processing", "result": None, "error": None,
            "commands": [], "user_id": "user-1",
            "realtime_transcript_lines": ["Alice: from buffer"],
        }

        # _fetch_transcript returns None → triggers realtime-buffer fallback
        saved_fields: list[dict] = []
        async def fake_run_full_analysis(_t):
            return {"summary": "ok"}

        with patch.object(recall_routes, "_fetch_transcript", AsyncMock(return_value=None)), \
             patch.object(recall_routes, "_db_save", side_effect=lambda b, f: saved_fields.append(f)), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "run_full_analysis", side_effect=fake_run_full_analysis), \
             patch.object(recall_routes, "build_analysis_transcript", side_effect=lambda t, owner_name=None: t), \
             patch("realtime_routes.cleanup_bot_state"):
            asyncio.run(recall_routes._process_bot_transcript("bot-fb"))

        done_save = next((f for f in saved_fields if f.get("status") == "done"), None)
        self.assertIsNotNone(done_save)
        self.assertIsNone(done_save.get("transcript_segments"))


class TestSaveMeetingEnrichment(unittest.TestCase):
    def _make_client(self, bot_session_row: dict | None):
        """Build a fake supabase client that returns a specific bot_sessions row."""
        captured_upserts: list[dict] = []

        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def neq(self, *a, **k): return self
            def maybe_single(self): return self
            def upsert(self, payload, **k):
                captured_upserts.append({"table": self.name, "payload": payload})
                class _Exec:
                    def execute(_): return MagicMock(data=[])
                return _Exec()
            def execute(self):
                if self.name == "bot_sessions":
                    return MagicMock(data=bot_session_row)
                if self.name == "workspace_members":
                    return MagicMock(data=[])
                return MagicMock(data=[])

        client = MagicMock()
        client.table = lambda name: FakeTable(name)
        client.upserts = captured_upserts
        return client

    def test_enriches_meeting_row_when_caller_owns_bot(self):
        import storage_routes
        client = self._make_client({
            "bot_id": "bot-A", "user_id": "user-1",
            "transcript_segments": [{"speaker": "A", "start": 0, "end": 1, "text": "hi"}],
        })
        entry = storage_routes.MeetingEntry(
            id=42, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={}, recall_bot_id="bot-A",
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertEqual(meetings_upsert["payload"].get("recall_bot_id"), "bot-A")
        self.assertEqual(meetings_upsert["payload"].get("recording_provider"), "recall")
        self.assertEqual(meetings_upsert["payload"].get("transcript_segments"),
                         [{"speaker": "A", "start": 0, "end": 1, "text": "hi"}])

    def test_writes_nulls_when_caller_does_not_own_bot(self):
        import storage_routes
        # Bot exists but belongs to user-2; caller is user-1
        client = self._make_client({
            "bot_id": "bot-B", "user_id": "user-2",
            "transcript_segments": [{"speaker": "X", "start": 0, "end": 1, "text": "secret"}],
        })
        entry = storage_routes.MeetingEntry(
            id=43, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={}, recall_bot_id="bot-B",
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            # Save must SUCCEED (no 403)
            result = asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
            self.assertEqual(result, {"ok": True})
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertIsNone(meetings_upsert["payload"].get("recall_bot_id"))
        self.assertIsNone(meetings_upsert["payload"].get("recording_provider"))
        self.assertIsNone(meetings_upsert["payload"].get("transcript_segments"))

    def test_writes_nulls_when_no_recall_bot_id_provided(self):
        import storage_routes
        client = self._make_client(None)
        entry = storage_routes.MeetingEntry(
            id=44, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={},
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertIsNone(meetings_upsert["payload"].get("recall_bot_id"))
        self.assertIsNone(meetings_upsert["payload"].get("recording_provider"))


class TestFanOutPropagatesRecordingFields(unittest.TestCase):
    def test_fan_out_includes_recall_columns(self):
        import storage_routes
        captured_upserts: list[dict] = []

        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def neq(self, *a, **k): return self
            def upsert(self, payload, **k):
                captured_upserts.append({"table": self.name, "payload": payload})
                class _Exec:
                    def execute(_): return MagicMock(data=[])
                return _Exec()
            def execute(self):
                if self.name == "workspace_members":
                    return MagicMock(data=[{"user_id": "teammate-1"}, {"user_id": "teammate-2"}])
                return MagicMock(data=[])

        client = MagicMock()
        client.table = lambda name: FakeTable(name)

        entry = storage_routes.MeetingEntry(
            id=100, date="2026-05-24T10:00:00Z", title="shared",
            transcript="t", result={"summary": "s"},
            workspace_id="ws-1", recall_bot_id="bot-shared",
        )

        asyncio.run(storage_routes._fan_out_to_workspace(
            client, entry, recorder_user_id="owner-1", workspace_id="ws-1",
        ))

        fan_payloads = [u["payload"] for u in captured_upserts if u["table"] == "meetings"]
        self.assertEqual(len(fan_payloads), 2, "expected one upsert per teammate")
        for p in fan_payloads:
            self.assertIn("recall_bot_id", p)
            self.assertIn("recording_provider", p)
            self.assertIn("transcript_segments", p)
            self.assertEqual(p.get("recall_bot_id"), "bot-shared")
            self.assertEqual(p.get("recording_provider"), "recall")


if __name__ == "__main__":
    unittest.main()

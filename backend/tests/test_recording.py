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

# Ensure RECALL_API_KEY is set so storage_routes.RECALL_API_KEY is non-empty
# when the module is (re-)imported during tests. Tests that exercise the 404/auth
# path return before this check; tests that mock httpx still need the guard to pass.
import os as _os
_os.environ.setdefault("RECALL_API_KEY", "test-key")

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
            {"speaker": "Alice", "start": 0.5, "end": 1.6, "text": "Hello world", "static_participant_id": None},
            {"speaker": "Bob", "start": 2.0, "end": 2.3, "text": "Hi", "static_participant_id": None},
        ])

    def test_skips_segments_with_no_words(self):
        raw = [
            {"speaker": "Alice", "words": []},
            {"speaker": "Bob", "words": [{"text": "ok", "start_time": 1.0, "end_time": 1.2}]},
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [{"speaker": "Bob", "start": 1.0, "end": 1.2, "text": "ok", "static_participant_id": None}])

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
            {"speaker": "Carol", "start": 0.1, "end": 0.3, "text": "yo", "static_participant_id": None},
        ])

    def test_falls_back_to_unknown_speaker_label(self):
        raw = [{"words": [{"text": "hi", "start_time": 0.0, "end_time": 0.2}]}]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Speaker", "start": 0.0, "end": 0.2, "text": "hi", "static_participant_id": None},
        ])

    def test_async_nested_timestamp_format(self):
        # deepgram_async nests timing under start_timestamp.relative (not start_time).
        # Before the fix this produced start=0/end=0 for every async segment.
        raw = [{
            "participant": {
                "name": "200-0",
                "extra_data": {"google_meet": {"static_participant_id": "ABC123"}},
            },
            "words": [
                {"text": "Hello", "start_timestamp": {"relative": 98.0, "absolute": None},
                 "end_timestamp": {"relative": 98.4, "absolute": None}},
                {"text": "there", "start_timestamp": {"relative": 98.4, "absolute": None},
                 "end_timestamp": {"relative": 98.9, "absolute": None}},
            ],
        }]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "200-0", "start": 98.0, "end": 98.9, "text": "Hello there",
             "static_participant_id": "ABC123"},
        ])

    def test_participant_id_relabel(self):
        from recall_routes import _relabel_segments_by_participant_id
        segments = [
            {"speaker": "200-0", "start": 1.0, "end": 2.0, "text": "hi", "static_participant_id": "A"},
            {"speaker": "100-0", "start": 2.0, "end": 3.0, "text": "yo", "static_participant_id": "B"},
            {"speaker": "300-0", "start": 3.0, "end": 4.0, "text": "ok", "static_participant_id": "C"},
        ]
        n = _relabel_segments_by_participant_id(segments, {"A": "Alice", "B": "Bob"})
        self.assertEqual(n, 2)
        self.assertEqual(segments[0]["speaker"], "Alice")
        self.assertEqual(segments[1]["speaker"], "Bob")
        self.assertEqual(segments[2]["speaker"], "300-0")  # unmapped id keeps anon label
        # Empty map is a no-op.
        self.assertEqual(_relabel_segments_by_participant_id(segments, {}), 0)


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
        # Real dialogue (>= _MIN_HUMAN_WORDS) so the no-show guard doesn't short-circuit;
        # this test exercises the segment-saving path, not the empty-meeting path.
        fake_response.json.return_value = [
            {"speaker": "Alice", "words": [
                {"text": w, "start_time": i * 0.3, "end_time": i * 0.3 + 0.3}
                for i, w in enumerate(
                    "hi everyone let us walk through the full product roadmap and plan today".split()
                )
            ]},
        ]

        # Capture _db_save calls
        saved_fields: list[dict] = []
        def fake_db_save(bot_id, fields):
            saved_fields.append(fields)

        async def fake_run_full_analysis(_t, **_kwargs):
            return {"summary": "ok"}

        with patch.object(recall_routes, "_fetch_transcript", AsyncMock(return_value=fake_response)), \
             patch.object(recall_routes, "_db_save", side_effect=fake_db_save), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "run_full_analysis", side_effect=fake_run_full_analysis), \
             patch.object(recall_routes, "build_analysis_transcript", side_effect=lambda t, owner_name=None: t), \
             patch("realtime_routes.cleanup_bot_state"):
            asyncio.run(recall_routes._process_bot_transcript("bot-xyz"))

        # Segments are persisted to bot_sessions BEFORE the status flips to "done"
        # (race fix: the browser saves the instant it sees "done" and resolves
        # segments server-side from bot_sessions, so they must land first).
        seg_idx = next((i for i, f in enumerate(saved_fields) if "transcript_segments" in f), None)
        done_idx = next((i for i, f in enumerate(saved_fields) if f.get("status") == "done"), None)
        self.assertIsNotNone(seg_idx, "expected a _db_save call carrying transcript_segments")
        self.assertIsNotNone(done_idx, "expected a status=done _db_save call")
        self.assertLess(seg_idx, done_idx, "segments must be persisted before status flips to done")
        seg_save = saved_fields[seg_idx]
        self.assertNotIn("status", seg_save, "the segment save must not also flip status to done")
        segs = seg_save["transcript_segments"]
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["speaker"], "Alice")
        self.assertEqual(segs[0]["start"], 0.0)
        self.assertEqual(
            segs[0]["text"],
            "hi everyone let us walk through the full product roadmap and plan today",
        )

    def test_segments_null_when_realtime_buffer_fallback_used(self):
        import recall_routes
        recall_routes.bot_store["bot-fb"] = {
            "status": "processing", "result": None, "error": None,
            "commands": [], "user_id": "user-1",
            "realtime_transcript_lines": [
                "Alice: let us walk through the full product roadmap and the plan for today",
            ],
        }

        # _fetch_transcript returns None → triggers realtime-buffer fallback
        saved_fields: list[dict] = []
        async def fake_run_full_analysis(_t, **_kwargs):
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


class TestParseExpiresHint(unittest.TestCase):
    def test_returns_int_when_x_amz_expires_present(self):
        import storage_routes
        url = "https://example.s3.amazonaws.com/foo.mp4?X-Amz-Expires=3600&X-Amz-Signature=abc"
        self.assertEqual(storage_routes.parse_expires_hint(url), 3600)

    def test_returns_none_when_param_missing(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint("https://x.com/foo.mp4"))

    def test_returns_none_for_non_integer_value(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint(
            "https://x.com/foo.mp4?X-Amz-Expires=forever"
        ))

    def test_returns_none_for_empty_input(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint(""))
        self.assertIsNone(storage_routes.parse_expires_hint(None))


class TestGetRecordingEndpoint(unittest.TestCase):
    def _make_client(self, meeting_row, workspace_member_rows=None):
        captured: list = []
        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def in_(self, *a, **k): return self
            def maybe_single(self): return self
            def execute(self):
                if self.name == "meetings":
                    return MagicMock(data=meeting_row)
                if self.name == "workspace_members":
                    return MagicMock(data=workspace_member_rows or [])
                return MagicMock(data=[])
        client = MagicMock()
        client.table = lambda name: FakeTable(name)
        return client

    def _fake_recall_response(self, recordings_payload, status_code=200):
        async def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = status_code
            resp.json = lambda: {"recordings": recordings_payload}
            return resp
        return fake_get

    def test_returns_video_url_when_video_mixed_present(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{
            "media_shortcuts": {
                "video_mixed": {"data": {"download_url": "https://s3/foo.mp4?X-Amz-Expires=86400"}},
                "audio_mixed": {"data": {"download_url": "https://s3/foo.mp3?X-Amz-Expires=86400"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "video")
        self.assertEqual(result["url"], "https://s3/foo.mp4?X-Amz-Expires=86400")
        self.assertEqual(result["expires_hint_seconds"], 86400)

    def test_falls_back_to_audio_when_only_audio_present(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{
            "media_shortcuts": {
                "audio_mixed": {"data": {"download_url": "https://s3/foo.mp3"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "audio")
        self.assertEqual(result["url"], "https://s3/foo.mp3")

    def test_returns_not_ready_when_recording_exists_but_no_urls(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{"media_shortcuts": {}}]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_ready"})

    def test_returns_no_recording_when_recordings_array_empty(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([])
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "no_recording"})

    def test_returns_expired_on_recall_404(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([], status_code=404)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "expired"})

    def test_returns_not_found_on_recall_403(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([], status_code=403)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_found"})

    def test_returns_not_a_bot_meeting_when_recall_bot_id_null(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": None, "recording_provider": None,
        })
        with patch.object(storage_routes, "_require_storage", return_value=client):
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_a_bot_meeting"})

    def test_returns_404_when_caller_not_owner_or_workspace_member(self):
        from fastapi import HTTPException
        import storage_routes
        # Meeting owned by user-99, no workspace
        client = self._make_client({
            "id": 1, "user_id": "user-99", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_workspace_member_can_access(self):
        import storage_routes
        # Meeting owned by user-99 in workspace ws-1; caller user-1 is a member
        client = self._make_client(
            {
                "id": 1, "user_id": "user-99", "workspace_id": "ws-1",
                "recall_bot_id": "bot-1", "recording_provider": "recall",
            },
            workspace_member_rows=[{"user_id": "user-1"}],
        )
        recordings = [{
            "media_shortcuts": {
                "video_mixed": {"data": {"download_url": "https://s3/v.mp4"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch.object(storage_routes, "RECALL_API_KEY", "test-key"), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "video")


if __name__ == "__main__":
    unittest.main()

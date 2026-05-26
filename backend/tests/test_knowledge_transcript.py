# backend/tests/test_knowledge_transcript.py
import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class _FakeQuery:
    def __init__(self, sink):
        self.sink = sink
        self._table = None
        self._payload = None
    def table(self, name):
        self._table = name
        return self
    def insert(self, payload):
        self._payload = ("insert", payload)
        return self
    def update(self, payload):
        self._payload = ("update", payload)
        return self
    def select(self, *_a, **_k):
        return self
    def eq(self, *_a, **_k):
        return self
    def single(self):
        return self
    def execute(self):
        self.sink.append((self._table, self._payload))
        return MagicMock(data=[])


class _FakeSupabase:
    def __init__(self):
        self.ops = []
    def table(self, name):
        q = _FakeQuery(self.ops)
        q._table = name
        return q


class IndexMeetingTranscriptTests(unittest.TestCase):
    def test_creates_doc_row_and_indexes_chunks(self):
        import importlib, knowledge_transcript
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()

        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_transcript, "check_user_quota",
                          new=AsyncMock(return_value=None)), \
             patch.object(knowledge_transcript, "embed_batch",
                          new=AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=42,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-25T14:00:00",
                title="Planning Meeting",
                transcript="Alice: hello. Bob: hi back. " * 30,
            ))

        # Should have inserted into knowledge_docs and knowledge_chunks
        tables_touched = [op[0] for op in fake_sb.ops]
        self.assertIn("knowledge_docs", tables_touched)
        self.assertIn("knowledge_chunks", tables_touched)

    def test_skips_empty_transcript(self):
        import importlib, knowledge_transcript
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()
        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=42,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-25T14:00:00",
                title="Empty",
                transcript="",
            ))
        self.assertEqual(fake_sb.ops, [])


    def test_marks_doc_error_when_quota_exceeded(self):
        import importlib, knowledge_transcript, knowledge_service
        importlib.reload(knowledge_transcript)

        fake_sb = _FakeSupabase()

        async def raise_quota(*_a, **_k):
            raise knowledge_service.QuotaExceeded("over limit")

        with patch.object(knowledge_transcript, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_transcript, "check_user_quota",
                          new=AsyncMock(side_effect=raise_quota)), \
             patch.object(knowledge_transcript, "embed_batch",
                          new=AsyncMock(return_value=[])):
            asyncio.run(knowledge_transcript.index_meeting_transcript(
                meeting_id=99,
                user_id=str(uuid.uuid4()),
                workspace_id=None,
                date="2026-05-26T14:00:00",
                title="Long meeting",
                transcript="word " * 5000,
            ))

        # We should have inserted the doc row, then UPDATED it to status="error".
        # No knowledge_chunks insert should have happened.
        ops = fake_sb.ops
        self.assertIn("knowledge_docs", [t for t, _ in ops])
        self.assertNotIn("knowledge_chunks", [t for t, _ in ops])
        # Find the error update
        error_updates = [
            payload for table, payload in ops
            if table == "knowledge_docs"
            and payload is not None
            and payload[0] == "update"
            and payload[1].get("status") == "error"
        ]
        self.assertEqual(len(error_updates), 1)
        self.assertIn("over limit", error_updates[0][1].get("error_message", ""))


if __name__ == "__main__":
    unittest.main()

# backend/tests/test_storage_routes_transcript_guard.py
"""Fix #1 — only the primary recorder's POST triggers transcript indexing."""
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub the supabase module before any backend imports resolve it.
fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

from fastapi import FastAPI
from fastapi.testclient import TestClient

auth = importlib.import_module("auth")
storage_routes = importlib.import_module("storage_routes")


class _FakeQuery:
    """Minimal Supabase client double — every chained call returns self and
    .execute() returns a result with data=[] so upsert/insert succeed."""

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def insert(self, _payload):
        return self

    def upsert(self, _payload, **_kw):
        return self

    def update(self, _payload):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class _Result:
            data = []
        return _Result()


class TranscriptGuardTests(unittest.TestCase):
    """Verify that asyncio.create_task(index_meeting_transcript(...)) is only
    triggered by the primary recorder, never by a workspace fan-out recipient."""

    def _make_client(self, user_id="user-A"):
        """Build a TestClient with the fake DB and the given user_id injected."""
        app = FastAPI()
        app.include_router(storage_routes.router)
        app.dependency_overrides[auth.require_user_id] = lambda: user_id
        return TestClient(app, raise_server_exceptions=True)

    def _payload(self, *, recorded_by_user_id):
        return {
            "id": 42,
            "date": "2026-05-26T14:00:00",
            "title": "Planning Meeting",
            "score": 80,
            "transcript": "Alice: hi. Bob: hi back.",
            "result": {},
            "share_token": "tok",
            "workspace_id": "ws-123",
            "recorded_by_user_id": recorded_by_user_id,
        }

    def _run_post(self, user_id, recorded_by_user_id):
        """Post /meetings and return (response, index_mock) where index_mock
        records every direct call to index_meeting_transcript (i.e. the moment
        the coroutine is created — before the task scheduler runs it)."""
        # index_meeting_transcript is called to *create* the coroutine; we
        # replace it with a regular MagicMock so .call_count reflects whether
        # the guard let execution reach that line.
        index_mock = MagicMock(return_value=MagicMock())  # returns a fake coroutine-like

        fake_db = _FakeQuery()
        original_supabase = storage_routes.supabase
        storage_routes.supabase = fake_db
        try:
            with patch("storage_routes.index_meeting_transcript", index_mock), \
                 patch("storage_routes.asyncio.create_task", side_effect=lambda c: None):
                client = self._make_client(user_id=user_id)
                resp = client.post("/meetings", json=self._payload(recorded_by_user_id=recorded_by_user_id))
        finally:
            storage_routes.supabase = original_supabase

        return resp, index_mock

    def test_indexes_when_caller_is_primary_recorder(self):
        """recorded_by_user_id=None → caller is the recorder → index."""
        resp, index_mock = self._run_post(user_id="user-A", recorded_by_user_id=None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(index_mock.call_count, 1)

    def test_indexes_when_recorded_by_matches_caller(self):
        """recorded_by_user_id equals user_id → caller is the recorder → index."""
        resp, index_mock = self._run_post(user_id="user-A", recorded_by_user_id="user-A")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(index_mock.call_count, 1)

    def test_skips_when_caller_is_fanout_recipient(self):
        """recorded_by_user_id is a *different* user → caller is a fan-out
        teammate and must NOT trigger transcript indexing."""
        resp, index_mock = self._run_post(user_id="user-B", recorded_by_user_id="user-A")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(index_mock.call_count, 0)


if __name__ == "__main__":
    unittest.main()

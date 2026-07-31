"""_persist_bot_meeting must be blocked only by the OWNER's existing row.

A teammate's self-saved row (which now carries recall_bot_id for dedup) must not
make the server persist skip the absent owner's copy — that would strand the
meeting for the one person who wasn't there, and silently skip their stand-in
follow-up brief.
"""

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

import os as _os
_os.environ.setdefault("RECALL_API_KEY", "test-key")

fake_groq_module = types.ModuleType("groq")
class _FakeAsyncGroq:
    def __init__(self, *a, **k):
        pass
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

import recall_routes
import storage_routes
from test_storage_routes import FakeSupabase


class TestPersistBotMeetingOwnerScoped(unittest.TestCase):
    def test_persist_not_blocked_by_teammates_row(self):
        fake = FakeSupabase()
        fake.tables["meeting_bots"] = []
        fake.tables["meetings"] = [
            # Teammate self-saved first (carries recall_bot_id after the dedup fix).
            {"id": 555, "user_id": "member-2", "date": "2026-07-30T10:00:00Z",
             "title": "M", "score": 50, "transcript": "t", "result": {"summary": "x"},
             "recall_bot_id": "bot-1"},
        ]
        fake.tables["bot_sessions"] = [
            {"bot_id": "bot-1", "user_id": "owner-9",
             "result": {"summary": "s", "health_score": {"score": 70}},
             "transcript": "t", "transcript_segments": None},
        ]
        recall_routes._standin_persisted.discard("bot-1")
        with patch.object(recall_routes, "supabase", fake), \
             patch.object(storage_routes, "supabase", fake), \
             patch.object(recall_routes, "_resolve_owner_workspace", return_value=("owner-9", None)):
            asyncio.run(recall_routes._persist_bot_meeting("bot-1"))

        owner_rows = [r for r in fake.tables["meetings"] if r.get("user_id") == "owner-9"]
        self.assertEqual(len(owner_rows), 1)  # the absent owner still gets their copy

    def test_persist_skips_when_owner_row_exists(self):
        fake = FakeSupabase()
        fake.tables["meeting_bots"] = []
        fake.tables["meetings"] = [
            {"id": 111, "user_id": "owner-9", "date": "2026-07-30T10:00:00Z",
             "title": "M", "score": 50, "transcript": "t", "result": {"summary": "x"},
             "recall_bot_id": "bot-1"},
        ]
        fake.tables["bot_sessions"] = [
            {"bot_id": "bot-1", "user_id": "owner-9",
             "result": {"summary": "s"}, "transcript": "t", "transcript_segments": None},
        ]
        recall_routes._standin_persisted.discard("bot-1")
        with patch.object(recall_routes, "supabase", fake), \
             patch.object(storage_routes, "supabase", fake), \
             patch.object(recall_routes, "_resolve_owner_workspace", return_value=("owner-9", None)):
            asyncio.run(recall_routes._persist_bot_meeting("bot-1"))

        owner_rows = [r for r in fake.tables["meetings"] if r.get("user_id") == "owner-9"]
        self.assertEqual(len(owner_rows), 1)  # idempotent — no second owner row


class TestStandinFollowupDispatch(unittest.TestCase):
    """The absent author's follow-up brief must fire regardless of who saved first."""

    def _run_dispatch(self, fake, **kwargs):
        from unittest.mock import AsyncMock
        import proxy_routes
        generate = AsyncMock()
        with patch.object(recall_routes, "supabase", fake), \
             patch.object(proxy_routes, "generate_standin_followups", generate), \
             patch.object(recall_routes, "_resolve_owner_workspace", return_value=("owner-9", None)):
            asyncio.run(recall_routes._dispatch_standin_followups("bot-1", **kwargs))
        return generate

    def test_dispatch_runs_when_browser_saved_first(self):
        # The original bug: the owner's row already exists (browser won the race),
        # _persist_bot_meeting early-returns, and the brief was silently skipped.
        fake = FakeSupabase()
        fake.tables["meetings"] = [
            {"id": 111, "user_id": "owner-9", "recall_bot_id": "bot-1",
             "date": "2026-07-30T10:00:00Z", "title": "M", "score": 50,
             "transcript": "t", "result": {"summary": "x"}},
        ]
        generate = self._run_dispatch(fake, result={"summary": "s"}, transcript="t")
        generate.assert_awaited_once_with("bot-1", 111, {"summary": "s"}, "t")

    def test_dispatch_loads_result_from_bot_sessions_when_not_given(self):
        # Startup-backfill shape: only a bot_id is known.
        fake = FakeSupabase()
        fake.tables["bot_sessions"] = [
            {"bot_id": "bot-1", "result": {"summary": "s"}, "transcript": "t"},
        ]
        generate = self._run_dispatch(fake)
        generate.assert_awaited_once_with("bot-1", None, {"summary": "s"}, "t")

    def test_dispatch_skips_without_result(self):
        fake = FakeSupabase()
        generate = self._run_dispatch(fake)
        generate.assert_not_awaited()


class TestFollowupClaimBeforeSend(unittest.TestCase):
    """generate_standin_followups must email at most once per rep, even when
    dispatched concurrently (overlapping deploy processes, startup backfill)."""

    def _generate(self, fake, email_mock, brief="the brief"):
        import proxy_routes
        from unittest.mock import AsyncMock
        with patch.object(proxy_routes, "supabase", fake), \
             patch.object(proxy_routes, "_build_followup_brief", AsyncMock(return_value=brief)), \
             patch.object(proxy_routes, "_email_followup_brief", email_mock):
            import asyncio as _a
            _a.run(proxy_routes.generate_standin_followups("bot-1", 111, {"summary": "s"}, "t"))

    def test_second_dispatch_does_not_email_again(self):
        from unittest.mock import AsyncMock
        fake = FakeSupabase()
        fake.tables["proxy_representations"] = [
            {"id": 1, "delivered_bot_id": "bot-1", "status": "delivered",
             "followup_brief": None, "author_email": "a@b.com", "author_user_id": "u1",
             "meeting_label": "M"},
        ]
        email = AsyncMock(return_value=True)
        self._generate(fake, email)
        self._generate(fake, email)
        self.assertEqual(email.await_count, 1)
        rep = fake.tables["proxy_representations"][0]
        self.assertEqual(rep["followup_brief"], "the brief")
        self.assertIsNotNone(rep.get("followup_sent_at"))

    def test_lost_claim_race_skips_email(self):
        # Simulate a concurrent dispatcher stamping the rep AFTER our stale read
        # but BEFORE our claim: the conditional update matches no row → no email.
        from unittest.mock import AsyncMock
        import proxy_routes
        fake = FakeSupabase()
        fake.tables["proxy_representations"] = [
            {"id": 1, "delivered_bot_id": "bot-1", "status": "delivered",
             "followup_brief": None, "author_email": "a@b.com", "author_user_id": "u1",
             "meeting_label": "M"},
        ]
        email = AsyncMock(return_value=True)

        async def build_and_lose_race(*_a, **_k):
            fake.tables["proxy_representations"][0]["followup_brief"] = "someone else's brief"
            return "our brief"

        with patch.object(proxy_routes, "supabase", fake), \
             patch.object(proxy_routes, "_build_followup_brief", build_and_lose_race), \
             patch.object(proxy_routes, "_email_followup_brief", email):
            asyncio.run(proxy_routes.generate_standin_followups("bot-1", 111, {"summary": "s"}, "t"))

        email.assert_not_awaited()
        self.assertEqual(fake.tables["proxy_representations"][0]["followup_brief"],
                         "someone else's brief")


if __name__ == "__main__":
    unittest.main()

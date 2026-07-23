"""Phase 4 — GET /live/{live_token} screenshare mirror payload.

Exercises the real `recall_routes.live_meeting` handler with a fake live-token
store and a faked `presentation.active_present_info`, asserting the members-only
gating on the `screenshare.view_url`:

  - presenting + authenticated workspace member  -> view_url set (+ active/goal)
  - presenting + authenticated personal-bot owner -> view_url set
  - presenting + anonymous link-holder           -> active true, view_url null
  - presenting + authenticated NON-member         -> active true, view_url null
  - not presenting                                -> active false, all null

No live meeting / Recall / real DB is involved; the workspace-member lookup is
served by a tiny in-memory fake supabase. (Noted: there is no live meeting to
run this against — verification is unit-level only.)
"""
import types
import unittest
from unittest import mock

import recall_routes as rc


class _FakeRequest:
    """Stand-in for starlette Request. `live_meeting` only forwards it to
    `_optional_user_id`, which every test patches, so its contents don't matter."""
    pass


# --- tiny fake supabase supporting the exact chain _caller_is_bot_member uses:
#     table(..).select(..).eq(..).eq(..).maybe_single().execute().data
class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, member_row):
        self._member_row = member_row

    def table(self, _name):
        return _FakeQuery(self._member_row)


_PRESENT = {"goal": "the Q3 roadmap", "token": "ptok-abc"}


class LiveScreensharePayloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot_id = "bot-xyz"
        self.token = "livetok-1"
        self._orig_index = dict(rc._live_token_index)
        self._orig_store = dict(rc.bot_store)
        self._orig_supabase = rc.supabase
        rc._live_token_index[self.token] = self.bot_id
        # Pre-set "brief" so the handler skips the _build_pre_meeting_brief thread
        # call; status="recording" keeps the empty-rt memory/counters no-op path.
        rc.bot_store[self.bot_id] = {
            "status": "recording",
            "commands": [],
            "result": None,
            "error": None,
            "brief": {"open_items": [], "recent_decisions": [], "blockers": []},
            "user_id": "owner-1",
            "workspace_id": None,
        }

    def tearDown(self):
        rc._live_token_index.clear()
        rc._live_token_index.update(self._orig_index)
        rc.bot_store.clear()
        rc.bot_store.update(self._orig_store)
        rc.supabase = self._orig_supabase

    async def _call(self):
        return await rc.live_meeting(self.token, _FakeRequest())

    def _patch_caller(self, caller_id):
        return mock.patch.object(rc, "_optional_user_id", mock.AsyncMock(return_value=caller_id))

    async def test_presenting_personal_owner_gets_view_url(self):
        # Personal bot (workspace_id=None): membership == owner match, no DB needed.
        with mock.patch("presentation.active_present_info", return_value=dict(_PRESENT)), \
             self._patch_caller("owner-1"):
            payload = await self._call()
        sc = payload["screenshare"]
        self.assertTrue(sc["active"])
        self.assertEqual(sc["goal"], "the Q3 roadmap")
        self.assertIsNotNone(sc["view_url"])
        self.assertTrue(sc["view_url"].endswith("/present/ptok-abc"))

    async def test_presenting_workspace_member_gets_view_url(self):
        rc.bot_store[self.bot_id]["workspace_id"] = "ws-1"
        rc.supabase = _FakeSupabase({"user_id": "u1"})  # membership row exists
        with mock.patch("presentation.active_present_info", return_value=dict(_PRESENT)), \
             self._patch_caller("u1"):
            payload = await self._call()
        sc = payload["screenshare"]
        self.assertTrue(sc["active"])
        self.assertTrue(sc["view_url"].endswith("/present/ptok-abc"))

    async def test_presenting_anonymous_no_view_url(self):
        with mock.patch("presentation.active_present_info", return_value=dict(_PRESENT)), \
             self._patch_caller(None):  # no Bearer -> anonymous link-holder
            payload = await self._call()
        sc = payload["screenshare"]
        self.assertTrue(sc["active"])
        self.assertEqual(sc["goal"], "the Q3 roadmap")
        self.assertIsNone(sc["view_url"])

    async def test_presenting_authenticated_nonmember_no_view_url(self):
        rc.bot_store[self.bot_id]["workspace_id"] = "ws-1"
        rc.supabase = _FakeSupabase(None)  # no membership row
        with mock.patch("presentation.active_present_info", return_value=dict(_PRESENT)), \
             self._patch_caller("stranger"):
            payload = await self._call()
        sc = payload["screenshare"]
        self.assertTrue(sc["active"])
        self.assertIsNone(sc["view_url"])

    async def test_not_presenting_inactive(self):
        with mock.patch("presentation.active_present_info", return_value=None), \
             self._patch_caller("owner-1"):
            payload = await self._call()
        sc = payload["screenshare"]
        self.assertFalse(sc["active"])
        self.assertIsNone(sc["goal"])
        self.assertIsNone(sc["view_url"])


if __name__ == "__main__":
    unittest.main()

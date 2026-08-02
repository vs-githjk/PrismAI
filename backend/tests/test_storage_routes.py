import importlib
import sys
from datetime import UTC, datetime, timedelta
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")


def _unused_create_client(*_args, **_kwargs):
    return None


fake_supabase_module.create_client = _unused_create_client
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

auth = importlib.import_module("auth")
storage_routes = importlib.import_module("storage_routes")


class FakeExecuteResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.mode = "select"
        self.selected_fields = None
        self.filters = []
        self.order_field = None
        self.order_desc = False
        self.limit_count = None
        self.update_payload = None
        self.insert_payload = None
        self.upsert_payload = None

    def select(self, fields):
        self.mode = "select"
        self.selected_fields = [field.strip() for field in fields.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def neq(self, field, value):
        self.filters.append((field, ("neq", value)))
        return self

    def is_(self, field, value):
        # Mirrors Supabase's .is_("col", None) → SQL `col IS NULL`.
        # Accepts either the Python None or the string "null" (some callsites use the literal).
        target = None if value in (None, "null", "NULL") else value
        self.filters.append((field, ("is_", target)))
        return self

    def ilike(self, field, pattern):
        needle = pattern.strip("%").lower()
        self.filters.append((field, ("ilike", needle)))
        return self

    def order(self, field, desc=False):
        self.order_field = field
        self.order_desc = desc
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def update(self, payload):
        self.mode = "update"
        self.update_payload = payload
        return self

    def delete(self):
        self.mode = "delete"
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.insert_payload = payload
        return self

    def upsert(self, payload, **kwargs):
        # on_conflict picks the composite/unique key to match an existing row on.
        # Default is "id" (covers most tables in the fake); the chats table uses
        # "meeting_id,user_id" because it has no surrogate id.
        self.mode = "upsert"
        self.upsert_payload = payload
        self.upsert_conflict_keys = [
            k.strip() for k in (kwargs.get("on_conflict") or "id").split(",")
        ]
        return self

    def _matches(self, row):
        for field, value in self.filters:
            if isinstance(value, tuple) and value[0] == "ilike":
                if value[1] not in str(row.get(field, "")).lower():
                    return False
            elif isinstance(value, tuple) and value[0] == "is_":
                if row.get(field) is not value[1]:
                    return False
            elif isinstance(value, tuple) and value[0] == "neq":
                if row.get(field) == value[1]:
                    return False
            elif row.get(field) != value:
                return False
        return True

    def execute(self):
        rows = self.client.tables[self.table_name]

        if self.mode == "select":
            matched = [row.copy() for row in rows if self._matches(row)]
            if self.order_field:
                matched.sort(key=lambda row: row.get(self.order_field), reverse=self.order_desc)
            if self.limit_count is not None:
                matched = matched[: self.limit_count]
            if self.selected_fields and self.selected_fields != ["*"]:
                matched = [
                    {field: row.get(field) for field in self.selected_fields}
                    for row in matched
                ]
            if getattr(self, "_maybe_single", False):
                return FakeExecuteResult(matched[0] if matched else None)
            return FakeExecuteResult(matched)

        if self.mode == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self.update_payload)
                    updated.append(row.copy())
            return FakeExecuteResult(updated)

        if self.mode == "delete":
            kept = []
            deleted = []
            for row in rows:
                if self._matches(row):
                    deleted.append(row.copy())
                else:
                    kept.append(row)
            self.client.tables[self.table_name] = kept
            return FakeExecuteResult(deleted)

        if self.mode == "insert":
            payload = self.insert_payload.copy()
            payload.setdefault("id", len(rows) + 1)
            rows.append(payload)
            return FakeExecuteResult([payload.copy()])

        if self.mode == "upsert":
            payload = self.upsert_payload.copy()
            conflict_keys = getattr(self, "upsert_conflict_keys", ["id"])
            key_values = tuple(payload.get(k) for k in conflict_keys)
            for row in rows:
                if tuple(row.get(k) for k in conflict_keys) == key_values:
                    row.update(payload)
                    return FakeExecuteResult([row.copy()])
            rows.append(payload)
            return FakeExecuteResult([payload.copy()])

        raise AssertionError(f"Unsupported mode: {self.mode}")


class FakeSupabase:
    def __init__(self):
        self.tables = {"meetings": [], "chats": [], "bot_sessions": [],
                       "knowledge_docs": [], "knowledge_chunks": [],
                       "workspace_members": []}

    def table(self, table_name):
        return FakeQuery(self, table_name)


class StorageRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeSupabase()
        self.original_supabase = storage_routes.supabase
        storage_routes.supabase = self.fake_db

        self.app = FastAPI()
        self.app.include_router(storage_routes.router)
        self.app.dependency_overrides[auth.require_user_id] = lambda: "user-123"
        self.client = TestClient(self.app)

    def tearDown(self):
        storage_routes.supabase = self.original_supabase
        self.app.dependency_overrides.clear()

    def test_get_meetings_returns_only_current_users_rows(self):
        self.fake_db.tables["meetings"] = [
            {"id": 2, "user_id": "user-999", "date": "2026-04-01", "title": "Other", "score": 10, "transcript": "", "result": {}, "share_token": None},
            {"id": 3, "user_id": "user-123", "date": "2026-04-02", "title": "Roadmap", "score": 88, "transcript": "a", "result": {}, "share_token": None},
            {"id": 1, "user_id": "user-123", "date": "2026-04-01", "title": "Budget", "score": 70, "transcript": "b", "result": {}, "share_token": None},
        ]

        response = self.client.get("/meetings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_meetings_filters_placeholder_results(self):
        self.fake_db.tables["meetings"] = [
            {
                "id": 5,
                "user_id": "user-123",
                "date": "2026-04-05",
                "title": "Placeholder",
                "score": 0,
                "transcript": "a",
                "result": {
                    "summary": "",
                    "action_items": [],
                    "decisions": [],
                    "health_score": {"score": 0, "verdict": ""},
                    "sentiment": {"notes": ""},
                },
                "share_token": None,
            },
            {
                "id": 4,
                "user_id": "user-123",
                "date": "2026-04-04",
                "title": "Real",
                "score": 88,
                "transcript": "b",
                "result": {"summary": "A real summary"},
                "share_token": None,
            },
        ]

        response = self.client.get("/meetings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [4])

    def test_save_meeting_attaches_user_id(self):
        payload = {
            "id": 11,
            "date": "2026-04-05",
            "title": "Weekly sync",
            "score": 92,
            "transcript": "Speaker: hello",
            "result": {"summary": "Done"},
            "share_token": "share-123",
        }

        response = self.client.post("/meetings", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fake_db.tables["meetings"][0]["user_id"], "user-123")
        self.assertEqual(self.fake_db.tables["meetings"][0]["share_token"], "share-123")

    def test_save_meeting_dedups_by_recall_bot_id(self):
        # The "5 meetings from 1 join" bug: the same bot saved more than once (browser
        # + server recovery across Render restarts) with different client ids must
        # converge to ONE row, not duplicate.
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-xyz", "user_id": "user-123", "transcript_segments": None},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 111, "user_id": "user-123", "date": "2026-07-05", "title": "M",
             "score": 50, "transcript": "t", "result": {"summary": "x"},
             "recall_bot_id": "bot-xyz"},
        ]
        # Second save for the SAME bot, different client-generated id.
        response = self.client.post("/meetings", json={
            "id": 999, "date": "2026-07-05", "title": "M", "score": 50,
            "transcript": "t", "result": {"summary": "x"}, "recall_bot_id": "bot-xyz",
        })
        self.assertEqual(response.status_code, 200)
        bot_rows = [r for r in self.fake_db.tables["meetings"] if r.get("recall_bot_id") == "bot-xyz"]
        self.assertEqual(len(bot_rows), 1)          # not duplicated
        self.assertEqual(bot_rows[0]["id"], 111)    # reused the existing row's id

    def test_save_meeting_dedups_for_non_owner_saver(self):
        # The stand-in duplication bug: a workspace teammate whose dashboard polls
        # a bot they DON'T own also auto-saves on done. Their save must converge
        # onto the fan-out copy the server persist already wrote for them — not
        # insert a second row (which duplicated every action item in Brief/insights).
        import caches
        caches.invalidate_user_workspaces()
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-standin", "user_id": "owner-9", "transcript_segments": [{"t": 1}]},
        ]
        # The caller keeps the bot reference only as a member of the bot's workspace.
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": "bot-standin", "owner_user_id": "owner-9", "workspace_id": "ws-1"},
        ]
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "owner-9"},
            {"workspace_id": "ws-1", "user_id": "user-123"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 111, "user_id": "owner-9", "date": "2026-07-30T10:00:00Z", "title": "M",
             "score": 50, "transcript": "t", "result": {"summary": "x"},
             "recall_bot_id": "bot-standin", "workspace_id": "ws-1",
             "recording_provider": "recall", "transcript_segments": [{"t": 1}]},
            {"id": 222, "user_id": "user-123", "date": "2026-07-30T10:00:00Z", "title": "M",
             "score": 50, "transcript": "t", "result": {"summary": "x"},
             "recall_bot_id": "bot-standin", "workspace_id": "ws-1",
             "recorded_by_user_id": "owner-9",
             "recording_provider": "recall", "transcript_segments": [{"t": 1}]},
        ]
        response = self.client.post("/meetings", json={
            "id": 999, "date": "2026-07-30T10:00:31Z", "title": "M", "score": 50,
            "transcript": "t", "result": {"summary": "x"},
            "recall_bot_id": "bot-standin", "recorded_by_user_id": "owner-9",
        })
        self.assertEqual(response.status_code, 200)
        mine = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "user-123"]
        self.assertEqual(len(mine), 1)            # converged — no duplicate row
        self.assertEqual(mine[0]["id"], 222)      # reused the fan-out copy's id
        # The non-owner save must not clobber the recording fields the fan-out wrote.
        self.assertEqual(mine[0]["transcript_segments"], [{"t": 1}])
        self.assertEqual(mine[0]["recording_provider"], "recall")

    def test_fan_out_reuses_members_existing_bot_row(self):
        # A member who self-saved before the fan-out arrived must get their row
        # UPDATED in place (enriched with recording fields), not a second fan_id copy.
        import asyncio as _asyncio

        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "owner-9"},
            {"workspace_id": "ws-1", "user_id": "member-2"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 555, "user_id": "member-2", "date": "2026-07-30T10:00:31Z", "title": "M",
             "score": 50, "transcript": "t", "result": {"summary": "x"},
             "share_token": "member-tok",
             "recall_bot_id": "bot-standin", "workspace_id": "ws-1"},
        ]
        entry = storage_routes.MeetingEntry(
            id=111, date="2026-07-30T10:00:00Z", title="M", score=50,
            transcript="t", result={"summary": "x"},
            workspace_id="ws-1", recall_bot_id="bot-standin",
        )
        entry.__dict__["_resolved_provider"] = "recall"
        entry.__dict__["_resolved_segments"] = [{"t": 1}]
        _asyncio.run(storage_routes._fan_out_to_workspace(self.fake_db, entry, "owner-9", "ws-1"))
        member_rows = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "member-2"]
        self.assertEqual(len(member_rows), 1)     # no fan_id duplicate
        self.assertEqual(member_rows[0]["id"], 555)
        self.assertEqual(member_rows[0]["transcript_segments"], [{"t": 1}])  # self-healed
        # Converged enrichment must not clobber the member's own share links.
        self.assertEqual(member_rows[0]["share_token"], "member-tok")

    def test_fan_out_does_not_clobber_recording_fields_without_segments(self):
        # Reverse order: server fan-out (with segments) landed first; a teammate's
        # save triggers a second fan-out that has NO resolved segments. Updating
        # existing rows must leave the recording fields alone.
        import asyncio as _asyncio

        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "user-123"},
            {"workspace_id": "ws-1", "user_id": "member-2"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 555, "user_id": "member-2", "date": "2026-07-30T10:00:00Z", "title": "M",
             "score": 50, "transcript": "t", "result": {"summary": "x"},
             "share_token": "member-tok",
             "recall_bot_id": "bot-standin", "workspace_id": "ws-1",
             "recording_provider": "recall", "transcript_segments": [{"t": 1}]},
        ]
        entry = storage_routes.MeetingEntry(
            id=999, date="2026-07-30T10:00:31Z", title="TAMPERED", score=50,
            transcript="attacker text", result={"summary": "attacker"},
            workspace_id="ws-1", recall_bot_id="bot-standin",
            recorded_by_user_id="owner-9",
        )
        _asyncio.run(storage_routes._fan_out_to_workspace(self.fake_db, entry, "owner-9", "ws-1"))
        member_rows = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "member-2"]
        self.assertEqual(len(member_rows), 1)
        self.assertEqual(member_rows[0]["transcript_segments"], [{"t": 1}])
        self.assertEqual(member_rows[0]["recording_provider"], "recall")
        # A converging writer without segments must not touch the member's row
        # AT ALL — no content tamper, no share-link wipe.
        self.assertEqual(member_rows[0]["title"], "M")
        self.assertEqual(member_rows[0]["transcript"], "t")
        self.assertEqual(member_rows[0]["share_token"], "member-tok")

    def test_save_meeting_drops_bot_reference_for_strangers(self):
        # A caller with NO relationship to the bot (not owner, not in its
        # workspace) must not be able to store a reference to it — the reference
        # is a capability (recording fetch, tombstone delete).
        import caches
        caches.invalidate_user_workspaces()
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-victim", "user_id": "victim-1", "transcript_segments": [{"t": 1}]},
        ]
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": "bot-victim", "owner_user_id": "victim-1", "workspace_id": "ws-victim"},
        ]
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-victim", "user_id": "victim-1"},
        ]
        response = self.client.post("/meetings", json={
            "id": 999, "date": "2026-07-30T10:00:00Z", "title": "fake", "score": 1,
            "transcript": "x", "result": {"summary": "x"}, "recall_bot_id": "bot-victim",
        })
        self.assertEqual(response.status_code, 200)
        saved = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "user-123"]
        self.assertEqual(len(saved), 1)
        self.assertIsNone(saved[0].get("recall_bot_id"))
        self.assertIsNone(saved[0].get("transcript_segments"))

    def test_delete_does_not_tombstone_someone_elses_bot(self):
        # Cross-user DoS guard: deleting your own row that references another
        # user's bot must NOT flip their meeting_bots row to 'deleted'.
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": "bot-victim", "owner_user_id": "victim-1",
             "workspace_id": None, "status": "done"},
        ]
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-victim", "user_id": "victim-1"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 999, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "fake", "workspace_id": None, "recall_bot_id": "bot-victim"},
        ]
        response = self.client.delete("/meetings/999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fake_db.tables["meeting_bots"][0]["status"], "done")

    def test_delete_tombstones_own_bot(self):
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": "bot-mine", "owner_user_id": "user-123",
             "workspace_id": None, "status": "done"},
        ]
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-mine", "user_id": "user-123"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 998, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "mine", "workspace_id": None, "recall_bot_id": "bot-mine"},
        ]
        response = self.client.delete("/meetings/998")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fake_db.tables["meeting_bots"][0]["status"], "deleted")

    def test_recording_endpoint_rejects_bot_strangers(self):
        # Even with row access, the recording is gated by the BOT's owner/workspace.
        import caches
        caches.invalidate_user_workspaces()
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": "bot-victim", "owner_user_id": "victim-1", "workspace_id": "ws-victim"},
        ]
        self.fake_db.tables["bot_sessions"] = [
            {"bot_id": "bot-victim", "user_id": "victim-1"},
        ]
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-victim", "user_id": "victim-1"},
        ]
        self.fake_db.tables["meetings"] = [
            # Attacker-owned row referencing the victim's bot (e.g. minted before
            # the save-side guard existed).
            {"id": 999, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "fake", "workspace_id": None, "recall_bot_id": "bot-victim"},
        ]
        response = self.client.get("/meetings/999/recording")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": None, "reason": "not_authorized"})

    def _bot_owned_by(self, bot_id, owner, workspace_id=None):
        import caches
        caches.invalidate_user_workspaces()
        self.fake_db.tables["bot_sessions"] = [{"bot_id": bot_id, "user_id": owner}]
        self.fake_db.tables["meeting_bots"] = [
            {"bot_id": bot_id, "owner_user_id": owner,
             "workspace_id": workspace_id, "status": "done"},
        ]

    def test_save_meeting_server_derives_recorder_from_bot_owner(self):
        # recorded_by_user_id decides meeting ownership in delete/move (whose
        # cascades hit every member's copy). A client must not be able to omit it
        # and become "owner" of someone else's recording.
        self._bot_owned_by("bot-v", "victim-1", "ws-1")
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "victim-1"},
            {"workspace_id": "ws-1", "user_id": "user-123"},
        ]
        response = self.client.post("/meetings", json={
            "id": 4242, "date": "2026-07-30T10:00:00Z", "title": "M", "score": 1,
            "transcript": "t", "result": {"summary": "x"},
            "workspace_id": "ws-1", "recall_bot_id": "bot-v",
            # recorded_by_user_id deliberately omitted (the escalation attempt)
        })
        self.assertEqual(response.status_code, 200)
        mine = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "user-123"]
        self.assertEqual(mine[0]["recorded_by_user_id"], "victim-1")

    def test_workspace_delete_by_non_bot_owner_only_removes_own_copy(self):
        # The cascade + tombstone must require real bot ownership, not a
        # self-declared row.
        self._bot_owned_by("bot-v", "victim-1", "ws-1")
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "victim-1"},
            {"workspace_id": "ws-1", "user_id": "user-123"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 100, "user_id": "victim-1", "date": "2026-07-30T10:00:00Z",
             "title": "M", "workspace_id": "ws-1", "recall_bot_id": "bot-v"},
            {"id": 4242, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "M", "workspace_id": "ws-1", "recall_bot_id": "bot-v",
             "recorded_by_user_id": None},  # attacker's row, ownership unclaimed
        ]
        response = self.client.delete("/meetings/4242")
        self.assertEqual(response.status_code, 200)
        remaining = {r["id"] for r in self.fake_db.tables["meetings"]}
        self.assertEqual(remaining, {100})  # victim's row survives
        self.assertEqual(self.fake_db.tables["meeting_bots"][0]["status"], "done")

    def test_recording_allows_workspace_member_for_moved_personal_bot(self):
        # Legit flow: bot recorded in Personal scope (meeting_bots.workspace_id
        # NULL), owner later moved the meeting into a workspace and fanned it out.
        # Members must still get the player.
        self._bot_owned_by("bot-o", "owner-9", None)
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "owner-9"},
            {"workspace_id": "ws-1", "user_id": "user-123"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 77, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "M", "workspace_id": "ws-1", "recall_bot_id": "bot-o",
             "recorded_by_user_id": "owner-9"},
        ]
        with patch.object(storage_routes, "RECALL_API_KEY", ""):
            response = self.client.get("/meetings/77/recording")
        # Passed the capability gate (fails later on the missing Recall key).
        self.assertEqual(response.status_code, 503)

    def test_recording_still_blocks_forged_recorder_claim(self):
        # Same shape as above but the row is NOT in a workspace the caller shares
        # with the bot owner → still refused.
        self._bot_owned_by("bot-o", "owner-9", None)
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-attacker", "user_id": "user-123"},
        ]
        self.fake_db.tables["meetings"] = [
            {"id": 78, "user_id": "user-123", "date": "2026-07-30T10:00:00Z",
             "title": "M", "workspace_id": None, "recall_bot_id": "bot-o",
             "recorded_by_user_id": "owner-9"},
        ]
        response = self.client.get("/meetings/78/recording")
        self.assertEqual(response.json(), {"url": None, "reason": "not_authorized"})

    def test_fan_out_enrichment_does_not_resurrect_deleted_member_row(self):
        import asyncio as _asyncio
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-1", "user_id": "owner-9"},
            {"workspace_id": "ws-1", "user_id": "member-2"},
        ]
        self.fake_db.tables["meetings"] = []  # member deleted their copy
        entry = storage_routes.MeetingEntry(
            id=111, date="2026-07-30T10:00:00Z", title="M", score=50,
            transcript="t", result={"summary": "x"},
            workspace_id="ws-1", recall_bot_id="bot-standin",
        )
        entry.__dict__["_resolved_segments"] = [{"t": 1}]
        _asyncio.run(storage_routes._fan_out_to_workspace(self.fake_db, entry, "owner-9", "ws-1"))
        rows = [r for r in self.fake_db.tables["meetings"] if r.get("user_id") == "member-2"]
        # A fresh full copy is fine; a 3-field skeleton is not.
        self.assertTrue(all(r.get("date") and r.get("result") is not None for r in rows))

    def test_move_meeting_owner_to_personal_cascades_removes_fanout(self):
        # Owner moves a workspace meeting to Personal → own copy becomes Personal AND
        # teammates' fan-out copies are removed (the meeting leaves the workspace).
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},
            {"id": 2, "user_id": "user-999", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},  # teammate fan-out copy
        ]
        resp = self.client.post("/meetings/1/move", json={"workspace_id": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["workspace_id"])
        rows = {r["id"]: r for r in self.fake_db.tables["meetings"]}
        self.assertEqual(set(rows), {1})               # teammate copy gone
        self.assertIsNone(rows[1]["workspace_id"])     # my copy is now Personal

    def test_move_meeting_to_workspace_requires_membership(self):
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": None, "recorded_by_user_id": "user-123"},
        ]
        with patch.object(storage_routes, "is_workspace_member", return_value=False):
            resp = self.client.post("/meetings/1/move", json={"workspace_id": "ws-x"})
        self.assertEqual(resp.status_code, 403)
        self.assertIsNone(self.fake_db.tables["meetings"][0]["workspace_id"])  # unchanged

    def test_move_meeting_to_workspace_fans_out_to_members(self):
        # Owner moves a Personal meeting into a workspace → own copy scoped to the
        # workspace AND a fan-out copy is created for each other member.
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": None, "recorded_by_user_id": "user-123",
             "recall_bot_id": None, "date": "2026-07-05", "title": "M", "result": {}, "transcript": "t"},
        ]
        self.fake_db.tables["workspace_members"] = [
            {"workspace_id": "ws-x", "user_id": "user-123"},
            {"workspace_id": "ws-x", "user_id": "user-999"},
        ]
        with patch.object(storage_routes, "is_workspace_member", return_value=True):
            resp = self.client.post("/meetings/1/move", json={"workspace_id": "ws-x"})
        self.assertEqual(resp.status_code, 200)
        rows = self.fake_db.tables["meetings"]
        owner_row = next(r for r in rows if r["id"] == 1)
        self.assertEqual(owner_row["workspace_id"], "ws-x")
        fan = [r for r in rows if r["user_id"] == "user-999"]
        self.assertEqual(len(fan), 1)                       # teammate got a copy
        self.assertEqual(fan[0]["workspace_id"], "ws-x")

    def test_move_meeting_non_owner_forbidden(self):
        # Caller holds a fan-out copy (recorded_by someone else) → cannot move directly.
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": "ws-a", "recorded_by_user_id": "user-999"},
        ]
        resp = self.client.post("/meetings/1/move", json={"workspace_id": ""})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.fake_db.tables["meetings"][0]["workspace_id"], "ws-a")  # unchanged

    def test_move_meeting_not_found(self):
        resp = self.client.post("/meetings/404/move", json={"workspace_id": ""})
        self.assertEqual(resp.status_code, 404)

    def test_delete_personal_meeting_removes_single_row_and_transcript_rag(self):
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": None, "recorded_by_user_id": None,
             "recall_bot_id": None, "date": "2026-07-05"},
        ]
        self.fake_db.tables["knowledge_docs"] = [
            {"id": "d1", "user_id": "user-123", "meeting_id": 1, "source_type": "meeting_transcript"},
            {"id": "d2", "user_id": "user-123", "meeting_id": 1, "source_type": "pdf"},  # manual upload — keep
        ]
        self.fake_db.tables["knowledge_chunks"] = [
            {"id": "c1", "doc_id": "d1"}, {"id": "c2", "doc_id": "d2"},
        ]
        resp = self.client.delete("/meetings/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.fake_db.tables["meetings"]), 0)
        # Auto-indexed transcript doc + its chunks gone; the manually-uploaded pdf stays.
        doc_ids = {d["id"] for d in self.fake_db.tables["knowledge_docs"]}
        self.assertEqual(doc_ids, {"d2"})
        chunk_ids = {c["id"] for c in self.fake_db.tables["knowledge_chunks"]}
        self.assertEqual(chunk_ids, {"c2"})

    def test_delete_workspace_owner_cascades_all_fanout_copies(self):
        # Owner deletes a bot workspace meeting → every copy (all members) is removed,
        # so it can't resurface via the dedup fetch. Copies share recall_bot_id. The bot
        # is tombstoned so startup recovery can't re-create it.
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},
            {"id": 2, "user_id": "user-999", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},  # teammate's fan-out copy
        ]
        self.fake_db.tables["meeting_bots"] = [{"bot_id": "bot-9", "status": "done"}]
        with patch.object(storage_routes, "is_workspace_member", return_value=True):
            resp = self.client.delete("/meetings/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scope"], "all_copies")
        self.assertEqual(len(self.fake_db.tables["meetings"]), 0)  # both copies gone
        self.assertEqual(self.fake_db.tables["meeting_bots"][0]["status"], "deleted")  # tombstoned

    def test_delete_workspace_owner_cascades_even_when_given_a_teammates_copy_id(self):
        # THE not_found bug: the dedup fetch can hand the frontend a teammate's copy id.
        # The owner deleting via that id must still cascade (resolve owner from the row,
        # delete by recall_bot_id) — not match 0 rows.
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-123", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},   # owner's own copy
            {"id": 2, "user_id": "user-999", "workspace_id": "ws-a", "recorded_by_user_id": "user-123",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},   # teammate's copy — id we delete by
        ]
        self.fake_db.tables["meeting_bots"] = [{"bot_id": "bot-9", "status": "done"}]
        with patch.object(storage_routes, "is_workspace_member", return_value=True):
            resp = self.client.delete("/meetings/2")  # owner (user-123) deletes via teammate's id
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scope"], "all_copies")
        self.assertGreaterEqual(resp.json()["deleted"], 2)
        self.assertEqual(len(self.fake_db.tables["meetings"]), 0)  # both gone

    def test_delete_workspace_non_owner_only_removes_own_copy(self):
        self.fake_db.tables["meetings"] = [
            {"id": 5, "user_id": "user-123", "workspace_id": "ws-a", "recorded_by_user_id": "user-999",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},  # my fan-out copy
            {"id": 6, "user_id": "user-999", "workspace_id": "ws-a", "recorded_by_user_id": "user-999",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},  # owner's copy — must survive
        ]
        self.fake_db.tables["meeting_bots"] = [{"bot_id": "bot-9", "status": "done"}]
        with patch.object(storage_routes, "is_workspace_member", return_value=True):
            resp = self.client.delete("/meetings/5")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["scope"], "own_copy")
        remaining = [r["id"] for r in self.fake_db.tables["meetings"]]
        self.assertEqual(remaining, [6])  # only my copy removed; owner's survives
        # A non-owner must NOT tombstone the bot — the owner still has the meeting.
        self.assertEqual(self.fake_db.tables["meeting_bots"][0]["status"], "done")

    def test_delete_workspace_requires_membership(self):
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-999", "workspace_id": "ws-a", "recorded_by_user_id": "user-999",
             "recall_bot_id": "bot-9", "date": "2026-07-05"},
        ]
        with patch.object(storage_routes, "is_workspace_member", return_value=False):
            resp = self.client.delete("/meetings/1")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(self.fake_db.tables["meetings"]), 1)  # untouched

    def test_get_insights_returns_user_scoped_recommended_actions(self):
        self.fake_db.tables["meetings"] = [
            {
                "id": 5,
                "user_id": "user-999",
                "date": "2026-04-03",
                "title": "Other team",
                "score": 80,
                "result": {"summary": "blocked on security review", "action_items": [], "decisions": [], "sentiment": {"overall": "neutral"}, "health_score": {"score": 80}},
            },
            {
                "id": 4,
                "user_id": "user-123",
                "date": "2026-04-04",
                "title": "Weekly sync",
                "score": 78,
                "result": {
                    "summary": "We are still blocked on vendor approval",
                    "action_items": [{"task": "Finalize launch plan", "owner": "Lisa", "due": ""}],
                    "decisions": [{"decision": "Move analytics to Q3", "owner": "Lisa", "importance": 1}],
                    "sentiment": {"overall": "unresolved", "notes": "The blocker is still unresolved"},
                    "health_score": {"score": 78},
                },
            },
            {
                "id": 3,
                "user_id": "user-123",
                "date": "2026-04-02",
                "title": "Roadmap review",
                "score": 71,
                "result": {
                    "summary": "We have a dependency and blocked rollout risk",
                    "action_items": [{"task": "Finalize vendor approval", "owner": "Lisa", "due": "Friday"}],
                    "decisions": [{"decision": "Move analytics to Q3", "owner": "Lisa", "importance": 2}],
                    "sentiment": {"overall": "tense", "notes": "risk remains unresolved"},
                    "health_score": {"score": 71},
                },
            },
        ]

        response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meeting_count"], 2)
        self.assertTrue(payload["recommended_actions"])
        self.assertTrue(payload["recommended_actions"][0]["meeting_ids"])
        self.assertEqual(payload["ownership_drift"][0]["owner"], "Lisa")

    def test_get_insights_handles_small_history(self):
        self.fake_db.tables["meetings"] = [
            {
                "id": 1,
                "user_id": "user-123",
                "date": "2026-04-01",
                "title": "One-off",
                "score": 90,
                "result": {
                    "summary": "All good",
                    "action_items": [{"task": "Ship it", "owner": "Alex", "due": "Tomorrow"}],
                    "decisions": [],
                    "sentiment": {"overall": "positive", "notes": ""},
                    "health_score": {"score": 90},
                },
            }
        ]

        response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meeting_count"], 1)
        self.assertEqual(payload["recommended_actions"], [])

    def test_get_insights_ignores_placeholder_results(self):
        # RELATIVE dates: avg_score is windowed to the last 30 days, so hardcoded
        # dates silently fall out of the window as time passes and this test starts
        # asserting the window instead of the placeholder filtering it is named for.
        recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        older = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        self.fake_db.tables["meetings"] = [
            {
                "id": 2,
                "user_id": "user-123",
                "date": recent,
                "title": "Placeholder",
                "score": 0,
                "result": {
                    "summary": "",
                    "action_items": [],
                    "decisions": [],
                    "health_score": {"score": 0, "verdict": ""},
                    "sentiment": {"notes": ""},
                },
            },
            {
                "id": 1,
                "user_id": "user-123",
                "date": older,
                "title": "Useful",
                "score": 91,
                "result": {
                    "summary": "All good",
                    "action_items": [{"task": "Ship it", "owner": "Alex", "due": "Tomorrow"}],
                    "decisions": [],
                    "sentiment": {"overall": "positive", "notes": ""},
                    "health_score": {"score": 91},
                },
            },
        ]

        response = self.client.get("/insights")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meeting_count"], 1)
        self.assertEqual(payload["avg_score"], 91)

    def test_share_link_is_public(self):
        self.fake_db.tables["meetings"] = [
            {"id": 1, "user_id": "user-999", "date": "2026-04-01", "title": "Shared", "score": 91, "transcript": "", "result": {"summary": "Visible"}, "share_token": "abc123"}
        ]

        response = self.client.get("/share/abc123")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Shared")
        self.assertEqual(response.json()["result"]["summary"], "Visible")

    def test_save_chat_updates_existing_user_meeting_pair(self):
        self.fake_db.tables["chats"] = [
            {"id": 1, "meeting_id": 7, "user_id": "user-123", "messages": [{"role": "assistant", "content": "old"}]},
            {"id": 2, "meeting_id": 7, "user_id": "user-999", "messages": [{"role": "assistant", "content": "other"}]},
        ]

        response = self.client.post("/chats/7", json={"messages": [{"role": "user", "content": "new"}]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.fake_db.tables["chats"]), 2)
        own_chat = next(row for row in self.fake_db.tables["chats"] if row["user_id"] == "user-123")
        self.assertEqual(own_chat["messages"], [{"role": "user", "content": "new"}])

    def test_get_all_chats_scopes_by_user(self):
        self.fake_db.tables["chats"] = [
            {"id": 1, "meeting_id": 1, "user_id": "user-123", "messages": [{"role": "assistant", "content": "mine"}]},
            {"id": 2, "meeting_id": 2, "user_id": "user-999", "messages": [{"role": "assistant", "content": "other"}]},
        ]

        response = self.client.get("/chats")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"1": [{"role": "assistant", "content": "mine"}]})


if __name__ == "__main__":
    unittest.main()

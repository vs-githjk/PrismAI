import importlib
import sys
import types
import unittest
from pathlib import Path

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

    def upsert(self, payload):
        self.mode = "upsert"
        self.upsert_payload = payload
        return self

    def _matches(self, row):
        for field, value in self.filters:
            if isinstance(value, tuple) and value[0] == "ilike":
                if value[1] not in str(row.get(field, "")).lower():
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
            if self.selected_fields:
                matched = [
                    {field: row.get(field) for field in self.selected_fields}
                    for row in matched
                ]
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
            row_id = payload.get("id")
            for row in rows:
                if row.get("id") == row_id:
                    row.update(payload)
                    return FakeExecuteResult([row.copy()])
            rows.append(payload)
            return FakeExecuteResult([payload.copy()])

        raise AssertionError(f"Unsupported mode: {self.mode}")


class FakeSupabase:
    def __init__(self):
        self.tables = {"meetings": [], "chats": []}

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
        self.assertEqual([row["id"] for row in response.json()], [3, 1])

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

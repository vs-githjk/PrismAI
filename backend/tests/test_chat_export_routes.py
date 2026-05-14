import importlib
import sys
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
fake_supabase_module.create_client = lambda *_args, **_kwargs: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)


class _FakeGroqCompletions:
    async def create(self, *args, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                finish_reason="stop",
                message=types.SimpleNamespace(content="mocked response", tool_calls=None),
            )]
        )


class _FakeAsyncGroq:
    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(completions=_FakeGroqCompletions())


fake_groq_module = types.ModuleType("groq")
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

fake_analysis_service = types.ModuleType("analysis_service")
fake_analysis_service.AGENT_MAP = {}
sys.modules.setdefault("analysis_service", fake_analysis_service)


auth = importlib.import_module("auth")
chat_routes = importlib.import_module("chat_routes")
export_routes = importlib.import_module("export_routes")


class FakeExecuteResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = []
        self.selected_fields = None
        self.order_field = None
        self.order_desc = False
        self.limit_count = None

    def select(self, fields):
        self.selected_fields = [field.strip() for field in fields.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self.order_field = field
        self.order_desc = desc
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def _matches(self, row):
        for field, value in self.filters:
            if row.get(field) != value:
                return False
        return True

    def execute(self):
        rows = [row.copy() for row in self.client.tables[self.table_name] if self._matches(row)]
        if self.order_field:
            rows.sort(key=lambda row: row.get(self.order_field), reverse=self.order_desc)
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        if self.selected_fields:
            rows = [{field: row.get(field) for field in self.selected_fields} for row in rows]
        return FakeExecuteResult(rows)


class FakeSupabase:
    def __init__(self):
        self.tables = {"meetings": []}

    def table(self, table_name):
        return FakeQuery(self, table_name)


class DummyHTTPXResponse:
    def __init__(self, status_code, payload=None, text="", json_error=False):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = text.encode() if text else b"payload"
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self.response


class ChatAndExportRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.original_supabase = chat_routes.supabase
        self.fake_db = FakeSupabase()
        chat_routes.supabase = self.fake_db

        self.app = FastAPI()
        self.app.include_router(chat_routes.create_chat_router(_FakeAsyncGroq()))
        self.app.include_router(export_routes.router)
        self.app.dependency_overrides[auth.require_user_id] = lambda: "user-123"
        self.client = TestClient(self.app)

    def tearDown(self):
        chat_routes.supabase = self.original_supabase
        self.app.dependency_overrides.clear()

    def test_chat_global_without_saved_meetings_returns_empty_state_message(self):
        response = self.client.post("/chat/global", json={"message": "What happened across all meetings?"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("No meetings found in your history yet", response.json()["response"])

    def test_chat_global_uses_only_signed_in_users_meetings(self):
        self.fake_db.tables["meetings"] = [
            {
                "id": 1,
                "user_id": "user-999",
                "title": "Other team",
                "date": "2026-04-02",
                "score": 42,
                "result": {"summary": "Other summary", "action_items": [], "decisions": []},
            },
            {
                "id": 2,
                "user_id": "user-123",
                "title": "My team",
                "date": "2026-04-03",
                "score": 91,
                "result": {"summary": "My summary", "action_items": [], "decisions": []},
            },
        ]

        response = self.client.post("/chat/global", json={"message": "Summarize my meetings"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("response"), "mocked response")

    def test_export_to_notion_rejects_invalid_page_url(self):
        response = self.client.post(
            "/export/notion",
            json={
                "token": "notion-token",
                "parent_page_id": "https://www.notion.so/not-a-valid-page",
                "title": "Meeting Analysis",
                "result": {},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not extract a valid Notion page ID", response.json()["detail"])

    def test_export_to_slack_success(self):
        with patch("export_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyHTTPXResponse(200))):
            response = self.client.post(
                "/export/slack",
                json={
                    "webhook_url": "https://hooks.slack.test/services/demo",
                    "title": "Weekly Sync",
                    "result": {
                        "summary": "All good",
                        "health_score": {"score": 91, "verdict": "Strong"},
                        "action_items": [{"task": "Ship auth", "owner": "Vidyut", "due": "Friday"}],
                        "decisions": [{"decision": "Delay analytics"}],
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_export_to_slack_failure_bubbles_as_502(self):
        with patch("export_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyHTTPXResponse(500, text="boom"))):
            response = self.client.post(
                "/export/slack",
                json={
                    "webhook_url": "https://hooks.slack.test/services/demo",
                    "title": "Weekly Sync",
                    "result": {},
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Slack webhook failed")

    def test_export_to_notion_non_json_error_falls_back_cleanly(self):
        valid_page_url = "https://www.notion.so/workspace/1234567890abcdef1234567890abcdef"
        with patch(
            "export_routes.httpx.AsyncClient",
            return_value=FakeAsyncClient(DummyHTTPXResponse(500, text="server error", json_error=True)),
        ):
            response = self.client.post(
                "/export/notion",
                json={
                    "token": "notion-token",
                    "parent_page_id": valid_page_url,
                    "title": "Meeting Analysis",
                    "result": {},
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Notion API error")


if __name__ == "__main__":
    unittest.main()

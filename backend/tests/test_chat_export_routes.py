import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
fake_analysis_service.TIER2_AGENTS = {}
fake_analysis_service._persona_text_for_agent = lambda *_a, **_k: ""
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
                    "webhook_url": "https://hooks.slack.com/services/T00/B00/demo",
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
                    "webhook_url": "https://hooks.slack.com/services/T00/B00/demo",
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


class ChatGroqResilienceTestCase(unittest.TestCase):
    """Regression: /chat must not 500 when the Groq call raises.

    Lead hypothesis from the prod 500 (diagnose 2026-06-08): an expired Google
    token left Gmail/calendar tools 'available', the model emitted a malformed
    tool call, and Groq rejected it with a 400 tool_use_failed — which
    _tool_calling_loop let propagate to an uncaught 500. realtime_routes already
    recovers from this; /chat did not."""

    def _build(self, groq):
        import chat_routes
        app = FastAPI()
        app.include_router(chat_routes.create_chat_router(groq))
        # raise_server_exceptions=False so an uncaught error surfaces as a 500
        # response we can assert on, instead of re-raising inside the test.
        return TestClient(app, raise_server_exceptions=False)

    def test_chat_with_tools_recovers_when_groq_400s_on_tool_call(self):
        import chat_routes

        calls = {"n": 0}

        class _Flaky:
            async def create(self, *args, **kwargs):
                calls["n"] += 1
                if "tools" in kwargs:
                    err = Exception("Error code: 400 - tool_use_failed: malformed tool call")
                    raise err
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    finish_reason="stop",
                    message=types.SimpleNamespace(content="plain answer", tool_calls=None),
                )])

        groq = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Flaky()))
        client = self._build(groq)

        with patch.object(chat_routes, "require_user_id", new=AsyncMock(return_value="user-123")), \
             patch.object(chat_routes, "_get_user_settings",
                          new=AsyncMock(return_value={"slack_bot_token": "x", "user_id": "user-123"})), \
             patch.object(chat_routes, "resolve_persona",
                          new=AsyncMock(return_value=types.SimpleNamespace(text=""))):
            resp = client.post("/chat", json={"message": "send a slack to the team", "transcript": ""})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["response"], "plain answer")
        self.assertGreaterEqual(calls["n"], 2)  # first (with tools) failed, retry (no tools) succeeded

    def test_chat_no_tools_degrades_gracefully_when_groq_raises(self):
        import chat_routes

        class _Down:
            async def create(self, *args, **kwargs):
                raise Exception("Error code: 503 - service unavailable")

        groq = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Down()))
        client = self._build(groq)

        # Unauthenticated path → no tools → direct create. Must not 500.
        with patch.object(chat_routes, "require_user_id",
                          new=AsyncMock(side_effect=__import__("fastapi").HTTPException(status_code=401))):
            resp = client.post("/chat", json={"message": "hello", "transcript": ""})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("response", resp.json())


class ChatImageTurnTestCase(unittest.TestCase):
    """Image analysis: the user turn switches to OpenAI vision format when images are present."""

    def test_plain_text_turn_without_images(self):
        turn = chat_routes._build_user_turn("hello", [])
        self.assertEqual(turn, {"role": "user", "content": "hello"})

    def test_vision_turn_with_images(self):
        turn = chat_routes._build_user_turn("what is this?", ["https://x/img.png"])
        self.assertEqual(turn["role"], "user")
        self.assertIsInstance(turn["content"], list)
        self.assertEqual(turn["content"][0], {"type": "text", "text": "what is this?"})
        self.assertEqual(turn["content"][1], {"type": "image_url", "image_url": {"url": "https://x/img.png"}})

    def test_images_capped_at_three(self):
        turn = chat_routes._build_user_turn("x", [f"u{i}" for i in range(10)])
        image_parts = [p for p in turn["content"] if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 3)

    def test_empty_message_with_image_gets_default_prompt(self):
        turn = chat_routes._build_user_turn("", ["u1"])
        self.assertEqual(turn["content"][0]["text"], "What's in this image?")

    def test_blank_urls_ignored(self):
        turn = chat_routes._build_user_turn("hi", ["", "  ", None])
        self.assertEqual(turn, {"role": "user", "content": "hi"})


class ResultContextTestCase(unittest.TestCase):
    """Chat grounding: the parsed result is rendered into context so chat can answer
    even when the browser has no raw transcript (bot-recorded meetings viewed live)."""

    def test_empty_result_returns_blank(self):
        self.assertEqual(chat_routes._result_context({}), "")
        self.assertEqual(chat_routes._result_context(None), "")

    def test_renders_summary_actions_decisions(self):
        ctx = chat_routes._result_context({
            "summary": "Roadmap review.",
            "action_items": [{"task": "Ship image analysis", "owner": "Vidyut", "due_date": "Friday"}],
            "decisions": [{"decision": "Prioritize image analysis", "owner": "Vidyut"}],
            "sentiment": {"overall": "collaborative", "notes": "aligned"},
        })
        self.assertIn("Ship image analysis", ctx)
        self.assertIn("owner: Vidyut", ctx)
        self.assertIn("due: Friday", ctx)
        self.assertIn("Prioritize image analysis", ctx)
        self.assertIn("Roadmap review.", ctx)
        self.assertIn("collaborative", ctx)

    def test_tolerates_string_decisions_and_missing_fields(self):
        ctx = chat_routes._result_context({
            "action_items": [{"task": "Do a thing"}],  # no owner/due
            "decisions": ["Went with option B"],        # bare string
        })
        self.assertIn("Do a thing", ctx)
        self.assertIn("Went with option B", ctx)


if __name__ == "__main__":
    unittest.main()

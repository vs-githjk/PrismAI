import importlib
import asyncio
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

fake_analysis_service = types.ModuleType("analysis_service")


async def _fake_run_full_analysis(_transcript: str):
    return {"summary": "ok", "agents_run": []}


fake_analysis_service.run_full_analysis = _fake_run_full_analysis
sys.modules.setdefault("analysis_service", fake_analysis_service)

recall_routes = importlib.import_module("recall_routes")


class DummyResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        return self.response


class RecallRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(recall_routes.router)
        self.client = TestClient(self.app)
        self.original_api_key = recall_routes.RECALL_API_KEY
        recall_routes.RECALL_API_KEY = "test-key"
        recall_routes.bot_store.clear()

    def tearDown(self):
        recall_routes.RECALL_API_KEY = self.original_api_key
        recall_routes.bot_store.clear()

    def test_recall_webhook_sets_recording_state(self):
        payload = {"bot_id": "bot-1", "event": "in_call_recording"}

        response = self.client.post("/recall-webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(recall_routes.bot_store["bot-1"]["status"], "recording")

    def test_recall_webhook_marks_fatal_error(self):
        payload = {"bot_id": "bot-2", "event": "fatal_error"}

        response = self.client.post("/recall-webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(recall_routes.bot_store["bot-2"]["status"], "error")
        self.assertEqual(recall_routes.bot_store["bot-2"]["error"], "Bot encountered a fatal error")

    def test_bot_status_404_is_preserved(self):
        with patch("recall_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyResponse(404))):
            response = self.client.get("/bot-status/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Bot not found")

    def test_bot_status_returns_live_recording_state(self):
        payload = {"status_changes": [{"code": "in_call_recording"}]}
        with patch("recall_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyResponse(200, payload))):
            response = self.client.get("/bot-status/bot-live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recording")

    def test_call_ended_webhook_starts_processing(self):
        request = types.SimpleNamespace(
            json=AsyncMock(return_value={"bot_id": "bot-3", "event": "call_ended"})
        )
        original_process = recall_routes._process_bot_transcript

        async def fake_process(bot_id):
            recall_routes.bot_store[bot_id]["result"] = {"summary": "done"}
            recall_routes.bot_store[bot_id]["status"] = "done"

        recall_routes._process_bot_transcript = fake_process
        try:
            response = asyncio.run(recall_routes.recall_webhook(request))
        finally:
            recall_routes._process_bot_transcript = original_process

        self.assertEqual(response, {"ok": True})
        self.assertEqual(recall_routes.bot_store["bot-3"]["status"], "done")
        self.assertEqual(recall_routes.bot_store["bot-3"]["result"], {"summary": "done"})


if __name__ == "__main__":
    unittest.main()

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


async def _fake_run_full_analysis(_transcript: str, **_kwargs):
    return {"summary": "ok", "agents_run": []}


fake_analysis_service.run_full_analysis = _fake_run_full_analysis
fake_analysis_service.build_analysis_transcript = lambda transcript, speakers=None, owner_name=None: transcript
sys.modules["analysis_service"] = fake_analysis_service

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
        # recall_webhook now reads request.body() (bytes) and parses JSON itself,
        # so it can verify the HMAC signature on the raw bytes when configured.
        payload_bytes = b'{"bot_id": "bot-3", "event": "call_ended"}'
        request = types.SimpleNamespace(
            body=AsyncMock(return_value=payload_bytes),
            headers={},
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


class LeaveReasonTestCase(unittest.TestCase):
    """The bot's disconnect reason is captured from Recall's status sub_code."""

    def test_extract_detail_from_status_node(self):
        payload = {"data": {"status": {"code": "call_ended", "sub_code": "bot_removed", "message": "m"}}}
        self.assertEqual(recall_routes._extract_status_detail(payload),
                         ("call_ended", "bot_removed", "m"))

    def test_extract_detail_from_data_node(self):
        payload = {"data": {"data": {"code": "call_ended", "sub_code": "recording_permission_denied"}}}
        code, sub, _ = recall_routes._extract_status_detail(payload)
        self.assertEqual((code, sub), ("call_ended", "recording_permission_denied"))

    def test_extract_detail_absent(self):
        self.assertEqual(recall_routes._extract_status_detail({"data": {}}), ("", "", ""))

    def test_reason_text_known_subcode(self):
        self.assertIn("removed Prism",
                      recall_routes._leave_reason_text("call_ended", "bot_removed", ""))

    def test_reason_text_falls_back_to_message_then_code(self):
        self.assertEqual(recall_routes._leave_reason_text("call_ended", "weird_code", "Custom msg"),
                         "Custom msg")
        self.assertIn("weird_code",
                      recall_routes._leave_reason_text("call_ended", "weird_code", ""))
        self.assertTrue(recall_routes._leave_reason_text("call_ended", "", ""))  # never empty

    def test_webhook_records_leave_reason(self):
        recall_routes.bot_store["bot-leave"] = {"status": "recording", "result": None, "error": None, "commands": []}
        payload_bytes = b'{"bot_id": "bot-leave", "event": "call_ended", "data": {"status": {"code": "call_ended", "sub_code": "bot_removed"}}}'
        request = types.SimpleNamespace(body=AsyncMock(return_value=payload_bytes), headers={})
        with patch.object(recall_routes, "_db_save"), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "_process_bot_transcript", new=AsyncMock()):
            asyncio.run(recall_routes.recall_webhook(request))
        self.assertIn("removed Prism", recall_routes.bot_store["bot-leave"]["leave_reason"])


class KeytermGroundingTestCase(unittest.TestCase):
    """Lever A — Deepgram nova-3 keyterm prompting from KB/workspace/meeting names."""

    def test_payload_omits_keyterm_when_empty(self):
        body = recall_routes._recall_bot_create_json(
            "https://meet/x", "rt", "wh", keyterms=[])
        dg = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
        self.assertNotIn("keyterm", dg)
        self.assertEqual(dg["model"], "nova-3")

    def test_payload_includes_and_clamps_keyterms(self):
        terms = [f"Term{i}" for i in range(60)]
        body = recall_routes._recall_bot_create_json(
            "https://meet/x", "rt", "wh", keyterms=terms)
        dg = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
        self.assertIn("keyterm", dg)
        self.assertEqual(len(dg["keyterm"]), 50)  # clamped to Deepgram's budget

    def test_name_from_email(self):
        self.assertEqual(recall_routes._name_from_email("jane.doe@acme.com"), "Jane Doe")
        self.assertEqual(recall_routes._name_from_email("vidyut0712@gmail.com"), "Vidyut")
        self.assertEqual(recall_routes._name_from_email("ravi_kumar@x.io"), "Ravi Kumar")

    def test_gather_keyterms_dedups_filters_and_caps(self):
        class _Resp:
            def __init__(self, data): self.data = data

        class _Query:
            def __init__(self, data): self._data = data
            def select(self, *_): return self
            def eq(self, *_): return self
            def in_(self, *_): return self
            def is_(self, *_): return self
            def gte(self, *_): return self
            def order(self, *_, **__): return self
            def limit(self, *_): return self
            def execute(self): return _Resp(self._data)

        class _SB:
            def table(self, name):
                if name == "workspace_members":
                    return _Query([{"user_email": "jane.doe@acme.com"},
                                   {"user_email": "jane.doe@acme.com"}])  # dup
                if name == "knowledge_docs":
                    return _Query([{"name": "Acme Roadmap.pdf"}, {"name": "document"}])
                if name == "meetings":
                    return _Query([{"result": {
                        "sentiment": {"speakers": [{"name": "Kanishq"}]},
                        "action_items": [{"owner": "Unassigned"}, {"owner": "Devajsinh"}],
                    }}])
                return _Query([])

        with patch.object(recall_routes, "supabase", _SB()), \
             patch("caches.get_user_workspace_ids", return_value=["ws1"]):
            terms = recall_routes._gather_keyterms("user-1", "ws1")

        # Jane Doe (deduped to one), Acme Roadmap (ext stripped), Kanishq, Devajsinh.
        self.assertIn("Jane Doe", terms)
        self.assertIn("Acme Roadmap", terms)
        self.assertIn("Kanishq", terms)
        self.assertIn("Devajsinh", terms)
        # Stopwords / "Unassigned" dropped; no duplicates.
        self.assertNotIn("document", terms)
        self.assertNotIn("Unassigned", terms)
        self.assertEqual(len(terms), len(set(t.lower() for t in terms)))

    def test_gather_keyterms_returns_empty_without_supabase(self):
        with patch.object(recall_routes, "supabase", None):
            self.assertEqual(recall_routes._gather_keyterms("u", "w"), [])


if __name__ == "__main__":
    unittest.main()

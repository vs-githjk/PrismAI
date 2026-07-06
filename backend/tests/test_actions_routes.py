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
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

actions_routes = importlib.import_module("actions_routes")
from auth import require_user_id


class ActionsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(actions_routes.router)
        self.app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(self.app)

    def test_rejects_non_allowlisted_tool(self):
        resp = self.client.post("/actions/execute", json={
            "tool": "web_search", "args": {"q": "x"}})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not executable", resp.json()["detail"])

    def test_rejects_unknown_tool(self):
        resp = self.client.post("/actions/execute", json={
            "tool": "definitely_not_a_tool", "args": {}})
        self.assertEqual(resp.status_code, 400)

    def test_executes_allowlisted_tool_and_returns_result(self):
        async def fake_settings(_uid):
            return {"jira_api_token": "t"}

        with patch.object(actions_routes, "_get_user_settings", new=fake_settings), \
             patch.object(actions_routes, "confirm_and_execute",
                          new=AsyncMock(return_value={"success": True, "url": "http://x/ISSUE-1",
                                                      "external_ref": {"tool": "jira_create_issue", "external_id": "ISSUE-1"}})), \
             patch.object(actions_routes, "supabase", None):
            resp = self.client.post("/actions/execute", json={
                "tool": "jira_create_issue",
                "args": {"summary": "Bug", "description": "desc"},
                "task": "file a bug",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_tool_error_becomes_400(self):
        async def fake_settings(_uid):
            return {}

        with patch.object(actions_routes, "_get_user_settings", new=fake_settings), \
             patch.object(actions_routes, "confirm_and_execute",
                          new=AsyncMock(return_value={"error": "Jira not connected"})):
            resp = self.client.post("/actions/execute", json={
                "tool": "jira_create_issue", "args": {"summary": "x"}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Jira not connected")


if __name__ == "__main__":
    unittest.main()

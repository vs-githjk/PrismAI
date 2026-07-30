"""MCP server protocol + auth-gate tests. No DB — resolve_mcp_user and one tool
handler are monkeypatched so we exercise the JSON-RPC layer in isolation."""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    mcp = importlib.import_module("mcp_server")
    # Auth: only "Bearer good" resolves to a user.
    monkeypatch.setattr(mcp, "resolve_mcp_user",
                        lambda req: "user-123" if req.headers.get("authorization") == "Bearer good" else None)

    async def fake_handler(uid, args):
        return {"open_action_items": [{"task": "ship", "owner": uid}], "count": 1}
    monkeypatch.setitem(mcp._TOOLS["list_open_action_items"], "handler", fake_handler)

    app = FastAPI()
    app.include_router(mcp.router)
    return TestClient(app)


def _call(client, payload, headers=None):
    r = client.post("/mcp", json=payload, headers=headers or {})
    return r


def test_initialize_echoes_protocol_version(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18"}})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["protocolVersion"] == "2025-06-18"
    assert body["result"]["serverInfo"]["name"] == "PrismAI"
    assert "tools" in body["result"]["capabilities"]


def test_tools_list_is_unauthenticated_and_readonly(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "list_open_action_items", "search_meetings", "get_meeting", "list_recent_meetings",
        "draft_coding_task", "get_meeting_documents",
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_tools_call_without_token_is_401(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "list_open_action_items", "arguments": {}}})
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_tools_call_with_token_returns_result(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "list_open_action_items", "arguments": {}}},
              headers={"authorization": "Bearer good"})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    assert "ship" in result["content"][0]["text"]


def test_unknown_tool_is_error(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "nope", "arguments": {}}},
              headers={"authorization": "Bearer good"})
    assert r.json()["error"]["code"] == -32602


def test_initialized_notification_returns_202_no_body(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202


def test_ping(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 6, "method": "ping"})
    assert r.json()["result"] == {}


def test_unknown_method_is_method_not_found(client):
    r = _call(client, {"jsonrpc": "2.0", "id": 7, "method": "foo/bar"})
    assert r.json()["error"]["code"] == -32601


# ── draft_coding_task handler (the v1.1 hero) ──
class _OneRowSupabase:
    """Minimal fake: meetings.select(...).eq('id',x).limit(1).execute() -> [row]."""
    def __init__(self, row):
        self._row = row

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": [self._row] if self._row else []})


def test_draft_coding_task_happy_path(monkeypatch):
    import asyncio
    import mcp_server as mcp
    monkeypatch.setattr(mcp, "supabase", _OneRowSupabase({
        "id": 42, "title": "Auth revamp", "workspace_id": None, "user_id": "u1",
        "transcript": "We need OAuth with PKCE and refresh rotation.",
        "result": {"summary": "Auth", "decisions": [], "action_items": []},
    }))
    import agents.utils as au
    async def fake_llm(system, user, **kw):
        assert "coding task" in system.lower()
        return "## Title\nAuth revamp\n## Scope\nAdd OAuth"
    monkeypatch.setattr(au, "llm_call", fake_llm)

    out = asyncio.run(mcp._tool_draft_coding_task("u1", {"meeting_id": "42", "focus": "OAuth"}))
    assert out["meeting_id"] == "42"
    assert out["focus"] == "OAuth"
    assert "Auth revamp" in out["task_brief"]
    assert out["url"].endswith("/dashboard?meeting=42")


def test_draft_coding_task_non_member_denied(monkeypatch):
    import asyncio
    import mcp_server as mcp
    monkeypatch.setattr(mcp, "supabase", _OneRowSupabase({
        "id": 7, "title": "X", "workspace_id": "ws-other", "user_id": "someone-else",
        "transcript": "…", "result": {},
    }))
    monkeypatch.setattr(mcp, "is_workspace_member", lambda *a, **k: False)
    with __import__("pytest").raises(mcp._ToolError):
        asyncio.run(mcp._tool_draft_coding_task("u1", {"meeting_id": "7"}))

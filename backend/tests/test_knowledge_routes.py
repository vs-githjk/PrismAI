import importlib
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase
fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)


class KnowledgeRoutesTests(unittest.TestCase):
    def _app(self):
        auth = importlib.import_module("auth")
        kr = importlib.import_module("knowledge_routes")
        importlib.reload(kr)
        app = FastAPI()
        app.include_router(kr.router)
        # Override require_user_id
        app.dependency_overrides[auth.require_user_id] = lambda: str(uuid.uuid4())
        return app, kr

    def test_upload_url_creates_doc_and_schedules_ingest(self):
        app, kr = self._app()
        client = TestClient(app)

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "doc-1"}]
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {}

        async def fake_ingest(*args, **kwargs):
            pass

        with patch.object(kr, "_supabase", lambda: mock_sb):
            with patch.object(kr, "_user_settings", new=AsyncMock(return_value={})):
                with patch.object(kr, "ingest_doc", new=fake_ingest):
                    resp = client.post("/knowledge/upload-url", json={"url": "https://example.com"})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("doc_id", resp.json())

    def test_list_docs_returns_filtered_results(self):
        app, kr = self._app()
        client = TestClient(app)

        # Chain now filters soft-deleted via .is_("deleted_at","null") BEFORE the
        # per-scope filters, so the call sequence on the personal-library path is:
        #   table → select → is_(deleted_at) → eq(user_id) → is_(workspace_id) → order → execute
        # MagicMock auto-chains identical attributes, so we configure one terminal.
        mock_sb = MagicMock()
        (
            mock_sb.table.return_value.select.return_value
            .is_.return_value
            .eq.return_value
            .is_.return_value
            .order.return_value
            .execute.return_value.data
        ) = [{"id": "d1", "name": "test.pdf", "status": "ready"}]
        with patch.object(kr, "_supabase", lambda: mock_sb):
            resp = client.get("/knowledge/docs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["docs"]), 1)

    def test_delete_doc_calls_soft_delete(self):
        app, kr = self._app()
        client = TestClient(app)

        async def fake_soft(doc_id, user_id):
            fake_soft.called = (doc_id, user_id)

        fake_soft.called = None

        with patch.object(kr, "soft_delete_doc", new=fake_soft):
            resp = client.delete("/knowledge/docs/doc-id-abc")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fake_soft.called[0], "doc-id-abc")


    def test_sibling_meeting_ids_unions_bot_copies(self):
        # A pin on the owner's copy must surface on teammates' fan-out copies of the
        # same logical meeting (matched by recall_bot_id). Original id is always included.
        import asyncio as _asyncio
        app, kr = self._app()
        row = types.SimpleNamespace(
            data=[{"recall_bot_id": "bot-1", "workspace_id": "ws", "date": "2026-07-13T02:14"}]
        )
        sib = types.SimpleNamespace(data=[{"id": 10}, {"id": 20}, {"id": 30}])
        mock_sb = MagicMock()
        with patch.object(kr, "_execute", new=AsyncMock(side_effect=[row, sib])):
            out = _asyncio.run(kr._sibling_meeting_ids(mock_sb, 10))
        self.assertEqual(set(out), {10, 20, 30})

    def test_sibling_meeting_ids_falls_back_to_self(self):
        # No matching meeting row → just the original id, never an empty set.
        import asyncio as _asyncio
        app, kr = self._app()
        empty = types.SimpleNamespace(data=[])
        mock_sb = MagicMock()
        with patch.object(kr, "_execute", new=AsyncMock(side_effect=[empty])):
            out = _asyncio.run(kr._sibling_meeting_ids(mock_sb, 42))
        self.assertEqual(out, [42])


if __name__ == "__main__":
    unittest.main()

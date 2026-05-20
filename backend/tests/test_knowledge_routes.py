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

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.execute.return_value.data = [
            {"id": "d1", "name": "test.pdf", "status": "ready"},
        ]
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


if __name__ == "__main__":
    unittest.main()

import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *_a, **_k): return self
    def insert(self, *_a, **_k): return self
    def update(self, *_a, **_k): return self
    def delete(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def single(self): return self
    def execute(self): return MagicMock(data=self._data, count=len(self._data) if isinstance(self._data, list) else 0)


class _FakeSupabase:
    def __init__(self, tables: dict):
        self._tables = tables
        self.rpc_calls = []
    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))
    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeQuery(self._tables.get(f"rpc:{name}", []))


class KnowledgeServiceTests(unittest.TestCase):
    def test_search_knowledge_uses_rpc_with_embedding(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        user_id = uuid.uuid4()
        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": str(uuid.uuid4()), "doc_id": str(uuid.uuid4()),
             "doc_name": "Budget.pdf", "source_type": "pdf",
             "sensitivity": "internal", "content": "Q2 budget is $50k",
             "metadata": {}, "score": 0.91},
        ]})

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what was the budget", str(user_id), meeting_id=None
                ))

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["doc_name"], "Budget.pdf")
        self.assertEqual(fake_sb.rpc_calls[0][0], "knowledge_search")

    def test_search_returns_empty_below_min_score(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": []})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.0] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "unknown", str(uuid.uuid4())
                ))
        self.assertEqual(matches, [])

    def test_conflict_detection_flags_top_two_close_scores(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": "c1", "doc_id": "d1", "doc_name": "Q1.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on enterprise", "metadata": {}, "score": 0.90},
            {"chunk_id": "c2", "doc_id": "d2", "doc_name": "Q2.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on SMB", "metadata": {}, "score": 0.88},
        ]})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what's the strategy", str(uuid.uuid4())
                ))
        self.assertTrue(matches[0].get("possible_conflict"))


if __name__ == "__main__":
    unittest.main()

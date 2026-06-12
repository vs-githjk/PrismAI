import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)


class KnowledgeLookupToolTests(unittest.TestCase):
    def test_returns_matches_with_strict_instruction(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(query, user_id, meeting_id=None, k=5, min_score=0.75, **_kwargs):
            # **_kwargs accepts rerank/rewrite_query/conversation_history kwargs
            # added in smart-RAG Phase 4/5. Test doesn't care what the tool
            # passes; only that the search result shape returns to the caller.
            return [{
                "doc_name": "Budget.pdf", "content": "Q2 budget is $50,000",
                "score": 0.92, "metadata": {"page": 3}, "doc_id": "d1",
                "sensitivity": "internal", "source_type": "pdf",
            }]

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "what's the budget", "user_id": "u1"},
                    user_settings={},
                ))

        self.assertIn("matches", result)
        self.assertEqual(len(result["matches"]), 1)
        self.assertIn("Answer ONLY", result["instruction"])
        self.assertIn("doc_name", result["instruction"])

    def test_returns_no_match_when_empty(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(*a, **k): return []

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "unknown", "user_id": "u1"},
                    user_settings={},
                ))

        self.assertTrue(result.get("no_match"))
        self.assertIn("web_search", result.get("next_step", ""))

    def test_fast_mode_disables_rerank_and_rewrite(self):
        # The live-meeting voice path sets fast_mode — rerank (70B, up to 4s)
        # and query rewrite (up to 3s) are dashboard-chat luxuries, not
        # something a spoken reply can wait for.
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        captured = {}

        async def fake_search(query, user_id, **kwargs):
            captured.update(kwargs)
            return []

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                asyncio.run(kl.knowledge_lookup(
                    {"query": "q", "user_id": "u1"},
                    user_settings={"fast_mode": True},
                ))
        self.assertFalse(captured["rerank"])
        self.assertFalse(captured["rewrite_query"])

    def test_default_path_keeps_rerank_and_rewrite(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        captured = {}

        async def fake_search(query, user_id, **kwargs):
            captured.update(kwargs)
            return []

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                asyncio.run(kl.knowledge_lookup(
                    {"query": "q", "user_id": "u1"},
                    user_settings={},
                ))
        self.assertTrue(captured["rerank"])
        self.assertTrue(captured["rewrite_query"])

    def test_no_match_next_step_guards_private_questions(self):
        # The old next_step unconditionally commanded "Call web_search" — for
        # private/internal questions (agendas, plans, docs) that guarantees a
        # pointless Tavily round + 4-7s of latency before an inevitable miss.
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(*a, **k): return []

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "unknown", "user_id": "u1"},
                    user_settings={},
                ))
        next_step = result.get("next_step", "")
        self.assertIn("web_search", next_step)
        self.assertIn("private", next_step.lower())
        self.assertIn("do NOT call web_search", next_step)

    def test_conflict_instruction_present_when_flagged(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(*a, **k):
            return [
                {"doc_name": "Q1.pdf", "content": "Enterprise", "score": 0.90,
                 "metadata": {}, "doc_id": "d1", "possible_conflict": True,
                 "sensitivity": "internal", "source_type": "pdf"},
                {"doc_name": "Q2.pdf", "content": "SMB", "score": 0.88,
                 "metadata": {}, "doc_id": "d2",
                 "sensitivity": "internal", "source_type": "pdf"},
            ]
        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "strategy", "user_id": "u1"},
                    user_settings={},
                ))
        self.assertIn("conflict", result["instruction"].lower())


if __name__ == "__main__":
    unittest.main()

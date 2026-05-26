# backend/tests/test_context_preprocessor.py
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class ContextPreprocessorTests(unittest.TestCase):
    def test_prepends_context_to_each_chunk(self):
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        chunks = [
            {"content": "Q2 budget allocation is $120k.", "chunk_index": 0, "metadata": {"page": 1}},
            {"content": "Q3 will scale up to $200k.", "chunk_index": 1, "metadata": {"page": 2}},
        ]

        async def fake_llm(system, user, **_):
            return "From 'Budget.pdf', section 'Budget Allocation'."

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=fake_llm)):
            result = asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Budget.pdf", doc_summary="Annual budget overview."
            ))

        # Original content preserved
        self.assertEqual(result[0]["content"], "Q2 budget allocation is $120k.")
        # embedded_content has preamble prepended
        self.assertIn("Budget.pdf", result[0]["embedded_content"])
        self.assertIn("Q2 budget allocation is $120k.", result[0]["embedded_content"])
        # Same for second chunk
        self.assertIn("Q3 will scale up to $200k.", result[1]["embedded_content"])

    def test_falls_back_to_content_when_llm_fails(self):
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        chunks = [{"content": "Q2 budget.", "chunk_index": 0, "metadata": {}}]

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=RuntimeError("llm down"))):
            result = asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Budget.pdf", doc_summary=""
            ))

        # On failure, embedded_content falls back to the original content
        self.assertEqual(result[0]["embedded_content"], "Q2 budget.")


if __name__ == "__main__":
    unittest.main()

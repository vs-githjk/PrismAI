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


    def test_bounds_concurrent_llm_calls(self):
        """Fix #3 — concurrent Groq calls should be capped by a semaphore.
        We verify by counting the maximum number of in-flight _llm_preamble
        calls during a 50-chunk ingest. With the semaphore, max in-flight
        must be <= 8."""
        import importlib
        from knowledge_ingest import context_preprocessor
        importlib.reload(context_preprocessor)

        in_flight = 0
        peak = 0

        async def slow_llm(system, user, **_):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return "From 'Doc.pdf'."

        chunks = [
            {"content": f"chunk {i}", "chunk_index": i, "metadata": {}}
            for i in range(50)
        ]

        with patch.object(context_preprocessor, "_llm_preamble",
                          new=AsyncMock(side_effect=slow_llm)):
            asyncio.run(context_preprocessor.add_context(
                chunks, doc_name="Doc.pdf", doc_summary=""
            ))

        self.assertLessEqual(peak, 8,
            f"Concurrent _llm_preamble calls peaked at {peak}; expected <= 8")


if __name__ == "__main__":
    unittest.main()

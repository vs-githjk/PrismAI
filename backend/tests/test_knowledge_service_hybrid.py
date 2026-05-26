# backend/tests/test_knowledge_service_hybrid.py
"""Phase 3 — RRF merge + hybrid search path."""
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class RRFMergeTests(unittest.TestCase):
    def test_combines_two_rankings(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a", "score": 0.9}, {"id": "b", "score": 0.8}, {"id": "c", "score": 0.7}]
        bm25 = [{"id": "b", "score": 5.0}, {"id": "d", "score": 4.0}, {"id": "a", "score": 3.0}]
        merged = _rrf_merge(vec, bm25, k_rrf=60)

        ids = [r["id"] for r in merged]
        # `b` appears in both lists at rank 2 (vec) and rank 1 (bm25) → highest fused score
        self.assertEqual(ids[0], "b")
        # `a` appears at rank 1 (vec) and rank 3 (bm25) → second highest
        self.assertEqual(ids[1], "a")
        # `c` and `d` each appear once; `c` at rank 3 (vec) vs `d` at rank 2 (bm25)
        # → d outranks c (1/(60+2) > 1/(60+3))
        self.assertEqual(ids[2], "d")
        self.assertEqual(ids[3], "c")

    def test_handles_empty_branch(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a"}, {"id": "b"}]
        merged_v_only = _rrf_merge(vec, [])
        self.assertEqual([r["id"] for r in merged_v_only], ["a", "b"])

        merged_bm_only = _rrf_merge([], vec)
        self.assertEqual([r["id"] for r in merged_bm_only], ["a", "b"])

        merged_both_empty = _rrf_merge([], [])
        self.assertEqual(merged_both_empty, [])

    def test_overwrites_score_with_fused(self):
        from knowledge_service import _rrf_merge

        vec = [{"id": "a", "score": 0.9}]
        bm25 = [{"id": "a", "score": 5.0}]
        merged = _rrf_merge(vec, bm25, k_rrf=60)

        self.assertEqual(merged[0]["match_type"], "hybrid")
        # Fused score = 1/(60+1) + 1/(60+1) ≈ 0.0328
        self.assertAlmostEqual(merged[0]["score"], 2 * (1 / 61), places=6)


if __name__ == "__main__":
    unittest.main()

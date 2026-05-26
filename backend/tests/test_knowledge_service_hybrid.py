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


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class SearchKnowledgeHybridTests(unittest.TestCase):
    def _patched_search(self, vec_rows, bm25_rows, hybrid):
        """Call search_knowledge with both RPCs faked. Returns the merged rows."""
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        # Fake supabase client whose .rpc(name, params).execute() returns the
        # appropriate row list based on RPC name.
        def fake_rpc(name, params):
            class _Q:
                def execute(self_inner):
                    if name == "knowledge_search":
                        return MagicMock(data=list(vec_rows))
                    if name == "knowledge_search_bm25":
                        return MagicMock(data=list(bm25_rows))
                    raise AssertionError(f"Unexpected RPC: {name}")
            return _Q()

        fake_sb = MagicMock()
        fake_sb.rpc = MagicMock(side_effect=fake_rpc)

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.0] * 1536)), \
             patch.object(knowledge_service, "get_user_workspace_ids",
                          new=lambda *_a, **_k: []):
            return asyncio.run(knowledge_service.search_knowledge(
                query="quarterly revenue", user_id="user-1",
                k=5, hybrid=hybrid,
            ))

    def test_hybrid_calls_both_rpcs_and_merges(self):
        vec = [
            {"id": "a", "doc_id": "d1", "score": 0.91, "source_type": "pdf"},
            {"id": "b", "doc_id": "d2", "score": 0.85, "source_type": "pdf"},
        ]
        bm25 = [
            {"id": "b", "doc_id": "d2", "score": 5.2, "source_type": "pdf"},
            {"id": "c", "doc_id": "d3", "score": 4.1, "source_type": "pdf"},
        ]
        rows = self._patched_search(vec, bm25, hybrid=True)
        ids = [r["id"] for r in rows]
        # `b` is the only doc in both lists → ranks first
        self.assertEqual(ids[0], "b")
        # match_type should be "hybrid"
        self.assertEqual(rows[0]["match_type"], "hybrid")

    def test_hybrid_false_preserves_vector_only_behavior(self):
        vec = [
            {"id": "a", "doc_id": "d1", "score": 0.91, "source_type": "pdf"},
            {"id": "b", "doc_id": "d2", "score": 0.85, "source_type": "pdf"},
        ]
        # If hybrid=False, the bm25 list should never be touched.
        rows = self._patched_search(vec, [], hybrid=False)
        ids = [r["id"] for r in rows]
        self.assertEqual(ids, ["a", "b"])
        # Vector-only path leaves score untouched (raw cosine)
        self.assertEqual(rows[0]["score"], 0.91)

    def test_transcript_cap_applies_in_hybrid_path(self):
        vec = [
            {"id": "t1", "doc_id": "d-t1", "score": 0.95, "source_type": "meeting_transcript"},
            {"id": "t2", "doc_id": "d-t2", "score": 0.94, "source_type": "meeting_transcript"},
            {"id": "t3", "doc_id": "d-t3", "score": 0.93, "source_type": "meeting_transcript"},
            {"id": "p1", "doc_id": "d-p1", "score": 0.92, "source_type": "pdf"},
            {"id": "p2", "doc_id": "d-p2", "score": 0.91, "source_type": "pdf"},
        ]
        rows = self._patched_search(vec, [], hybrid=True)
        transcript_count = sum(1 for r in rows if r.get("source_type") == "meeting_transcript")
        # At most 2 transcripts in the top-k (existing cap behavior)
        self.assertLessEqual(transcript_count, 2)


if __name__ == "__main__":
    unittest.main()

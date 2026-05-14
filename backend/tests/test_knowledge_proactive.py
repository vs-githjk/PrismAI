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


def _state(transcript_lines, **extra):
    s = {
        "transcript_buffer": transcript_lines,
        "processing": False,
    }
    s.update(extra)
    return s


def _patch_bot(kp, user_id="user-1", meeting_id="meet-1"):
    """Stub the _bot_record lookup so user_id/meeting_id come from a fake bot_store."""
    return patch.object(kp, "_bot_record",
                        side_effect=lambda _bid: {"user_id": user_id, "meeting_id": meeting_id})


class KnowledgeProactiveTests(unittest.TestCase):
    def test_skips_when_processing_flag_set(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        called = []
        with patch.object(kp, "search_knowledge", new=AsyncMock(side_effect=lambda *a, **k: called.append(1) or [])):
            asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state(["a"], processing=True)))
        self.assertEqual(called, [])

    def test_skips_when_no_match_above_threshold(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        posted = []
        with _patch_bot(kp):
            with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=[])):
                with patch.object(kp, "_post_chat", new=AsyncMock(side_effect=lambda *a, **k: posted.append(a))):
                    asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state(["line " + str(i) for i in range(15)])))
        self.assertEqual(posted, [])

    def test_posts_when_match_passes_all_gates(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "Strategy.pdf",
            "content": "Focus on enterprise customers in Q2.",
            "score": 0.91, "sensitivity": "public", "metadata": {},
        }]
        with _patch_bot(kp):
            with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
                with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                    asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state([f"l{i}" for i in range(15)])))
        mock_post.assert_awaited_once()

    def test_dedupe_skips_repeat_within_window(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "S.pdf", "content": "X",
            "score": 0.91, "sensitivity": "public", "metadata": {},
        }]
        with _patch_bot(kp):
            with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
                with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                    state = _state([f"l{i}" for i in range(15)])
                    asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", state))
                    asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", state))
        self.assertEqual(mock_post.await_count, 1)

    def test_filters_confidential_docs(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "Secret.pdf", "content": "X",
            "score": 0.95, "sensitivity": "confidential", "meeting_id": None, "metadata": {},
        }]
        with _patch_bot(kp):
            with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
                with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                    asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state([f"l{i}" for i in range(15)])))
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

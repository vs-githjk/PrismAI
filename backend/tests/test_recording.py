import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase/groq so recall_routes imports cleanly in tests
fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

fake_groq_module = types.ModuleType("groq")
class _FakeAsyncGroq:
    def __init__(self, *a, **k): pass
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

from recall_routes import _segments_from_recall_data


class TestSegmentsFromRecallData(unittest.TestCase):
    def test_streaming_provider_shape_with_words(self):
        raw = [
            {
                "speaker": "Alice",
                "words": [
                    {"text": "Hello", "start_time": 0.5, "end_time": 1.0},
                    {"text": "world", "start_time": 1.1, "end_time": 1.6},
                ],
            },
            {
                "speaker": "Bob",
                "words": [
                    {"text": "Hi", "start_time": 2.0, "end_time": 2.3},
                ],
            },
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [
            {"speaker": "Alice", "start": 0.5, "end": 1.6, "text": "Hello world"},
            {"speaker": "Bob", "start": 2.0, "end": 2.3, "text": "Hi"},
        ])

    def test_skips_segments_with_no_words(self):
        raw = [
            {"speaker": "Alice", "words": []},
            {"speaker": "Bob", "words": [{"text": "ok", "start_time": 1.0, "end_time": 1.2}]},
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [{"speaker": "Bob", "start": 1.0, "end": 1.2, "text": "ok"}])

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(_segments_from_recall_data([]))

    def test_returns_none_for_non_list_input(self):
        self.assertIsNone(_segments_from_recall_data({"transcript": "blob"}))
        self.assertIsNone(_segments_from_recall_data("plain string"))
        self.assertIsNone(_segments_from_recall_data(None))

    def test_uses_participant_name_when_speaker_missing(self):
        raw = [{
            "participant": {"name": "Carol"},
            "words": [{"text": "yo", "start_time": 0.1, "end_time": 0.3}],
        }]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Carol", "start": 0.1, "end": 0.3, "text": "yo"},
        ])

    def test_falls_back_to_unknown_speaker_label(self):
        raw = [{"words": [{"text": "hi", "start_time": 0.0, "end_time": 0.2}]}]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Speaker", "start": 0.0, "end": 0.2, "text": "hi"},
        ])


if __name__ == "__main__":
    unittest.main()

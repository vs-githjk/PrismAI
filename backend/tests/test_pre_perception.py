import os
import sys
import time
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")


from perception_state import (
    TTLSet,
    bump,
    ensure_counters,
    get_drops,
    is_partial,
    operational_counters,
    record_drop,
    security_counters,
    synth_event_id,
)


class TTLSetTests(unittest.TestCase):
    def test_returns_seen_on_second_insert(self):
        s = TTLSet(ttl_seconds=60, max_size=100)
        self.assertFalse(s.contains_or_add("a", now=0.0))
        self.assertTrue(s.contains_or_add("a", now=1.0))

    def test_evicts_oldest_when_size_capped(self):
        # Step-by-step trace:
        #   add a@0.0          → [a]
        #   add b@1.0          → [a, b]
        #   add c@2.0 (full)   → evict a → [b, c]
        # So 'a' is gone, 'b' and 'c' still present.
        s = TTLSet(ttl_seconds=600, max_size=2)
        s.contains_or_add("a", now=0.0)
        s.contains_or_add("b", now=1.0)
        s.contains_or_add("c", now=2.0)
        self.assertFalse(s.contains_or_add("a", now=3.0))  # 'a' was evicted
        # Inserting a back at step above (now full again) evicts oldest, 'b'.
        # Final state: [c, a]
        self.assertTrue(s.contains_or_add("c", now=4.0))   # 'c' still there
        self.assertFalse(s.contains_or_add("b", now=5.0))  # 'b' was evicted

    def test_evicts_expired_on_access(self):
        s = TTLSet(ttl_seconds=10, max_size=100)
        s.contains_or_add("a", now=0.0)
        # 11s later, 'a' should be expired and removed on next access.
        self.assertFalse(s.contains_or_add("b", now=11.0))
        self.assertFalse(s.contains_or_add("a", now=12.0))  # treated as new
        self.assertEqual(len(s), 2)  # b and a, not the original a

    def test_refresh_on_repeat_hit_keeps_entry_alive(self):
        # Touching an existing key updates its insert timestamp. Important so
        # an event that keeps retrying within the TTL stays deduped.
        s = TTLSet(ttl_seconds=10, max_size=100)
        s.contains_or_add("a", now=0.0)
        # 8s later: still seen, refreshed.
        self.assertTrue(s.contains_or_add("a", now=8.0))
        # 17s after original insert (9s after refresh): should still be seen.
        self.assertTrue(s.contains_or_add("a", now=17.0))


class SynthEventIdTests(unittest.TestCase):
    def _make_segment(self, words):
        return {"words": words, "participant": {"name": "Alice"}}

    def test_deterministic_for_identical_input(self):
        seg = self._make_segment([
            {"text": "Hi,",
             "start_timestamp": {"absolute": "2026-05-15T12:25:49.742Z"},
             "end_timestamp":   {"absolute": "2026-05-15T12:25:50.061Z"}},
            {"text": "Prism.",
             "start_timestamp": {"absolute": "2026-05-15T12:25:50.061Z"},
             "end_timestamp":   {"absolute": "2026-05-15T12:25:50.462Z"}},
        ])
        a = synth_event_id("bot-1", "transcript.data", seg)
        b = synth_event_id("bot-1", "transcript.data", seg)
        self.assertEqual(a, b)

    def test_different_text_yields_different_id(self):
        # Critical: corrected re-emissions (Prasim → Prism) must NOT collapse,
        # so they pass A.1 dedup and the existing fuzzy text-dedup catches them.
        ts1 = {"absolute": "2026-05-15T12:25:49.742Z"}
        ts2 = {"absolute": "2026-05-15T12:25:50.061Z"}
        seg_a = self._make_segment([{"text": "Prasim.", "start_timestamp": ts1, "end_timestamp": ts2}])
        seg_b = self._make_segment([{"text": "Prism.",  "start_timestamp": ts1, "end_timestamp": ts2}])
        self.assertNotEqual(
            synth_event_id("bot-1", "transcript.data", seg_a),
            synth_event_id("bot-1", "transcript.data", seg_b),
        )

    def test_different_bot_id_yields_different_id(self):
        seg = self._make_segment([
            {"text": "hi",
             "start_timestamp": {"absolute": "x"},
             "end_timestamp":   {"absolute": "y"}},
        ])
        self.assertNotEqual(
            synth_event_id("bot-A", "transcript.data", seg),
            synth_event_id("bot-B", "transcript.data", seg),
        )

    def test_empty_words_does_not_collapse_across_calls(self):
        # No words → use monotonic_ns seed so we never produce a constant id.
        seg = {"words": [], "participant": {"name": "Alice"}}
        a = synth_event_id("bot-1", "transcript.data", seg)
        b = synth_event_id("bot-1", "transcript.data", seg)
        self.assertNotEqual(a, b)


class IsPartialTests(unittest.TestCase):
    def test_segment_is_final_false_is_partial(self):
        self.assertTrue(is_partial({"is_final": False}, None))

    def test_data_field_is_final_false_is_partial(self):
        self.assertTrue(is_partial({}, {"is_final": False}))

    def test_transcript_is_final_false_is_partial(self):
        self.assertTrue(is_partial({}, {"transcript": {"is_final": False}}))

    def test_absent_field_defaults_to_final(self):
        # Today's Recall payload has no is_final; default-to-final is the
        # safe behavior — we don't want to drop real events on a config gap.
        self.assertFalse(is_partial({"words": []}, {"data": {}}))

    def test_is_final_true_is_not_partial(self):
        self.assertFalse(is_partial({"is_final": True}, None))


class CountersAndDropsTests(unittest.TestCase):
    def test_ensure_counters_initializes_defaults(self):
        state = {}
        c = ensure_counters(state)
        for k in ("dedup_hits", "partial_drops", "cancel_count",
                  "replace_depth_hits", "cousin_hit_no_match",
                  "injection_redactions", "owner_gate_blocks"):
            self.assertIn(k, c)
            self.assertEqual(c[k], 0)

    def test_ensure_counters_backfills_missing_keys(self):
        state = {"counters": {"dedup_hits": 5}}
        c = ensure_counters(state)
        self.assertEqual(c["dedup_hits"], 5)
        self.assertEqual(c["partial_drops"], 0)

    def test_bump_increments(self):
        state = {}
        bump(state, "dedup_hits")
        bump(state, "dedup_hits", 3)
        self.assertEqual(state["counters"]["dedup_hits"], 4)

    def test_operational_and_security_split(self):
        state = {}
        bump(state, "dedup_hits", 2)
        bump(state, "injection_redactions", 7)
        op = operational_counters(state)
        sec = security_counters(state)
        self.assertIn("dedup_hits", op)
        self.assertNotIn("injection_redactions", op)
        self.assertIn("injection_redactions", sec)
        self.assertNotIn("dedup_hits", sec)
        self.assertEqual(op["dedup_hits"], 2)
        self.assertEqual(sec["injection_redactions"], 7)

    def test_record_and_get_drops_with_reason_tag(self):
        record_drop("bot-drop-1", "abcd1234efgh", "Alice", "Hi Prism, ...", "dedup")
        record_drop("bot-drop-1", "ffff5678abcd", "Bob",   "Hello world", "partial")
        drops = get_drops("bot-drop-1")
        self.assertEqual(len(drops), 2)
        reasons = [d["reason"] for d in drops]
        self.assertEqual(reasons, ["dedup", "partial"])
        self.assertEqual(drops[0]["hash_prefix"], "abcd1234")  # first 8

    def test_drop_ring_buffer_caps_at_100(self):
        for i in range(150):
            record_drop("bot-cap", f"id{i:04d}aaaa", "S", "t", "dedup")
        drops = get_drops("bot-cap")
        self.assertEqual(len(drops), 100)
        # Oldest 50 should be evicted; newest 100 retained.
        self.assertEqual(drops[0]["hash_prefix"], "id0050aa"[:8])
        self.assertEqual(drops[-1]["hash_prefix"], "id0149aa"[:8])


class ReplayBurstTests(unittest.TestCase):
    """Recall reconnect replay: same event_id arrives many times; A.1 must
    drop all but the first. The shared TTLSet absorbs the burst regardless
    of order with the existing backpressure layer."""

    def test_replay_burst_all_dropped_after_first(self):
        s = TTLSet(ttl_seconds=600, max_size=100)
        seg = {
            "words": [{
                "text": "hello",
                "start_timestamp": {"absolute": "2026-05-15T12:00:00.000Z"},
                "end_timestamp":   {"absolute": "2026-05-15T12:00:01.000Z"},
            }],
            "participant": {"name": "Alice"},
        }
        ev_id = synth_event_id("bot-replay", "transcript.data", seg)
        results = [s.contains_or_add(ev_id, now=float(i)) for i in range(5)]
        # First one is new, rest are dedup hits.
        self.assertEqual(results, [False, True, True, True, True])


if __name__ == "__main__":
    unittest.main()

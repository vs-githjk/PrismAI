"""Unit tests for the shared workspace-membership cache.

What we lock in here:
  - cache hit on second read within TTL
  - per-user isolation
  - explicit invalidation (single + blanket)
  - TTL expiry forces refresh
  - DB failure NOT cached (transient blip must heal next call)
  - defensive copy (caller mutation can't poison cache)
  - is_workspace_member uses the same cached list (zero extra round-trips)
  - PRISM_WORKSPACE_CACHE=0 fully bypasses the cache (pass-through to DB)
  - cache_stats() reports the right counters
"""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase before any import that drags it in
_fake_sb_mod = types.ModuleType("supabase")
_fake_sb_mod.create_client = lambda *_a, **_k: None
_fake_sb_mod.Client = object
sys.modules.setdefault("supabase", _fake_sb_mod)

import caches  # noqa: E402


class _CountingQuery:
    def __init__(self, sb, table_name):
        self._sb = sb
        self._table = table_name

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self

    def execute(self):
        if self._table == "workspace_members":
            self._sb.query_count += 1
        return MagicMock(data=self._sb._rows)


class _CountingSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.query_count = 0

    def table(self, name):
        return _CountingQuery(self, name)


class WorkspaceCacheTests(unittest.TestCase):
    def setUp(self):
        caches._reset_for_tests()
        self.prior_flag = os.environ.get("PRISM_WORKSPACE_CACHE")
        os.environ["PRISM_WORKSPACE_CACHE"] = "1"

    def tearDown(self):
        caches._reset_for_tests()
        if self.prior_flag is None:
            os.environ.pop("PRISM_WORKSPACE_CACHE", None)
        else:
            os.environ["PRISM_WORKSPACE_CACHE"] = self.prior_flag

    # ── get_user_workspace_ids ──────────────────────────────────────────────

    def test_cache_hit_on_second_call(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        a = caches.get_user_workspace_ids(sb, "user-a")
        b = caches.get_user_workspace_ids(sb, "user-a")
        self.assertEqual(a, ["ws-1"])
        self.assertEqual(b, ["ws-1"])
        self.assertEqual(sb.query_count, 1)

    def test_per_user_isolation(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        caches.get_user_workspace_ids(sb, "user-a")
        caches.get_user_workspace_ids(sb, "user-b")
        self.assertEqual(sb.query_count, 2)

    def test_explicit_invalidation_forces_refresh(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        caches.get_user_workspace_ids(sb, "user-a")
        caches.invalidate_user_workspaces("user-a")
        caches.get_user_workspace_ids(sb, "user-a")
        self.assertEqual(sb.query_count, 2)

    def test_invalidate_all_clears_every_entry(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        caches.get_user_workspace_ids(sb, "user-a")
        caches.get_user_workspace_ids(sb, "user-b")
        caches.invalidate_user_workspaces(None)
        caches.get_user_workspace_ids(sb, "user-a")
        caches.get_user_workspace_ids(sb, "user-b")
        self.assertEqual(sb.query_count, 4)

    def test_db_failure_not_cached(self):
        class FailingSupabase:
            def __init__(self): self.query_count = 0
            def table(self, _n):
                self.query_count += 1
                raise RuntimeError("DB down")

        sb = FailingSupabase()
        self.assertEqual(caches.get_user_workspace_ids(sb, "u"), [])
        self.assertEqual(caches.get_user_workspace_ids(sb, "u"), [])
        self.assertEqual(sb.query_count, 2, "transient failures must NOT be cached")

    def test_defensive_copy(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        first = caches.get_user_workspace_ids(sb, "u")
        first.append("tampered")
        second = caches.get_user_workspace_ids(sb, "u")
        self.assertEqual(second, ["ws-1"])

    def test_ttl_expiry_forces_refresh(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        with patch("caches.time.monotonic",
                   side_effect=[0.0, caches._WORKSPACE_CACHE_TTL_S + 1.0]):
            caches.get_user_workspace_ids(sb, "u")
            caches.get_user_workspace_ids(sb, "u")
        self.assertEqual(sb.query_count, 2)

    def test_invalidate_unknown_user_is_noop(self):
        caches.invalidate_user_workspaces("never-cached")  # must not raise

    # ── is_workspace_member ─────────────────────────────────────────────────

    def test_is_workspace_member_uses_cached_list(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}, {"workspace_id": "ws-2"}])
        self.assertTrue(caches.is_workspace_member(sb, "u", "ws-2"))
        self.assertTrue(caches.is_workspace_member(sb, "u", "ws-1"))
        self.assertFalse(caches.is_workspace_member(sb, "u", "ws-99"))
        self.assertEqual(sb.query_count, 1, "three checks → one DB read")

    def test_is_workspace_member_with_empty_inputs(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        self.assertFalse(caches.is_workspace_member(sb, "", "ws-1"))
        self.assertFalse(caches.is_workspace_member(sb, "u", ""))
        self.assertEqual(sb.query_count, 0, "empty inputs must not touch DB")

    # ── Flag-off bypass ─────────────────────────────────────────────────────

    def test_flag_off_bypasses_cache_entirely(self):
        os.environ["PRISM_WORKSPACE_CACHE"] = "0"
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        caches.get_user_workspace_ids(sb, "u")
        caches.get_user_workspace_ids(sb, "u")
        caches.get_user_workspace_ids(sb, "u")
        self.assertEqual(sb.query_count, 3, "flag off → no caching")
        self.assertEqual(caches.cache_stats()["hits"], 0)
        self.assertEqual(caches.cache_stats()["misses"], 0)

    def test_flag_off_failure_still_returns_empty(self):
        os.environ["PRISM_WORKSPACE_CACHE"] = "0"

        class FailingSupabase:
            def table(self, _n): raise RuntimeError("DB down")

        self.assertEqual(caches.get_user_workspace_ids(FailingSupabase(), "u"), [])

    # ── cache_stats ─────────────────────────────────────────────────────────

    def test_cache_stats_counters_track_hits_misses_failures(self):
        sb = _CountingSupabase([{"workspace_id": "ws-1"}])
        caches.get_user_workspace_ids(sb, "u-a")  # miss
        caches.get_user_workspace_ids(sb, "u-a")  # hit
        caches.get_user_workspace_ids(sb, "u-b")  # miss

        class FailingSupabase:
            def table(self, _n): raise RuntimeError("boom")

        caches.get_user_workspace_ids(FailingSupabase(), "u-c")  # miss + failure

        stats = caches.cache_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 3)
        self.assertEqual(stats["failures"], 1)
        self.assertEqual(stats["size"], 2)  # u-a and u-b cached; u-c failed
        self.assertTrue(stats["enabled"])

    def test_cache_stats_reports_flag_state(self):
        os.environ["PRISM_WORKSPACE_CACHE"] = "0"
        self.assertFalse(caches.cache_stats()["enabled"])


if __name__ == "__main__":
    unittest.main()

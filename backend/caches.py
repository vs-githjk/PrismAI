"""Shared in-process caches for hot membership/settings lookups.

The single value cached here is "all workspaces user X belongs to". That same
query lives at four call sites today:
  - knowledge_service.search_knowledge  (knowledge_lookup tool every chat)
  - knowledge_routes.list_docs          (every /knowledge/docs?meeting_id=...)
  - recall_routes._find_shared_workspace_bot  (every /join-meeting)
  - storage_routes membership checks    (every /meetings, /insights, /meetings/{id})

By centralising the cache + lookup, all four collapse to one DB round-trip
per user per TTL window. Membership checks reduce to `ws in cached_list`
(no DB).

Design choices documented inline. Flag-gated for emergency rollback.
"""

import os
import time
from typing import Optional


# ── Configuration ───────────────────────────────────────────────────────────

def _cache_on() -> bool:
    """Read at call time so a test or operator can flip the flag mid-run
    without a module reload."""
    return os.getenv("PRISM_WORKSPACE_CACHE", "1") == "1"


_WORKSPACE_CACHE_TTL_S = int(os.getenv("PRISM_WORKSPACE_CACHE_TTL_S", "300"))


# ── State ───────────────────────────────────────────────────────────────────

# user_id -> (workspace_ids, expires_at_monotonic)
_workspace_ids_cache: dict[str, tuple[list[str], float]] = {}

# Lightweight counters surfaced via /health for operator visibility.
# Reset on process restart — that's fine, we want a rolling signal.
_stats = {"hits": 0, "misses": 0, "failures": 0}


# ── Public API ──────────────────────────────────────────────────────────────

def get_user_workspace_ids(sb, user_id: str) -> list[str]:
    """All workspace IDs the user belongs to.

    On cache hit: returns a defensive copy of the cached list — caller may
    mutate freely. On miss: queries Supabase, caches the result with TTL,
    returns the list. On query FAILURE: returns [] and DOES NOT cache — a
    transient blip mustn't lock the user out of workspace data for the full
    TTL window.

    Pass-through path (flag off): the cache layer is bypassed entirely; every
    call queries Supabase. This lets operators flip the flag for instant
    rollback without redeploy.
    """
    if not _cache_on():
        ids = _fetch(sb, user_id)
        if ids is None:
            return []
        return ids

    now = time.monotonic()
    cached = _workspace_ids_cache.get(user_id)
    if cached is not None:
        ids, expires_at = cached
        if now < expires_at:
            _stats["hits"] += 1
            return list(ids)

    _stats["misses"] += 1
    fresh = _fetch(sb, user_id)
    if fresh is None:
        _stats["failures"] += 1
        return []
    _workspace_ids_cache[user_id] = (fresh, now + _WORKSPACE_CACHE_TTL_S)
    return list(fresh)


def is_workspace_member(sb, user_id: str, workspace_id: str) -> bool:
    """Membership check derived from the cached list. Replaces the 1-row
    `select user_id WHERE workspace_id=? AND user_id=?` pattern with zero
    additional round-trips once the user's list is warm.

    Empty / missing IDs return False (callers should still raise 403).
    """
    if not user_id or not workspace_id:
        return False
    return workspace_id in get_user_workspace_ids(sb, user_id)


def invalidate_user_workspaces(user_id: Optional[str] = None) -> None:
    """Drop cached entries after a membership mutation.
    Pass None to clear everything (used for workspace deletion, which can
    affect every member — a rare op, so a blanket clear is acceptable).
    Safe to call when nothing is cached.
    """
    if user_id is None:
        _workspace_ids_cache.clear()
    else:
        _workspace_ids_cache.pop(user_id, None)


def cache_stats() -> dict:
    """Snapshot for /health. Reset on process restart."""
    return {
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "failures": _stats["failures"],
        "size": len(_workspace_ids_cache),
        "enabled": _cache_on(),
        "ttl_s": _WORKSPACE_CACHE_TTL_S,
    }


# ── Internals ───────────────────────────────────────────────────────────────

def _fetch(sb, user_id: str) -> Optional[list[str]]:
    """Returns the list on success, None on failure. None is the signal to
    NOT cache (transient errors should heal on next call, not stick around
    for the TTL window)."""
    try:
        res = (
            sb.table("workspace_members")
            .select("workspace_id")
            .eq("user_id", user_id)
            .execute()
        )
        return [r["workspace_id"] for r in (res.data or []) if r.get("workspace_id")]
    except Exception:
        return None


# Test-only helper — keeps tests from poking at private state.
def _reset_for_tests() -> None:
    _workspace_ids_cache.clear()
    _stats["hits"] = 0
    _stats["misses"] = 0
    _stats["failures"] = 0

# backend/personas.py
"""Persona resolution + in-process cache.

Mirrors caches.py: flag-gated, env-tunable TTL, transient failures don't
poison the cache, stats surface for /health.

Public API:
    PRESETS:           dict of preset name → instruction string
    ResolvedPersona:   frozen dataclass returned by resolve_persona
    resolve_persona:   async — user override → workspace default → "default"
    invalidate_persona: drop cached entries after PATCH
    cache_stats:       snapshot for /health
    _reset_for_tests:  used by test fixtures
"""

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

# ── Presets ─────────────────────────────────────────────────────────────────

PRESETS: dict[str, str] = {
    "default":  "",
    "concise":  (
        "Be terse. Cut filler, hedges, and throat-clearing. Prefer short "
        "sentences and bulleted lists over paragraphs. Skip preambles like "
        "\"Sure!\" or \"Great question\"."
    ),
    "formal":   (
        "Use an executive register: measured, precise, and polished. No "
        "contractions, no slang, no emoji. Default to declarative statements; "
        "qualify only where uncertainty is real."
    ),
    "cheeky":   (
        "Have a dry wit. Add light sarcasm or playful jabs where they fit "
        "naturally — never at the user's expense. Humor decorates the answer; "
        "it never replaces substance."
    ),
    "socratic": (
        "Surface the user's assumptions by asking pointed questions. Where a "
        "direct answer exists, give it; where the request is ambiguous, name "
        "the ambiguity and pose one or two clarifying questions."
    ),
}

CUSTOM_PROMPT_MAX_CHARS = 500


# ── Configuration ───────────────────────────────────────────────────────────

def _cache_on() -> bool:
    """Read at call time so a test can flip the flag without reloading."""
    return os.getenv("PRISM_PERSONA_CACHE", "1") == "1"


# Import-time read (mirrors caches.py). Overriding this in tests requires
# importlib.reload(personas), not just patch.dict(os.environ, ...).
_CACHE_TTL_S: int = int(os.getenv("PRISM_PERSONA_CACHE_TTL_S", "300"))


# ── State ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedPersona:
    preset: str   # 'default' | 'concise' | 'formal' | 'cheeky' | 'socratic' | 'custom'
    text:   str   # raw instruction (no safety wrapper); empty for 'default'


# (user_id, workspace_id_or_None) -> (ResolvedPersona, expires_at_monotonic)
_cache: dict[tuple[str, Optional[str]], tuple[ResolvedPersona, float]] = {}
_stats = {"hits": 0, "misses": 0, "failures": 0}


# ── Public API ──────────────────────────────────────────────────────────────

async def resolve_persona(sb, user_id: str, workspace_id: Optional[str]) -> ResolvedPersona:
    """Effective persona for this user in this workspace context.

    Precedence: user override (preset or custom) → workspace default → 'default'.
    Returns the raw text; the caller (or llm_call via contextvar) wraps it in
    the safety preamble.
    """
    if not _cache_on():
        return await _fetch(sb, user_id, workspace_id) or ResolvedPersona("default", "")

    now = time.monotonic()
    key = (user_id, workspace_id)
    cached = _cache.get(key)
    if cached is not None and now < cached[1]:
        _stats["hits"] += 1
        return cached[0]

    _stats["misses"] += 1
    fresh = await _fetch(sb, user_id, workspace_id)
    if fresh is None:
        _stats["failures"] += 1
        return ResolvedPersona("default", "")  # safe fallback, NOT cached
    _cache[key] = (fresh, now + _CACHE_TTL_S)
    return fresh


def invalidate_persona(user_id: Optional[str] = None, workspace_id: Optional[str] = None) -> None:
    """Drop cached entries after settings mutation.

    - PATCH user_settings      → invalidate_persona(user_id=...)
    - PATCH workspaces         → invalidate_persona(workspace_id=...)
    - clear all                → invalidate_persona()
    """
    if user_id is None and workspace_id is None:
        _cache.clear()
        return
    drop = [
        k for k in _cache
        if (user_id is not None and k[0] == user_id)
        or (workspace_id is not None and k[1] == workspace_id)
    ]
    for k in drop:
        del _cache[k]


def cache_stats() -> dict:
    """Snapshot for /health. Reset on process restart."""
    return {
        **_stats,
        "size": len(_cache),
        "enabled": _cache_on(),
        "ttl_s": _CACHE_TTL_S,
    }


# ── Internals ───────────────────────────────────────────────────────────────

async def _execute(query):
    """Mirror knowledge_service._execute — dispatch sync Supabase call to a
    worker thread so the FastAPI loop stays responsive."""
    return await asyncio.to_thread(query.execute)


async def _fetch(sb, user_id: str, workspace_id: Optional[str]) -> Optional[ResolvedPersona]:
    """Returns the resolved persona on success, None on failure."""
    try:
        user_res = await _execute(
            sb.table("user_settings")
            .select("persona_preset, persona_custom_prompt")
            .eq("user_id", user_id)
            .maybe_single()
        )
        u = (user_res.data or {}) if user_res else {}
        preset = u.get("persona_preset") or "default"
        custom = (u.get("persona_custom_prompt") or "")[:CUSTOM_PROMPT_MAX_CHARS]

        if preset == "custom" and custom:
            return ResolvedPersona("custom", custom)
        if preset != "default" and preset in PRESETS:
            return ResolvedPersona(preset, PRESETS[preset])

        if workspace_id:
            ws_res = await _execute(
                sb.table("workspaces")
                .select("default_persona")
                .eq("id", workspace_id)
                .maybe_single()
            )
            ws = (ws_res.data or {}) if ws_res else {}
            ws_preset = ws.get("default_persona") or "default"
            if ws_preset != "default" and ws_preset in PRESETS:
                return ResolvedPersona(ws_preset, PRESETS[ws_preset])

        return ResolvedPersona("default", "")
    except Exception as exc:
        # Broad except mirrors caches.py — a transient DB blip mustn't lock
        # the user into "default" forever. But unlike caches.py we make two
        # DB calls here, doubling the failure surface — log so misconfigured
        # column names or chains don't disappear silently in prod.
        print(f"[personas] _fetch failed for user={user_id} ws={workspace_id}: {exc!r}")
        return None


def _reset_for_tests() -> None:
    _cache.clear()
    _stats["hits"] = 0
    _stats["misses"] = 0
    _stats["failures"] = 0

"""Proactive knowledge surfacing. Called from _compress_and_persist (one hook)."""

import hashlib
import time
from typing import Optional

from embeddings import QuotaExhausted
from knowledge_service import search_knowledge

PROACTIVE_MIN_SCORE = 0.85
DEDUPE_WINDOW_SECONDS = 60
DOC_COOLDOWN_SECONDS = 600  # 10 minutes
LAST_N_LINES = 10

_dedupe_cache: dict[str, tuple[str, float]] = {}  # bot_id -> (window_hash, ts)
_doc_cooldown: dict[tuple[str, str], float] = {}  # (bot_id, doc_id) -> last_surfaced_at
_quota_warning_logged_at: float = 0.0  # rate-limit the "quota exhausted" message


def _window_hash(lines: list[str]) -> str:
    joined = "\n".join(lines[-LAST_N_LINES:])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _allowed_by_sensitivity(match: dict, meeting_id: Optional[str]) -> bool:
    sens = match.get("sensitivity", "internal")
    if sens == "public":
        return True
    if sens == "confidential":
        return False
    # internal: only when pinned to this meeting
    return match.get("meeting_id") == meeting_id and meeting_id is not None


async def _post_chat(bot_id: str, message: str) -> None:
    # Lazy import to avoid pulling realtime_routes at module load time
    try:
        from realtime_routes import _send_chat_response
        await _send_chat_response(bot_id, message)
    except Exception as exc:
        print(f"[proactive-knowledge] failed to post for {bot_id}: {exc}")


def _bot_record(bot_id: str) -> dict:
    # Lazy import — bot_store lives in realtime_routes
    try:
        from realtime_routes import bot_store
        return bot_store.get(bot_id) or {}
    except Exception:
        return {}


def cleanup_bot(bot_id: str) -> None:
    """Called by realtime_routes when a bot is removed — drop its caches."""
    _dedupe_cache.pop(bot_id, None)
    for k in list(_doc_cooldown.keys()):
        if k[0] == bot_id:
            _doc_cooldown.pop(k, None)


async def maybe_proactive_knowledge_check(bot_id: str, state: dict) -> None:
    """Top-level entry. Runs all gates, posts to meeting chat if a match passes."""
    if state.get("processing"):
        return

    lines = state.get("transcript_buffer") or []
    if len(lines) < LAST_N_LINES:
        return

    record = _bot_record(bot_id)
    user_id = record.get("user_id")
    meeting_id = record.get("meeting_id")
    if not user_id:
        return

    now = time.time()

    # Dedupe gate
    wh = _window_hash(lines)
    prev = _dedupe_cache.get(bot_id)
    if prev and prev[0] == wh and (now - prev[1]) < DEDUPE_WINDOW_SECONDS:
        return
    _dedupe_cache[bot_id] = (wh, now)

    query_text = "\n".join(lines[-LAST_N_LINES:])
    try:
        matches = await search_knowledge(query_text, user_id, meeting_id=meeting_id,
                                         k=3, min_score=PROACTIVE_MIN_SCORE)
    except QuotaExhausted:
        # Embeddings quota is out; the breaker logs once at trip time. Rate-limit our own log to hourly.
        global _quota_warning_logged_at
        if (now - _quota_warning_logged_at) > 3600:
            print(f"[proactive-knowledge] disabled while OpenAI quota is exhausted")
            _quota_warning_logged_at = now
        return
    except Exception as exc:
        print(f"[proactive-knowledge] search failed for {bot_id}: {exc}")
        return

    for m in matches:
        doc_id = m.get("doc_id")
        if not doc_id:
            continue

        if not _allowed_by_sensitivity(m, meeting_id):
            continue

        last = _doc_cooldown.get((bot_id, doc_id), 0.0)
        if (now - last) < DOC_COOLDOWN_SECONDS:
            continue

        _doc_cooldown[(bot_id, doc_id)] = now

        snippet = (m.get("content") or "").strip().replace("\n", " ")
        if len(snippet) > 200:
            snippet = snippet[:200].rsplit(" ", 1)[0] + "..."
        message = f"From {m.get('doc_name')}: {snippet}\n(Say \"Prism, more\" for details.)"
        await _post_chat(bot_id, message)
        return  # one proactive surfacing per check window

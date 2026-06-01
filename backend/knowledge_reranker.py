# backend/knowledge_reranker.py
"""Smart-RAG Phase 4 — LLM-based reranker over top-N candidates.

Why Groq (not local BGE / Cohere): we already have Groq + Llama 3.3 70B in the
stack. A single Groq call adds ~300-500ms — fits the on-demand latency budget
(~800ms total) — and avoids (a) loading a 500MB+ cross-encoder into memory on
Render (RAM pressure on the free tier) and (b) introducing yet another vendor
key. The downside is slightly more variable latency and not-quite-cross-encoder
quality. Tradeoff approved in the smart-RAG follow-up plan.

Always reachable via PRISM_RERANKER_ENABLED=0 for an emergency rollback.

NOT used on the proactive surfacing path — proactive must stay ~150ms and runs
every 20 transcript lines. Only the on-demand `knowledge_lookup` tool path
calls rerank.
"""

import asyncio
import json
import os
import re
from typing import Optional

from agents.utils import llm_call


_SYSTEM = (
    "You are a search relevance ranker. Given a user query and a numbered list "
    "of candidate text passages, identify the passages that BEST answer or "
    "support the query. Prefer passages that contain specific facts directly "
    "addressing the query over generic or tangentially-related passages.\n\n"
    "Output ONLY a JSON array of the passage indices, most relevant first. "
    "Do not include passages that are clearly irrelevant. "
    "Example output: [3, 0, 7]"
)

# How much of each candidate to show the ranker. Keeps the prompt under
# ~6k tokens even for 30 candidates and avoids paying for long-tail content
# at rerank time — the original `content` is still returned to the user
# unchanged for citation purposes.
_CANDIDATE_SNIPPET_CHARS = 320

# Max candidates we feed into a single rerank call. If the upstream pipeline
# gives us more than this, we truncate — Llama can handle more but quality
# degrades and latency rises non-linearly past ~30.
_MAX_CANDIDATES = 30

# Hard cap on rerank latency in seconds. Beyond this we fall back to the
# pre-rerank order rather than blocking the user.
_RERANK_TIMEOUT_S = 4.0


def _enabled() -> bool:
    """Read at call time so an operator can flip the flag without redeploy."""
    return os.getenv("PRISM_RERANKER_ENABLED", "1") == "1"


def _build_user_prompt(query: str, candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        # `embedded_content` preserves the contextual preamble which helps
        # the ranker disambiguate "which doc is this from?" — fall back to
        # `content` for pre-Phase-2 chunks.
        text = c.get("embedded_content") or c.get("content") or ""
        snippet = text[:_CANDIDATE_SNIPPET_CHARS].replace("\n", " ").strip()
        lines.append(f"[{i}] {snippet}")
    return (
        f"Query: {query}\n\n"
        f"Candidates:\n" + "\n".join(lines)
    )


def _parse_indices(raw: str, n_candidates: int) -> Optional[list[int]]:
    """Parse the LLM's JSON-array response. Returns None on any parse failure
    so the caller can fall back to pre-rerank order."""
    if not raw:
        return None
    # Find the first JSON array in the response — defends against models that
    # add stray prose despite the "Output ONLY" instruction.
    match = re.search(r"\[[\s\S]*?\]", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    # Coerce to ints, drop out-of-range / duplicates while preserving order.
    seen: set[int] = set()
    result: list[int] = []
    for item in parsed:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= n_candidates or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return result or None


async def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Reorder `candidates` by query relevance using an LLM judge. Returns
    up to `top_k` items, ordered most-relevant first. Falls back to the
    input order on any failure — never raises."""
    if not _enabled() or not candidates:
        return candidates[:top_k]
    # No work needed when there's nothing to actually reorder.
    if len(candidates) <= 1:
        return candidates[:top_k]

    pool = candidates[:_MAX_CANDIDATES]
    user_prompt = _build_user_prompt(query, pool)
    # Tight max_tokens — we're just asking for a JSON array of indices.
    try:
        raw = await asyncio.wait_for(
            llm_call(_SYSTEM, user_prompt, temperature=0.0, max_tokens=80),
            timeout=_RERANK_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        print(f"[reranker] timeout after {_RERANK_TIMEOUT_S}s, falling back to input order")
        return candidates[:top_k]
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[reranker] LLM call failed ({type(exc).__name__}): {exc}; falling back")
        return candidates[:top_k]

    indices = _parse_indices(raw, len(pool))
    if not indices:
        # Parse failure — input order is the safe fallback.
        return candidates[:top_k]

    reranked = [pool[i] for i in indices[:top_k]]
    # Tag rerank state so downstream telemetry / display knows the score is
    # rank-derived, not similarity-derived.
    for new_rank, row in enumerate(reranked):
        row["rerank_position"] = new_rank
        row["match_type"] = "reranked"
    return reranked

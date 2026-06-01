# backend/knowledge_query_rewriter.py
"""Smart-RAG Phase 5 — terse / follow-up query rewriting.

Embeddings are weak signal when the query is one or two words ("Q3?") or
references a prior turn ("and engineering?"). This module rewrites such
queries into standalone search-friendly form ONCE before embedding/BM25.

Cheap heuristic gate avoids spending a Groq call on already-clear queries:
- skip if query >= 5 tokens AND has no obvious pronoun/connective referring
  to prior turn

Flag: PRISM_QUERY_REWRITE_ENABLED=0 disables. Off-path for proactive surfacing.
"""

import asyncio
import os
import re
from typing import Optional

from agents.utils import llm_call


_SYSTEM = (
    "Rewrite the user's terse or context-dependent question into a single "
    "self-contained search query suitable for a document search engine. "
    "Use the conversation history (if any) to resolve references like 'it', "
    "'that', 'and X?'. Output ONLY the rewritten query — no preface, no "
    "punctuation other than what belongs in the question, no quotation marks."
)

# Words/patterns that suggest the query depends on prior context.
# These trigger a rewrite even if the query is otherwise long enough.
_FOLLOWUP_PATTERNS = re.compile(
    r"\b(it|that|this|those|these|they|them|their|its|"
    r"and|also|what about|how about|same|too|either|"
    r"others?|previous|prior|earlier|just now|"
    r"more|further|next|continue|go on)\b",
    re.IGNORECASE,
)

_MIN_TOKENS_TO_SKIP_REWRITE = 5
_RESPONSE_MAX_TOKENS = 60
_REWRITE_TIMEOUT_S = 3.0


def _enabled() -> bool:
    return os.getenv("PRISM_QUERY_REWRITE_ENABLED", "1") == "1"


def _needs_rewrite(query: str) -> bool:
    """Heuristic decision: do we want to spend a Groq call on this query?"""
    if not query or not query.strip():
        return False
    tokens = query.strip().split()
    if len(tokens) < _MIN_TOKENS_TO_SKIP_REWRITE:
        return True
    # Long-enough query with a follow-up signal — rewrite anyway.
    if _FOLLOWUP_PATTERNS.search(query):
        return True
    return False


def _format_history(history: Optional[list[str]]) -> str:
    """history is a list of strings — alternating turns or just prior questions.
    Cap to the last 5 entries to keep the prompt tight."""
    if not history:
        return "(no prior turns)"
    tail = [h for h in history[-5:] if h and isinstance(h, str)]
    return "\n".join(f"- {h.strip()[:200]}" for h in tail) or "(no prior turns)"


async def maybe_rewrite_query(
    query: str,
    conversation_history: Optional[list[str]] = None,
) -> str:
    """Return the query as-is if no rewrite is warranted, otherwise the
    rewritten standalone form. Never raises — falls back to the original
    query on any failure."""
    if not _enabled():
        return query
    if not _needs_rewrite(query):
        return query

    user = (
        f"Conversation history (oldest → newest):\n"
        f"{_format_history(conversation_history)}\n\n"
        f"User question to rewrite: {query.strip()}"
    )
    try:
        rewritten = await asyncio.wait_for(
            llm_call(_SYSTEM, user, temperature=0.0, max_tokens=_RESPONSE_MAX_TOKENS),
            timeout=_REWRITE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        print(f"[query-rewrite] timeout after {_REWRITE_TIMEOUT_S}s; using original query")
        return query
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[query-rewrite] LLM call failed ({type(exc).__name__}): {exc}; using original")
        return query

    rewritten = (rewritten or "").strip().strip('"').strip("'")
    # Sanity: if the LLM returns nothing or echoes the original verbatim,
    # skip overwriting. If it returns something absurdly long, fall back.
    if not rewritten or rewritten.lower() == query.strip().lower():
        return query
    if len(rewritten) > 400:
        return query
    return rewritten

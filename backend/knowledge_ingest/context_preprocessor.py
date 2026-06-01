# backend/knowledge_ingest/context_preprocessor.py
"""Per-chunk context preamble generator. One Groq call per chunk.
Result is prepended to chunk content BEFORE embedding (stored as embedded_content);
the original chunk content stays in `content` for citation display."""

import asyncio
import hashlib
from collections import OrderedDict

from agents.utils import llm_call

PREAMBLE_MODEL_MAX_TOKENS = 80
_PROMPT = (
    "You generate a one-sentence context preamble for a chunk of a longer document. "
    "Given the document name, an optional document summary, and the chunk's section "
    "heading (if any), produce a preamble of the form: "
    "\"From '<doc_name>', section '<heading or \"near top\">'.\" "
    "Output ONLY the preamble sentence — no preface, no quotes around the whole output."
)

# Cap concurrent Groq calls so a big doc doesn't flood the API and get
# rate-limited (every 429 silently degrades to embedding the raw chunk).
# 8 is comfortably under Groq's default RPS for our workload.
_GROQ_SEM = asyncio.Semaphore(8)


# ── Bounded LRU cache so resync of an unchanged chunk doesn't pay the Groq
#    cost, but long-running backends don't accumulate unbounded memory. The
#    previous unbounded dict could grow ~120 bytes per unique chunk forever.
_CACHE_MAX = 5000

class _LRU(OrderedDict[str, str]):
    """Tiny LRU. Access moves to MRU end; insert evicts LRU when over cap."""

    def __init__(self, cap: int):
        super().__init__()
        self._cap = cap

    def get_or_none(self, key: str) -> str | None:
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def put(self, key: str, value: str) -> None:
        if key in self:
            self.move_to_end(key)
            self[key] = value
            return
        self[key] = value
        if len(self) > self._cap:
            # popitem(last=False) → evict the LRU entry.
            self.popitem(last=False)

_cache: _LRU = _LRU(_CACHE_MAX)


def _cache_key(doc_name: str, chunk_text: str, heading: str) -> str:
    h = hashlib.sha1(f"{doc_name}|{heading}|{chunk_text}".encode("utf-8")).hexdigest()
    return h


async def _llm_preamble(doc_name: str, doc_summary: str, heading: str) -> str:
    user = (
        f"Document name: {doc_name}\n"
        f"Document summary: {doc_summary or '(none)'}\n"
        f"Section heading: {heading or '(none — near top)'}"
    )
    # max_tokens enforces our design intent (one short sentence) at the LLM
    # boundary — preamble runs for every chunk, so a runaway response would
    # multiply token spend and dilute the embedding signal.
    return await llm_call(_PROMPT, user, temperature=0.0, max_tokens=PREAMBLE_MODEL_MAX_TOKENS)


# Expected transient failures — log + fall back. Anything else (asyncio
# cancellation, programming errors) should propagate.
_TRANSIENT_PREAMBLE_ERRORS = (
    asyncio.TimeoutError,
    ConnectionError,
    OSError,            # network-level failures from httpx
)


async def _preamble_for_chunk(chunk: dict, doc_name: str, doc_summary: str) -> str:
    heading = (chunk.get("metadata") or {}).get("heading") or ""
    key = _cache_key(doc_name, chunk["content"], heading)
    cached = _cache.get_or_none(key)
    if cached is not None:
        return cached
    try:
        async with _GROQ_SEM:
            preamble = (await _llm_preamble(doc_name, doc_summary, heading=heading)).strip()
    except asyncio.CancelledError:
        # Honor task cancellation — never swallow.
        raise
    except _TRANSIENT_PREAMBLE_ERRORS as exc:
        print(f"[context_preprocessor] transient preamble error: {type(exc).__name__}: {exc}")
        preamble = ""
    except Exception as exc:
        # Anything else (Groq API error wrappers, validation failures, etc.)
        # — log the type so a real bug doesn't hide silently, then fall back.
        print(f"[context_preprocessor] unexpected preamble error: {type(exc).__name__}: {exc}")
        preamble = ""
    if preamble:
        _cache.put(key, preamble)
    return preamble


async def add_context(chunks: list[dict], doc_name: str, doc_summary: str = "") -> list[dict]:
    """Annotate each chunk with `embedded_content` = preamble + content.
    Preserves `content` for citation display. On any per-chunk failure,
    `embedded_content` falls back to `content` so ingest never blocks."""
    if not chunks:
        return chunks

    # Fan out preamble generation in parallel. Concurrent Groq calls are
    # capped at 8 by `_GROQ_SEM` inside `_preamble_for_chunk`, so large docs
    # don't trigger rate-limit 429s regardless of how many chunks they have.
    preambles = await asyncio.gather(*(
        _preamble_for_chunk(c, doc_name, doc_summary) for c in chunks
    ))

    out = []
    for chunk, preamble in zip(chunks, preambles):
        new = dict(chunk)
        if preamble:
            new["embedded_content"] = f"{preamble} {chunk['content']}"
        else:
            new["embedded_content"] = chunk["content"]
        out.append(new)
    return out

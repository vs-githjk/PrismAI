"""OpenAI embeddings client with batching and retry logic."""

import asyncio
import os
import time
from typing import Optional

import httpx
import tiktoken
from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
MAX_TOKENS_PER_INPUT = 8000
BATCH_SIZE = 100

# Circuit breaker for insufficient_quota — quota does not replenish on its own, so
# retrying within the same minute always wastes 7s of backoff. Skip outright until cooldown.
QUOTA_COOLDOWN_SECONDS = 900  # 15 min — long enough to avoid log spam, short enough to recover after billing top-up
_quota_blocked_until: float = 0.0

_client: Optional[AsyncOpenAI] = None
_encoder = None


class QuotaExhausted(Exception):
    """Raised when OpenAI returns insufficient_quota. Distinct from transient 429 rate-limits."""
    pass


def _is_quota_exhausted(exc: Exception) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            if err.get("code") == "insufficient_quota" or err.get("type") == "insufficient_quota":
                return True
    msg = str(exc).lower()
    return "insufficient_quota" in msg or "exceeded your current quota" in msg


# Connection-level failures carry no HTTP status_code (the request never got a
# response), so the status-based retry predicate below skips them. On Render a
# long-idle keep-alive socket gets reaped upstream; the next reuse surfaces as
# httpx.RemoteProtocolError ("Server disconnected without sending a response")
# or, wrapped by the OpenAI SDK, openai.APIConnectionError. These are transient
# — httpx evicts the dead connection so the retry opens a fresh one. Matched by
# class name (incl. the MRO) so we don't hard-depend on a specific httpx/openai
# exception hierarchy, and so it survives the test suite's openai stub.
_TRANSIENT_CONNECTION_ERROR_NAMES = frozenset({
    "APIConnectionError", "APITimeoutError",
    "RemoteProtocolError", "ConnectError", "ConnectTimeout",
    "ReadError", "ReadTimeout", "WriteError", "PoolTimeout",
})


def is_transient_connection_error(exc: BaseException) -> bool:
    """True for connection-level transients worth retrying (no HTTP status)."""
    return bool(
        {base.__name__ for base in type(exc).__mro__}
        & _TRANSIENT_CONNECTION_ERROR_NAMES
    )


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        # keepalive_expiry caps how long an idle pooled connection is reused.
        # Render's upstream silently reaps idle sockets; expiring ours first
        # avoids handing a dead connection to the next request. Retry in
        # _call_with_retry still covers the race within the window. 45s (was
        # 20s) keeps the socket warm across a typical gap between live-meeting
        # KB lookups — a cold reconnect measured up to ~9s on 2026-06-12.
        _client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            http_client=httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=45.0),
            ),
        )
    return _client


def _get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _truncate(text: str) -> str:
    enc = _get_encoder()
    tokens = enc.encode(text)
    if len(tokens) <= MAX_TOKENS_PER_INPUT:
        return text
    return enc.decode(tokens[:MAX_TOKENS_PER_INPUT])


async def _call_with_retry(inputs: list[str], max_retries: int = 3) -> list[list[float]]:
    global _quota_blocked_until

    # Fast-fail if we've already determined the account is out of quota.
    now = time.time()
    if now < _quota_blocked_until:
        raise QuotaExhausted(
            f"OpenAI quota exhausted; cooling down for {int(_quota_blocked_until - now)}s"
        )

    delay = 1.0
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = await _get_client().embeddings.create(
                model=EMBEDDING_MODEL,
                input=inputs,
            )
            return [d.embedding for d in resp.data]
        except Exception as exc:
            last_err = exc
            # insufficient_quota is permanent until billing is fixed — never retry, trip the breaker.
            if _is_quota_exhausted(exc):
                _quota_blocked_until = time.time() + QUOTA_COOLDOWN_SECONDS
                print(f"[embeddings] OpenAI quota exhausted; pausing embedding calls for {QUOTA_COOLDOWN_SECONDS}s")
                raise QuotaExhausted(str(exc)) from exc
            status = getattr(exc, "status_code", None)
            transient = status in (429, 500, 502, 503, 504) or is_transient_connection_error(exc)
            if transient and attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if is_transient_connection_error(exc):
                # Pin the host on the way out (helps tell OpenAI vs Supabase apart
                # when this same exception type shows up in other call sites).
                print(f"[embeddings] connection error after {attempt + 1} attempt(s): "
                      f"{type(exc).__name__}: {exc}")
            raise
    raise last_err  # pragma: no cover


async def embed_text(text: str) -> list[float]:
    """Embed a single string. Truncates to 8000 tokens if longer."""
    truncated = _truncate(text)
    result = await _call_with_retry([truncated])
    return result[0]


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed many strings, batching into groups of 100."""
    if not texts:
        return []
    truncated = [_truncate(t) for t in texts]
    all_vecs: list[list[float]] = []
    for i in range(0, len(truncated), BATCH_SIZE):
        batch = truncated[i : i + BATCH_SIZE]
        all_vecs.extend(await _call_with_retry(batch))
    return all_vecs

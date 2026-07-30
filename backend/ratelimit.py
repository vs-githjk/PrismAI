"""Lightweight in-memory IP rate limiting for the unauthenticated endpoints.

The public demo endpoints (`/analyze`, `/analyze-stream`, `/agent`, `/chat`,
`/join-meeting`) are intentionally auth-free so the pre-login flow works — but
they each spend real money per call (LLM tokens, Recall bot joins). Without a
limit, anyone can hammer them and burn the budget (cost-DoS). This caps them
per client IP.

⚠️ Single-worker only. State is a per-process dict, so the effective cap is
`limit × worker_count`. This is correct as long as Render runs one uvicorn
worker and one instance (see render.yaml — no `--workers`, no autoscaling).
If we ever scale horizontally or add workers, move this to a shared store
(Redis) or the limits will leak.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

# name -> {ip -> [timestamps]}
_buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


def client_ip(request: Request) -> str:
    """Best-effort client IP. Behind Render's proxy the real client is in
    X-Forwarded-For (first hop); fall back to the socket peer, then a shared
    'unknown' bucket so no-IP callers still get rate-limited together."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce(request: Request, name: str, per_minute: int, *, detail: str | None = None) -> None:
    """Sliding-window limit of `per_minute` requests per client IP for the
    logical endpoint `name`. Raises 429 when exceeded."""
    ip = client_ip(request)
    now = time.time()
    log = _buckets[name][ip]
    # drop timestamps older than the 60s window (in place)
    log[:] = [t for t in log if now - t < 60]
    if len(log) >= per_minute:
        raise HTTPException(
            status_code=429,
            detail=detail or "Too many requests — please slow down and try again in a minute.",
        )
    log.append(now)

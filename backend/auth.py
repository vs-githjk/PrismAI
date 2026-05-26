"""Auth dependency for FastAPI routes.

`require_user_id` is the single Bearer-token validator used by every
authenticated endpoint. Two validation paths:

1. LOCAL (HS256 JWT verification with the Supabase JWT secret) — runs first
   when `PRISM_LOCAL_JWT=1` AND `SUPABASE_JWT_SECRET` is set. ~1ms, no I/O.

2. REMOTE (HTTP GET to `${SUPABASE_URL}/auth/v1/user`) — always available
   as the fallback path. ~70ms over the WAN. Honors Supabase's revocation
   state, so signed-out tokens are rejected immediately rather than waiting
   for their `exp` to lapse.

The local path is opt-in (flag off by default). When the flag is on, EVERY
local failure falls back to remote so that JWT secret rotation, env-var
misconfig, or library bugs cannot lock the whole app out.

Security tradeoff (local mode only): tokens whose user has signed out
remain valid until `exp` (Supabase default ~1 hour). Production should
only flip the flag on after weighing this against the ~70ms-per-request
savings on hot dashboard polling paths.
"""

import os
from typing import Optional

import httpx
import jwt
from fastapi import HTTPException, Request
from supabase import Client as SupabaseClient, create_client

import clients

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
supabase: SupabaseClient | None = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def _local_jwt_on() -> bool:
    """Read the flag at call time, NOT at import time, so tests can flip it
    via monkeypatching `os.environ` without re-importing the module."""
    return os.getenv("PRISM_LOCAL_JWT", "0") == "1"


def _validate_jwt_local(token: str) -> Optional[str]:
    """HS256-verify the Supabase access token. Returns `sub` on success,
    None on any failure (caller falls back to remote).

    Hard-pinned algorithm + audience + issuer to defend against:
      - alg=none confusion attacks
      - cross-project token reuse
      - clock-skew false rejects (60s leeway)
    """
    if not SUPABASE_JWT_SECRET or not SUPABASE_URL:
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=f"{SUPABASE_URL}/auth/v1",
            leeway=60,
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None


async def _validate_remote(token: str, request: Request) -> Optional[str]:
    """Round-trip Supabase to validate the token. Returns user_id on success,
    None on a 4xx, raises HTTPException(503) on transport failure.

    Uses the pooled `app.state.http` via `clients.get_http()` so we get
    keep-alive + connection reuse rather than burning a TLS handshake
    on every request.
    """
    try:
        async with clients.get_http(request) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_KEY,
                },
                timeout=10,
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        return None
    try:
        user = resp.json()
    except ValueError:
        return None
    user_id = user.get("id")
    return user_id if isinstance(user_id, str) and user_id else None


async def require_user_id(request: Request) -> str:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Auth is not configured")

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Fast path: local JWT verification. Opt-in via flag; any failure falls
    # through to the remote path so a bad config doesn't lock the app out.
    if _local_jwt_on():
        local_user_id = _validate_jwt_local(token)
        if local_user_id:
            return local_user_id
        # We don't log per-request — that would defeat the speedup if
        # someone left a bad secret in env. Operators should monitor by
        # comparing flag-on traffic to Supabase /auth/v1/user request rate.

    remote_user_id = await _validate_remote(token, request)
    if not remote_user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return remote_user_id

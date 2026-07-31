"""Unauthenticated auth helpers.

POST /auth/provider-hint — given an email, returns the OAuth providers of an
account that CANNOT password-login (it exists but has no email identity),
else an empty list. Non-existent emails and password-capable accounts are
deliberately indistinguishable: the only fact this endpoint reveals is the
hint the login dialog needs ("this account uses Google").
"""

import os
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import clients

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ponytail: in-memory per-IP throttle, fine on one instance; promote to shared
# middleware if more unauthenticated endpoints appear.
_HINT_WINDOW_S = 60
_HINT_MAX_PER_WINDOW = 10
_hint_hits: dict[str, list[float]] = {}


def _rate_ok(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _hint_hits.get(ip, []) if now - t < _HINT_WINDOW_S]
    if len(hits) >= _HINT_MAX_PER_WINDOW:
        _hint_hits[ip] = hits
        return False
    hits.append(now)
    _hint_hits[ip] = hits
    return True


def _hint_from_users(users: list, email: str) -> list[str]:
    """Pick the exact-email user (GoTrue's `filter` is a fuzzy search) and
    return its providers only when it has no email identity."""
    for user in users:
        if (user.get("email") or "").lower() != email:
            continue
        providers = (user.get("app_metadata") or {}).get("providers") or []
        return [] if "email" in providers else providers
    return []


class ProviderHintRequest(BaseModel):
    email: str


@router.post("/auth/provider-hint")
async def provider_hint(body: ProviderHintRequest, request: Request):
    email = body.email.strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="Invalid email")
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"providers": []}
    ip = request.client.host if request.client else "unknown"
    if not _rate_ok(ip):
        raise HTTPException(status_code=429, detail="Too many requests")

    try:
        async with clients.get_http(request) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                params={"filter": email, "per_page": 10},
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                timeout=10,
            )
        users = resp.json().get("users", []) if resp.status_code == 200 else []
    except Exception:
        return {"providers": []}  # best-effort hint — never block the login flow

    return {"providers": _hint_from_users(users, email)}

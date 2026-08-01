"""OAuth 2.1 authorization-server core for the MCP connector (Milestone B).

Claude.ai's custom-connector UI requires OAuth, so we run a minimal AS:
  * Dynamic Client Registration (RFC 7591) — Claude registers itself.
  * Authorization-code flow with PKCE S256 (mandatory).
  * Opaque access + refresh tokens (hashed at rest); refresh rotates on use.

Identity is Supabase (the user signs in with Google/MS on our consent page); we
issue our OWN tokens bound to that user_id. `resolve_oauth_token` is what the MCP
auth seam calls to turn an access token back into a user_id.

Security notes:
  * Only SHA-256 hashes of codes/tokens are stored; plaintext lives only in the
    HTTP response to the client.
  * Auth codes are single-use and short-lived; PKCE binds the code to the client
    that started the flow (no client secret needed for public clients).
  * redirect_uri is validated against the client's registered allowlist on both
    /authorize and /token (prevents open-redirect / code interception).
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from auth import supabase

DEFAULT_SCOPE = "meetings:read"
_AUTH_CODE_TTL = timedelta(minutes=10)
_ACCESS_TTL = timedelta(hours=1)
_REFRESH_TTL = timedelta(days=30)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s: str) -> datetime:
    # Supabase returns ISO strings; normalize to aware UTC.
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ─────────────────────────── PKCE ───────────────────────────

def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """S256: challenge == base64url(sha256(verifier)) without padding."""
    if not code_verifier or not code_challenge:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, code_challenge)


# ─────────────────────────── clients (DCR) ───────────────────────────

def register_client(client_name: str, redirect_uris: list[str], *, public: bool = True) -> dict:
    """Dynamic Client Registration. Public clients (PKCE) get no secret."""
    if not supabase:
        raise RuntimeError("Supabase not configured")
    client_id = "prism_client_" + secrets.token_urlsafe(16)
    secret_plain = None
    secret_hash = None
    if not public:
        secret_plain = secrets.token_urlsafe(32)
        secret_hash = _hash(secret_plain)
    supabase.table("oauth_clients").insert({
        "client_id": client_id,
        "client_secret_hash": secret_hash,
        "client_name": (client_name or "MCP client")[:120],
        "redirect_uris": redirect_uris or [],
    }).execute()
    out = {"client_id": client_id, "redirect_uris": redirect_uris or []}
    if secret_plain:
        out["client_secret"] = secret_plain
    return out


def get_client(client_id: str) -> dict | None:
    if not supabase or not client_id:
        return None
    res = supabase.table("oauth_clients").select("*").eq("client_id", client_id).limit(1).execute()
    return (res.data or [None])[0]


def redirect_uri_allowed(client: dict, redirect_uri: str) -> bool:
    uris = client.get("redirect_uris") or []
    return redirect_uri in uris


# ─────────────────────────── authorization codes ───────────────────────────

def issue_auth_code(client_id: str, user_id: str, redirect_uri: str,
                    code_challenge: str, scope: str = DEFAULT_SCOPE) -> str:
    """Mint a single-use PKCE-bound authorization code. Returns the plaintext code."""
    if not supabase:
        raise RuntimeError("Supabase not configured")
    code = "prism_ac_" + secrets.token_urlsafe(32)
    supabase.table("oauth_auth_codes").insert({
        "code_hash": _hash(code),
        "client_id": client_id,
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "scope": scope or DEFAULT_SCOPE,
        "expires_at": _iso(_now() + _AUTH_CODE_TTL),
    }).execute()
    return code


def exchange_auth_code(code: str, code_verifier: str, redirect_uri: str, client_id: str) -> dict | None:
    """Validate + consume an auth code. Returns {user_id, scope} or None. Enforces
    single-use, expiry, PKCE, and redirect_uri/client match."""
    if not supabase or not code:
        return None
    ch = _hash(code)
    res = supabase.table("oauth_auth_codes").select("*").eq("code_hash", ch).limit(1).execute()
    row = (res.data or [None])[0]
    if not row:
        return None
    # Single-use: mark consumed immediately (best-effort atomic-ish via the used flag).
    if row.get("used"):
        return None
    supabase.table("oauth_auth_codes").update({"used": True}).eq("code_hash", ch).execute()
    if row.get("client_id") != client_id:
        return None
    if row.get("redirect_uri") != redirect_uri:
        return None
    if _parse_iso(row["expires_at"]) < _now():
        return None
    if not verify_pkce(code_verifier, row.get("code_challenge") or ""):
        return None
    return {"user_id": row["user_id"], "scope": row.get("scope") or DEFAULT_SCOPE}


# ─────────────────────────── tokens ───────────────────────────

def _issue_token_pair(client_id: str, user_id: str, scope: str) -> dict:
    access = "prism_at_" + secrets.token_urlsafe(32)
    refresh = "prism_rt_" + secrets.token_urlsafe(32)
    now = _now()
    supabase.table("oauth_tokens").insert({
        "access_token_hash": _hash(access),
        "refresh_token_hash": _hash(refresh),
        "client_id": client_id,
        "user_id": user_id,
        "scope": scope,
        "access_expires_at": _iso(now + _ACCESS_TTL),
        "refresh_expires_at": _iso(now + _REFRESH_TTL),
    }).execute()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": int(_ACCESS_TTL.total_seconds()),
        "scope": scope,
    }


def issue_tokens_for_code(client_id: str, user_id: str, scope: str = DEFAULT_SCOPE) -> dict:
    if not supabase:
        raise RuntimeError("Supabase not configured")
    return _issue_token_pair(client_id, user_id, scope or DEFAULT_SCOPE)


def rotate_refresh_token(refresh_token: str, client_id: str) -> dict | None:
    """OAuth 2.1 refresh rotation: validate the refresh token, REVOKE it, and issue
    a fresh pair. Returns the new token dict or None."""
    if not supabase or not refresh_token:
        return None
    rh = _hash(refresh_token)
    res = supabase.table("oauth_tokens").select("*").eq("refresh_token_hash", rh).limit(1).execute()
    row = (res.data or [None])[0]
    if not row or row.get("revoked_at"):
        return None
    if row.get("client_id") != client_id:
        return None
    if row.get("refresh_expires_at") and _parse_iso(row["refresh_expires_at"]) < _now():
        return None
    # Revoke the old row (rotation) before issuing the new pair.
    supabase.table("oauth_tokens").update({"revoked_at": _iso(_now())}).eq("id", row["id"]).execute()
    return _issue_token_pair(row["client_id"], row["user_id"], row.get("scope") or DEFAULT_SCOPE)


def resolve_oauth_token(access_token: str) -> str | None:
    """Access token → user_id, or None if unknown/expired/revoked. Hot path."""
    if not supabase or not access_token or not access_token.startswith("prism_at_"):
        return None
    try:
        res = (
            supabase.table("oauth_tokens")
            .select("user_id, access_expires_at, revoked_at")
            .eq("access_token_hash", _hash(access_token)).limit(1).execute()
        )
    except Exception as exc:
        print(f"[oauth] resolve failed: {exc}")
        return None
    row = (res.data or [None])[0]
    if not row or row.get("revoked_at"):
        return None
    if _parse_iso(row["access_expires_at"]) < _now():
        return None
    return row.get("user_id")

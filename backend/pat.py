"""Personal Access Tokens — long-lived, user-issued API keys for the MCP connector.

A user generates a token in Settings, pastes it into Claude/ChatGPT once, and the
MCP server (`/mcp`) authenticates every request with it, scoping data to that user.

Security:
  * Only the SHA-256 hash is stored; the plaintext is returned exactly once.
  * Tokens are opaque random strings prefixed `prism_pat_` so they're greppable /
    revocable if one ever leaks into a log.
  * Revocation is a soft delete (`revoked_at`); a revoked token stops resolving.

This module is auth-model-agnostic on purpose: `resolve_mcp_user(request)` is the
single seam the MCP tools call. Today it resolves a PAT; Milestone B (OAuth 2.1)
will extend the SAME function to also accept an OAuth bearer token, so the tool
layer never changes.
"""

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import Request

from auth import supabase

_TABLE = "personal_access_tokens"
TOKEN_PREFIX = "prism_pat_"
# Shown (non-secret) in the UI so a user can recognize a token in a list.
_PREFIX_DISPLAY_LEN = len(TOKEN_PREFIX) + 6


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_plaintext() -> str:
    # 32 urlsafe bytes ≈ 43 chars of entropy — well beyond guessable.
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def create_token(user_id: str, name: str = "API token", workspace_id: str = "") -> dict:
    """Mint a new token for `user_id`. Returns metadata PLUS the one-time plaintext
    under `token`. The caller must surface `token` to the user immediately — it is
    never retrievable again."""
    if not supabase:
        raise RuntimeError("Supabase not configured")
    plaintext = _generate_plaintext()
    row = {
        "user_id": user_id,
        "name": (name or "API token").strip()[:80] or "API token",
        "token_hash": _hash(plaintext),
        "token_prefix": plaintext[:_PREFIX_DISPLAY_LEN],
        "workspace_id": workspace_id or "",
    }
    res = supabase.table(_TABLE).insert(row).execute()
    created = (res.data or [{}])[0]
    return {
        "id": created.get("id"),
        "name": row["name"],
        "prefix": row["token_prefix"],
        "workspace_id": row["workspace_id"],
        "created_at": created.get("created_at"),
        "token": plaintext,  # one-time only
    }


def list_tokens(user_id: str) -> list[dict]:
    """Active (non-revoked) tokens for a user — metadata only, never the hash."""
    if not supabase:
        return []
    res = (
        supabase.table(_TABLE)
        .select("id, name, token_prefix, workspace_id, created_at, last_used_at")
        .eq("user_id", user_id)
        .is_("revoked_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    out = []
    for r in res.data or []:
        out.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "prefix": r.get("token_prefix"),
            "workspace_id": r.get("workspace_id") or "",
            "created_at": r.get("created_at"),
            "last_used_at": r.get("last_used_at"),
        })
    return out


def revoke_token(user_id: str, token_id: str) -> bool:
    """Soft-revoke a token the caller owns. Scoped by user_id so one user can't
    revoke another's token (IDOR guard)."""
    if not supabase:
        return False
    res = (
        supabase.table(_TABLE)
        .update({"revoked_at": _now_iso()})
        .eq("id", token_id)
        .eq("user_id", user_id)
        .is_("revoked_at", "null")
        .execute()
    )
    return bool(res.data)


def resolve_pat(plaintext: str) -> str | None:
    """Look up a token by hash → return its user_id, or None if unknown/revoked.
    Best-effort touches last_used_at. This is the hot path (every MCP call)."""
    if not supabase or not plaintext or not plaintext.startswith(TOKEN_PREFIX):
        return None
    try:
        res = (
            supabase.table(_TABLE)
            .select("id, user_id, revoked_at")
            .eq("token_hash", _hash(plaintext))
            .limit(1)
            .execute()
        )
    except Exception as exc:
        print(f"[pat] resolve failed: {exc}")
        return None
    row = (res.data or [None])[0]
    if not row or row.get("revoked_at"):
        return None
    # Best-effort usage stamp; never block resolution on it.
    try:
        supabase.table(_TABLE).update({"last_used_at": _now_iso()}).eq("id", row["id"]).execute()
    except Exception:
        pass
    return row.get("user_id")


def _bearer_or_apikey(request: Request) -> str | None:
    """Extract the credential from either `Authorization: Bearer <t>` or
    `X-API-Key: <t>` (both are allowlisted header names for MCP static-header auth)."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    xkey = request.headers.get("x-api-key")
    if xkey:
        return xkey.strip()
    return None


def resolve_mcp_user(request: Request) -> str | None:
    """The single auth seam for MCP tools. Returns the caller's user_id or None.

    v1: resolves a PrismAI Personal Access Token.
    Milestone B will extend this to also accept an OAuth 2.1 bearer token —
    without changing any tool that calls it.
    """
    cred = _bearer_or_apikey(request)
    if not cred:
        return None
    return resolve_pat(cred)

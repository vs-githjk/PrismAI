"""OAuth core flow tests with an in-memory fake Supabase. Covers the security-
critical path: DCR → PKCE auth code (single-use) → token exchange → resolve →
refresh rotation (old pair invalidated)."""

import base64
import hashlib
import importlib

import pytest


# ── minimal fake Supabase supporting the chained query API oauth.py uses ──
class _Query:
    def __init__(self, table):
        self.table = table
        self._filters = []
        self._payload = None
        self._op = None
        self._limit = None

    def insert(self, row):
        self._op = "insert"; self._payload = dict(row); return self

    def select(self, *_a, **_k):
        self._op = "select"; return self

    def update(self, patch):
        self._op = "update"; self._payload = dict(patch); return self

    def eq(self, col, val):
        self._filters.append((col, val)); return self

    def limit(self, n):
        self._limit = n; return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        if self._op == "insert":
            row = self._payload
            row.setdefault("id", f"id-{len(self.table.rows)}")
            self.table.rows.append(row)
            return type("R", (), {"data": [row]})
        if self._op == "select":
            hits = [r for r in self.table.rows if self._match(r)]
            if self._limit:
                hits = hits[: self._limit]
            return type("R", (), {"data": hits})
        if self._op == "update":
            hits = [r for r in self.table.rows if self._match(r)]
            for r in hits:
                r.update(self._payload)
            return type("R", (), {"data": hits})
        return type("R", (), {"data": []})


class _Table:
    def __init__(self):
        self.rows = []


class _FakeSupabase:
    def __init__(self):
        self._tables = {}

    def table(self, name):
        self._tables.setdefault(name, _Table())
        return _Query(self._tables[name])


def _pkce():
    verifier = base64.urlsafe_b64encode(b"x" * 40).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


@pytest.fixture()
def oauth(monkeypatch):
    mod = importlib.import_module("oauth")
    monkeypatch.setattr(mod, "supabase", _FakeSupabase())
    return mod


def test_full_authorization_code_flow(oauth):
    reg = oauth.register_client("Claude", ["https://claude.ai/api/mcp/auth_callback"])
    cid = reg["client_id"]
    assert cid.startswith("prism_client_")
    assert "client_secret" not in reg  # public client

    verifier, challenge = _pkce()
    code = oauth.issue_auth_code(cid, "user-9", "https://claude.ai/api/mcp/auth_callback", challenge)

    # Wrong verifier fails.
    assert oauth.exchange_auth_code(code, "bad-verifier", "https://claude.ai/api/mcp/auth_callback", cid) is None
    # (that attempt consumed the code — issue a fresh one for the happy path)
    code2 = oauth.issue_auth_code(cid, "user-9", "https://claude.ai/api/mcp/auth_callback", challenge)
    res = oauth.exchange_auth_code(code2, verifier, "https://claude.ai/api/mcp/auth_callback", cid)
    assert res and res["user_id"] == "user-9"
    # Single-use: second exchange fails.
    assert oauth.exchange_auth_code(code2, verifier, "https://claude.ai/api/mcp/auth_callback", cid) is None


def test_redirect_uri_mismatch_rejected(oauth):
    reg = oauth.register_client("Claude", ["https://claude.ai/api/mcp/auth_callback"])
    _, challenge = _pkce()
    verifier, challenge = _pkce()
    code = oauth.issue_auth_code(reg["client_id"], "u", "https://claude.ai/api/mcp/auth_callback", challenge)
    # Attacker swaps redirect_uri at token time.
    assert oauth.exchange_auth_code(code, verifier, "https://evil.example/cb", reg["client_id"]) is None


def test_token_issue_resolve_and_refresh_rotation(oauth):
    reg = oauth.register_client("Claude", ["https://cb"])
    cid = reg["client_id"]
    tokens = oauth.issue_tokens_for_code(cid, "user-42")
    assert tokens["access_token"].startswith("prism_at_")
    assert tokens["token_type"] == "Bearer"
    # Access token resolves to the user.
    assert oauth.resolve_oauth_token(tokens["access_token"]) == "user-42"
    # An unknown token does not resolve.
    assert oauth.resolve_oauth_token("prism_at_nope") is None

    # Refresh rotation issues a new pair and invalidates the old one.
    new = oauth.rotate_refresh_token(tokens["refresh_token"], cid)
    assert new and new["access_token"] != tokens["access_token"]
    assert oauth.resolve_oauth_token(new["access_token"]) == "user-42"
    # Old access token is now revoked (rotation revoked the whole row).
    assert oauth.resolve_oauth_token(tokens["access_token"]) is None
    # Old refresh token can't be reused.
    assert oauth.rotate_refresh_token(tokens["refresh_token"], cid) is None


def test_refresh_wrong_client_rejected(oauth):
    reg = oauth.register_client("Claude", ["https://cb"])
    tokens = oauth.issue_tokens_for_code(reg["client_id"], "u")
    assert oauth.rotate_refresh_token(tokens["refresh_token"], "prism_client_other") is None

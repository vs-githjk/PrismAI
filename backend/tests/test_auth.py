import asyncio
import importlib
import os
import sys
import time
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt as pyjwt
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_args, **_kwargs: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

auth = importlib.import_module("auth")


# ── Test doubles ─────────────────────────────────────────────────────────────

class DummyResponse:
    def __init__(self, status_code, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class FakeHttpClient:
    """A stand-in for `httpx.AsyncClient` that yields a single canned `get()`
    response. Captures `(url, headers)` so we can assert on them."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def get(self, url, headers=None, **_kwargs):
        self.calls.append((url, headers or {}))
        if self.error:
            raise self.error
        return self.response


def install_fake_http(monkeypatch_target: object, client: FakeHttpClient):
    """Install `client` as the value yielded by `auth.clients.get_http()` for
    the duration of the patch. Returns the patch context-manager so callers
    can use `with install_fake_http(...):`."""

    @asynccontextmanager
    async def fake_get_http(_request=None):
        yield client

    return patch.object(monkeypatch_target, "get_http", fake_get_http)


def make_request(headers=None):
    """A minimal Request stand-in. `auth.require_user_id` only reads
    `.headers` and passes the request through to `clients.get_http()` which
    we mock — so no `app.state` plumbing is required here."""
    return types.SimpleNamespace(headers=headers or {})


def make_jwt(*, secret="test-secret", iss=None, aud="authenticated", sub="user-123",
             exp_offset=300, alg="HS256", url="https://example.supabase.co"):
    """Mint a Supabase-shaped HS256 access token for tests."""
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": iss if iss is not None else f"{url}/auth/v1",
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()) - 1,
    }
    return pyjwt.encode(payload, secret, algorithm=alg)


# ── Existing remote-only behavior (no flag) ──────────────────────────────────

class RemoteValidationTests(unittest.TestCase):
    """Behavior with PRISM_LOCAL_JWT unset/0 — what production runs today."""

    def setUp(self):
        self.original_url = auth.SUPABASE_URL
        self.original_key = auth.SUPABASE_KEY
        self.prior_flag = os.environ.pop("PRISM_LOCAL_JWT", None)
        auth.SUPABASE_URL = "https://example.supabase.co"
        auth.SUPABASE_KEY = "service-role"

    def tearDown(self):
        auth.SUPABASE_URL = self.original_url
        auth.SUPABASE_KEY = self.original_key
        if self.prior_flag is not None:
            os.environ["PRISM_LOCAL_JWT"] = self.prior_flag

    def test_missing_bearer_header_returns_401(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(auth.require_user_id(make_request()))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Authentication required")

    def test_empty_token_returns_401(self):
        req = make_request({"authorization": "Bearer "})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_supabase_outage_returns_503(self):
        req = make_request({"authorization": "Bearer token"})
        fake = FakeHttpClient(error=httpx.ConnectError("boom"))
        with install_fake_http(auth.clients, fake):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "Auth service unavailable")

    def test_invalid_user_payload_returns_401(self):
        req = make_request({"authorization": "Bearer token"})
        fake = FakeHttpClient(response=DummyResponse(200, json_error=True))
        with install_fake_http(auth.clients, fake):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_remote_401_propagates_to_401(self):
        req = make_request({"authorization": "Bearer token"})
        fake = FakeHttpClient(response=DummyResponse(401))
        with install_fake_http(auth.clients, fake):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_remote_happy_path_returns_user_id(self):
        req = make_request({"authorization": "Bearer token"})
        fake = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-42"}))
        with install_fake_http(auth.clients, fake):
            result = asyncio.run(auth.require_user_id(req))
        self.assertEqual(result, "user-42")
        self.assertEqual(len(fake.calls), 1)
        url, headers = fake.calls[0]
        self.assertIn("/auth/v1/user", url)
        self.assertEqual(headers["Authorization"], "Bearer token")
        self.assertEqual(headers["apikey"], "service-role")


# ── Local JWT validation (flag on) ───────────────────────────────────────────

class LocalJwtValidationTests(unittest.TestCase):
    """Behavior with PRISM_LOCAL_JWT=1. Every local failure must transparently
    fall back to the remote path so a bad secret can't lock the app out."""

    SECRET = "test-jwt-secret"

    def setUp(self):
        self.original_url = auth.SUPABASE_URL
        self.original_key = auth.SUPABASE_KEY
        self.original_jwt_secret = auth.SUPABASE_JWT_SECRET
        self.prior_flag = os.environ.get("PRISM_LOCAL_JWT")
        auth.SUPABASE_URL = "https://example.supabase.co"
        auth.SUPABASE_KEY = "service-role"
        auth.SUPABASE_JWT_SECRET = self.SECRET
        os.environ["PRISM_LOCAL_JWT"] = "1"

    def tearDown(self):
        auth.SUPABASE_URL = self.original_url
        auth.SUPABASE_KEY = self.original_key
        auth.SUPABASE_JWT_SECRET = self.original_jwt_secret
        if self.prior_flag is None:
            os.environ.pop("PRISM_LOCAL_JWT", None)
        else:
            os.environ["PRISM_LOCAL_JWT"] = self.prior_flag

    def _run_with_remote(self, token: str, remote: FakeHttpClient):
        req = make_request({"authorization": f"Bearer {token}"})
        with install_fake_http(auth.clients, remote):
            return asyncio.run(auth.require_user_id(req)), remote

    def test_valid_local_jwt_skips_remote_entirely(self):
        token = make_jwt(secret=self.SECRET, sub="local-user-1")
        remote = FakeHttpClient(response=DummyResponse(500))  # would fail if reached
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "local-user-1")
        self.assertEqual(len(remote.calls), 0, "remote must NOT be called on local hit")

    def test_expired_token_falls_back_to_remote(self):
        token = make_jwt(secret=self.SECRET, exp_offset=-3600)  # expired 1h ago
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-42"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "user-42")
        self.assertEqual(len(remote.calls), 1)

    def test_wrong_signature_falls_back_to_remote(self):
        token = make_jwt(secret="WRONG-SECRET")
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-99"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "user-99")
        self.assertEqual(len(remote.calls), 1)

    def test_alg_none_attack_falls_back_to_remote(self):
        # Forge an unsigned JWT with alg=none — PyJWT will reject this when
        # algorithms=["HS256"] is pinned. Falls back to remote, which then
        # also rejects → 401.
        payload = {
            "sub": "attacker",
            "aud": "authenticated",
            "iss": f"{auth.SUPABASE_URL}/auth/v1",
            "exp": int(time.time()) + 3600,
        }
        forged = pyjwt.encode(payload, key="", algorithm="none")
        remote = FakeHttpClient(response=DummyResponse(401))
        req = make_request({"authorization": f"Bearer {forged}"})
        with install_fake_http(auth.clients, remote):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(len(remote.calls), 1, "alg=none must not be accepted locally")

    def test_wrong_audience_falls_back_to_remote(self):
        token = make_jwt(secret=self.SECRET, aud="some-other-project")
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-1"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "user-1")
        self.assertEqual(len(remote.calls), 1)

    def test_wrong_issuer_falls_back_to_remote(self):
        token = make_jwt(secret=self.SECRET, iss="https://different.supabase.co/auth/v1")
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-1"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "user-1")
        self.assertEqual(len(remote.calls), 1)

    def test_missing_jwt_secret_falls_back_to_remote(self):
        # Empty secret → local validation is a no-op, every request reaches remote.
        auth.SUPABASE_JWT_SECRET = ""
        token = make_jwt(secret=self.SECRET)
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "u"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "u")
        self.assertEqual(len(remote.calls), 1)

    def test_local_fail_then_remote_fail_returns_401(self):
        token = make_jwt(secret="WRONG-SECRET")
        remote = FakeHttpClient(response=DummyResponse(401))
        req = make_request({"authorization": f"Bearer {token}"})
        with install_fake_http(auth.clients, remote):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(req))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(len(remote.calls), 1)

    def test_token_missing_sub_falls_back_to_remote(self):
        # A token that decodes cleanly but has no `sub` field can't identify
        # a user — must fall back to remote rather than returning ""/None.
        payload = {
            "aud": "authenticated",
            "iss": f"{auth.SUPABASE_URL}/auth/v1",
            "exp": int(time.time()) + 3600,
        }
        token = pyjwt.encode(payload, self.SECRET, algorithm="HS256")
        remote = FakeHttpClient(response=DummyResponse(200, payload={"id": "user-7"}))
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "user-7")
        self.assertEqual(len(remote.calls), 1)

    def test_clock_skew_within_leeway_accepted(self):
        # Token expired 30s ago — within the 60s leeway, should still verify
        # locally without hitting remote.
        token = make_jwt(secret=self.SECRET, exp_offset=-30, sub="skew-user")
        remote = FakeHttpClient(response=DummyResponse(500))  # would fail if reached
        user_id, remote = self._run_with_remote(token, remote)
        self.assertEqual(user_id, "skew-user")
        self.assertEqual(len(remote.calls), 0)


if __name__ == "__main__":
    unittest.main()

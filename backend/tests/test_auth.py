import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_args, **_kwargs: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

auth = importlib.import_module("auth")


class DummyResponse:
    def __init__(self, status_code, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class FakeAsyncClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.response


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.original_url = auth.SUPABASE_URL
        self.original_key = auth.SUPABASE_KEY
        auth.SUPABASE_URL = "https://example.supabase.co"
        auth.SUPABASE_KEY = "service-role"

    def tearDown(self):
        auth.SUPABASE_URL = self.original_url
        auth.SUPABASE_KEY = self.original_key

    def test_missing_bearer_header_returns_401(self):
        request = types.SimpleNamespace(headers={})

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(auth.require_user_id(request))

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Authentication required")

    def test_supabase_outage_returns_503(self):
        request = types.SimpleNamespace(headers={"authorization": "Bearer token"})
        error = httpx.ConnectError("boom")

        with patch("auth.httpx.AsyncClient", return_value=FakeAsyncClient(error=error)):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(request))

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "Auth service unavailable")

    def test_invalid_user_payload_returns_401(self):
        request = types.SimpleNamespace(headers={"authorization": "Bearer token"})

        with patch("auth.httpx.AsyncClient", return_value=FakeAsyncClient(response=DummyResponse(200, json_error=True))):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(auth.require_user_id(request))

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "Invalid or expired session")


if __name__ == "__main__":
    unittest.main()

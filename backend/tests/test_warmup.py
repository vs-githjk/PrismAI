"""Tests for connection warm-up (diagnosed 2026-06-12: cold OpenAI ~9s,
cold Supabase ~4s, edge-tts ~2.7s — all paid by the first live KB lookup)."""

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)

import warmup  # noqa: E402


class WarmupTests(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_touches_all_three_connections(self):
        called = []

        async def fake_embed():
            called.append("embeddings")

        async def fake_sb():
            called.append("supabase")

        async def fake_tts():
            called.append("tts")

        with mock.patch.object(warmup, "_warm_embeddings", new=fake_embed), \
             mock.patch.object(warmup, "_warm_supabase", new=fake_sb), \
             mock.patch.object(warmup, "_warm_tts", new=fake_tts):
            await warmup.warm_external_connections("test")
        self.assertEqual(sorted(called), ["embeddings", "supabase", "tts"])

    async def test_warmup_swallows_failures(self):
        async def boom():
            raise RuntimeError("connection refused")

        with mock.patch.object(warmup, "_warm_embeddings", new=boom), \
             mock.patch.object(warmup, "_warm_supabase", new=boom), \
             mock.patch.object(warmup, "_warm_tts", new=boom):
            # Must not raise — warm-up is strictly best-effort.
            await warmup.warm_external_connections("test")

    async def test_bot_init_schedules_warmup(self):
        import realtime_routes as rt
        with mock.patch.object(rt, "warm_external_connections",
                               new=mock.AsyncMock()) as warm, \
             mock.patch.object(rt, "_get_settings_for_bot", new=mock.AsyncMock()):
            rt.init_bot_realtime("bot-warm-test")
            await asyncio.sleep(0)  # let the created tasks start
            try:
                warm.assert_awaited()
            finally:
                rt.cleanup_bot_state("bot-warm-test")


if __name__ == "__main__":
    unittest.main()

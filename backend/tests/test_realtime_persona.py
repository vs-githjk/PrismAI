# backend/tests/test_realtime_persona.py
"""_get_settings_for_bot resolves the owner's persona from the row it already
fetches — no second DB query."""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

if "pysbd" not in sys.modules:
    _fake_pysbd = types.ModuleType("pysbd")
    class _FakeSegmenter:
        def __init__(self, *_a, **_k): pass
        def segment(self, text): return [text]
    _fake_pysbd.Segmenter = _FakeSegmenter
    sys.modules["pysbd"] = _fake_pysbd

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")

import personas
import realtime_routes as rr


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, row):
        self._row = row
    def select(self, *_a, **_k):
        return self
    def eq(self, *_a, **_k):
        return self
    def maybe_single(self):
        return self
    def execute(self):
        return _Result(self._row)


def _fake_sb(row):
    sb = types.SimpleNamespace()
    sb.table = lambda _name: _FakeQuery(row)
    return sb


class GetSettingsForBotPersonaTests(unittest.TestCase):
    def setUp(self):
        rr._bot_settings_cache.clear()
        self._orig_sb = rr.supabase
        self._orig_store = dict(rr.bot_store)

    def tearDown(self):
        rr.supabase = self._orig_sb
        rr.bot_store.clear()
        rr.bot_store.update(self._orig_store)
        rr._bot_settings_cache.clear()

    def test_persona_text_resolved_from_row(self):
        # Row has a persona but NO google token → no calendar import path.
        rr.supabase = _fake_sb({"persona_preset": "cheeky", "persona_custom_prompt": None})
        rr.bot_store["botX"] = {"user_id": "u1"}
        settings = asyncio.run(rr._get_settings_for_bot("botX"))
        self.assertEqual(settings["persona_text"], personas.PRESETS["cheeky"])

    def test_persona_text_empty_when_no_user(self):
        rr.supabase = _fake_sb({"persona_preset": "cheeky"})
        rr.bot_store["botY"] = {}  # no user_id → no fetch
        settings = asyncio.run(rr._get_settings_for_bot("botY"))
        self.assertEqual(settings["persona_text"], "")


if __name__ == "__main__":
    unittest.main()

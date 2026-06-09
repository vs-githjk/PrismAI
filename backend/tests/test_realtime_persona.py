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

if "fastapi" not in sys.modules:
    _fake_fastapi = types.ModuleType("fastapi")
    class _FakeRouter:
        def __init__(self, *_a, **_k): pass
        def get(self, *_a, **_k):
            def _decorator(fn): return fn
            return _decorator
        def post(self, *_a, **_k):
            def _decorator(fn): return fn
            return _decorator
        def delete(self, *_a, **_k):
            def _decorator(fn): return fn
            return _decorator
        def put(self, *_a, **_k):
            def _decorator(fn): return fn
            return _decorator
    _fake_fastapi.APIRouter = _FakeRouter
    _fake_fastapi.Request = object
    _fake_fastapi.Depends = lambda *_a, **_k: None
    _fake_fastapi.HTTPException = type("HTTPException", (Exception,), {})
    sys.modules["fastapi"] = _fake_fastapi

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
import recall_routes


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Table-aware chainable fake: returns the canned row for the table name."""
    def __init__(self, responses, table_name):
        self._responses = responses
        self._table = table_name
    def select(self, *_a, **_k):
        return self
    def eq(self, *_a, **_k):
        return self
    def maybe_single(self):
        return self
    def execute(self):
        return _Result(self._responses.get(self._table))


def _fake_sb(user_row=None, ws_row=None):
    responses = {"user_settings": user_row, "workspaces": ws_row}
    sb = types.SimpleNamespace()
    sb.table = lambda name: _FakeQuery(responses, name)
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
        rr.supabase = _fake_sb(user_row={"persona_preset": "cheeky", "persona_custom_prompt": None})
        rr.bot_store["botX"] = {"user_id": "u1"}
        settings = asyncio.run(rr._get_settings_for_bot("botX"))
        self.assertEqual(settings["persona_text"], personas.PRESETS["cheeky"])

    def test_persona_text_empty_when_no_user(self):
        rr.supabase = _fake_sb(user_row={"persona_preset": "cheeky"})
        rr.bot_store["botY"] = {}  # no user_id → no fetch
        settings = asyncio.run(rr._get_settings_for_bot("botY"))
        self.assertEqual(settings["persona_text"], "")

    def test_workspace_default_used_when_personal_default(self):
        # Personal persona is default, but the bot's workspace has a default.
        rr.supabase = _fake_sb(
            user_row={"persona_preset": "default"},
            ws_row={"default_persona": "formal"},
        )
        rr.bot_store["botZ"] = {"user_id": "u1", "workspace_id": "ws1"}
        settings = asyncio.run(rr._get_settings_for_bot("botZ"))
        self.assertEqual(settings["persona_text"], personas.PRESETS["formal"])


class JoinMeetingRequestTests(unittest.TestCase):
    def test_workspace_id_field_accepted(self):
        req = recall_routes.JoinMeetingRequest(meeting_url="https://x", workspace_id="ws1")
        self.assertEqual(req.workspace_id, "ws1")

    def test_workspace_id_defaults_none(self):
        req = recall_routes.JoinMeetingRequest(meeting_url="https://x")
        self.assertIsNone(req.workspace_id)


class BotIdentityWiringTests(unittest.TestCase):
    """_get_settings_for_bot also resolves the bot's display name + registers
    its wake-word alias. Detection / prefix construction honor that name."""

    def setUp(self):
        rr._bot_settings_cache.clear()
        rr._BOT_WAKE_ALIAS.clear()
        rr._WAKE_PATTERN_CACHE.clear()
        self._orig_sb = rr.supabase
        self._orig_store = dict(rr.bot_store)

    def tearDown(self):
        rr.supabase = self._orig_sb
        rr.bot_store.clear()
        rr.bot_store.update(self._orig_store)
        rr._bot_settings_cache.clear()
        rr._BOT_WAKE_ALIAS.clear()
        rr._WAKE_PATTERN_CACHE.clear()

    def test_settings_populates_bot_name_and_wake_alias(self):
        rr.supabase = _fake_sb(user_row={"persona_preset": "concise"})
        rr.bot_store["botA"] = {"user_id": "u1"}
        settings = asyncio.run(rr._get_settings_for_bot("botA"))
        self.assertEqual(settings["bot_name"], "Flash")
        self.assertEqual(rr._BOT_WAKE_ALIAS["botA"], "Flash")

    def test_default_persona_leaves_no_extra_alias(self):
        # Default preset → bot is still "Prism", no extra wake alias registered.
        rr.supabase = _fake_sb(user_row={"persona_preset": "default"})
        rr.bot_store["botB"] = {"user_id": "u1"}
        settings = asyncio.run(rr._get_settings_for_bot("botB"))
        self.assertEqual(settings["bot_name"], "Prism")
        self.assertEqual(rr._BOT_WAKE_ALIAS.get("botB", ""), "")

    def test_workspace_default_name_propagates_to_bot(self):
        rr.supabase = _fake_sb(
            user_row={"persona_preset": "default"},
            ws_row={"default_persona": "cheeky"},
        )
        rr.bot_store["botC"] = {"user_id": "u1", "workspace_id": "ws1"}
        settings = asyncio.run(rr._get_settings_for_bot("botC"))
        self.assertEqual(settings["bot_name"], "Glint")
        self.assertEqual(rr._BOT_WAKE_ALIAS["botC"], "Glint")

    def test_detect_command_honors_persona_alias(self):
        rr._BOT_WAKE_ALIAS["botD"] = "Flash"
        # Persona name wakes the bot.
        self.assertEqual(rr._detect_command("Flash, summarize this meeting.", "botD"),
                         "summarize this meeting.")
        # Base alias still works (Prism is always-on).
        self.assertEqual(rr._detect_command("Prism, summarize this meeting.", "botD"),
                         "summarize this meeting.")
        # Other personas' names do NOT trigger this bot.
        self.assertIsNone(rr._detect_command("Glint, summarize this meeting.", "botD"))
        # Unaddressed chatter passes through.
        self.assertIsNone(rr._detect_command("the flash drive is on the desk", "botD"))

    def test_detect_command_default_bot_only_uses_prism(self):
        # No alias registered (default preset) — only "Prism" wakes.
        self.assertIsNone(rr._detect_command("Flash, what time is it?", "botE"))
        self.assertEqual(rr._detect_command("Prism, what time is it?", "botE"),
                         "what time is it?")

    def test_has_trigger_word_honors_alias(self):
        rr._BOT_WAKE_ALIAS["botF"] = "Echo"
        self.assertTrue(rr._has_trigger_word("hey Echo, are you there", "botF"))
        self.assertTrue(rr._has_trigger_word("hey Prism, are you there", "botF"))
        self.assertFalse(rr._has_trigger_word("hey Flash, are you there", "botF"))

    def test_static_prefix_includes_name_when_persona_renames(self):
        prefix_named = rr._build_static_prefix(has_gmail=False, has_calendar=False,
                                                persona_text="", bot_name="Flash")
        self.assertIn("Your name in this meeting is Flash", prefix_named)

    def test_static_prefix_byte_identical_when_default(self):
        # Default bot name → prefix is byte-identical to the no-name call.
        prefix_default = rr._build_static_prefix(has_gmail=False, has_calendar=False,
                                                  persona_text="", bot_name="Prism")
        prefix_omitted = rr._build_static_prefix(has_gmail=False, has_calendar=False,
                                                  persona_text="")
        self.assertEqual(prefix_default, prefix_omitted)

    def test_cleanup_drops_wake_alias(self):
        rr._BOT_WAKE_ALIAS["botZ"] = "Flash"
        rr.cleanup_bot_state("botZ")
        self.assertNotIn("botZ", rr._BOT_WAKE_ALIAS)


if __name__ == "__main__":
    unittest.main()

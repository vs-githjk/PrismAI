# backend/tests/test_personas.py
"""Persona resolver + cache. Mirrors the caches.py test pattern."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules.setdefault("supabase", fake)


_stub_supabase()


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Chainable fake — returns canned rows from `responses` dict keyed by
    the table name passed at construction time. No mutable state on chain
    calls so chaining can't accidentally cross-contaminate."""
    def __init__(self, responses, table_name):
        self.responses = responses
        self._table = table_name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Result(self.responses.get(self._table))


def _fake_sb(user_row=None, ws_row=None):
    """Build a fake Supabase client whose .table(name).select()...execute()
    returns the canned rows for that table."""
    responses = {"user_settings": user_row, "workspaces": ws_row}
    sb = MagicMock()
    sb.table = lambda name: _FakeQuery(responses, name)
    return sb


class ResolvePersonaTests(unittest.TestCase):
    def setUp(self):
        import personas
        personas._reset_for_tests()
        # Make the async _execute synchronous for tests
        async def _exec(q):
            return q.execute()
        self._exec_patch = patch.object(personas, "_execute", _exec)
        self._exec_patch.start()

    def tearDown(self):
        self._exec_patch.stop()

    def test_user_override_wins_over_workspace_default(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "concise", "persona_custom_prompt": None},
            ws_row={"default_persona": "formal"},
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", "ws1"))
        self.assertEqual(rp.preset, "concise")
        self.assertIn("Be terse", rp.text)

    def test_workspace_default_used_when_user_has_no_override(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "default", "persona_custom_prompt": None},
            ws_row={"default_persona": "formal"},
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", "ws1"))
        self.assertEqual(rp.preset, "formal")
        self.assertIn("executive register", rp.text)

    def test_system_default_when_nothing_set(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "default", "persona_custom_prompt": None},
            ws_row={"default_persona": "default"},
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", "ws1"))
        self.assertEqual(rp.preset, "default")
        self.assertEqual(rp.text, "")

    def test_custom_prompt_returned_verbatim(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "custom",
                       "persona_custom_prompt": "Talk like a pirate."},
            ws_row=None,
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(rp.preset, "custom")
        self.assertEqual(rp.text, "Talk like a pirate.")

    def test_custom_with_empty_prompt_falls_through(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "custom", "persona_custom_prompt": ""},
            ws_row={"default_persona": "concise"},
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", "ws1"))
        self.assertEqual(rp.preset, "concise")

    def test_no_workspace_means_personal_mode(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "default", "persona_custom_prompt": None},
            ws_row=None,
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(rp.preset, "default")

    def test_cache_hit_avoids_db(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "concise", "persona_custom_prompt": None},
            ws_row=None,
        )
        asyncio.run(personas.resolve_persona(sb, "u1", None))
        asyncio.run(personas.resolve_persona(sb, "u1", None))
        stats = personas.cache_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_invalidate_by_user_drops_entries(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "concise", "persona_custom_prompt": None},
            ws_row=None,
        )
        asyncio.run(personas.resolve_persona(sb, "u1", None))
        personas.invalidate_persona(user_id="u1")
        asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(personas.cache_stats()["misses"], 2)

    def test_invalidate_by_workspace_drops_members(self):
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "default", "persona_custom_prompt": None},
            ws_row={"default_persona": "formal"},
        )
        asyncio.run(personas.resolve_persona(sb, "u1", "wsX"))
        asyncio.run(personas.resolve_persona(sb, "u2", "wsX"))
        personas.invalidate_persona(workspace_id="wsX")
        # Both u1 and u2 should now re-miss.
        asyncio.run(personas.resolve_persona(sb, "u1", "wsX"))
        asyncio.run(personas.resolve_persona(sb, "u2", "wsX"))
        self.assertEqual(personas.cache_stats()["misses"], 4)

    def test_cache_off_via_env(self):
        import personas
        with patch.dict("os.environ", {"PRISM_PERSONA_CACHE": "0"}):
            sb = _fake_sb(
                user_row={"persona_preset": "concise", "persona_custom_prompt": None},
                ws_row=None,
            )
            asyncio.run(personas.resolve_persona(sb, "u1", None))
            asyncio.run(personas.resolve_persona(sb, "u1", None))
            self.assertEqual(personas.cache_stats()["hits"], 0)

    def test_transient_failure_returns_default_and_not_cached(self):
        import personas
        sb = MagicMock()
        def boom(_name):
            raise RuntimeError("connection lost")
        sb.table = boom
        rp = asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(rp.preset, "default")
        self.assertEqual(personas.cache_stats()["failures"], 1)
        self.assertEqual(personas.cache_stats()["size"], 0)

    def test_warm_preset_resolves(self):
        """Sanity: 'warm' preset is registered and resolves to non-empty text."""
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "warm", "persona_custom_prompt": None},
            ws_row=None,
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(rp.preset, "warm")
        self.assertIn("warmth", rp.text.lower())

    def test_analytical_preset_resolves(self):
        """Sanity: 'analytical' preset is registered and resolves to non-empty text."""
        import personas
        sb = _fake_sb(
            user_row={"persona_preset": "analytical", "persona_custom_prompt": None},
            ws_row=None,
        )
        rp = asyncio.run(personas.resolve_persona(sb, "u1", None))
        self.assertEqual(rp.preset, "analytical")
        # Distinctive marker — analytical leads with structure & numbers.
        self.assertIn("evidence", rp.text.lower())


class PersonaTextFromSettingsTests(unittest.TestCase):
    """Row-only resolution used by the live bot (no DB call, user-portion only)."""

    def test_empty_row_returns_empty(self):
        import personas
        self.assertEqual(personas.persona_text_from_settings({}), "")

    def test_default_preset_returns_empty(self):
        import personas
        self.assertEqual(
            personas.persona_text_from_settings({"persona_preset": "default"}), ""
        )

    def test_preset_returns_preset_text(self):
        import personas
        out = personas.persona_text_from_settings({"persona_preset": "concise"})
        self.assertEqual(out, personas.PRESETS["concise"])

    def test_custom_returns_verbatim(self):
        import personas
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": "Talk like a pirate."}
        )
        self.assertEqual(out, "Talk like a pirate.")

    def test_custom_whitespace_falls_through_to_empty(self):
        import personas
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": "   "}
        )
        self.assertEqual(out, "")

    def test_custom_capped_at_max_chars(self):
        import personas
        long = "x" * (personas.CUSTOM_PROMPT_MAX_CHARS + 50)
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": long}
        )
        self.assertEqual(len(out), personas.CUSTOM_PROMPT_MAX_CHARS)


class PersonaTextResolvedTests(unittest.TestCase):
    """Full-precedence TEXT resolution reusing a pre-fetched user_settings row
    (personal override → workspace default → ''). Used by the live bot."""

    def setUp(self):
        import personas
        personas._reset_for_tests()
        async def _exec(q):
            return q.execute()
        self._exec_patch = patch.object(personas, "_execute", _exec)
        self._exec_patch.start()

    def tearDown(self):
        self._exec_patch.stop()

    def test_personal_override_wins_without_ws_fetch(self):
        import personas
        # ws_row present but must be ignored when personal override exists.
        sb = _fake_sb(ws_row={"default_persona": "formal"})
        out = asyncio.run(personas.persona_text_resolved(
            sb, {"persona_preset": "concise", "persona_custom_prompt": None}, "ws1"))
        self.assertEqual(out, personas.PRESETS["concise"])

    def test_workspace_default_used_when_personal_is_default(self):
        import personas
        sb = _fake_sb(ws_row={"default_persona": "formal"})
        out = asyncio.run(personas.persona_text_resolved(
            sb, {"persona_preset": "default"}, "ws1"))
        self.assertEqual(out, personas.PRESETS["formal"])

    def test_no_workspace_id_falls_to_empty(self):
        import personas
        sb = _fake_sb()
        out = asyncio.run(personas.persona_text_resolved(
            sb, {"persona_preset": "default"}, None))
        self.assertEqual(out, "")

    def test_workspace_default_of_default_returns_empty(self):
        import personas
        sb = _fake_sb(ws_row={"default_persona": "default"})
        out = asyncio.run(personas.persona_text_resolved(
            sb, {"persona_preset": "default"}, "ws1"))
        self.assertEqual(out, "")


class PersonaIdentityTests(unittest.TestCase):
    """Bot-display name + greeting wiring."""

    def test_name_per_preset(self):
        import personas
        self.assertEqual(personas.persona_name_from_preset("default"), "Prism")
        self.assertEqual(personas.persona_name_from_preset("concise"), "Flash")
        self.assertEqual(personas.persona_name_from_preset("formal"), "Crystal")
        self.assertEqual(personas.persona_name_from_preset("cheeky"), "Glint")
        self.assertEqual(personas.persona_name_from_preset("socratic"), "Echo")
        self.assertEqual(personas.persona_name_from_preset("warm"), "Glow")
        self.assertEqual(personas.persona_name_from_preset("analytical"), "Spectrum")

    def test_name_for_custom_falls_back_to_prism(self):
        import personas
        # Custom personas are tone-only; the bot still calls itself Prism.
        self.assertEqual(personas.persona_name_from_preset("custom"), "Prism")
        self.assertEqual(personas.persona_name_from_preset(None), "Prism")
        self.assertEqual(personas.persona_name_from_preset("nonexistent"), "Prism")

    def test_greeting_per_preset_mentions_the_name(self):
        import personas
        # Each persona's greeting must self-identify with the matching name so
        # the bot's first chat message in the meeting is unambiguous.
        for preset in ("concise", "formal", "cheeky", "socratic", "warm", "analytical"):
            name = personas.PERSONA_NAMES[preset]
            greeting = personas.persona_greeting_from_preset(preset)
            self.assertIn(name, greeting, f"{preset!r} greeting missing name {name!r}")

    def test_greeting_for_default_says_prism(self):
        import personas
        self.assertIn("Prism", personas.persona_greeting_from_preset("default"))

    def test_greeting_for_custom_falls_back_to_default(self):
        import personas
        self.assertEqual(
            personas.persona_greeting_from_preset("custom"),
            personas.PERSONA_GREETINGS["default"],
        )


class PersonaIdentityResolvedTests(unittest.TestCase):
    """Full-precedence (name, text, preset) resolution for the live bot."""

    def setUp(self):
        import personas
        personas._reset_for_tests()
        async def _exec(q):
            return q.execute()
        self._exec_patch = patch.object(personas, "_execute", _exec)
        self._exec_patch.start()

    def tearDown(self):
        self._exec_patch.stop()

    def test_personal_override_returns_name_text_preset(self):
        import personas
        sb = _fake_sb()
        name, text, preset = asyncio.run(personas.persona_identity_resolved(
            sb, {"persona_preset": "cheeky"}, None))
        self.assertEqual(name, "Glint")
        self.assertEqual(text, personas.PRESETS["cheeky"])
        self.assertEqual(preset, "cheeky")

    def test_workspace_fallback_returns_workspace_name(self):
        import personas
        sb = _fake_sb(ws_row={"default_persona": "analytical"})
        name, text, preset = asyncio.run(personas.persona_identity_resolved(
            sb, {"persona_preset": "default"}, "ws1"))
        self.assertEqual(name, "Spectrum")
        self.assertEqual(text, personas.PRESETS["analytical"])
        self.assertEqual(preset, "analytical")

    def test_no_personal_no_workspace_returns_prism_default(self):
        import personas
        sb = _fake_sb()
        name, text, preset = asyncio.run(personas.persona_identity_resolved(
            sb, {"persona_preset": "default"}, None))
        self.assertEqual(name, "Prism")
        self.assertEqual(text, "")
        self.assertEqual(preset, "default")

    def test_custom_persona_keeps_prism_name_with_text(self):
        import personas
        # Custom tone but no Prism-family name (custom is tone-only).
        sb = _fake_sb()
        name, text, preset = asyncio.run(personas.persona_identity_resolved(
            sb, {"persona_preset": "custom", "persona_custom_prompt": "Be a pirate."}, None))
        self.assertEqual(name, "Prism")
        self.assertEqual(text, "Be a pirate.")
        self.assertEqual(preset, "custom")


if __name__ == "__main__":
    unittest.main()

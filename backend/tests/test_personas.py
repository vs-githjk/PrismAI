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


if __name__ == "__main__":
    unittest.main()

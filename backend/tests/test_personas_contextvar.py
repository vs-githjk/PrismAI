# backend/tests/test_personas_contextvar.py
"""Contextvar isolation + llm_call wrap."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules.setdefault("supabase", fake)


_stub_supabase()


class LlmCallPersonaWrapTests(unittest.TestCase):
    def _fake_anthropic(self, captured):
        """Build a fake Anthropic client whose messages.create captures the
        system prompt (a separate kwarg in the Messages API) and returns a stub."""
        client = MagicMock()
        async def create(**kwargs):
            captured["system"] = kwargs["system"]
            block = MagicMock()
            block.text = "ok"
            resp = MagicMock()
            resp.content = [block]
            return resp
        client.messages.create = AsyncMock(side_effect=create)
        return client

    def test_no_persona_leaves_system_prompt_unchanged(self):
        import importlib
        from agents import utils
        importlib.reload(utils)
        captured = {}
        with patch.object(utils, "_get_anthropic", lambda: self._fake_anthropic(captured)):
            asyncio.run(utils.llm_call("You are a summarizer.", "transcript here"))
        self.assertEqual(captured["system"], "You are a summarizer.")

    def test_persona_set_appends_safety_wrapped_suffix(self):
        import importlib
        from agents import utils
        importlib.reload(utils)
        captured = {}

        async def run():
            utils._PERSONA_TEXT.set("Be terse.")
            await utils.llm_call("You are a summarizer.", "transcript")

        with patch.object(utils, "_get_anthropic", lambda: self._fake_anthropic(captured)):
            asyncio.run(run())

        sys_msg = captured["system"]
        self.assertIn("You are a summarizer.", sys_msg)
        self.assertIn("Tone instruction", sys_msg)
        self.assertIn("does not change facts, schema, scores, or JSON keys", sys_msg)
        self.assertIn("Be terse.", sys_msg)


class ContextvarIsolationTests(unittest.TestCase):
    def test_parallel_gather_sees_own_persona(self):
        """Two tasks launched via asyncio.gather, each setting a different
        persona inside its own coroutine, must read their own value."""
        import importlib
        from agents import utils
        importlib.reload(utils)

        captured = {"a": None, "b": None}

        async def task(name, persona_text):
            utils._PERSONA_TEXT.set(persona_text)
            await asyncio.sleep(0.01)  # yield to the loop, give the other task a chance to clobber
            captured[name] = utils._PERSONA_TEXT.get()

        async def run():
            await asyncio.gather(task("a", "persona-A"), task("b", "persona-B"))

        asyncio.run(run())
        self.assertEqual(captured["a"], "persona-A")
        self.assertEqual(captured["b"], "persona-B")


if __name__ == "__main__":
    unittest.main()

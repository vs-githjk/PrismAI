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

os.environ.setdefault("GROQ_API_KEY", "test")


class TaintRegistryTests(unittest.TestCase):
    def setUp(self):
        from tools.registry import register_tool, _TOOLS
        self._TOOLS = _TOOLS
        self._added = []

        async def _noop(_args, user_settings=None):
            return {"ok": True}

        register_tool(
            name="mock_tainted",
            description="tainted",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
            taints_context=True,
        )
        register_tool(
            name="mock_safe",
            description="safe",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
        )
        self._added = ["mock_tainted", "mock_safe"]

    def tearDown(self):
        for name in self._added:
            self._TOOLS.pop(name, None)

    def test_tainted_flag_stored(self):
        self.assertTrue(self._TOOLS["mock_tainted"]["taints_context"])
        self.assertFalse(self._TOOLS["mock_safe"]["taints_context"])

    def test_is_tainted_helper(self):
        from tools.registry import is_tainted
        self.assertTrue(is_tainted("mock_tainted"))
        self.assertFalse(is_tainted("mock_safe"))
        self.assertFalse(is_tainted("does_not_exist"))

    def test_web_search_is_tainted(self):
        # Production check: the actual web_search tool must be tainted.
        import tools.web_search  # noqa: F401 — triggers registration
        from tools.registry import is_tainted
        self.assertTrue(is_tainted("web_search"))


class TaintEnforcementHelperTests(unittest.TestCase):
    """Exercise the loop's enforcement helper for both the structured tool_calls
    path and the malformed-generation recovery path. The helper is the single
    chokepoint both paths call after executing tools."""

    def setUp(self):
        from tools.registry import register_tool, _TOOLS
        self._TOOLS = _TOOLS

        async def _noop(_args, user_settings=None):
            return {"ok": True}

        register_tool(
            name="mock_tainted",
            description="tainted",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
            taints_context=True,
        )
        register_tool(
            name="mock_safe",
            description="safe",
            parameters={"type": "object", "properties": {}},
            handler=_noop,
        )

    def tearDown(self):
        for name in ("mock_tainted", "mock_safe"):
            self._TOOLS.pop(name, None)

    def _fresh_kwargs(self):
        return {
            "model": "llama-3.3-70b-versatile",
            "temperature": 0.3,
            "messages": [{"role": "system", "content": "x"}],
            "tools": [{"type": "function", "function": {"name": "mock_safe"}}],
            "tool_choice": "auto",
        }

    def test_structured_path_strips_tools_after_tainted(self):
        # Simulates iteration 1: model returns a tool_call for the tainted tool.
        # After execution, the helper must remove `tools`/`tool_choice` so iteration 2
        # cannot dispatch any further tools.
        from realtime_routes import _strip_tools_if_tainted
        call_kwargs = self._fresh_kwargs()
        stripped = _strip_tools_if_tainted(call_kwargs, ["mock_tainted"])
        self.assertTrue(stripped)
        self.assertNotIn("tools", call_kwargs)
        self.assertNotIn("tool_choice", call_kwargs)

    def test_recovery_path_strips_tools_after_tainted(self):
        # Same enforcement when the tool call was recovered from a malformed
        # <function=mock_tainted {...}> generation rather than structured tool_calls.
        from realtime_routes import _strip_tools_if_tainted
        call_kwargs = self._fresh_kwargs()
        synth_tc_payload = [{
            "id": "call_synth_0_0_123",
            "type": "function",
            "function": {"name": "mock_tainted", "arguments": "{}"},
        }]
        executed_names = [tc["function"]["name"] for tc in synth_tc_payload]
        stripped = _strip_tools_if_tainted(call_kwargs, executed_names)
        self.assertTrue(stripped)
        self.assertNotIn("tools", call_kwargs)
        self.assertNotIn("tool_choice", call_kwargs)

    def test_non_tainted_tool_keeps_tools(self):
        from realtime_routes import _strip_tools_if_tainted
        call_kwargs = self._fresh_kwargs()
        stripped = _strip_tools_if_tainted(call_kwargs, ["mock_safe"])
        self.assertFalse(stripped)
        self.assertIn("tools", call_kwargs)
        self.assertIn("tool_choice", call_kwargs)

    def test_mixed_batch_with_tainted_strips_tools(self):
        # If a single batch executes both a safe and a tainted tool, taint wins.
        from realtime_routes import _strip_tools_if_tainted
        call_kwargs = self._fresh_kwargs()
        stripped = _strip_tools_if_tainted(call_kwargs, ["mock_safe", "mock_tainted"])
        self.assertTrue(stripped)
        self.assertNotIn("tools", call_kwargs)


if __name__ == "__main__":
    unittest.main()

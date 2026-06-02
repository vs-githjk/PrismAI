# backend/tests/test_persona_wrappers.py
"""Persona suffix wrappers (canonical + tool-aware) and contextvar delegation."""
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.utils import (
    persona_suffix,
    persona_suffix_agentic,
    get_persona_suffix,
    _PERSONA_TEXT,
)


class PersonaWrapperTests(unittest.TestCase):
    def test_persona_suffix_empty_returns_empty(self):
        self.assertEqual(persona_suffix(""), "")

    def test_persona_suffix_whitespace_returns_empty(self):
        self.assertEqual(persona_suffix("   "), "")

    def test_persona_suffix_wraps_text(self):
        out = persona_suffix("Be terse.")
        self.assertIn("Be terse.", out)
        self.assertIn("Tone instruction", out)

    def test_agentic_empty_returns_empty(self):
        self.assertEqual(persona_suffix_agentic(""), "")
        self.assertEqual(persona_suffix_agentic("   "), "")

    def test_agentic_fences_tool_calls(self):
        out = persona_suffix_agentic("Be terse.")
        self.assertIn("Be terse.", out)
        # The distinguishing clause: persona must not change tool behavior.
        self.assertIn("your available tools", out)

    def test_get_persona_suffix_delegates_to_canonical(self):
        token = _PERSONA_TEXT.set("Be terse.")
        try:
            self.assertEqual(get_persona_suffix(), persona_suffix("Be terse."))
        finally:
            _PERSONA_TEXT.reset(token)


if __name__ == "__main__":
    unittest.main()

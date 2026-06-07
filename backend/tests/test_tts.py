"""Unit tests for tools.tts provider gating (PRISM_FORCE_EDGE_TTS)."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools import tts  # noqa: E402


class ForceEdgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_force_edge_skips_elevenlabs(self):
        called = {"eleven": False, "edge": False}

        async def fake_eleven(text):
            called["eleven"] = True
            return b"eleven"

        async def fake_edge(text):
            called["edge"] = True
            return b"edge"

        with mock.patch.object(tts, "ELEVENLABS_API_KEY", "set"), \
             mock.patch.object(tts, "_tts_elevenlabs", fake_eleven), \
             mock.patch.object(tts, "_tts_edge", fake_edge), \
             mock.patch.dict(os.environ, {"PRISM_FORCE_EDGE_TTS": "1"}):
            out = await tts.text_to_speech("hello")

        self.assertEqual(out, b"edge")
        self.assertFalse(called["eleven"])
        self.assertTrue(called["edge"])

    async def test_default_uses_elevenlabs_when_key_set(self):
        tts._eleven_blocked_until = 0.0

        async def fake_eleven(text):
            return b"eleven"

        async def fake_edge(text):
            return b"edge"

        with mock.patch.object(tts, "ELEVENLABS_API_KEY", "set"), \
             mock.patch.object(tts, "_tts_elevenlabs", fake_eleven), \
             mock.patch.object(tts, "_tts_edge", fake_edge), \
             mock.patch.dict(os.environ, {}, clear=True):
            out = await tts.text_to_speech("hello")

        self.assertEqual(out, b"eleven")


if __name__ == "__main__":
    unittest.main()

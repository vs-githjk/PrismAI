import importlib
import asyncio
import sys
import types
import unittest
from pathlib import Path

from fastapi.dependencies import utils as fastapi_dependency_utils
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_args, **_kwargs: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)


class _FakeGroqCompletions:
    async def create(self, *args, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="mocked response"))]
        )


class _FakeGroqAudioTranscriptions:
    async def create(self, *args, **kwargs):
        return types.SimpleNamespace(text="mock transcript")


class _FakeGroqAudio:
    def __init__(self):
        self.transcriptions = _FakeGroqAudioTranscriptions()


class _FakeAsyncGroq:
    def __init__(self, *args, **kwargs):
        self.chat = types.SimpleNamespace(completions=_FakeGroqCompletions())
        self.audio = _FakeGroqAudio()


fake_groq_module = types.ModuleType("groq")
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

fake_analysis_service = types.ModuleType("analysis_service")
fake_analysis_service.AGENT_MAP = {}
fake_analysis_service.AGENT_RESULT_KEY = {}
fake_analysis_service.build_analysis_transcript = lambda transcript, speakers=None: transcript


async def _fake_run_full_analysis(_transcript: str):
    return {"summary": "ok", "agents_run": []}


fake_analysis_service.run_full_analysis = _fake_run_full_analysis
sys.modules["analysis_service"] = fake_analysis_service

fastapi_dependency_utils.ensure_multipart_is_installed = lambda: None


analysis_routes = importlib.import_module("analysis_routes")
main = importlib.import_module("main")


class MainRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_analyze_rejects_empty_transcript(self):
        response = self.client.post("/analyze", json={"transcript": "   ", "speakers": []})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Transcript cannot be empty")

    def test_analyze_returns_result(self):
        response = self.client.post("/analyze", json={"transcript": "Hello world", "speakers": []})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"summary": "ok", "agents_run": []})

    def test_transcribe_returns_mocked_transcript(self):
        class FakeUploadFile:
            filename = "demo.wav"
            content_type = "audio/wav"

            async def read(self):
                return b"audio-bytes"

        router = analysis_routes.create_analysis_router(_FakeAsyncGroq())
        transcribe_endpoint = next(
            route.endpoint for route in router.routes if getattr(route, "path", None) == "/transcribe"
        )
        response = asyncio.run(transcribe_endpoint(FakeUploadFile()))

        self.assertEqual(response, {"transcript": "mock transcript"})


if __name__ == "__main__":
    unittest.main()

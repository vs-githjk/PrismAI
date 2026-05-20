import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_openai():
    fake = types.ModuleType("openai")
    fake.AsyncOpenAI = MagicMock()
    sys.modules["openai"] = fake
    return fake


class EmbeddingsTests(unittest.TestCase):
    def test_embed_text_calls_openai_with_correct_model(self):
        _stub_openai()
        import importlib
        embeddings = importlib.import_module("embeddings")
        importlib.reload(embeddings)

        mock_create = AsyncMock(return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)]))
        with patch.object(embeddings, "_get_client") as mock_client:
            mock_client.return_value.embeddings.create = mock_create
            vec = asyncio.run(embeddings.embed_text("hello world"))

        self.assertEqual(len(vec), 1536)
        mock_create.assert_awaited_once()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["model"], "text-embedding-3-small")
        self.assertEqual(kwargs["input"], ["hello world"])

    def test_embed_batch_chunks_into_groups_of_100(self):
        _stub_openai()
        import importlib
        embeddings = importlib.import_module("embeddings")
        importlib.reload(embeddings)

        call_count = 0

        async def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(data=[MagicMock(embedding=[0.1] * 1536) for _ in kwargs["input"]])

        with patch.object(embeddings, "_get_client") as mock_client:
            mock_client.return_value.embeddings.create = fake_create
            vectors = asyncio.run(embeddings.embed_batch([f"chunk {i}" for i in range(250)]))

        self.assertEqual(len(vectors), 250)
        self.assertEqual(call_count, 3)  # 100 + 100 + 50

    def test_embed_text_retries_on_429(self):
        _stub_openai()
        import importlib
        embeddings = importlib.import_module("embeddings")
        importlib.reload(embeddings)

        attempts = 0

        async def flaky(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                err = Exception("Rate limit")
                err.status_code = 429
                raise err
            return MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])

        with patch.object(embeddings, "_get_client") as mock_client:
            mock_client.return_value.embeddings.create = flaky
            with patch.object(embeddings.asyncio, "sleep", AsyncMock()):
                vec = asyncio.run(embeddings.embed_text("retry me"))

        self.assertEqual(attempts, 3)
        self.assertEqual(len(vec), 1536)


if __name__ == "__main__":
    unittest.main()

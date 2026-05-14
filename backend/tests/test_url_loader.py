import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _fake_response(status: int, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data or {})
    resp.text = text
    return resp


class UrlLoaderTests(unittest.TestCase):
    def test_tavily_success(self):
        from knowledge_ingest import url_loader

        ok = _fake_response(200, json_data={
            "results": [{"raw_content": "Article body text from Tavily."}]
        })

        async def fake_post(self, url, *args, **kwargs):
            return ok

        with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}):
            with patch("httpx.AsyncClient.post", new=fake_post):
                result = asyncio.run(url_loader.load("https://example.com/page"))

        self.assertIn("Article body text", result.text)

    def test_falls_back_to_jina_on_tavily_failure(self):
        from knowledge_ingest import url_loader

        async def fake_post(self, url, *args, **kwargs):
            return _fake_response(500)

        async def fake_get(self, url, *args, **kwargs):
            return _fake_response(200, text="Jina markdown content here.")

        with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}):
            with patch("httpx.AsyncClient.post", new=fake_post):
                with patch("httpx.AsyncClient.get", new=fake_get):
                    result = asyncio.run(url_loader.load("https://example.com/page"))

        self.assertIn("Jina markdown content", result.text)

    def test_raises_when_both_fail(self):
        from knowledge_ingest import url_loader
        from knowledge_ingest.loaders_base import LoaderError

        async def fake_post(self, url, *args, **kwargs):
            return _fake_response(500)

        async def fake_get(self, url, *args, **kwargs):
            return _fake_response(403)

        with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}):
            with patch("httpx.AsyncClient.post", new=fake_post):
                with patch("httpx.AsyncClient.get", new=fake_get):
                    with self.assertRaises(LoaderError):
                        asyncio.run(url_loader.load("https://example.com"))


if __name__ == "__main__":
    unittest.main()

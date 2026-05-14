import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _fake_response(status: int, content=b"", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.json = MagicMock(return_value=json_data or {})
    return resp


class GdriveLoaderTests(unittest.TestCase):
    def test_loads_google_doc_as_text(self):
        from knowledge_ingest import gdrive_loader

        meta_resp = _fake_response(200, json_data={"mimeType": "application/vnd.google-apps.document", "name": "MyDoc"})
        export_resp = _fake_response(200, content=b"Hello from Google Doc")

        async def fake_get(self, url, *args, **kwargs):
            if "/export" in url:
                return export_resp
            return meta_resp

        with patch("httpx.AsyncClient.get", new=fake_get):
            result = asyncio.run(gdrive_loader.load("file-id-123", token="g-token"))

        self.assertIn("Hello from Google Doc", result.text)

    def test_raises_on_401(self):
        from knowledge_ingest import gdrive_loader
        from knowledge_ingest.loaders_base import LoaderError

        async def fake_get(self, url, *args, **kwargs):
            return _fake_response(401)

        with patch("httpx.AsyncClient.get", new=fake_get):
            with self.assertRaises(LoaderError) as ctx:
                asyncio.run(gdrive_loader.load("file-id", token="bad"))
            self.assertIn("reconnect", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()

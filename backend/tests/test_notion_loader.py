import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class NotionLoaderTests(unittest.TestCase):
    def test_loads_blocks_as_text(self):
        from knowledge_ingest import notion_loader

        blocks = {
            "results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello"}]}},
                {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
            ],
            "has_more": False,
        }

        async def fake_fetch(*args, **kwargs):
            return blocks

        with patch.object(notion_loader, "_fetch_blocks", new=fake_fetch):
            result = asyncio.run(notion_loader.load("page-id-abc", token="notion-token"))

        self.assertIn("Hello", result.text)
        self.assertIn("Title", result.text)

    def test_raises_when_token_missing(self):
        from knowledge_ingest import notion_loader
        from knowledge_ingest.loaders_base import LoaderError

        with self.assertRaises(LoaderError):
            asyncio.run(notion_loader.load("page-id", token=""))


if __name__ == "__main__":
    unittest.main()

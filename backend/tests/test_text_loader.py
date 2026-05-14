import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class TextLoaderTests(unittest.TestCase):
    def test_loads_utf8_text(self):
        from knowledge_ingest import text_loader
        result = asyncio.run(text_loader.load("Hello world.".encode("utf-8")))
        self.assertEqual(result.text, "Hello world.")

    def test_handles_invalid_bytes_with_replace(self):
        from knowledge_ingest import text_loader
        result = asyncio.run(text_loader.load(b"good \xff\xfe bad"))
        self.assertIn("good", result.text)

    def test_empty_raises(self):
        from knowledge_ingest import text_loader
        from knowledge_ingest.loaders_base import LoaderError
        with self.assertRaises(LoaderError):
            asyncio.run(text_loader.load(b""))


if __name__ == "__main__":
    unittest.main()

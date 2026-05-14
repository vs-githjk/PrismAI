import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub python-docx so the test can run without the package installed
fake_docx = types.ModuleType("docx")
fake_docx.Document = MagicMock()
sys.modules.setdefault("docx", fake_docx)


class DocxLoaderTests(unittest.TestCase):
    def test_loads_paragraphs_in_order(self):
        from knowledge_ingest import docx_loader

        fake_doc = MagicMock()
        fake_doc.paragraphs = [
            MagicMock(text="First paragraph."),
            MagicMock(text="Second paragraph."),
        ]
        fake_doc.tables = []

        with patch.object(docx_loader, "Document", return_value=fake_doc):
            result = asyncio.run(docx_loader.load(b"fake-docx-bytes"))

        self.assertIn("First paragraph.", result.text)
        self.assertIn("Second paragraph.", result.text)
        # Order preserved
        self.assertLess(result.text.index("First"), result.text.index("Second"))

    def test_includes_tables_as_markdown(self):
        from knowledge_ingest import docx_loader

        fake_doc = MagicMock()
        fake_doc.paragraphs = [MagicMock(text="Intro")]
        cell_a = MagicMock(text="Header A")
        cell_b = MagicMock(text="Header B")
        cell_c = MagicMock(text="Val 1")
        cell_d = MagicMock(text="Val 2")
        row1 = MagicMock(cells=[cell_a, cell_b])
        row2 = MagicMock(cells=[cell_c, cell_d])
        fake_table = MagicMock(rows=[row1, row2])
        fake_doc.tables = [fake_table]

        with patch.object(docx_loader, "Document", return_value=fake_doc):
            result = asyncio.run(docx_loader.load(b"fake"))

        self.assertIn("| Header A | Header B |", result.text)
        self.assertIn("| Val 1 | Val 2 |", result.text)


if __name__ == "__main__":
    unittest.main()

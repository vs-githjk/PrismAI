import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub fitz before importing pdf_loader so we don't need PyMuPDF installed in CI
fake_fitz = types.ModuleType("fitz")
fake_fitz.open = MagicMock()
sys.modules.setdefault("fitz", fake_fitz)

# Stub pytesseract
fake_tesseract = types.ModuleType("pytesseract")
fake_tesseract.image_to_string = MagicMock(return_value="")
sys.modules.setdefault("pytesseract", fake_tesseract)

# Stub PIL
fake_pil = types.ModuleType("PIL")
fake_image_mod = types.ModuleType("PIL.Image")
fake_image_mod.open = MagicMock()
fake_pil.Image = fake_image_mod
sys.modules.setdefault("PIL", fake_pil)
sys.modules.setdefault("PIL.Image", fake_image_mod)


class PdfLoaderTests(unittest.TestCase):
    def test_loads_text_pdf(self):
        from knowledge_ingest import pdf_loader

        fake_page = MagicMock()
        fake_page.get_text.return_value = "Page one body text."
        fake_doc = MagicMock()
        fake_doc.__iter__.return_value = iter([fake_page])
        fake_doc.__len__.return_value = 1

        with patch.object(pdf_loader.fitz, "open", return_value=fake_doc):
            result = asyncio.run(pdf_loader.load(b"%PDF-1.4 fake bytes"))

        self.assertIn("Page one body text", result.text)
        self.assertEqual(len(result.page_metadata), 1)
        self.assertEqual(result.page_metadata[0]["page"], 1)

    def test_falls_back_to_ocr_when_empty(self):
        from knowledge_ingest import pdf_loader

        empty_page = MagicMock()
        empty_page.get_text.return_value = ""
        empty_page.get_pixmap.return_value.tobytes.return_value = b"fake-png-bytes"
        fake_doc = MagicMock()
        fake_doc.__iter__.return_value = iter([empty_page])
        fake_doc.__len__.return_value = 1

        with patch.object(pdf_loader.fitz, "open", return_value=fake_doc):
            with patch.object(pdf_loader, "_ocr_image", return_value="OCR text from scan"):
                result = asyncio.run(pdf_loader.load(b"%PDF-1.4 fake"))

        self.assertIn("OCR text from scan", result.text)

    def test_raises_loader_error_when_both_fail(self):
        from knowledge_ingest import pdf_loader
        from knowledge_ingest.loaders_base import LoaderError

        empty_page = MagicMock()
        empty_page.get_text.return_value = ""
        empty_page.get_pixmap.return_value.tobytes.return_value = b""
        fake_doc = MagicMock()
        fake_doc.__iter__.return_value = iter([empty_page])
        fake_doc.__len__.return_value = 1

        with patch.object(pdf_loader.fitz, "open", return_value=fake_doc):
            with patch.object(pdf_loader, "_ocr_image", return_value=""):
                with self.assertRaises(LoaderError):
                    asyncio.run(pdf_loader.load(b"%PDF-1.4 empty"))


if __name__ == "__main__":
    unittest.main()

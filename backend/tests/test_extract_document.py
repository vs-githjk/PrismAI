"""/extract-document — turns an uploaded .docx/.pdf/.txt into text for the
Article/Report input path (reuses the knowledge-base loaders)."""
import io
import sys
import importlib
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

analysis_routes = importlib.import_module("analysis_routes")


def _make_docx(text: str) -> bytes:
    from docx import Document
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class ExtractDocumentTestCase(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(analysis_routes.create_analysis_router(openai_client=None))
        self.client = TestClient(app)
        analysis_routes._doc_extract_log.clear()

    def _post(self, filename, content, ctype="application/octet-stream"):
        return self.client.post("/extract-document", files={"file": (filename, content, ctype)})

    def test_docx_extraction(self):
        content = _make_docx("FDE Academy expansion plan.\nSecond paragraph with detail.")
        r = self._post("report.docx", content)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("FDE Academy expansion plan.", body["transcript"])
        self.assertIn("Second paragraph", body["transcript"])
        self.assertEqual(body["filename"], "report.docx")
        self.assertGreater(body["words"], 5)

    def test_txt_extraction(self):
        r = self._post("notes.txt", b"Just some plain text notes.")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["transcript"], "Just some plain text notes.")

    def test_unsupported_type_rejected(self):
        r = self._post("thing.doc", b"\xd0\xcf legacy word bytes")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported file type", r.json()["detail"])

    def test_empty_document_rejected(self):
        r = self._post("empty.txt", b"   \n  ")
        self.assertEqual(r.status_code, 400)
        detail = r.json()["detail"].lower()
        self.assertTrue("empty" in detail or "no readable text" in detail, detail)

    def test_oversized_rejected(self):
        big = b"x" * (analysis_routes._DOC_MAX_BYTES + 1)
        r = self._post("huge.txt", big)
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.json()["detail"].lower())

    def test_rate_limited(self):
        for _ in range(analysis_routes._DOC_EXTRACT_PER_MINUTE):
            self._post("n.txt", b"hello there friend")
        r = self._post("n.txt", b"hello there friend")
        self.assertEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()

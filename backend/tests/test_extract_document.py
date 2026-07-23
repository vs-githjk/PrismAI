"""/extract-document — turns an uploaded .docx/.pdf/.txt into text for the
Article/Report input path (reuses the knowledge-base loaders).

Isolation notes (this suite shares a process with mock-heavy siblings):
- `test_docx_loader.py` installs a FAKE `docx` module in sys.modules via setdefault;
  import the REAL python-docx here first (this file collects before that one) so our
  build+parse round-trip uses the genuine library.
- Import `analysis_routes` LAZILY (in setUp, not at module import) so we don't populate
  the module cache before `test_main_routes.py` installs its fake `analysis_service`
  — importing it at collection time would defeat that test's mock.
"""
import io
import sys
import unittest
from pathlib import Path

import docx  # noqa: F401 — pin the REAL python-docx before a sibling's fake shim wins

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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
        import analysis_routes  # lazy — see module docstring
        self.ar = analysis_routes
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
        big = b"x" * (self.ar._DOC_MAX_BYTES + 1)
        r = self._post("huge.txt", big)
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.json()["detail"].lower())

    def test_rate_limited(self):
        for _ in range(self.ar._DOC_EXTRACT_PER_MINUTE):
            self._post("n.txt", b"hello there friend")
        r = self._post("n.txt", b"hello there friend")
        self.assertEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()

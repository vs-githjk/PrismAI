# Knowledge Base & Real-Time RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable PrismAI to ingest user-supplied documents (PDF/DOCX/TXT/URL/Notion/Google Drive) and use them during live meetings — answering questions with citations, surfacing relevant content proactively, falling back to web search and then to asking the user when documents are insufficient.

**Architecture:** RAG with Supabase pgvector. OpenAI text-embedding-3-small for embeddings. Tavily for web search and URL extraction. Document-grounded answers via strict-grounding system prompt and citation requirement. Zero modifications to existing prism logic except a single try/except hook in `_compress_and_persist`.

**Tech Stack:** FastAPI + Python (unittest for tests), Supabase Postgres + pgvector, OpenAI embeddings, Tavily search/extract, PyMuPDF + python-docx + Tesseract OCR, React + Vite frontend.

**Spec:** [docs/superpowers/specs/2026-05-11-knowledge-base-rag-design.md](../specs/2026-05-11-knowledge-base-rag-design.md)

---

## Pre-flight (manual, do once)

- [ ] **P1: Run database migration**

In the Supabase SQL editor, run:
```
backend/../supabase/knowledge_migration.sql
```
Verify with:
```sql
select * from pg_extension where extname = 'vector';
\d knowledge_docs
\d knowledge_chunks
```

- [ ] **P2: Add environment variables**

Append to `backend/.env`:
```
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

- [ ] **P3: Add Google Drive scope**

In Google Cloud Console → OAuth consent screen → Scopes, add `https://www.googleapis.com/auth/drive.readonly`. Save. The next user re-consent will include Drive.

- [ ] **P4: Create Supabase Storage bucket**

In Supabase dashboard → Storage → New bucket:
- Name: `knowledge`
- Public: NO
- File size limit: 50 MB

Add the RLS policy:
```sql
create policy "users access own knowledge files"
  on storage.objects for all
  using (bucket_id = 'knowledge' and auth.uid()::text = (storage.foldername(name))[1]);
```

- [ ] **P5: Install new Python dependencies**

Append to `backend/requirements.txt`:
```
openai>=1.30.0
pymupdf>=1.24.0
python-docx>=1.1.0
pytesseract>=0.3.10
tiktoken>=0.7.0
notion-client>=2.2.1
google-api-python-client>=2.130.0
google-auth>=2.30.0
```

Install Tesseract OCR binary:
- Windows: `winget install --id UB-Mannheim.TesseractOCR`
- Mac: `brew install tesseract`
- Linux: `apt-get install tesseract-ocr`

Then:
```bash
cd backend && pip install -r requirements.txt
```

- [ ] **P6: Add `.superpowers/` to `.gitignore`**

```bash
echo ".superpowers/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore superpowers brainstorming artifacts"
```

---

## Task 1: Embeddings Client

**Files:**
- Create: `backend/embeddings.py`
- Test: `backend/tests/test_embeddings.py`

- [ ] **Step 1.1: Write the failing test**

Create `backend/tests/test_embeddings.py`:

```python
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
        self.assertEqual(kwargs["input"], "hello world")

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
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd backend && python -m unittest tests.test_embeddings -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'embeddings'`.

- [ ] **Step 1.3: Implement `embeddings.py`**

Create `backend/embeddings.py`:

```python
"""OpenAI embeddings client with batching and retry logic."""

import asyncio
import os
from typing import Optional

import tiktoken
from openai import AsyncOpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
MAX_TOKENS_PER_INPUT = 8000
BATCH_SIZE = 100

_client: Optional[AsyncOpenAI] = None
_encoder = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def _get_encoder():
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _truncate(text: str) -> str:
    enc = _get_encoder()
    tokens = enc.encode(text)
    if len(tokens) <= MAX_TOKENS_PER_INPUT:
        return text
    return enc.decode(tokens[:MAX_TOKENS_PER_INPUT])


async def _call_with_retry(inputs: list[str], max_retries: int = 3) -> list[list[float]]:
    delay = 1.0
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = await _get_client().embeddings.create(
                model=EMBEDDING_MODEL,
                input=inputs,
            )
            return [d.embedding for d in resp.data]
        except Exception as exc:
            last_err = exc
            status = getattr(exc, "status_code", None)
            if status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_err  # pragma: no cover


async def embed_text(text: str) -> list[float]:
    """Embed a single string. Truncates to 8000 tokens if longer."""
    truncated = _truncate(text)
    result = await _call_with_retry([truncated])
    return result[0]


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed many strings, batching into groups of 100."""
    if not texts:
        return []
    truncated = [_truncate(t) for t in texts]
    all_vecs: list[list[float]] = []
    for i in range(0, len(truncated), BATCH_SIZE):
        batch = truncated[i : i + BATCH_SIZE]
        all_vecs.extend(await _call_with_retry(batch))
    return all_vecs
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
cd backend && python -m unittest tests.test_embeddings -v
```

Expected: 3 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add backend/embeddings.py backend/tests/test_embeddings.py backend/requirements.txt
git commit -m "feat(knowledge): add OpenAI embeddings client with batching and retry"
```

---

## Task 2: Chunker

**Files:**
- Create: `backend/knowledge_ingest/__init__.py`
- Create: `backend/knowledge_ingest/chunker.py`
- Test: `backend/tests/test_chunker.py`

- [ ] **Step 2.1: Write the failing test**

Create `backend/tests/test_chunker.py`:

```python
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class ChunkerTests(unittest.TestCase):
    def test_short_text_returns_single_chunk(self):
        from knowledge_ingest.chunker import chunk_text
        chunks = chunk_text("Hello world. This is short.", base_metadata={})
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], "Hello world. This is short.")

    def test_long_text_splits_with_overlap(self):
        from knowledge_ingest.chunker import chunk_text
        sentences = [f"Sentence number {i}." for i in range(300)]
        text = " ".join(sentences)
        chunks = chunk_text(text, base_metadata={})
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c["content"].split()), 500)

    def test_chunks_preserve_base_metadata(self):
        from knowledge_ingest.chunker import chunk_text
        chunks = chunk_text("A. B. C.", base_metadata={"page": 3, "heading": "Intro"})
        self.assertEqual(chunks[0]["metadata"]["page"], 3)
        self.assertEqual(chunks[0]["metadata"]["heading"], "Intro")

    def test_chunks_have_sequential_indices(self):
        from knowledge_ingest.chunker import chunk_text
        text = " ".join([f"S{i}." for i in range(500)])
        chunks = chunk_text(text, base_metadata={})
        for i, c in enumerate(chunks):
            self.assertEqual(c["chunk_index"], i)

    def test_table_marker_preserved_as_single_chunk(self):
        from knowledge_ingest.chunker import chunk_text
        big_table = "| A | B |\n" + "\n".join([f"| row{i} | val{i} |" for i in range(100)])
        chunks = chunk_text(big_table, base_metadata={"is_table": True})
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0]["metadata"]["is_table"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
cd backend && python -m unittest tests.test_chunker -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 2.3: Implement chunker**

Create `backend/knowledge_ingest/__init__.py`:
```python
```

Create `backend/knowledge_ingest/chunker.py`:

```python
"""Sliding-window chunker with sentence-boundary preservation."""

import re
from typing import Optional

import tiktoken

CHUNK_SIZE_TOKENS = 400
OVERLAP_TOKENS = 80

_encoder = None


def _enc():
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text) if s.strip()]


def chunk_text(text: str, base_metadata: Optional[dict] = None) -> list[dict]:
    """Split text into overlapping chunks of ~400 tokens, snapped to sentence ends.

    If base_metadata indicates a table (is_table=True), the text is returned as
    a single chunk regardless of size.
    """
    base_metadata = base_metadata or {}
    text = text.strip()
    if not text:
        return []

    if base_metadata.get("is_table"):
        return [{"content": text, "chunk_index": 0, "metadata": dict(base_metadata)}]

    enc = _enc()
    sentences = _split_sentences(text)
    if not sentences:
        return [{"content": text, "chunk_index": 0, "metadata": dict(base_metadata)}]

    chunks: list[dict] = []
    buf: list[str] = []
    buf_tokens = 0
    idx = 0

    for sent in sentences:
        sent_tokens = len(enc.encode(sent))
        if buf and buf_tokens + sent_tokens > CHUNK_SIZE_TOKENS:
            content = " ".join(buf).strip()
            chunks.append({
                "content": content,
                "chunk_index": idx,
                "metadata": dict(base_metadata),
            })
            idx += 1
            # Build overlap from tail of buf
            tail: list[str] = []
            tail_tokens = 0
            for s in reversed(buf):
                t = len(enc.encode(s))
                if tail_tokens + t > OVERLAP_TOKENS:
                    break
                tail.insert(0, s)
                tail_tokens += t
            buf = tail
            buf_tokens = tail_tokens
        buf.append(sent)
        buf_tokens += sent_tokens

    if buf:
        content = " ".join(buf).strip()
        chunks.append({
            "content": content,
            "chunk_index": idx,
            "metadata": dict(base_metadata),
        })

    return chunks
```

- [ ] **Step 2.4: Run test to verify it passes**

```bash
cd backend && python -m unittest tests.test_chunker -v
```

Expected: 5 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add backend/knowledge_ingest/__init__.py backend/knowledge_ingest/chunker.py backend/tests/test_chunker.py
git commit -m "feat(knowledge): add sliding-window chunker with sentence boundaries"
```

---

## Task 3a: PDF Loader

**Files:**
- Create: `backend/knowledge_ingest/loaders_base.py`
- Create: `backend/knowledge_ingest/pdf_loader.py`
- Test: `backend/tests/test_pdf_loader.py`

- [ ] **Step 3a.1: Create LoaderError base**

Create `backend/knowledge_ingest/loaders_base.py`:

```python
"""Shared types for document loaders."""

from typing import NamedTuple


class LoadedDoc(NamedTuple):
    text: str
    page_metadata: list[dict]  # one dict per page or section


class LoaderError(Exception):
    """User-friendly error raised when a doc can't be loaded."""
```

- [ ] **Step 3a.2: Write the failing test for PDF**

Create `backend/tests/test_pdf_loader.py`:

```python
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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
```

- [ ] **Step 3a.3: Run test to verify it fails**

```bash
cd backend && python -m unittest tests.test_pdf_loader -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3a.4: Implement `pdf_loader.py`**

Create `backend/knowledge_ingest/pdf_loader.py`:

```python
"""PDF loader: PyMuPDF for text, Tesseract OCR fallback for scanned pages."""

import io

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from .loaders_base import LoadedDoc, LoaderError


def _ocr_image(png_bytes: bytes) -> str:
    if not png_bytes:
        return ""
    try:
        img = Image.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""


async def load(content: bytes) -> LoadedDoc:
    """Load a PDF from bytes. Falls back to OCR on pages with no text layer."""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise LoaderError(f"Unable to open PDF: {exc}")

    parts: list[str] = []
    page_meta: list[dict] = []
    used_ocr = False

    for page_num, page in enumerate(doc, start=1):
        text = (page.get_text() or "").strip()
        if not text:
            png_bytes = page.get_pixmap(dpi=200).tobytes("png")
            text = _ocr_image(png_bytes)
            if text:
                used_ocr = True
        if text:
            parts.append(text)
            page_meta.append({"page": page_num, "ocr": bool(used_ocr)})

    if not parts:
        raise LoaderError(
            "PDF appears to be empty or unreadable. If it's a scanned document, "
            "try a higher-quality scan or paste the content manually."
        )

    return LoadedDoc(text="\n\n".join(parts), page_metadata=page_meta)
```

- [ ] **Step 3a.5: Run test to verify it passes**

```bash
cd backend && python -m unittest tests.test_pdf_loader -v
```

Expected: 3 tests PASS.

- [ ] **Step 3a.6: Commit**

```bash
git add backend/knowledge_ingest/loaders_base.py backend/knowledge_ingest/pdf_loader.py backend/tests/test_pdf_loader.py
git commit -m "feat(knowledge): add PDF loader with PyMuPDF + OCR fallback"
```

---

## Task 3b: DOCX Loader

**Files:**
- Create: `backend/knowledge_ingest/docx_loader.py`
- Test: `backend/tests/test_docx_loader.py`

- [ ] **Step 3b.1: Write failing test**

Create `backend/tests/test_docx_loader.py`:

```python
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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
```

- [ ] **Step 3b.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_docx_loader -v
```

Expected: FAIL.

- [ ] **Step 3b.3: Implement docx_loader**

Create `backend/knowledge_ingest/docx_loader.py`:

```python
"""DOCX loader using python-docx."""

import io

from docx import Document

from .loaders_base import LoadedDoc, LoaderError


def _table_to_markdown(table) -> str:
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


async def load(content: bytes) -> LoadedDoc:
    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:
        raise LoaderError(f"Unable to open DOCX: {exc}")

    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())

    for table in doc.tables:
        md = _table_to_markdown(table)
        if md.strip():
            parts.append("\n" + md + "\n")

    if not parts:
        raise LoaderError("DOCX is empty.")

    return LoadedDoc(text="\n\n".join(parts), page_metadata=[{"page": 1}])
```

- [ ] **Step 3b.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_docx_loader -v
```

Expected: 2 tests PASS.

- [ ] **Step 3b.5: Commit**

```bash
git add backend/knowledge_ingest/docx_loader.py backend/tests/test_docx_loader.py
git commit -m "feat(knowledge): add DOCX loader with table-to-markdown conversion"
```

---

## Task 3c: Text Loader

**Files:**
- Create: `backend/knowledge_ingest/text_loader.py`
- Test: `backend/tests/test_text_loader.py`

- [ ] **Step 3c.1: Write failing test**

Create `backend/tests/test_text_loader.py`:

```python
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
```

- [ ] **Step 3c.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_text_loader -v
```

- [ ] **Step 3c.3: Implement**

Create `backend/knowledge_ingest/text_loader.py`:

```python
"""Plain text / markdown loader."""

from .loaders_base import LoadedDoc, LoaderError


async def load(content: bytes) -> LoadedDoc:
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise LoaderError("File is empty.")
    return LoadedDoc(text=text, page_metadata=[{"page": 1}])
```

- [ ] **Step 3c.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_text_loader -v
```

- [ ] **Step 3c.5: Commit**

```bash
git add backend/knowledge_ingest/text_loader.py backend/tests/test_text_loader.py
git commit -m "feat(knowledge): add plain text loader"
```

---

## Task 3d: URL Loader (Tavily Extract + Jina fallback)

**Files:**
- Create: `backend/knowledge_ingest/url_loader.py`
- Test: `backend/tests/test_url_loader.py`

- [ ] **Step 3d.1: Write failing test**

Create `backend/tests/test_url_loader.py`:

```python
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

        with patch.object(url_loader, "TAVILY_API_KEY", "fake-key"):
            with patch("httpx.AsyncClient.post", new=fake_post):
                result = asyncio.run(url_loader.load("https://example.com/page"))

        self.assertIn("Article body text", result.text)

    def test_falls_back_to_jina_on_tavily_failure(self):
        from knowledge_ingest import url_loader

        async def fake_post(self, url, *args, **kwargs):
            return _fake_response(500)

        async def fake_get(self, url, *args, **kwargs):
            return _fake_response(200, text="Jina markdown content here.")

        with patch.object(url_loader, "TAVILY_API_KEY", "fake-key"):
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

        with patch.object(url_loader, "TAVILY_API_KEY", "fake-key"):
            with patch("httpx.AsyncClient.post", new=fake_post):
                with patch("httpx.AsyncClient.get", new=fake_get):
                    with self.assertRaises(LoaderError):
                        asyncio.run(url_loader.load("https://example.com"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3d.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_url_loader -v
```

- [ ] **Step 3d.3: Implement**

Create `backend/knowledge_ingest/url_loader.py`:

```python
"""URL loader using Tavily Extract with Jina Reader fallback."""

import os

import httpx

from .loaders_base import LoadedDoc, LoaderError

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


async def _try_tavily(url: str) -> str:
    if not TAVILY_API_KEY:
        return ""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TAVILY_EXTRACT_URL,
            json={"urls": [url], "api_key": TAVILY_API_KEY},
        )
    if resp.status_code != 200:
        return ""
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return ""
    return (results[0].get("raw_content") or "").strip()


async def _try_jina(url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"https://r.jina.ai/{url}")
    if resp.status_code != 200:
        return ""
    return (resp.text or "").strip()


async def load(url: str) -> LoadedDoc:
    text = await _try_tavily(url)
    if not text:
        text = await _try_jina(url)
    if not text:
        raise LoaderError(
            "Couldn't extract content from this URL. It may require login or "
            "render content with JavaScript. Try exporting the page as a PDF and uploading that instead."
        )
    return LoadedDoc(text=text, page_metadata=[{"source_url": url}])
```

- [ ] **Step 3d.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_url_loader -v
```

- [ ] **Step 3d.5: Commit**

```bash
git add backend/knowledge_ingest/url_loader.py backend/tests/test_url_loader.py
git commit -m "feat(knowledge): add URL loader with Tavily Extract + Jina fallback"
```

---

## Task 3e: Notion Loader

**Files:**
- Create: `backend/knowledge_ingest/notion_loader.py`
- Test: `backend/tests/test_notion_loader.py`

- [ ] **Step 3e.1: Write failing test**

Create `backend/tests/test_notion_loader.py`:

```python
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
```

- [ ] **Step 3e.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_notion_loader -v
```

- [ ] **Step 3e.3: Implement**

Create `backend/knowledge_ingest/notion_loader.py`:

```python
"""Notion loader using integration token (paste-based, not OAuth)."""

import httpx

from .loaders_base import LoadedDoc, LoaderError

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _extract_text(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def _block_to_text(block: dict) -> str:
    btype = block.get("type", "")
    inner = block.get(btype, {})
    rt = inner.get("rich_text", [])
    text = _extract_text(rt)
    if btype.startswith("heading_"):
        return f"\n# {text}\n"
    if btype == "to_do":
        marker = "[x]" if inner.get("checked") else "[ ]"
        return f"{marker} {text}"
    if btype == "bulleted_list_item" or btype == "numbered_list_item":
        return f"- {text}"
    return text


async def _fetch_blocks(page_id: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(f"{NOTION_API}/blocks/{page_id}/children", headers=headers)
    if resp.status_code == 401:
        raise LoaderError("Notion token is invalid or expired — please reconnect.")
    if resp.status_code != 200:
        raise LoaderError(f"Notion API error {resp.status_code}")
    return resp.json()


async def load(page_id: str, token: str) -> LoadedDoc:
    if not token:
        raise LoaderError("Notion integration token is not configured.")

    page_id = page_id.replace("-", "").strip()
    # Format as UUID if needed
    if len(page_id) == 32:
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"

    data = await _fetch_blocks(page_id, token)
    parts = []
    for block in data.get("results", []):
        text = _block_to_text(block).strip()
        if text:
            parts.append(text)

    if not parts:
        raise LoaderError("Notion page is empty or has no readable blocks.")

    return LoadedDoc(text="\n".join(parts), page_metadata=[{"notion_page_id": page_id}])
```

- [ ] **Step 3e.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_notion_loader -v
```

- [ ] **Step 3e.5: Commit**

```bash
git add backend/knowledge_ingest/notion_loader.py backend/tests/test_notion_loader.py
git commit -m "feat(knowledge): add Notion loader using integration token"
```

---

## Task 3f: Google Drive Loader

**Files:**
- Create: `backend/knowledge_ingest/gdrive_loader.py`
- Test: `backend/tests/test_gdrive_loader.py`

- [ ] **Step 3f.1: Write failing test**

Create `backend/tests/test_gdrive_loader.py`:

```python
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
```

- [ ] **Step 3f.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_gdrive_loader -v
```

- [ ] **Step 3f.3: Implement**

Create `backend/knowledge_ingest/gdrive_loader.py`:

```python
"""Google Drive loader. Reuses the existing google_access_token."""

import httpx

from .loaders_base import LoadedDoc, LoaderError
from . import pdf_loader

DRIVE_API = "https://www.googleapis.com/drive/v3/files"


async def _get_metadata(file_id: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{DRIVE_API}/{file_id}",
            headers=headers,
            params={"fields": "mimeType,name"},
        )
    if resp.status_code == 401:
        raise LoaderError("Google access expired — please reconnect.")
    if resp.status_code == 404:
        raise LoaderError("File not found in Drive (or no access).")
    if resp.status_code != 200:
        raise LoaderError(f"Drive metadata error {resp.status_code}")
    return resp.json()


async def _download_or_export(file_id: str, token: str, mime: str) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    if mime == "application/vnd.google-apps.document":
        url = f"{DRIVE_API}/{file_id}/export"
        params = {"mimeType": "text/plain"}
    elif mime == "application/vnd.google-apps.spreadsheet":
        url = f"{DRIVE_API}/{file_id}/export"
        params = {"mimeType": "text/csv"}
    else:
        url = f"{DRIVE_API}/{file_id}"
        params = {"alt": "media"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        raise LoaderError(f"Drive download failed: {resp.status_code}")
    return resp.content


async def load(file_id: str, token: str) -> LoadedDoc:
    if not token:
        raise LoaderError("Google Drive is not connected.")
    meta = await _get_metadata(file_id, token)
    mime = meta.get("mimeType", "")
    content = await _download_or_export(file_id, token, mime)

    if mime == "application/pdf":
        return await pdf_loader.load(content)

    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise LoaderError("File is empty or unreadable.")

    return LoadedDoc(text=text, page_metadata=[{"gdrive_file_id": file_id, "name": meta.get("name")}])
```

- [ ] **Step 3f.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_gdrive_loader -v
```

- [ ] **Step 3f.5: Commit**

```bash
git add backend/knowledge_ingest/gdrive_loader.py backend/tests/test_gdrive_loader.py
git commit -m "feat(knowledge): add Google Drive loader reusing existing OAuth token"
```

---

## Task 4: knowledge_service core

**Files:**
- Create: `backend/knowledge_service.py`
- Test: `backend/tests/test_knowledge_service.py`

- [ ] **Step 4.1: Write failing test**

Create `backend/tests/test_knowledge_service.py`:

```python
import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *_a, **_k): return self
    def insert(self, *_a, **_k): return self
    def update(self, *_a, **_k): return self
    def delete(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def single(self): return self
    def execute(self): return MagicMock(data=self._data)


class _FakeSupabase:
    def __init__(self, tables: dict):
        self._tables = tables
        self.rpc_calls = []
    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))
    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeQuery(self._tables.get(f"rpc:{name}", []))


class KnowledgeServiceTests(unittest.TestCase):
    def test_search_knowledge_uses_rpc_with_embedding(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        user_id = uuid.uuid4()
        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": str(uuid.uuid4()), "doc_id": str(uuid.uuid4()),
             "doc_name": "Budget.pdf", "source_type": "pdf",
             "sensitivity": "internal", "content": "Q2 budget is $50k",
             "metadata": {}, "score": 0.91},
        ]})

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what was the budget", str(user_id), meeting_id=None
                ))

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["doc_name"], "Budget.pdf")
        self.assertEqual(fake_sb.rpc_calls[0][0], "knowledge_search")

    def test_search_returns_empty_below_min_score(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": []})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.0] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "unknown", str(uuid.uuid4())
                ))
        self.assertEqual(matches, [])

    def test_conflict_detection_flags_top_two_close_scores(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": "c1", "doc_id": "d1", "doc_name": "Q1.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on enterprise", "metadata": {}, "score": 0.90},
            {"chunk_id": "c2", "doc_id": "d2", "doc_name": "Q2.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on SMB", "metadata": {}, "score": 0.88},
        ]})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what's the strategy", str(uuid.uuid4())
                ))
        self.assertTrue(matches[0].get("possible_conflict"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_knowledge_service -v
```

- [ ] **Step 4.3: Implement knowledge_service**

Create `backend/knowledge_service.py`:

```python
"""Core knowledge service: ingestion orchestration + similarity search."""

import asyncio
import os
import uuid
from typing import Optional

from supabase import Client, create_client

from embeddings import embed_text, embed_batch
from knowledge_ingest.chunker import chunk_text
from knowledge_ingest.loaders_base import LoaderError

MIN_SCORE_DEFAULT = 0.75
CONFLICT_THRESHOLD = 0.05
MAX_CHUNKS_PER_USER = 50_000

_sb_client: Optional[Client] = None


def _supabase() -> Client:
    global _sb_client
    if _sb_client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        _sb_client = create_client(url, key)
    return _sb_client


class QuotaExceeded(Exception):
    pass


async def check_user_quota(user_id: str, new_chunks: int) -> None:
    sb = _supabase()
    res = sb.table("knowledge_chunks").select("id", count="exact").eq("user_id", user_id).execute()
    current = getattr(res, "count", 0) or 0
    if current + new_chunks > MAX_CHUNKS_PER_USER:
        raise QuotaExceeded(
            f"Quota exceeded: you have {current} chunks, this would add {new_chunks} "
            f"(limit {MAX_CHUNKS_PER_USER}). Delete some documents first."
        )


async def search_knowledge(
    query: str,
    user_id: str,
    meeting_id: Optional[str] = None,
    k: int = 5,
    min_score: float = MIN_SCORE_DEFAULT,
) -> list[dict]:
    """Embed query, run pgvector similarity search, return matches with conflict flag."""
    query_vec = await embed_text(query)
    sb = _supabase()
    resp = sb.rpc(
        "knowledge_search",
        {
            "query_embedding": query_vec,
            "caller_user_id": user_id,
            "meeting_filter": meeting_id,
            "match_limit": k,
            "min_score": min_score,
        },
    ).execute()
    rows = resp.data or []
    if len(rows) >= 2:
        top, second = rows[0], rows[1]
        if (
            top.get("doc_id") != second.get("doc_id")
            and abs((top.get("score") or 0) - (second.get("score") or 0)) < CONFLICT_THRESHOLD
        ):
            rows[0]["possible_conflict"] = True
    return rows


async def ingest_doc(doc_id: str, content: bytes | str, source_type: str, user_settings: dict) -> None:
    """Background worker. Loads → chunks → embeds → inserts.
    Updates status field at each phase. Never raises — errors written to error_message.
    """
    sb = _supabase()
    try:
        sb.table("knowledge_docs").update({"status": "processing"}).eq("id", doc_id).execute()

        doc_row = sb.table("knowledge_docs").select("*").eq("id", doc_id).single().execute().data
        if not doc_row:
            return
        user_id = doc_row["user_id"]

        if source_type == "pdf":
            from knowledge_ingest import pdf_loader
            loaded = await pdf_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "docx":
            from knowledge_ingest import docx_loader
            loaded = await docx_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "txt":
            from knowledge_ingest import text_loader
            loaded = await text_loader.load(content if isinstance(content, bytes) else content.encode())
        elif source_type == "url":
            from knowledge_ingest import url_loader
            loaded = await url_loader.load(content if isinstance(content, str) else content.decode())
        elif source_type == "notion":
            from knowledge_ingest import notion_loader
            token = user_settings.get("notion_access_token", "")
            loaded = await notion_loader.load(content if isinstance(content, str) else content.decode(), token=token)
        elif source_type == "gdrive":
            from knowledge_ingest import gdrive_loader
            token = user_settings.get("google_access_token", "")
            loaded = await gdrive_loader.load(content if isinstance(content, str) else content.decode(), token=token)
        else:
            raise LoaderError(f"Unknown source_type: {source_type}")

        base_meta = (loaded.page_metadata or [{}])[0]
        chunks = chunk_text(loaded.text, base_metadata=base_meta)

        await check_user_quota(user_id, len(chunks))

        contents = [c["content"] for c in chunks]
        vectors = await embed_batch(contents)

        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "content": chunks[i]["content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
        if rows:
            sb.table("knowledge_chunks").insert(rows).execute()

        sb.table("knowledge_docs").update({
            "status": "ready",
            "chunk_count": len(rows),
            "last_synced_at": "now()",
            "error_message": None,
        }).eq("id", doc_id).execute()

    except LoaderError as exc:
        sb.table("knowledge_docs").update({
            "status": "error", "error_message": str(exc),
        }).eq("id", doc_id).execute()
    except QuotaExceeded as exc:
        sb.table("knowledge_docs").update({
            "status": "error", "error_message": str(exc),
        }).eq("id", doc_id).execute()
    except Exception as exc:
        sb.table("knowledge_docs").update({
            "status": "error", "error_message": f"Unexpected error: {str(exc)[:200]}",
        }).eq("id", doc_id).execute()


async def soft_delete_doc(doc_id: str, user_id: str) -> None:
    sb = _supabase()
    sb.table("knowledge_docs").update({"deleted_at": "now()"}).eq("id", doc_id).eq("user_id", user_id).execute()
```

- [ ] **Step 4.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_knowledge_service -v
```

- [ ] **Step 4.5: Commit**

```bash
git add backend/knowledge_service.py backend/tests/test_knowledge_service.py
git commit -m "feat(knowledge): add core service with ingestion + similarity search + conflict detection"
```

---

## Task 5: knowledge_routes REST API

**Files:**
- Create: `backend/knowledge_routes.py`
- Modify: `backend/main.py` (register router — one line)
- Test: `backend/tests/test_knowledge_routes.py`

- [ ] **Step 5.1: Write failing test**

Create `backend/tests/test_knowledge_routes.py`:

```python
import importlib
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase
fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)


class KnowledgeRoutesTests(unittest.TestCase):
    def _app(self):
        auth = importlib.import_module("auth")
        kr = importlib.import_module("knowledge_routes")
        importlib.reload(kr)
        app = FastAPI()
        app.include_router(kr.router)
        # Override require_user_id
        app.dependency_overrides[auth.require_user_id] = lambda: str(uuid.uuid4())
        return app, kr

    def test_upload_url_creates_doc_and_schedules_ingest(self):
        app, kr = self._app()
        client = TestClient(app)

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "doc-1"}]
        mock_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value.data = []

        with patch.object(kr, "_supabase", lambda: mock_sb):
            with patch.object(kr, "_user_settings", new=AsyncMock(return_value={})):
                resp = client.post("/knowledge/upload-url", json={"url": "https://example.com"})

        self.assertEqual(resp.status_code, 200)
        self.assertIn("doc_id", resp.json())

    def test_list_docs_returns_filtered_results(self):
        app, kr = self._app()
        client = TestClient(app)

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.execute.return_value.data = [
            {"id": "d1", "name": "test.pdf", "status": "ready"},
        ]
        with patch.object(kr, "_supabase", lambda: mock_sb):
            resp = client.get("/knowledge/docs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["docs"]), 1)

    def test_delete_doc_calls_soft_delete(self):
        app, kr = self._app()
        client = TestClient(app)

        async def fake_soft(doc_id, user_id):
            fake_soft.called = (doc_id, user_id)

        fake_soft.called = None

        with patch.object(kr, "soft_delete_doc", new=fake_soft):
            resp = client.delete("/knowledge/docs/doc-id-abc")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fake_soft.called[0], "doc-id-abc")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_knowledge_routes -v
```

- [ ] **Step 5.3: Implement knowledge_routes**

Create `backend/knowledge_routes.py`:

```python
"""Knowledge Base REST API."""

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from auth import require_user_id, supabase as auth_supabase
from knowledge_service import (
    ingest_doc,
    soft_delete_doc,
    search_knowledge,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_EXT = {"pdf", "docx", "txt", "md"}


def _supabase():
    return auth_supabase


async def _user_settings(user_id: str) -> dict:
    sb = _supabase()
    row = sb.table("user_settings").select("*").eq("user_id", user_id).single().execute().data
    return row or {}


class UploadUrlRequest(BaseModel):
    url: str
    meeting_id: Optional[str] = None
    sensitivity: str = "internal"


class ConnectSourceRequest(BaseModel):
    source_type: str  # 'notion' | 'gdrive'
    source_id: str
    name: str
    meeting_id: Optional[str] = None
    sensitivity: str = "internal"


class UpdateDocRequest(BaseModel):
    name: Optional[str] = None
    sensitivity: Optional[str] = None
    meeting_id: Optional[str] = None


def _insert_doc_row(sb, *, user_id: str, name: str, source_type: str,
                    source_url: Optional[str] = None, file_path: Optional[str] = None,
                    size_bytes: Optional[int] = None, meeting_id: Optional[str] = None,
                    sensitivity: str = "internal") -> str:
    doc_id = str(uuid.uuid4())
    sb.table("knowledge_docs").insert({
        "id": doc_id,
        "user_id": user_id,
        "name": name,
        "source_type": source_type,
        "source_url": source_url,
        "file_path": file_path,
        "size_bytes": size_bytes,
        "meeting_id": meeting_id,
        "sensitivity": sensitivity,
        "status": "processing",
    }).execute()
    return doc_id


@router.post("/upload")
async def upload_file(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    meeting_id: Optional[str] = Form(None),
    sensitivity: str = Form("internal"),
    user_id: str = Depends(require_user_id),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FILE_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    source_type = "pdf" if ext == "pdf" else "docx" if ext == "docx" else "txt"
    sb = _supabase()

    file_path = f"{user_id}/{uuid.uuid4()}.{ext}"
    sb.storage.from_("knowledge").upload(file_path, content, {"content-type": file.content_type or "application/octet-stream"})

    doc_id = _insert_doc_row(
        sb, user_id=user_id, name=file.filename or "Untitled",
        source_type=source_type, file_path=file_path, size_bytes=len(content),
        meeting_id=meeting_id, sensitivity=sensitivity,
    )

    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, content, source_type, settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.post("/upload-url")
async def upload_url(req: UploadUrlRequest, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    doc_id = _insert_doc_row(
        sb, user_id=user_id, name=req.url, source_type="url",
        source_url=req.url, meeting_id=req.meeting_id, sensitivity=req.sensitivity,
    )
    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, req.url, "url", settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.post("/connect-source")
async def connect_source(req: ConnectSourceRequest, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    if req.source_type not in ("notion", "gdrive"):
        raise HTTPException(status_code=400, detail="source_type must be 'notion' or 'gdrive'")
    sb = _supabase()
    doc_id = _insert_doc_row(
        sb, user_id=user_id, name=req.name, source_type=req.source_type,
        source_url=req.source_id, meeting_id=req.meeting_id, sensitivity=req.sensitivity,
    )
    settings = await _user_settings(user_id)
    background.add_task(ingest_doc, doc_id, req.source_id, req.source_type, settings)
    return {"doc_id": doc_id, "status": "processing"}


@router.get("/docs")
async def list_docs(meeting_id: Optional[str] = None, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    q = sb.table("knowledge_docs").select("*").eq("user_id", user_id).is_("deleted_at", "null")
    if meeting_id:
        q = q.eq("meeting_id", meeting_id)
    rows = q.order("created_at", desc=True).execute().data or []
    return {"docs": rows}


@router.patch("/docs/{doc_id}")
async def update_doc(doc_id: str, req: UpdateDocRequest, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    update = {k: v for k, v in req.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    sb.table("knowledge_docs").update(update).eq("id", doc_id).eq("user_id", user_id).execute()
    return {"ok": True}


@router.delete("/docs/{doc_id}")
async def delete_doc(doc_id: str, user_id: str = Depends(require_user_id)):
    await soft_delete_doc(doc_id, user_id)
    return {"ok": True}


@router.post("/docs/{doc_id}/resync")
async def resync_doc(doc_id: str, background: BackgroundTasks, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    doc = sb.table("knowledge_docs").select("*").eq("id", doc_id).eq("user_id", user_id).single().execute().data
    if not doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    settings = await _user_settings(user_id)
    # Delete old chunks atomically
    sb.table("knowledge_chunks").delete().eq("doc_id", doc_id).execute()
    sb.table("knowledge_docs").update({"status": "processing"}).eq("id", doc_id).execute()

    src = doc["source_type"]
    if src in ("url", "notion", "gdrive"):
        content = doc.get("source_url") or ""
    else:
        # Re-download from storage
        file_path = doc["file_path"]
        content = sb.storage.from_("knowledge").download(file_path)
    background.add_task(ingest_doc, doc_id, content, src, settings)
    return {"ok": True}


@router.get("/queries")
async def list_queries(bot_id: Optional[str] = None, limit: int = 50, user_id: str = Depends(require_user_id)):
    sb = _supabase()
    q = sb.table("knowledge_queries").select("*").eq("user_id", user_id)
    if bot_id:
        q = q.eq("bot_id", bot_id)
    rows = q.order("created_at", desc=True).limit(limit).execute().data or []
    return {"queries": rows}
```

- [ ] **Step 5.4: Register router in `main.py`**

Open `backend/main.py`. Locate the section where existing routers are included. Add:

```python
from knowledge_routes import router as knowledge_router
app.include_router(knowledge_router)
```

(Place this near the other `app.include_router(...)` calls.)

- [ ] **Step 5.5: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_knowledge_routes -v
```

- [ ] **Step 5.6: Commit**

```bash
git add backend/knowledge_routes.py backend/tests/test_knowledge_routes.py backend/main.py
git commit -m "feat(knowledge): add REST API for upload, list, update, delete, resync"
```

---

## Task 6: knowledge_lookup tool

**Files:**
- Create: `backend/tools/knowledge_lookup.py`
- Test: `backend/tests/test_knowledge_lookup_tool.py`

- [ ] **Step 6.1: Write failing test**

Create `backend/tests/test_knowledge_lookup_tool.py`:

```python
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)


class KnowledgeLookupToolTests(unittest.TestCase):
    def test_returns_matches_with_strict_instruction(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(query, user_id, meeting_id=None, k=5, min_score=0.75):
            return [{
                "doc_name": "Budget.pdf", "content": "Q2 budget is $50,000",
                "score": 0.92, "metadata": {"page": 3}, "doc_id": "d1",
                "sensitivity": "internal", "source_type": "pdf",
            }]

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "what's the budget", "user_id": "u1"},
                    user_settings={},
                ))

        self.assertIn("matches", result)
        self.assertEqual(len(result["matches"]), 1)
        self.assertIn("Answer ONLY", result["instruction"])
        self.assertIn("doc_name", result["instruction"])

    def test_returns_no_match_when_empty(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(*a, **k): return []

        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "unknown", "user_id": "u1"},
                    user_settings={},
                ))

        self.assertTrue(result.get("no_match"))
        self.assertIn("web_search", result.get("next_step", ""))

    def test_conflict_instruction_present_when_flagged(self):
        import importlib
        kl = importlib.import_module("tools.knowledge_lookup")
        importlib.reload(kl)

        async def fake_search(*a, **k):
            return [
                {"doc_name": "Q1.pdf", "content": "Enterprise", "score": 0.90,
                 "metadata": {}, "doc_id": "d1", "possible_conflict": True,
                 "sensitivity": "internal", "source_type": "pdf"},
                {"doc_name": "Q2.pdf", "content": "SMB", "score": 0.88,
                 "metadata": {}, "doc_id": "d2",
                 "sensitivity": "internal", "source_type": "pdf"},
            ]
        with patch.object(kl, "search_knowledge", new=fake_search):
            with patch.object(kl, "_log_query", new=AsyncMock()):
                result = asyncio.run(kl.knowledge_lookup(
                    {"query": "strategy", "user_id": "u1"},
                    user_settings={},
                ))
        self.assertIn("conflict", result["instruction"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_knowledge_lookup_tool -v
```

- [ ] **Step 6.3: Implement knowledge_lookup**

Create `backend/tools/knowledge_lookup.py`:

```python
"""knowledge_lookup tool — retrieves grounding chunks from the user's knowledge base."""

from typing import Optional

from auth import supabase as auth_supabase
from knowledge_service import search_knowledge

from .registry import register_tool


STRICT_INSTRUCTION = (
    "Answer ONLY using the content in `matches` above. "
    "When you answer, cite the source by saying \"According to {doc_name}: ...\". "
    "If the matches do not contain the answer, respond with exactly the token "
    "NO_GROUNDED_ANSWER so the system can fall back to web_search. "
    "Do not synthesize, infer, or guess beyond the provided content."
)

CONFLICT_INSTRUCTION = (
    " IMPORTANT: Multiple documents may contain conflicting information. "
    "If the matches disagree, present BOTH views with their respective doc_name "
    "and any date metadata. Do NOT pick one — let the user decide."
)


async def _log_query(user_id: str, bot_id: Optional[str], query: str,
                     matched_doc: Optional[str], match_score: Optional[float],
                     fallback: Optional[str]) -> None:
    try:
        auth_supabase.table("knowledge_queries").insert({
            "user_id": user_id,
            "bot_id": bot_id,
            "query_text": query[:500],
            "matched_doc": matched_doc,
            "match_score": match_score,
            "fallback": fallback,
        }).execute()
    except Exception:
        pass  # audit log never breaks the request


async def knowledge_lookup(args: dict, user_settings: Optional[dict] = None) -> dict:
    query = (args.get("query") or "").strip()
    user_id = args.get("user_id") or (user_settings or {}).get("user_id", "")
    meeting_id = args.get("meeting_id")
    bot_id = args.get("bot_id")
    if not query or not user_id:
        return {"error": "Both query and user_id are required"}

    matches = await search_knowledge(query, user_id, meeting_id=meeting_id, k=5, min_score=0.75)

    if not matches:
        await _log_query(user_id, bot_id, query, None, None, None)
        return {
            "no_match": True,
            "next_step": "Call web_search with this query. If web_search also fails, "
                         "compose a brief question to ask the meeting participants directly.",
        }

    has_conflict = any(m.get("possible_conflict") for m in matches)
    instruction = STRICT_INSTRUCTION + (CONFLICT_INSTRUCTION if has_conflict else "")

    top = matches[0]
    await _log_query(user_id, bot_id, query, top.get("doc_id"), top.get("score"), None)

    formatted = [
        {
            "doc_name": m.get("doc_name"),
            "content": m.get("content"),
            "source_type": m.get("source_type"),
            "score": round(float(m.get("score") or 0), 3),
            "metadata": m.get("metadata") or {},
        }
        for m in matches
    ]
    return {"matches": formatted, "instruction": instruction}


register_tool(
    name="knowledge_lookup",
    description=(
        "Look up information in the user's uploaded knowledge base "
        "(PDFs, documents, web pages, Notion, Google Drive). Use this FIRST when the "
        "user asks a factual question that might be in their documents. Returns "
        "matched content with source citations. If no match, falls back to web_search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The user's question or the topic to look up."},
        },
        "required": ["query"],
    },
    handler=knowledge_lookup,
    requires=None,
    confirm=False,
)
```

- [ ] **Step 6.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_knowledge_lookup_tool -v
```

- [ ] **Step 6.5: Commit**

```bash
git add backend/tools/knowledge_lookup.py backend/tests/test_knowledge_lookup_tool.py
git commit -m "feat(knowledge): add knowledge_lookup tool with strict grounding + conflict handling"
```

---

## Task 7: web_search tool

**Files:**
- Create: `backend/tools/web_search.py`
- Test: `backend/tests/test_web_search_tool.py`

- [ ] **Step 7.1: Write failing test**

Create `backend/tests/test_web_search_tool.py`:

```python
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _fake_resp(status, data):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    return r


class WebSearchToolTests(unittest.TestCase):
    def test_returns_top_results(self):
        import importlib
        ws = importlib.import_module("tools.web_search")
        importlib.reload(ws)

        async def fake_post(self, url, *a, **k):
            return _fake_resp(200, {"results": [
                {"title": "T1", "url": "https://a.com", "content": "Content A"},
                {"title": "T2", "url": "https://b.com", "content": "Content B"},
                {"title": "T3", "url": "https://c.com", "content": "Content C"},
            ]})

        with patch.object(ws, "TAVILY_API_KEY", "fake"):
            with patch("httpx.AsyncClient.post", new=fake_post):
                with patch.object(ws, "_log_query", new=AsyncMock()):
                    result = asyncio.run(ws.web_search(
                        {"query": "what is X", "user_id": "u1"}, user_settings={}
                    ))

        self.assertEqual(len(result["results"]), 3)
        self.assertIn("Cite", result["instruction"])

    def test_returns_error_when_tavily_missing(self):
        import importlib
        ws = importlib.import_module("tools.web_search")
        importlib.reload(ws)
        with patch.object(ws, "TAVILY_API_KEY", ""):
            result = asyncio.run(ws.web_search({"query": "q", "user_id": "u"}, user_settings={}))
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_web_search_tool -v
```

- [ ] **Step 7.3: Implement web_search**

Create `backend/tools/web_search.py`:

```python
"""web_search tool — Tavily fallback when the knowledge base has no match."""

import os
from typing import Optional

import httpx

from auth import supabase as auth_supabase

from .registry import register_tool

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

INSTRUCTION = (
    "Answer using ONLY the snippets in `results` above. "
    "Cite the URL inline like \"(source: https://...)\". "
    "If the results don't contain the answer, respond with exactly NO_WEB_ANSWER "
    "so the system can ask the meeting participants directly."
)


async def _log_query(user_id: str, bot_id: Optional[str], query: str) -> None:
    try:
        auth_supabase.table("knowledge_queries").insert({
            "user_id": user_id,
            "bot_id": bot_id,
            "query_text": query[:500],
            "fallback": "web_search",
        }).execute()
    except Exception:
        pass


async def web_search(args: dict, user_settings: Optional[dict] = None) -> dict:
    if not TAVILY_API_KEY:
        return {"error": "Web search is not configured (TAVILY_API_KEY missing)"}

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}

    user_id = args.get("user_id") or (user_settings or {}).get("user_id", "")
    bot_id = args.get("bot_id")

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": 3,
        "include_answer": False,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(TAVILY_SEARCH_URL, json=payload)

    if resp.status_code != 200:
        return {"error": f"Web search failed ({resp.status_code})"}

    data = resp.json()
    items = data.get("results") or []
    if not items:
        return {"no_results": True, "next_step": "Compose a question for the meeting participants."}

    if user_id:
        await _log_query(user_id, bot_id, query)

    return {
        "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:1000]}
            for r in items[:3]
        ],
        "instruction": INSTRUCTION,
    }


register_tool(
    name="web_search",
    description=(
        "Search the public web. Use this ONLY when knowledge_lookup returned "
        "NO_GROUNDED_ANSWER or no_match. Returns up to 3 results with citations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
        },
        "required": ["query"],
    },
    handler=web_search,
    requires=None,
    confirm=False,
)
```

- [ ] **Step 7.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_web_search_tool -v
```

- [ ] **Step 7.5: Commit**

```bash
git add backend/tools/web_search.py backend/tests/test_web_search_tool.py
git commit -m "feat(knowledge): add web_search tool with Tavily integration"
```

---

## Task 8: Register tools

**Files:**
- Modify: `backend/tools/__init__.py`

- [ ] **Step 8.1: Inspect current __init__.py**

```bash
cat backend/tools/__init__.py
```

- [ ] **Step 8.2: Add import lines**

Open `backend/tools/__init__.py` and append at the bottom:

```python
# Knowledge base tools (auto-register on import)
from . import knowledge_lookup  # noqa: F401
from . import web_search  # noqa: F401
```

- [ ] **Step 8.3: Verify registration**

```bash
cd backend && python -c "
import tools
from tools.registry import get_available_tools
names = [t['function']['name'] for t in get_available_tools({})]
print('Registered:', names)
assert 'knowledge_lookup' in names
assert 'web_search' in names
print('OK')
"
```

Expected: prints `OK` and shows both tool names in the list.

- [ ] **Step 8.4: Commit**

```bash
git add backend/tools/__init__.py
git commit -m "feat(knowledge): register knowledge_lookup and web_search tools"
```

---

## Task 9: knowledge_proactive module

**Files:**
- Create: `backend/knowledge_proactive.py`
- Test: `backend/tests/test_knowledge_proactive.py`

- [ ] **Step 9.1: Write failing test**

Create `backend/tests/test_knowledge_proactive.py`:

```python
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *_a, **_k: None
fake_supabase.Client = object
sys.modules.setdefault("supabase", fake_supabase)


def _state(transcript_lines, **extra):
    s = {
        "transcript_lines": transcript_lines,
        "user_id": "user-1",
        "meeting_id": "meet-1",
        "processing": False,
    }
    s.update(extra)
    return s


class KnowledgeProactiveTests(unittest.TestCase):
    def test_skips_when_processing_flag_set(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        called = []
        with patch.object(kp, "search_knowledge", new=AsyncMock(side_effect=lambda *a, **k: called.append(1) or [])):
            asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state(["a"], processing=True)))
        self.assertEqual(called, [])

    def test_skips_when_no_match_above_threshold(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        posted = []
        with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=[])):
            with patch.object(kp, "_post_chat", new=AsyncMock(side_effect=lambda *a, **k: posted.append(a))):
                asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state(["line " + str(i) for i in range(15)])))
        self.assertEqual(posted, [])

    def test_posts_when_match_passes_all_gates(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "Strategy.pdf",
            "content": "Focus on enterprise customers in Q2.",
            "score": 0.91, "sensitivity": "public", "metadata": {},
        }]
        with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
            with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state([f"l{i}" for i in range(15)])))
        mock_post.assert_awaited_once()

    def test_dedupe_skips_repeat_within_window(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "S.pdf", "content": "X",
            "score": 0.91, "sensitivity": "public", "metadata": {},
        }]
        with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
            with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                state = _state([f"l{i}" for i in range(15)])
                asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", state))
                asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", state))
        self.assertEqual(mock_post.await_count, 1)

    def test_filters_confidential_docs(self):
        import importlib
        kp = importlib.import_module("knowledge_proactive")
        importlib.reload(kp)
        kp._dedupe_cache.clear()
        kp._doc_cooldown.clear()

        match = [{
            "doc_id": "d1", "doc_name": "Secret.pdf", "content": "X",
            "score": 0.95, "sensitivity": "confidential", "meeting_id": None, "metadata": {},
        }]
        with patch.object(kp, "search_knowledge", new=AsyncMock(return_value=match)):
            with patch.object(kp, "_post_chat", new=AsyncMock()) as mock_post:
                asyncio.run(kp.maybe_proactive_knowledge_check("bot-1", _state([f"l{i}" for i in range(15)])))
        mock_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 9.2: Run to verify fail**

```bash
cd backend && python -m unittest tests.test_knowledge_proactive -v
```

- [ ] **Step 9.3: Implement knowledge_proactive**

Create `backend/knowledge_proactive.py`:

```python
"""Proactive knowledge surfacing. Called from _compress_and_persist (one hook)."""

import hashlib
import time
from typing import Optional

from knowledge_service import search_knowledge

PROACTIVE_MIN_SCORE = 0.85
DEDUPE_WINDOW_SECONDS = 60
DOC_COOLDOWN_SECONDS = 600  # 10 minutes
LAST_N_LINES = 10

_dedupe_cache: dict[str, tuple[str, float]] = {}  # bot_id -> (window_hash, ts)
_doc_cooldown: dict[tuple[str, str], float] = {}  # (bot_id, doc_id) -> last_surfaced_at


def _window_hash(lines: list[str]) -> str:
    joined = "\n".join(lines[-LAST_N_LINES:])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _allowed_by_sensitivity(match: dict, meeting_id: Optional[str]) -> bool:
    sens = match.get("sensitivity", "internal")
    if sens == "public":
        return True
    if sens == "confidential":
        return False
    # internal: only when pinned to this meeting
    return match.get("meeting_id") == meeting_id and meeting_id is not None


async def _post_chat(bot_id: str, message: str) -> None:
    # Lazy import to avoid pulling realtime_routes at module load time
    try:
        from realtime_routes import _send_chat_response
        await _send_chat_response(bot_id, message)
    except Exception as exc:
        print(f"[proactive-knowledge] failed to post for {bot_id}: {exc}")


async def maybe_proactive_knowledge_check(bot_id: str, state: dict) -> None:
    """Top-level entry. Runs all gates, posts to meeting chat if a match passes."""
    if state.get("processing"):
        return

    lines = state.get("transcript_lines") or []
    if len(lines) < LAST_N_LINES:
        return

    user_id = state.get("user_id")
    meeting_id = state.get("meeting_id")
    if not user_id:
        return

    now = time.time()

    # Dedupe gate
    wh = _window_hash(lines)
    prev = _dedupe_cache.get(bot_id)
    if prev and prev[0] == wh and (now - prev[1]) < DEDUPE_WINDOW_SECONDS:
        return
    _dedupe_cache[bot_id] = (wh, now)

    query_text = "\n".join(lines[-LAST_N_LINES:])
    try:
        matches = await search_knowledge(query_text, user_id, meeting_id=meeting_id,
                                         k=3, min_score=PROACTIVE_MIN_SCORE)
    except Exception as exc:
        print(f"[proactive-knowledge] search failed for {bot_id}: {exc}")
        return

    for m in matches:
        doc_id = m.get("doc_id")
        if not doc_id:
            continue

        if not _allowed_by_sensitivity(m, meeting_id):
            continue

        last = _doc_cooldown.get((bot_id, doc_id), 0.0)
        if (now - last) < DOC_COOLDOWN_SECONDS:
            continue

        _doc_cooldown[(bot_id, doc_id)] = now

        snippet = (m.get("content") or "").strip().replace("\n", " ")
        if len(snippet) > 200:
            snippet = snippet[:200].rsplit(" ", 1)[0] + "…"
        message = f"💡 From {m.get('doc_name')}: {snippet}\n(Say \"Prism, more\" for details.)"
        await _post_chat(bot_id, message)
        return  # one proactive surfacing per check window
```

- [ ] **Step 9.4: Run to verify pass**

```bash
cd backend && python -m unittest tests.test_knowledge_proactive -v
```

- [ ] **Step 9.5: Commit**

```bash
git add backend/knowledge_proactive.py backend/tests/test_knowledge_proactive.py
git commit -m "feat(knowledge): add proactive surfacing with sensitivity + cooldown gates"
```

---

## Task 10: Hook into realtime_routes.py (THE ONE TOUCH)

**Files:**
- Modify: `backend/realtime_routes.py` (inside `_compress_and_persist` only)

- [ ] **Step 10.1: Locate the hook point**

```bash
grep -n "_compress_and_persist" backend/realtime_routes.py | head -5
```

Open `backend/realtime_routes.py` and find the `_compress_and_persist` function. Find the last line of the function body (after compression + persistence has completed).

- [ ] **Step 10.2: Add the hook**

Inside `_compress_and_persist`, immediately before the final `return` (or at the very end if there is no return), add:

```python
    # Proactive knowledge check — additive, isolated, never raises
    try:
        from knowledge_proactive import maybe_proactive_knowledge_check
        await maybe_proactive_knowledge_check(bot_id, state)
    except Exception as exc:
        print(f"[proactive-knowledge] hook error for {bot_id}: {exc}")
```

The try/except guarantees the existing flow keeps working even if `knowledge_proactive` is missing or raises.

- [ ] **Step 10.3: Verify the bot still starts cleanly**

```bash
cd backend && python -c "import realtime_routes; print('realtime_routes import OK')"
```

Expected: `realtime_routes import OK`. If you see a NameError or ImportError, the hook was inserted in the wrong scope — revert and place it inside `_compress_and_persist` only.

- [ ] **Step 10.4: Run the full backend test suite**

```bash
cd backend && python -m unittest discover tests -v
```

Expected: all existing tests still pass, plus all new knowledge tests pass.

- [ ] **Step 10.5: Commit**

```bash
git add backend/realtime_routes.py
git commit -m "feat(knowledge): hook proactive knowledge check into _compress_and_persist"
```

---

## Task 11: Frontend — Knowledge Base page

**Files:**
- Create: `frontend/src/lib/knowledge.js`
- Create: `frontend/src/components/KnowledgeBase.jsx`
- Create: `frontend/src/components/KnowledgeUploadModal.jsx`
- Create: `frontend/src/components/KnowledgeDocCard.jsx`
- Modify: `frontend/src/App.jsx` (add route + nav link)

- [ ] **Step 11.1: Create API client**

Create `frontend/src/lib/knowledge.js`:

```javascript
import { apiFetch } from './api'

export async function listDocs({ meetingId } = {}) {
  const qs = meetingId ? `?meeting_id=${encodeURIComponent(meetingId)}` : ''
  const r = await apiFetch(`/knowledge/docs${qs}`)
  return r.docs || []
}

export async function uploadFile(file, { meetingId, sensitivity = 'internal' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (meetingId) form.append('meeting_id', meetingId)
  form.append('sensitivity', sensitivity)
  return apiFetch('/knowledge/upload', { method: 'POST', body: form })
}

export async function uploadUrl(url, { meetingId, sensitivity = 'internal' } = {}) {
  return apiFetch('/knowledge/upload-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, meeting_id: meetingId, sensitivity }),
  })
}

export async function connectSource({ sourceType, sourceId, name, meetingId, sensitivity = 'internal' }) {
  return apiFetch('/knowledge/connect-source', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_type: sourceType, source_id: sourceId, name,
      meeting_id: meetingId, sensitivity,
    }),
  })
}

export async function updateDoc(docId, patch) {
  return apiFetch(`/knowledge/docs/${docId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export async function deleteDoc(docId) {
  return apiFetch(`/knowledge/docs/${docId}`, { method: 'DELETE' })
}

export async function resyncDoc(docId) {
  return apiFetch(`/knowledge/docs/${docId}/resync`, { method: 'POST' })
}
```

- [ ] **Step 11.2: Create KnowledgeDocCard**

Create `frontend/src/components/KnowledgeDocCard.jsx`:

```jsx
import { FileText, Globe, RefreshCw, Trash2 } from 'lucide-react'
import { deleteDoc, resyncDoc, updateDoc } from '../lib/knowledge'

const SENSITIVITY_COLOR = {
  public: 'text-emerald-300 bg-emerald-500/10',
  internal: 'text-sky-300 bg-sky-500/10',
  confidential: 'text-rose-300 bg-rose-500/10',
}

const STATUS_LABEL = {
  processing: 'Processing…',
  ready: 'Ready',
  error: 'Error',
  stale: 'Stale',
}

export default function KnowledgeDocCard({ doc, onChange }) {
  const Icon = doc.source_type === 'url' ? Globe : FileText

  const handleDelete = async () => {
    if (!confirm(`Delete "${doc.name}"?`)) return
    await deleteDoc(doc.id)
    onChange?.()
  }

  const handleResync = async () => {
    await resyncDoc(doc.id)
    onChange?.()
  }

  const handleSensitivity = async (e) => {
    await updateDoc(doc.id, { sensitivity: e.target.value })
    onChange?.()
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className="h-4 w-4 text-cyan-200/70 flex-shrink-0" />
          <span className="text-sm font-medium text-white truncate">{doc.name}</span>
        </div>
        <span className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wider ${SENSITIVITY_COLOR[doc.sensitivity] || ''}`}>
          {doc.sensitivity}
        </span>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-white/50">
        <span>{STATUS_LABEL[doc.status] || doc.status}</span>
        <span>·</span>
        <span>{doc.chunk_count} chunks</span>
        {doc.meeting_id && <><span>·</span><span>Pinned</span></>}
      </div>
      {doc.error_message && (
        <p className="text-[11px] text-rose-300/80">{doc.error_message}</p>
      )}
      <div className="flex items-center gap-2 pt-1">
        <select
          value={doc.sensitivity}
          onChange={handleSensitivity}
          className="rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/80"
        >
          <option value="public">Public</option>
          <option value="internal">Internal</option>
          <option value="confidential">Confidential</option>
        </select>
        <button onClick={handleResync} className="rounded border border-white/10 bg-white/5 p-1 hover:text-cyan-300">
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
        <button onClick={handleDelete} className="rounded border border-white/10 bg-white/5 p-1 hover:text-rose-300">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 11.3: Create KnowledgeUploadModal**

Create `frontend/src/components/KnowledgeUploadModal.jsx`:

```jsx
import { useState } from 'react'
import { X, Upload, Link as LinkIcon, FileText } from 'lucide-react'
import { uploadFile, uploadUrl, connectSource } from '../lib/knowledge'

export default function KnowledgeUploadModal({ open, onClose, meetingId, onUploaded }) {
  const [tab, setTab] = useState('file')
  const [url, setUrl] = useState('')
  const [notionId, setNotionId] = useState('')
  const [notionName, setNotionName] = useState('')
  const [sensitivity, setSensitivity] = useState('internal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!open) return null

  const close = () => { setError(null); setBusy(false); onClose() }

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true); setError(null)
    try {
      await uploadFile(file, { meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  const handleUrl = async () => {
    if (!url.trim()) return
    setBusy(true); setError(null)
    try {
      await uploadUrl(url.trim(), { meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Failed to ingest URL')
    } finally {
      setBusy(false)
    }
  }

  const handleNotion = async () => {
    if (!notionId.trim() || !notionName.trim()) return
    setBusy(true); setError(null)
    try {
      await connectSource({ sourceType: 'notion', sourceId: notionId.trim(), name: notionName.trim(), meetingId, sensitivity })
      onUploaded?.(); close()
    } catch (err) {
      setError(err?.message || 'Failed to connect Notion page')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#0c0a17] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Add to Knowledge Base</h3>
          <button onClick={close}><X className="h-4 w-4 text-white/60" /></button>
        </div>

        <div className="mb-4 flex gap-1 rounded-lg bg-white/5 p-1">
          {[
            { id: 'file', label: 'File', icon: Upload },
            { id: 'url', label: 'URL', icon: LinkIcon },
            { id: 'notion', label: 'Notion', icon: FileText },
          ].map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs ${tab === t.id ? 'bg-cyan-400/20 text-cyan-200' : 'text-white/60 hover:text-white'}`}
            >
              <t.icon className="h-3 w-3" /> {t.label}
            </button>
          ))}
        </div>

        <div className="mb-3 flex items-center gap-2 text-xs text-white/60">
          Sensitivity:
          <select value={sensitivity} onChange={e => setSensitivity(e.target.value)}
                  className="rounded border border-white/10 bg-white/5 px-2 py-1 text-white/80">
            <option value="public">Public</option>
            <option value="internal">Internal</option>
            <option value="confidential">Confidential</option>
          </select>
        </div>

        {tab === 'file' && (
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={handleFile} disabled={busy}
                 className="block w-full rounded border border-white/10 bg-white/5 p-3 text-sm text-white/80" />
        )}

        {tab === 'url' && (
          <div className="space-y-2">
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/article"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <button onClick={handleUrl} disabled={busy || !url.trim()}
                    className="w-full rounded bg-cyan-400 px-3 py-2 text-sm font-semibold text-[#07040f] disabled:opacity-40">
              {busy ? 'Ingesting…' : 'Add URL'}
            </button>
          </div>
        )}

        {tab === 'notion' && (
          <div className="space-y-2">
            <input value={notionName} onChange={e => setNotionName(e.target.value)} placeholder="Display name"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <input value={notionId} onChange={e => setNotionId(e.target.value)} placeholder="Notion page ID (UUID)"
                   className="w-full rounded border border-white/10 bg-white/5 px-3 py-2 text-sm text-white" />
            <p className="text-[11px] text-white/40">
              Paste the page ID from the Notion URL. Make sure the page is shared with your integration.
            </p>
            <button onClick={handleNotion} disabled={busy || !notionId.trim() || !notionName.trim()}
                    className="w-full rounded bg-cyan-400 px-3 py-2 text-sm font-semibold text-[#07040f] disabled:opacity-40">
              {busy ? 'Connecting…' : 'Add Notion Page'}
            </button>
          </div>
        )}

        {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
      </div>
    </div>
  )
}
```

- [ ] **Step 11.4: Create KnowledgeBase page**

Create `frontend/src/components/KnowledgeBase.jsx`:

```jsx
import { useEffect, useState, useCallback } from 'react'
import { Plus, BookOpen } from 'lucide-react'
import { listDocs } from '../lib/knowledge'
import KnowledgeDocCard from './KnowledgeDocCard'
import KnowledgeUploadModal from './KnowledgeUploadModal'

export default function KnowledgeBase({ meetingId } = {}) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listDocs({ meetingId })
      setDocs(list)
    } finally {
      setLoading(false)
    }
  }, [meetingId])

  useEffect(() => { refresh() }, [refresh])

  // Poll while any doc is processing
  useEffect(() => {
    if (!docs.some(d => d.status === 'processing')) return
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [docs, refresh])

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-cyan-300" />
          <h1 className="text-xl font-semibold text-white">Knowledge Base</h1>
        </div>
        <button onClick={() => setModalOpen(true)}
                className="flex items-center gap-1.5 rounded-lg bg-cyan-400 px-3 py-1.5 text-xs font-semibold text-[#07040f] hover:bg-cyan-300">
          <Plus className="h-3.5 w-3.5" /> Add Document
        </button>
      </div>

      {loading && docs.length === 0 ? (
        <p className="text-sm text-white/50">Loading…</p>
      ) : docs.length === 0 ? (
        <p className="text-sm text-white/50">No documents yet. Click "Add Document" to upload.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {docs.map(d => <KnowledgeDocCard key={d.id} doc={d} onChange={refresh} />)}
        </div>
      )}

      <KnowledgeUploadModal open={modalOpen} onClose={() => setModalOpen(false)}
                            meetingId={meetingId} onUploaded={refresh} />
    </div>
  )
}
```

- [ ] **Step 11.5: Wire route in App.jsx**

Open `frontend/src/App.jsx`. At the top, add the import:
```javascript
import KnowledgeBase from './components/KnowledgeBase'
```

Find the existing routing logic (look for `currentPage` or similar state). Add a `'knowledge'` case that renders `<KnowledgeBase />`. Then add a nav link in your sidebar/dashboard menu that sets the page to `'knowledge'`.

(The exact placement depends on existing routing — match the pattern used by other dashboard pages.)

- [ ] **Step 11.6: Manual smoke test**

```bash
cd frontend && npm run dev
```

In a separate terminal:
```bash
cd backend && uvicorn main:app --reload --port 8000
```

In the browser:
1. Log in
2. Navigate to Knowledge Base
3. Click "Add Document" → upload a PDF
4. Watch the card flip from "Processing…" to "Ready"
5. Check the chunk count is non-zero

- [ ] **Step 11.7: Commit**

```bash
git add frontend/src/components/KnowledgeBase.jsx frontend/src/components/KnowledgeUploadModal.jsx frontend/src/components/KnowledgeDocCard.jsx frontend/src/lib/knowledge.js frontend/src/App.jsx
git commit -m "feat(knowledge): add Knowledge Base UI with upload modal and doc cards"
```

---

## Task 12: Mid-meeting upload affordance

**Files:**
- Modify: `frontend/src/components/dashboard/MeetingView.jsx`

- [ ] **Step 12.1: Locate the meeting view file**

```bash
find frontend/src -name "MeetingView.jsx"
```

- [ ] **Step 12.2: Add a Pinned Documents panel**

In `MeetingView.jsx`, identify a logical section (sidebar or tab) for a new panel. Import:

```javascript
import { useState, useEffect, useCallback } from 'react'
import { Paperclip, Plus } from 'lucide-react'
import { listDocs } from '../../lib/knowledge'
import KnowledgeDocCard from '../KnowledgeDocCard'
import KnowledgeUploadModal from '../KnowledgeUploadModal'
```

Inside the component, add:

```javascript
const [pinnedDocs, setPinnedDocs] = useState([])
const [uploadOpen, setUploadOpen] = useState(false)

const refreshDocs = useCallback(async () => {
  if (!meetingId) return
  const list = await listDocs({ meetingId })
  setPinnedDocs(list)
}, [meetingId])

useEffect(() => { refreshDocs() }, [refreshDocs])

useEffect(() => {
  if (!pinnedDocs.some(d => d.status === 'processing')) return
  const id = setInterval(refreshDocs, 5000)
  return () => clearInterval(id)
}, [pinnedDocs, refreshDocs])
```

In the JSX, add a new section:

```jsx
<section className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
  <div className="mb-3 flex items-center justify-between">
    <div className="flex items-center gap-2">
      <Paperclip className="h-4 w-4 text-cyan-300" />
      <h3 className="text-sm font-semibold text-white">Pinned Documents</h3>
    </div>
    <button onClick={() => setUploadOpen(true)}
            className="flex items-center gap-1 rounded border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-white/80 hover:bg-white/10">
      <Plus className="h-3 w-3" /> Add
    </button>
  </div>
  {pinnedDocs.length === 0 ? (
    <p className="text-[11px] text-white/40">No documents pinned to this meeting.</p>
  ) : (
    <div className="space-y-2">
      {pinnedDocs.map(d => <KnowledgeDocCard key={d.id} doc={d} onChange={refreshDocs} />)}
    </div>
  )}
  <KnowledgeUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)}
                        meetingId={meetingId} onUploaded={refreshDocs} />
</section>
```

- [ ] **Step 12.3: Manual smoke test during a live meeting**

1. Start a meeting and invite Prism (bot joins).
2. Open the meeting view in PrismAI; locate the new "Pinned Documents" panel.
3. Click Add → upload a PDF.
4. Wait for status to flip to "Ready" (5–30 s).
5. In the meeting, say: "Prism, what does the document say about <topic>?"
6. Verify Prism answers with "According to <doc name>: …" in the meeting chat.

- [ ] **Step 12.4: Commit**

```bash
git add frontend/src/components/dashboard/MeetingView.jsx
git commit -m "feat(knowledge): mid-meeting document upload in meeting view"
```

---

## Final Verification Checklist

Run before declaring done. Each item is a literal user action with an observable expected outcome.

- [ ] **V1 — Privacy:** Upload doc with sensitivity=`confidential`, leave unpinned. Start a meeting. Verify proactive surfacing does NOT mention the doc even when topic matches.
- [ ] **V2 — Privacy:** Pin the same `confidential` doc to a meeting. Ask "Prism, what does <doc> say?" — confirm on-demand answer works.
- [ ] **V3 — Mid-meeting upload:** Start a meeting, then upload a PDF from MeetingView. Wait for "Ready". Ask Prism about its content. Confirm citation.
- [ ] **V4 — Soft delete:** During a search, delete a doc. Run another search — confirm no error, no broken citation.
- [ ] **V5 — Cost guard:** Upload a 60 MB file. Confirm error "File exceeds 50 MB limit".
- [ ] **V6 — Conflict detection:** Upload two contradicting docs ("Strategy: enterprise" vs "Strategy: SMB"). Ask Prism about strategy. Confirm BOTH are surfaced with `doc_name`s.
- [ ] **V7 — OAuth expiry:** Manually expire Google token in Supabase. Try to re-sync a gdrive doc. Confirm `status='error'` with "reconnect required".
- [ ] **V8 — Scanned PDF:** Upload a scanned (image-only) PDF. Confirm OCR fallback fires (logs show `ocr=True`); chunks are created.
- [ ] **V9 — Dynamic URL:** Paste a JS-rendered SPA URL. Confirm either content is extracted (Tavily) or clean LoaderError surfaces in UI.
- [ ] **V10 — No-match fallback:** Ask a question completely unrelated to any uploaded doc. Confirm bot calls `web_search` and answers with web citation.
- [ ] **V11 — Web also fails:** Ask a question that's unanswerable (e.g., "what did Alice say in yesterday's meeting?"). Confirm bot posts a clarifying question in meeting chat.
- [ ] **V12 — Hallucination guard:** Ask about an obscure detail. If matches are present but don't contain the answer, confirm bot says NO_GROUNDED_ANSWER → falls through to web_search rather than making something up.
- [ ] **V13 — Regression:** Run the full original test suite — `cd backend && python -m unittest discover tests -v`. Confirm all previously-passing tests still pass.
- [ ] **V14 — Existing bot flow:** Start a meeting without uploading any docs. Verify Prism's transcript capture, command processing, and proactive nudges all behave exactly as before.

---

## Spec Coverage Check

| Spec section | Tasks covering it |
|---|---|
| Document types (PDF/DOCX/TXT/URL/Notion/Drive) | 3a–3f |
| Per-user library + per-meeting pinning | 5 (routes), 11 (UI), 12 (mid-meeting) |
| On-demand lookup | 6 |
| Proactive surfacing | 9, 10 |
| In-meeting-chat "ask user" fallback | 6 (instruction returns NO_GROUNDED_ANSWER), 7 (returns NO_WEB_ANSWER) |
| Citation requirement | 6 (STRICT_INSTRUCTION) |
| Sensitivity tiers | Migration, 5 (PATCH), 9 (filter), 11 (UI) |
| Cost controls | 4 (quota), 5 (file size) |
| Conflict detection | 4 (CONFLICT_THRESHOLD), 6 (CONFLICT_INSTRUCTION) |
| OAuth expiry handling | 3e, 3f (LoaderError "reconnect") |
| Soft delete | 4, 5, migration |
| Audit log | 6, 7 (log_query) |

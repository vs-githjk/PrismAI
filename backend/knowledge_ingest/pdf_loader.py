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

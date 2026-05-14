"""Plain text / markdown loader."""

from .loaders_base import LoadedDoc, LoaderError


async def load(content: bytes) -> LoadedDoc:
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise LoaderError("File is empty.")
    return LoadedDoc(text=text, page_metadata=[{"page": 1}])

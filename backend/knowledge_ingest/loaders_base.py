"""Shared types for document loaders."""

from typing import NamedTuple


class LoadedDoc(NamedTuple):
    text: str
    page_metadata: list[dict]  # one dict per page or section


class LoaderError(Exception):
    """User-friendly error raised when a doc can't be loaded."""

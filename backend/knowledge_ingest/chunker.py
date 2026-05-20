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

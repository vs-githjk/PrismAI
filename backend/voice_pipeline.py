"""Streaming sentence segmentation + TTS dispatch policy.

Tests-only in PR-3. No integration with realtime_routes yet — that's PR-4.

Dependency note: pysbd is the rule-based segmenter used here. Last upstream
release was 2021; the project is feature-complete ("done"), not actively
developed. We pin the version in requirements.txt and accept the supply-chain
risk for an inactive but small, pure-Python dependency. If pysbd ever needs a
security update we'd have to fork or migrate; not a concern at our scale today.
"""

import pysbd


class StreamingSegmenter:
    """Incremental sentence segmenter for streamed LLM output.

    Re-segments the full growing buffer on every `feed()` and tracks committed
    sentence count (NOT byte cursor) so abbreviation/URL fixes inside the most
    recent sentence don't desync the cursor. Microseconds at typical reply
    sizes; don't optimize until profiled.

    `feed()` holds back the LAST sentence (it may still be growing); `flush()`
    releases it. `flush()` is naturally idempotent — once `_prev_count` has
    advanced past the end, the next call returns [].
    """

    def __init__(self):
        self._seg = pysbd.Segmenter(language="en", clean=False)
        self._buffer = ""
        self._prev_count = 0

    def feed(self, new_tokens: str) -> list[str]:
        if not new_tokens:
            return []
        self._buffer += new_tokens
        sentences = self._seg.segment(self._buffer)
        # Hold the last sentence — it may still be extending.
        if len(sentences) <= 1:
            return []
        committed_end = len(sentences) - 1
        new = [s.strip() for s in sentences[self._prev_count:committed_end]]
        self._prev_count = committed_end
        return [s for s in new if s]

    def flush(self) -> list[str]:
        sentences = self._seg.segment(self._buffer)
        new = [s.strip() for s in sentences[self._prev_count:]]
        self._prev_count = len(sentences)
        return [s for s in new if s]


class TtsDispatcher:
    """Concat-policy buffer: hold sentences until total ≥ min_chars, then emit.

    Applied uniformly — no special-case for the opener. The PR-4 soak decides
    whether we need a "first sentence escapes early" exception; until then,
    even the opener waits for the min_chars threshold.
    """

    def __init__(self, min_chars: int = 25):
        self.min_chars = min_chars
        self._buffer = ""

    def push(self, sentence: str) -> list[str]:
        sentence = (sentence or "").strip()
        if not sentence:
            return []
        if self._buffer:
            self._buffer = f"{self._buffer} {sentence}"
        else:
            self._buffer = sentence
        if len(self._buffer) >= self.min_chars:
            out = [self._buffer]
            self._buffer = ""
            return out
        return []

    def flush(self) -> list[str]:
        if not self._buffer:
            return []
        out = [self._buffer]
        self._buffer = ""
        return out

"""Per-bot utterance accumulator. Turns wire-level transcript chunks into
semantic utterances, bounded by speaker change, pause timeout, terminal
punctuation, or max-length cap.

Pure logic; async glue lives in realtime_routes.py.

──────────────────────────────────────────────────────────────────────────
THREAT-MODEL NOTE
──────────────────────────────────────────────────────────────────────────
Chunks reach this module from a webhook endpoint that accepts external
input. Callers MUST:
  • sanitize speaker_name (control chars + length cap) at the call site
  • use participant_id (Recall-assigned, stable) as the speaker_id —
    this is the load-bearing field for owner gating downstream
  • verify the bot_id at the route layer (token-in-URL) before invoking

──────────────────────────────────────────────────────────────────────────
CONCURRENCY
──────────────────────────────────────────────────────────────────────────
All entry points must be called under the bot's memory_lock. The class
is NOT internally synchronized.

`on_flush` MUST be non-blocking. Any I/O must be deferred via
asyncio.create_task in the caller's binding. A blocking on_flush will
block tick → next add_chunk → death spiral. The class catches and logs
exceptions from on_flush so a buggy callback can't crash the tick loop,
but it can't defend against on_flush HANGING.

──────────────────────────────────────────────────────────────────────────
KNOWN LIMITATIONS
──────────────────────────────────────────────────────────────────────────
1. Re-emission detection uses character-prefix overlap on normalized text.
   If Deepgram corrects a word EARLY in an utterance (e.g. "prasim" →
   "prism") mid-stream, the corrected chunk won't match prefix and will
   be appended, producing a duplicate fragment. This is the same blind
   spot the legacy 3s fuzzy dedup had — not a regression.

2. Pause threshold is measured against chunk ARRIVAL time, not audio
   time. A burst of delayed webhooks (network blip then catch-up) is
   correctly handled (chunks arrive within ms of each other → no flush).
   A long network gap appears as a long silence and may split an
   utterance prematurely.

3. Out-of-order chunks for the same speaker concatenate in arrival
   order, not audio-timestamp order. Recall webhooks are rarely
   out-of-order in practice; instrument and revisit if observed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional
import hashlib
import re
import time


# ── Tunables ──────────────────────────────────────────────────────────────
# All env overrides happen in the caller (realtime_routes); this module
# takes them as constructor args.
PAUSE_MS = 1200
PUNCT_GRACE_MS = 200
MAX_UTTERANCE_CHARS = 500
MAX_UTTERANCE_WORDS = 80
MAX_PENDING_SPEAKERS = 100  # DoS guard
# Multiplier applied to PAUSE_MS when the speaker's last chunk did NOT
# end in sentence-terminating punctuation. Speakers pause to think mid-
# thought; we should NOT prematurely flush an obviously-incomplete chunk
# like "...send the email to which". 2.0× gives an effective ~2.4s pause
# tolerance for mid-thought waits while keeping the post-sentence flush
# fast (1.2s).
INCOMPLETE_PAUSE_MULTIPLIER = 2.0

# Flush reason enum (open string — callers can extend)
REASON_PAUSE = "pause"
REASON_SPEAKER_CHANGE = "speaker_change"
REASON_PUNCT = "punct"
REASON_MAX_CHARS = "max_chars"
REASON_MAX_WORDS = "max_words"
REASON_FLUSH_ALL = "flush_all"


@dataclass
class PendingUtterance:
    """In-progress accumulation for a single speaker. Internal state of
    Accumulator; should not be exposed outside this module."""
    speaker_id: str
    speaker_name: str
    text: str = ""
    first_word_mono: float = 0.0
    last_word_mono: float = 0.0
    last_word_abs: str = ""
    word_count: int = 0
    chunk_count: int = 0
    punct_pending_since: Optional[float] = None
    # True if the most recent chunk ended in a sentence terminator
    # (`.`, `!`, `?`). False means the speaker is mid-thought (e.g.
    # "...send a mail to which"). tick() uses a longer pause threshold
    # when False so a brief thinking pause doesn't split one logical
    # command into two utterances.
    last_chunk_complete: bool = False


@dataclass
class FlushedUtterance:
    """A completed utterance, emitted to on_flush. This is the unit
    downstream consumers (transcript buffer, slow-path command dispatch,
    memory extraction) should operate on."""
    utterance_id: str       # stable hash; audit trail
    speaker_id: str         # load-bearing for owner gating
    speaker_name: str       # display only
    text: str
    word_count: int
    chunk_count: int
    duration_ms: int
    flush_reason: str


class Accumulator:
    def __init__(
        self,
        bot_id: str,
        on_flush: Callable[[FlushedUtterance], None],
        on_evicted: Optional[Callable[[str], None]] = None,
        pause_ms: int = PAUSE_MS,
        punct_grace_ms: int = PUNCT_GRACE_MS,
        max_chars: int = MAX_UTTERANCE_CHARS,
        max_words: int = MAX_UTTERANCE_WORDS,
        max_pending: int = MAX_PENDING_SPEAKERS,
        incomplete_pause_multiplier: float = INCOMPLETE_PAUSE_MULTIPLIER,
    ):
        self.bot_id = bot_id
        self.pending: dict[str, PendingUtterance] = {}
        self.on_flush = on_flush
        self.on_evicted = on_evicted
        self.pause_ms = pause_ms
        self.punct_grace_ms = punct_grace_ms
        self.max_chars = max_chars
        self.max_words = max_words
        self.max_pending = max_pending
        self.incomplete_pause_multiplier = incomplete_pause_multiplier

    # ── Entry points ──────────────────────────────────────────────────────

    def add_chunk(
        self,
        speaker_id: str,
        speaker_name: str,
        text: str,
        now_mono: Optional[float] = None,
        last_word_abs: str = "",
    ) -> None:
        """Append a chunk to the speaker's pending utterance. May trigger
        flushes:
          • Floor change: any OTHER speaker with a pending utterance is
            flushed first (reason=speaker_change).
          • Max-cap: if the speaker's pending hits MAX_WORDS or
            MAX_CHARS after appending, it's flushed immediately
            (reason=max_words / max_chars).
        """
        if not speaker_id or not text.strip():
            return
        now = now_mono if now_mono is not None else time.monotonic()

        # Floor change → flush all other speakers
        for other_id in list(self.pending.keys()):
            if other_id != speaker_id:
                self._flush(other_id, now, reason=REASON_SPEAKER_CHANGE)

        cur = self.pending.get(speaker_id)
        if cur is None:
            # DoS guard: cap concurrent pending speakers. Real meetings
            # cap at ~50 participants; anything over MAX_PENDING_SPEAKERS
            # is anomalous (synthetic speaker_ids, an attack). Evict the
            # oldest WITHOUT flushing (don't reward the attacker by
            # surfacing their content downstream).
            if len(self.pending) >= self.max_pending:
                oldest = min(self.pending.values(), key=lambda u: u.last_word_mono)
                self.pending.pop(oldest.speaker_id, None)
                if self.on_evicted:
                    try:
                        self.on_evicted(oldest.speaker_id)
                    except Exception as e:
                        print(
                            f"[accumulator] on_evicted error "
                            f"bot={self.bot_id[:8]} evicted={oldest.speaker_id[:8]}: {e}"
                        )
            cur = PendingUtterance(
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                first_word_mono=now,
                last_word_mono=now,
            )
            self.pending[speaker_id] = cur

        # Intra-utterance re-emission detection. Deepgram smart_format
        # with interim_results may resend a refined/cumulative version
        # of an in-progress chunk. If the new text substantially overlaps
        # the pending tail (60%+ char overlap on normalized form), treat
        # it as a re-emission: newer wins, REPLACE pending text.
        cur_norm = _normalize(cur.text)
        new_norm = _normalize(text)
        if cur_norm and _is_reemission(cur_norm, new_norm):
            # Replace only if the new version is at least as long — protects
            # against an out-of-order older interim arriving and shrinking
            # pending. Update timestamps either way.
            if len(new_norm) >= len(cur_norm):
                cur.text = text.strip()
                cur.word_count = len(text.split())
            cur.last_word_mono = now
            cur.last_word_abs = last_word_abs or cur.last_word_abs
            cur.chunk_count += 1
            cur.punct_pending_since = now if _ends_in_terminal_punct(text) else None
            return

        cur.text = (cur.text + " " + text.strip()).strip() if cur.text else text.strip()
        cur.last_word_mono = now
        cur.last_word_abs = last_word_abs or cur.last_word_abs
        cur.word_count += len(text.split())
        # Track whether THIS chunk ended in a sentence terminator. Used
        # by tick() to decide between normal and extended pause windows.
        cur.last_chunk_complete = _ends_in_terminal_punct(text)
        cur.chunk_count += 1
        cur.punct_pending_since = now if _ends_in_terminal_punct(text) else None

        # Max-cap check after append
        if cur.word_count >= self.max_words:
            self._flush(speaker_id, now, reason=REASON_MAX_WORDS)
        elif len(cur.text) >= self.max_chars:
            self._flush(speaker_id, now, reason=REASON_MAX_CHARS)

    def tick(self, now_mono: Optional[float] = None) -> None:
        """Called from a background task on ~100ms cadence. Flushes any
        speaker past the pause threshold OR past the punctuation grace
        window.

        Adaptive pause: if the speaker's last chunk did NOT end in
        sentence-terminating punctuation, use a longer pause window
        (`pause_ms × incomplete_pause_multiplier`). This is the fix for
        the "...send a mail to which" → "0712@gmail.com" case where the
        speaker pauses mid-thought to remember a value. The normal
        1.2s pause is too aggressive for thinking pauses; the extended
        ~2.4s pause catches them while still flushing quickly once the
        thought is complete.
        """
        now = now_mono if now_mono is not None else time.monotonic()
        pause_s = self.pause_ms / 1000.0
        incomplete_pause_s = pause_s * self.incomplete_pause_multiplier
        grace_s = self.punct_grace_ms / 1000.0
        for speaker_id in list(self.pending.keys()):
            cur = self.pending[speaker_id]
            effective_pause = pause_s if cur.last_chunk_complete else incomplete_pause_s
            if (now - cur.last_word_mono) >= effective_pause:
                self._flush(speaker_id, now, reason=REASON_PAUSE)
            elif (
                cur.punct_pending_since is not None
                and (now - cur.punct_pending_since) >= grace_s
            ):
                self._flush(speaker_id, now, reason=REASON_PUNCT)

    def discard_speaker(self, speaker_id: str) -> None:
        """Drop pending for a speaker WITHOUT emitting on_flush. Called by
        the fast-path stop-command detector so the surrounding words don't
        re-fire as a slow-path action command.

        Example: user says "Prism, send the email. Wait, stop." The fast
        path fires the stop on the chunk containing 'stop' and calls this
        to ensure the full utterance (which includes the send-action verbs)
        never reaches the slow-path command dispatcher.
        """
        self.pending.pop(speaker_id, None)

    def flush_all(self, now_mono: Optional[float] = None) -> None:
        """Emit any remaining pending utterances. Called on bot teardown."""
        now = now_mono if now_mono is not None else time.monotonic()
        for speaker_id in list(self.pending.keys()):
            self._flush(speaker_id, now, reason=REASON_FLUSH_ALL)

    # ── Internal ─────────────────────────────────────────────────────────

    def _flush(self, speaker_id: str, now: float, reason: str) -> None:
        cur = self.pending.pop(speaker_id, None)
        if cur is None or not cur.text.strip():
            return
        flushed = FlushedUtterance(
            utterance_id=_utterance_id(self.bot_id, cur),
            speaker_id=cur.speaker_id,
            speaker_name=cur.speaker_name,
            text=cur.text.strip(),
            word_count=cur.word_count,
            chunk_count=cur.chunk_count,
            duration_ms=int(max(0.0, cur.last_word_mono - cur.first_word_mono) * 1000),
            flush_reason=reason,
        )
        try:
            self.on_flush(flushed)
        except Exception as e:
            # NEVER let a downstream bug crash the tick task or block
            # ingress. Log and continue.
            print(
                f"[accumulator] on_flush error bot={self.bot_id[:8]} "
                f"utt={flushed.utterance_id} reason={reason}: {e}"
            )


# ── Helpers ─────────────────────────────────────────────────────────────

_PUNCT_STRIP = re.compile(r"[^\w\s]")


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Used for
    re-emission detection only — NOT for any persisted text."""
    return _PUNCT_STRIP.sub("", s).lower().strip()


def _is_reemission(cur_norm: str, new_norm: str, min_prefix_chars: int = 3) -> bool:
    """Heuristic re-emission detection. True if the new chunk is a
    refined / cumulative version of the current pending text — same
    audio span, different model confidence/formatting.

    Match rule: one normalized string must be a strict prefix of the
    other, AND the shorter must be at least `min_prefix_chars` characters.
    This catches Deepgram interim_results cumulative partials ("prism" →
    "prism can" → "prism can you") which always extend the prior emission
    from the start. Pause threshold (1200ms default) is the time-based
    discriminator: separate utterances arrive after a flush, so a chunk
    arriving for an EXISTING pending is by definition within the same
    utterance.

    Known blind spot: corrections that change words EARLY in the
    utterance (e.g. "prasim can you" → "prism, can you see") don't share
    a clean character-prefix and won't be detected as re-emission. The
    legacy 3s fuzzy dedup had the same blind spot.
    """
    if not cur_norm or not new_norm:
        return False
    if new_norm == cur_norm:
        return True
    shorter_len = min(len(cur_norm), len(new_norm))
    if shorter_len < min_prefix_chars:
        return False
    return new_norm.startswith(cur_norm) or cur_norm.startswith(new_norm)


def _ends_in_terminal_punct(text: str) -> bool:
    """Detect end-of-thought punctuation that should trigger a short-grace
    flush. Defends against pure-punctuation chunks (empty word content)
    and the obvious abbreviation cases ('Mr.', 'Dr.', 'U.S.' is harder)."""
    s = text.strip()
    if not s or s[-1] not in ".!?":
        return False
    # Pure-punctuation chunk: no flush trigger (would prematurely close
    # an utterance that's actually still in progress)
    if sum(1 for c in s if c.isalnum()) == 0:
        return False
    # Abbreviation guard: short single-cap token before the period is
    # likely an honorific or initial, not a sentence end.
    last_token = s.rsplit(None, 1)[-1].rstrip(".!?")
    if len(last_token) <= 2 and last_token.isalpha() and last_token[0].isupper():
        return False
    return True


def _utterance_id(bot_id: str, u: PendingUtterance) -> str:
    """Stable hash for audit trail. Deterministic from (bot, speaker,
    first-word mono, last-word abs, text) — replaying the same chunks
    produces the same id."""
    return hashlib.sha1(
        f"{bot_id}|{u.speaker_id}|{u.first_word_mono:.4f}|{u.last_word_abs}|{u.text}".encode()
    ).hexdigest()[:12]

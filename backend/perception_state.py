"""Pre-perception layer state — event-id dedup, partial-drop ratio observability,
and counter scaffolding shared between realtime_routes and the live/bot-counter
endpoints.

Gated downstream by PRISM_PRE_PERCEPTION=1. Importing this module is cheap and
safe regardless of the flag; the wiring at the realtime_events() handler is what
actually consults these helpers.
"""

import asyncio
import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# ── Clock helpers ────────────────────────────────────────────────────────────
# All windowing/dedup arithmetic uses monotonic time. Wall-clock (time.time)
# is reserved for human-readable logging.
_now_mono = time.monotonic


# ── Global event-id dedup ─────────────────────────────────────────────────────
# Lazy-swept TTL set. Memory budget at 10k entries × ~232B (CPython dict +
# string object overhead) ≈ 2.3 MB realistic, up to ~5 MB under fragmentation.
# Shared across all bots; collisions are vanishingly unlikely because event ids
# include bot_id + ISO timestamps + text.
class TTLSet:
    """O(1) amortized contains_or_add with both time- and size-based eviction.

    Internal structure:
      _seen: dict[key -> insert_monotonic_ts] — for fast membership + freshness
      _order: deque[key]                       — for FIFO eviction
    """

    __slots__ = ("_seen", "_order", "ttl", "max_size")

    def __init__(self, ttl_seconds: float = 600.0, max_size: int = 10_000):
        self._seen: dict[str, float] = {}
        self._order: deque[str] = deque()
        self.ttl = ttl_seconds
        self.max_size = max_size

    def _evict_expired(self, now: float) -> None:
        # Sweep front of deque while head is expired. Bounded by k = number of
        # expired entries, amortized O(1) per insert.
        while self._order:
            head = self._order[0]
            ts = self._seen.get(head)
            if ts is None:
                self._order.popleft()
                continue
            if now - ts > self.ttl:
                self._order.popleft()
                self._seen.pop(head, None)
            else:
                break

    def contains_or_add(self, key: str, now: Optional[float] = None) -> bool:
        """Returns True if key was already present (and refreshes its TTL).
        Returns False if newly added."""
        if now is None:
            now = _now_mono()
        self._evict_expired(now)
        if key in self._seen:
            self._seen[key] = now
            return True
        # Size cap — evict oldest if at limit.
        if len(self._seen) >= self.max_size:
            oldest = self._order.popleft()
            self._seen.pop(oldest, None)
        self._seen[key] = now
        self._order.append(key)
        return False

    def __len__(self) -> int:
        return len(self._seen)


# Module-level singleton. Created lazily on first import; survives uvicorn
# reloads of realtime_routes because this module isn't touched on reload.
_seen_events = TTLSet(ttl_seconds=600.0, max_size=10_000)


def seen_events() -> TTLSet:
    return _seen_events


# ── Event-id synthesis ────────────────────────────────────────────────────────
# Recall does not provide a stable event_id on the transcript segment payload
# (verified empirically in [DEBUG-trsc1] dump 2026-05-14). We synthesize one
# from (bot_id, event_type, first_word_absolute_ts, last_word_absolute_ts, text).
# The absolute timestamps are ISO 8601 strings as Recall sends them — byte-stable
# across re-serialization, no rounding needed.

# For degenerate inputs (no segment / empty words), we never want to collapse
# two distinct events into the same hash. monotonic_ns has 100ns granularity
# on Windows so back-to-back calls can collide. A monotonically increasing
# in-process counter is collision-free by construction.
_unique_seq = 0


def _next_unique_seed() -> int:
    global _unique_seq
    _unique_seq += 1
    return _unique_seq


def synth_event_id(bot_id: str, event_type: str, segment: dict) -> str:
    if not isinstance(segment, dict):
        return hashlib.sha1(
            f"{bot_id}|{event_type}|nonseg|{_next_unique_seed()}".encode()
        ).hexdigest()
    words = segment.get("words") or []
    if not words:
        speaker = (segment.get("participant") or {}).get("name", "")
        seed = f"{bot_id}|{event_type}|empty|{speaker}|{_next_unique_seed()}"
        return hashlib.sha1(seed.encode()).hexdigest()
    first_abs = (
        (words[0].get("start_timestamp") or {}).get("absolute")
        or (words[0].get("start_timestamp") or {}).get("relative")
        or ""
    )
    last_abs = (
        (words[-1].get("end_timestamp") or {}).get("absolute")
        or (words[-1].get("end_timestamp") or {}).get("relative")
        or ""
    )
    text = " ".join(w.get("text", "") for w in words)
    return hashlib.sha1(
        f"{bot_id}|{event_type}|{first_abs}|{last_abs}|{text}".encode()
    ).hexdigest()


# ── is_final detection (defensive multi-location lookup) ─────────────────────
# Empirically (2026-05-14 dump) the segment had keys ['words','language_code',
# 'participant'] with no is_final. With interim_results=true set in the
# Deepgram config, partials may arrive — either at a different envelope key,
# under a different event_type, or be dropped by Recall before reaching us.
# We check three locations and treat absence as "final" (safe default).
def is_partial(segment: Optional[dict], data_field: Optional[dict]) -> bool:
    for container in (segment, data_field):
        if not isinstance(container, dict):
            continue
        v = container.get("is_final")
        if v is False:
            return True
        if v is True:
            return False
    if isinstance(data_field, dict):
        transcript_obj = data_field.get("transcript")
        if isinstance(transcript_obj, dict):
            v = transcript_obj.get("is_final")
            if v is False:
                return True
            if v is True:
                return False
    return False


# ── Drop-reason ring buffer (per bot, 100 entries, oldest evicted) ───────────
@dataclass
class DroppedEvent:
    when_mono: float
    bot_id: str
    hash_prefix: str
    speaker: str
    text_excerpt: str
    reason: str  # open enum: "dedup" | "partial" | "cousin_no_match" | …


_RING_BUFFER_SIZE = 100
_drop_rings: dict[str, deque] = {}


def record_drop(
    bot_id: str,
    event_id: str,
    speaker: str,
    text: str,
    reason: str,
) -> None:
    ring = _drop_rings.get(bot_id)
    if ring is None:
        ring = deque(maxlen=_RING_BUFFER_SIZE)
        _drop_rings[bot_id] = ring
    ring.append(
        DroppedEvent(
            when_mono=_now_mono(),
            bot_id=bot_id,
            hash_prefix=event_id[:8] if event_id else "",
            speaker=speaker or "",
            text_excerpt=(text or "")[:40],
            reason=reason,
        )
    )


def get_drops(bot_id: str) -> list[dict]:
    ring = _drop_rings.get(bot_id)
    if not ring:
        return []
    return [
        {
            "when_mono": d.when_mono,
            "hash_prefix": d.hash_prefix,
            "speaker": d.speaker,
            "text_excerpt": d.text_excerpt,
            "reason": d.reason,
        }
        for d in ring
    ]


def cleanup_bot(bot_id: str) -> None:
    """Called when a bot is removed — drop its ring buffer."""
    _drop_rings.pop(bot_id, None)


# ── Counters ─────────────────────────────────────────────────────────────────
# Operational counters live in bot state under "counters". We expose a typed
# accessor so the call sites don't sprinkle string keys.
_DEFAULT_COUNTERS = {
    # Operational (safe to expose on possession-based /live/{token})
    "dedup_hits": 0,
    "partial_drops": 0,
    "cancel_count": 0,                      # aggregate, kept for legacy/at-a-glance
    "cancel_at_llm_read": 0,                # cancel fired inside LLM stream loop
    "cancel_at_segmenter": 0,               # cancel fired between segmenter feeds
    "cancel_at_upload": 0,                  # cancel fired before chunk upload
    "cancel_at_dispatch": 0,                # cancel fired before tool dispatch
    "tts_chunks_generated_but_cancelled": 0,  # upper-bound waste signal
    "replace_depth_hits": 0,
    "cousin_hit_no_match": 0,
    "stop_command_fired": 0,
    # Security signal (owner-only)
    "injection_redactions": 0,
    "owner_gate_blocks": 0,
    "owner_impersonation_attempts": 0,
    "ingress_rate_limited": 0,
    "accumulator_evictions": 0,
}


def ensure_counters(state: dict) -> dict:
    c = state.get("counters")
    if not isinstance(c, dict):
        c = dict(_DEFAULT_COUNTERS)
        state["counters"] = c
        return c
    # Backfill any new keys without overwriting existing values.
    for k, v in _DEFAULT_COUNTERS.items():
        c.setdefault(k, v)
    return c


_OPERATIONAL_KEYS = (
    "dedup_hits",
    "partial_drops",
    "cancel_count",
    "cancel_at_llm_read",
    "cancel_at_segmenter",
    "cancel_at_upload",
    "cancel_at_dispatch",
    "tts_chunks_generated_but_cancelled",
    "replace_depth_hits",
    "cousin_hit_no_match",
    "stop_command_fired",
)

_SECURITY_KEYS = (
    "injection_redactions",
    "owner_gate_blocks",
    "owner_impersonation_attempts",
    "ingress_rate_limited",
    "accumulator_evictions",
)


def operational_counters(state: dict) -> dict:
    c = ensure_counters(state)
    return {k: c.get(k, 0) for k in _OPERATIONAL_KEYS}


def security_counters(state: dict) -> dict:
    c = ensure_counters(state)
    return {k: c.get(k, 0) for k in _SECURITY_KEYS}


def bump(state: dict, key: str, amount: int = 1) -> None:
    c = ensure_counters(state)
    c[key] = c.get(key, 0) + amount


# ── Phonetic cousins of "prism" ──────────────────────────────────────────────
# Single source of truth for cousin-aware matching. Used by:
#   • cousin_hit_no_match telemetry (Phase A polish)
#   • stop-command detection (Phase B)
#   • future tier-1 phonetic wake-word match
# Grow this list from real misses observed via the 10% sample log on
# `cousin_hit_no_match` events.
PRISM_COUSINS = (
    "prism", "prismai", "prism ai",
    "prison", "brism", "prisma", "prisms",
    "prasim", "prasum", "prizon",
)

_COUSINS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(c) for c in PRISM_COUSINS) + r")\b",
    re.IGNORECASE,
)


def has_cousin(text: str) -> bool:
    """True if any Prism cousin appears in the text as a whole word."""
    return bool(text) and bool(_COUSINS_RE.search(text))


# ── Stop-command pattern ─────────────────────────────────────────────────────
# Tight list per Phase B spec. Excludes "wait" and "hold on" intentionally —
# those are turn-taking signals, not interrupts. Phonetic cousins are pulled
# from PRISM_COUSINS so a mishearing of the wake word still cancels.
_STOP_VERBS = r"(?:stop|cancel|nevermind|never\s+mind|shut\s+up|quiet)"
_STOP_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(c) for c in PRISM_COUSINS) + r")\b"
    r"[,\s]+" + _STOP_VERBS + r"\b",
    re.IGNORECASE,
)


def is_stop_command(text: str) -> bool:
    """True if utterance is a cancel/stop directive addressed to Prism."""
    return bool(text) and bool(_STOP_PATTERN.search(text))


# ── Stable text sampling ──────────────────────────────────────────────────────
def should_sample(text: str, fraction_pct: int = 10) -> bool:
    """Deterministic sampling: stable across runs for the same text.
    Used so the 10% cousin_hit sample log gives a consistent slice across
    soak windows."""
    if not text or fraction_pct <= 0:
        return False
    if fraction_pct >= 100:
        return True
    # Hash-based bucket; not cryptographic. md5 chosen for stable output across
    # Python builds (str.__hash__ is randomized per process).
    bucket = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16) % 100
    return bucket < fraction_pct


# ── Speaking session (barge-in / cancellation primitive) ─────────────────────
@dataclass
class SpeakingSession:
    """One active TTS-and-upload pipeline for a bot.

    Cancellation is cooperative: the streamed-TTS code paths check
    `cancel_event.is_set()` at three sites (LLM-read loop, segmenter feed,
    before upload) and a fourth at tool dispatch. The first check that fires
    bumps the corresponding cancel_at_* counter and bails.

    `tool_dispatch_committed` flips True the instant we begin awaiting a
    tool handler. After that, the session is considered to have side effects
    in flight and is no longer cancellable (the LLM synthesis turn that
    follows the tool result IS cancellable; the tool call itself is not).
    """

    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_mono: float = field(default_factory=_now_mono)
    chunks_generated: int = 0          # TTS audio chunks produced
    chunks_uploaded: int = 0           # subset that reached Recall
    cancelled_at_chunk: Optional[int] = None
    tool_dispatch_committed: bool = False
    waste_recorded: bool = False       # idempotency flag for chunks-wasted counter

    def cancel(self) -> None:
        if not self.cancel_event.is_set():
            self.cancel_event.set()
            if self.cancelled_at_chunk is None:
                self.cancelled_at_chunk = self.chunks_generated

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()


def get_session(state: dict) -> Optional[SpeakingSession]:
    return state.get("speaking_session")


# ── Lock ordering rule (Phase C.1) ───────────────────────────────────────────
# Two locks live in bot state:
#   memory_lock   — guards meeting_memory fields (live_decisions, transcript
#                   buffer mutation, structured-state writes, compression).
#   session_lock  — guards the speaking-session swap (cancel old → install new).
# When both are needed, ALWAYS acquire memory_lock FIRST, then session_lock.
# Today no code path acquires the reverse, so this rule prevents deadlock
# preemptively. If you ever need session_lock first, refactor to a single
# lock — do NOT introduce reverse acquisition.

def get_memory_lock(state: dict) -> asyncio.Lock:
    """Per-bot lock guarding meeting_memory mutations.

    Created lazily. Critical sections must NOT include network awaits —
    only the actual list/dict mutation. Keep them tight; a long-held memory
    lock blocks structured-state updates from concurrent transcripts.

    See module-level ordering rule: acquire memory_lock BEFORE session_lock
    when both are required.
    """
    lock = state.get("memory_lock")
    if lock is None:
        lock = asyncio.Lock()
        state["memory_lock"] = lock
    return lock


def get_session_lock(state: dict) -> asyncio.Lock:
    """Per-bot lock guarding session swap (supersede / clear).

    See module-level ordering rule: when both memory_lock and session_lock
    are needed, acquire memory_lock FIRST.
    """
    lock = state.get("session_lock")
    if lock is None:
        lock = asyncio.Lock()
        state["session_lock"] = lock
    return lock


async def supersede_session(state: dict, new_session: SpeakingSession) -> Optional[SpeakingSession]:
    """Atomically cancel any in-flight session and install `new_session`.

    Returns the previous session if one was active, else None.
    Caller holds responsibility for incrementing replace_depth_hits when
    the returned session is not None.
    """
    async with get_session_lock(state):
        old = state.get("speaking_session")
        if old is not None and not old.is_cancelled:
            old.cancel()
        state["speaking_session"] = new_session
        return old


async def clear_session(state: dict, session: SpeakingSession) -> None:
    """Clear the active session iff it's still `session`. Race-safe."""
    async with get_session_lock(state):
        if state.get("speaking_session") is session:
            state["speaking_session"] = None


# ── Phase D: speaker normalization + owner gate ──────────────────────────────
# Recall/Deepgram speaker labels are inconsistent: "Abhinav Dasari" from the
# join request might come back as "Abhinav", "abhinav.dasari", "ABHINAV", or
# "Speaker 1" when diarization loses confidence. Without normalization, the
# owner-gate on confirm=True tools either fails open (no string matches, every
# attempt allowed) or fails closed (owner blocked from their own tools). Both
# are wrong.

_SPEAKER_N_RE = re.compile(r"^speaker\s*\d+$", re.IGNORECASE)


def normalize_speaker(name: Optional[str]) -> str:
    """Lowercase, strip everything that isn't a-z. Stable bucket for comparison."""
    if not name:
        return ""
    return re.sub(r"[^a-z]", "", name.lower())


def is_owner_speaker(speaker: Optional[str], owner_full: Optional[str]) -> bool:
    """Fail-closed match: speaker is the bot owner iff the normalized strings
    match, contain each other, or share a first-name token.

    Specifically refuses:
      - empty/missing speaker
      - empty/missing owner_full
      - "Speaker 1" / "Speaker 2" / etc. (Recall fallback when diarization
        loses confidence — we never trust this with privileged actions)
    """
    if not speaker or not owner_full:
        return False
    if _SPEAKER_N_RE.match(speaker.strip()):
        return False
    s = normalize_speaker(speaker)
    o = normalize_speaker(owner_full)
    if not s or not o:
        return False
    if s == o:
        return True
    if s in o or o in s:
        return True
    # First-name token fallback. e.g. owner "Abhinav Dasari" vs speaker "Abhinav".
    owner_first = normalize_speaker(owner_full.split()[0]) if owner_full.split() else ""
    speaker_first = normalize_speaker(speaker.split()[0]) if speaker.split() else ""
    if owner_first and speaker_first and owner_first == speaker_first:
        return True
    return False


# ── Owner participant-ID lock ───────────────────────────────────────────────
# Name-based owner matching (is_owner_speaker above) is vulnerable to display-
# name impersonation: an attacker who joins the meeting as "Abhinav" passes
# the first-name-token fallback and can fire confirm-tools against the real
# owner's accounts. The participant-ID lock hardens this:
#
#   1. For the first OWNER_LOCK_GRACE_SECONDS after the bot joins, no one is
#      locked. This grace window prevents an attacker who speaks before the
#      real owner from grabbing the lock.
#   2. After the grace window, the next chunk whose speaker name matches the
#      owner (via is_owner_speaker) AND has a non-empty participant_id locks
#      that participant_id as the owner. Subsequent owner checks use ID match.
#   3. If a DIFFERENT participant_id later matches by name, it's flagged as a
#      probable impersonation attempt — the owner gate refuses the action.
#
# Gated behind PRISM_OWNER_ID_LOCK=1 so rollout is independent of any larger
# refactor (e.g. the utterance accumulator). Caller checks the flag.

OWNER_LOCK_GRACE_SECONDS = 5.0


def maybe_lock_owner_id(
    state: dict,
    speaker_id: Optional[str],
    speaker_name: Optional[str],
    owner_full: Optional[str],
) -> None:
    """Attempt to lock the owner's participant_id on the current chunk.
    No-op if already locked, if no speaker_id, if name doesn't match, or
    if we're still inside the grace window since bot join.

    Caller responsibility: gate on PRISM_OWNER_ID_LOCK=1 before calling.
    """
    if state.get("owner_speaker_id"):
        return  # already locked
    if not speaker_id or not speaker_name or not owner_full:
        return
    join_ts = state.get("bot_join_mono")
    if join_ts is None:
        return  # not initialized — fail closed
    if (_now_mono() - join_ts) < OWNER_LOCK_GRACE_SECONDS:
        return  # grace window — wait for the real owner to speak
    if not is_owner_speaker(speaker_name, owner_full):
        return
    state["owner_speaker_id"] = speaker_id
    print(
        f"[security] owner_id_locked speaker_id={speaker_id[:8]!r} "
        f"name={speaker_name!r} owner_full={owner_full!r}"
    )


def is_owner_with_lock(
    state: dict,
    speaker_id: Optional[str],
    speaker_name: Optional[str],
    owner_full: Optional[str],
) -> bool:
    """Owner check with optional participant-ID lock. When the lock is set,
    ID match is authoritative — a name-only match by a different participant
    is REFUSED (and logged as a probable impersonation).

    When the lock is not set (pre-grace-window, or PRISM_OWNER_ID_LOCK=0),
    falls back to the legacy name-only match.
    """
    locked_id = state.get("owner_speaker_id")
    if locked_id:
        if speaker_id and speaker_id == locked_id:
            return True
        # Name match without matching ID = impersonation attempt
        if is_owner_speaker(speaker_name, owner_full):
            bump(state, "owner_impersonation_attempts")
            print(
                f"[security] owner_impersonation_attempt "
                f"speaker_id={(speaker_id or '')[:8]!r} name={speaker_name!r} "
                f"locked_id={locked_id[:8]!r}"
            )
        return False
    # Lock not set yet — name match is the only signal we have
    return is_owner_speaker(speaker_name, owner_full)


# ── Phase D: injection-pattern detection (defense in depth) ──────────────────
# Reuses the same pattern shape as PR-2's web_search defense. This catches the
# obvious 5% of attacks; the real defense is the XML-spotlight trust framing
# (D.1) + the owner-gate on confirm-tools (D.3). Don't oversell the regex.
_INJECTION_PATTERNS = re.compile(
    r"ignore\s+(?:all\s+)?previous|"
    r"system\s*:|"
    r"<\|im_(?:start|end)\|>|"
    r"new\s+instructions|"
    r"forget\s+(?:your|the)|"
    r"reveal\s+(?:your|the)\s+system",
    re.IGNORECASE,
)


def sanitize_for_injection(text: str) -> tuple[str, int]:
    """Replace any injection-pattern matches with [REDACTED]. Returns
    (clean_text, n_redactions). Don't drop — the user might legitimately say
    something that looks like an injection; we just neutralize the trigger.
    """
    if not text:
        return text, 0
    n = 0
    def _sub(m):
        nonlocal n
        n += 1
        return "[REDACTED]"
    clean = _INJECTION_PATTERNS.sub(_sub, text)
    return clean, n

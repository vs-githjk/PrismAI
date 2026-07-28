"""Per-turn latency stopwatch — t0→t4, the one number that could send us to
MeetingBaaS.

Each spoken turn records five markers:

    t0  Flux EndOfTurn event timestamp          (user stopped talking)
    t1  final transcript in hand                (STT done)
    t2  first LLM token                         (brain started replying)
    t3  first TTS audio byte from Cartesia      (mouth started rendering)
    t4  first audio frame sent to the speaker page + measured WS RTT/2
        (send-side proxy — one clock, no browser-clock trust)

The interval that matters most is **t3→t4 plus the speaker page's playout ping**:
that's Recall's Output-Media mix hop, the only latency floor we can't tune. It is
logged LOUDLY (see `_LOUD`). Everything else we control.

Design notes (ponytail):
- One monotonic clock (`time.perf_counter`), so intervals never see wall-clock
  jumps. Absolute wall time is stamped once per turn for the JSONL only.
- Missing markers are fine — a turn the bot declined to answer has no t2/t3/t4;
  intervals over absent markers are simply omitted. No exceptions on partial turns.
- JSONL append is best-effort; a failed write never touches the audio path.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Optional

# Ordered markers. Intervals are computed between adjacent present markers.
_MARKERS = ("t0", "t1", "t2", "t3", "t4")

# Human labels for the adjacent-pair intervals, for the rolling summary.
_INTERVALS = (
    ("t0", "t1", "stt"),        # end-of-turn → final transcript
    ("t1", "t2", "llm_first"),  # transcript → first LLM token
    ("t2", "t3", "tts_first"),  # first token → first TTS byte
    ("t3", "t4", "mix_hop"),    # first TTS byte → first frame to speaker  ← LOUD
    ("t0", "t4", "total"),      # full voice-to-first-audio
)

# The mix hop is the unknown; surface it on its own line so ops can grep it.
_LOUD = "mix_hop"

_LOG_PATH = Path(os.getenv("PRISM_VOICE_TIMINGS", "voice_timings.jsonl"))
_SUMMARY_EVERY = int(os.getenv("PRISM_VOICE_TIMINGS_SUMMARY_EVERY", "10"))


class TurnStopwatch:
    """One turn. Call `mark("t0")` … `mark("t4")` as milestones happen, then
    `finish()` to append the JSONL row and feed the rolling summary.

    `rtt_ms` (optional) is the measured speaker-WS round trip; half of it is added
    to the mix-hop reading as the send-side transit proxy (t4 is captured when we
    *send* the first frame, not when the page plays it — the page's playout ping
    closes the rest of the loop and is logged separately)."""

    __slots__ = ("bot_id", "turn_id", "_marks", "_wall_start", "rtt_ms", "meta")

    def __init__(self, bot_id: str, turn_id: str, meta: Optional[dict] = None):
        self.bot_id = bot_id
        self.turn_id = turn_id
        self._marks: dict[str, float] = {}
        self._wall_start = time.time()
        self.rtt_ms: Optional[float] = None
        self.meta = meta or {}

    def mark(self, name: str) -> None:
        if name not in _MARKERS:
            raise ValueError(f"unknown marker {name!r}; expected one of {_MARKERS}")
        # First write wins — a marker re-fired by a retry keeps the earliest time.
        self._marks.setdefault(name, time.perf_counter())

    def set_rtt_ms(self, rtt_ms: float) -> None:
        self.rtt_ms = rtt_ms

    def intervals_ms(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for a, b, label in _INTERVALS:
            if a in self._marks and b in self._marks:
                ms = (self._marks[b] - self._marks[a]) * 1000.0
                if label == _LOUD and self.rtt_ms is not None:
                    ms += self.rtt_ms / 2.0
                out[label] = round(ms, 1)
        return out

    def finish(self) -> dict:
        intervals = self.intervals_ms()
        row = {
            "ts": round(self._wall_start, 3),
            "bot": self.bot_id[:12],
            "turn": self.turn_id,
            "intervals_ms": intervals,
            "have": [m for m in _MARKERS if m in self._marks],
            **({"rtt_ms": round(self.rtt_ms, 1)} if self.rtt_ms is not None else {}),
            **({"meta": self.meta} if self.meta else {}),
        }
        _append_jsonl(row)
        if _LOUD in intervals:
            # The one line ops watch. Grep-friendly, always emitted.
            print(f"[voice-latency] MIX-HOP bot={row['bot']} t3->t4={intervals[_LOUD]}ms "
                  f"(rtt/2 included={self.rtt_ms is not None})")
        _AGG.ingest(intervals)
        return row


def _append_jsonl(row: dict) -> None:
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:  # never let logging touch the audio path
        print(f"[voice-latency] jsonl write skipped: {e}")


class _RollingAggregator:
    """Keeps a bounded window of each interval and logs median/p90 every N turns."""

    def __init__(self, window: int = 200):
        self._series: dict[str, list[float]] = {}
        self._window = window
        self._turns = 0

    def ingest(self, intervals: dict[str, float]) -> None:
        for label, ms in intervals.items():
            s = self._series.setdefault(label, [])
            s.append(ms)
            if len(s) > self._window:
                del s[: len(s) - self._window]
        self._turns += 1
        if _SUMMARY_EVERY > 0 and self._turns % _SUMMARY_EVERY == 0:
            self.log_summary()

    def log_summary(self) -> None:
        parts = []
        for _, _, label in _INTERVALS:
            s = self._series.get(label)
            if not s:
                continue
            med = statistics.median(s)
            p90 = _pctl(s, 90)
            tag = "  <<LOUD" if label == _LOUD else ""
            parts.append(f"{label}: med={med:.0f} p90={p90:.0f} (n={len(s)}){tag}")
        if parts:
            print("[voice-latency] SUMMARY " + " | ".join(parts))


def _pctl(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (q / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


_AGG = _RollingAggregator()


# ── per-bot open turn ─────────────────────────────────────────────────────────
# The markers are set from four different places (Flux capture, the voice channel, the
# speaker sink) that never see each other. One slot per bot joins them: the ears open a
# turn, the mouth takes it. Without this only t3/t4 are ever populated — which is why
# Phase 5 §3's "review the t0–t4 medians per segment" needed it.

_OPEN: dict[str, TurnStopwatch] = {}


def open_turn(bot_id: str, meta: Optional[dict] = None) -> TurnStopwatch:
    """A finished human turn arrived. t0 (speech end) and t1 (final transcript) are the
    same instant on the Flux path — the semantic end-of-turn decision IS the transcript,
    so there is no separate STT wait to measure from out here."""
    turn = TurnStopwatch(bot_id, f"t{int(time.time() * 1000)}", meta)
    turn.mark("t0")
    turn.mark("t1")
    _OPEN[bot_id] = turn
    return turn


def mark_turn(bot_id: str, marker: str) -> None:
    """Stamp a marker on this bot's open turn, if there is one."""
    turn = _OPEN.get(bot_id)
    if turn is not None:
        turn.mark(marker)


def take_turn(bot_id: str) -> Optional[TurnStopwatch]:
    """Claim the open turn (the mouth's first chunk wins; later chunks get None and keep
    the stopwatch already running in the sink)."""
    return _OPEN.pop(bot_id, None)


def cleanup_bot(bot_id: str) -> None:
    _OPEN.pop(bot_id, None)


def _demo() -> None:
    """Runnable self-check: assert intervals + rtt math are computed correctly."""
    sw = TurnStopwatch("botxxxxxxxx", "turn-1")
    base = time.perf_counter()
    # Fabricate marks by writing directly (bypassing real clock) to test the math.
    sw._marks = {"t0": base, "t1": base + 0.10, "t2": base + 0.40,
                 "t3": base + 0.55, "t4": base + 0.75}
    sw.set_rtt_ms(40.0)  # → +20ms on mix_hop
    iv = sw.intervals_ms()
    assert abs(iv["stt"] - 100.0) < 1.0, iv
    assert abs(iv["llm_first"] - 300.0) < 1.0, iv
    assert abs(iv["tts_first"] - 150.0) < 1.0, iv
    assert abs(iv["mix_hop"] - (200.0 + 20.0)) < 1.0, iv  # t3→t4=200ms + rtt/2=20ms
    assert abs(iv["total"] - 750.0) < 1.0, iv

    # Partial turn (bot declined): only t0/t1 present → only stt interval.
    sw2 = TurnStopwatch("botxxxxxxxx", "turn-2")
    sw2._marks = {"t0": base, "t1": base + 0.2}
    iv2 = sw2.intervals_ms()
    assert set(iv2) == {"stt"}, iv2

    # Percentile sanity.
    assert _pctl([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9.1, _pctl([1,2,3,4,5,6,7,8,9,10], 90)

    # Per-bot open turn: the ears open it, the voice channel marks t2, the mouth claims
    # it exactly once — a second claim must return None so streamed chunks 2..n keep the
    # stopwatch already running instead of each opening a bogus turn.
    turn = open_turn("botopen", {"speaker": "Dana"})
    assert "t0" in turn._marks and "t1" in turn._marks
    mark_turn("botopen", "t2")
    assert "t2" in turn._marks
    assert take_turn("botopen") is turn
    assert take_turn("botopen") is None
    mark_turn("botopen", "t3")            # no open turn → silently ignored, never raises
    open_turn("botgone")
    cleanup_bot("botgone")
    assert take_turn("botgone") is None
    print("stopwatch self-check OK")


if __name__ == "__main__":
    _demo()

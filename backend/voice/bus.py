"""Phase 3 — the command queue + visibility bus that connects the two channels.

Replaces item 10 (the 3s blind `_COMMAND_DEBOUNCE_S` window) with a per-bot command
queue and **tiered dedup**:

  tier 1  — normalized string similarity (difflib ratio ≥ 0.85) within a ~3s window
            = the same command re-heard on the rolling transcript → drop.
  tier 2  — the ambiguous middle band (0.60–0.85) goes to a small fast model (Groq
            8B, one yes/no: "same request or a new request?"). Distinct requests both
            run, in order. This is what the old debounce couldn't do — a second
            speaker asking right after the first is no longer swallowed.

Accepted commands drain SERIALLY through a handler the voice channel registers
(`set_command_handler`). Status is surfaced via `emit_status` — today a structured log
line (the seam the live-share payload + richer narration hook into later); the ack +
done narration themselves live in the handler, which already has the coroutine context.

Deliberately NOT a general pub/sub event bus: one producer (the agent tool loop) feeds
two consumers (chat-ack timing, voice narration) that share one coroutine, so an
emitter abstraction would be structure with no second caller. `# ponytail:` — add the
subscriber list when a real second consumer (live-share) needs it.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Awaitable, Callable, Optional

# Command-handler signature: (bot_id, command, speaker, from_chat) -> awaitable.
CommandHandler = Callable[[str, str, str, bool], Awaitable[None]]

_HANDLER: Optional[CommandHandler] = None

_DEDUP_WINDOW_S = float(os.getenv("PRISM_DEDUP_WINDOW_S", "3"))
_DEDUP_DROP_RATIO = 0.85   # ≥ this within the window → tier-1 drop (same re-heard command)
_DEDUP_AMBIG_RATIO = 0.60  # [ambig, drop) → tier-2 model adjudicates
_TIER2_MODEL = os.getenv("PRISM_DEDUP_TIER2_MODEL", "llama-3.1-8b-instant")
_QUEUE_MAX = 3  # depth cap — mirrors the old FIFO cap


def set_command_handler(handler: CommandHandler) -> None:
    """Register the coroutine that runs one accepted command (the voice-channel split).
    Set once at import of voice_channel; the bus stays decoupled from it (no cycle)."""
    global _HANDLER
    _HANDLER = handler


def emit_status(bot_id: str, event: str, **data) -> None:
    """Visibility hook: dispatched / running / done / blocked / error. A structured log
    line today; the seam a live-share status feed plugs into later."""
    detail = " ".join(f"{k}={v!r}" for k, v in data.items())
    print(f"[bus] bot={bot_id[:8]} {event} {detail}".rstrip())


def _norm(text: str) -> str:
    from realtime_routes import _normalize_cmd
    return _normalize_cmd(text)


class CommandBus:
    """Per-bot queue + tiered dedup + serial drain."""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self._queue: deque = deque()
        self._recent: list[tuple[str, float]] = []  # (norm, ts) accepted/seen recently
        self._draining = False
        self._inflight_norm: Optional[str] = None

    def _prune(self, now: float) -> None:
        self._recent = [(n, t) for (n, t) in self._recent if now - t < _DEDUP_WINDOW_S]

    def _candidates(self) -> list[str]:
        """Norms to compare a new command against: recent history + in-flight + queued."""
        out = [n for (n, _) in self._recent]
        if self._inflight_norm:
            out.append(self._inflight_norm)
        out.extend(_norm(c) for (c, _s, _f) in self._queue)
        return [n for n in out if n]

    async def _is_dup(self, norm: str, command: str) -> bool:
        now = time.time()
        self._prune(now)
        best = 0.0
        best_other = ""
        for other in self._candidates():
            r = SequenceMatcher(None, norm, other).ratio()
            if r > best:
                best, best_other = r, other
        if best >= _DEDUP_DROP_RATIO:
            emit_status(self.bot_id, "dedup_drop", tier=1, ratio=round(best, 2))
            return True
        if best >= _DEDUP_AMBIG_RATIO:
            same = await _tier2_same_request(best_other, norm)
            emit_status(self.bot_id, "dedup_tier2", ratio=round(best, 2), same=same)
            return same
        return False

    async def submit(self, command: str, speaker: str, from_chat: bool = False) -> str:
        """Dedup + enqueue. Returns 'accepted' | 'dropped_dup' | 'dropped_full'."""
        command = (command or "").strip()
        if not command:
            return "dropped_dup"
        norm = _norm(command)
        if norm and await self._is_dup(norm, command):
            return "dropped_dup"
        if len(self._queue) >= _QUEUE_MAX:
            emit_status(self.bot_id, "queue_full", depth=len(self._queue))
            return "dropped_full"
        self._recent.append((norm, time.time()))
        self._queue.append((command, speaker, from_chat))
        emit_status(self.bot_id, "queued", depth=len(self._queue), command=command[:60])
        if not self._draining:
            asyncio.create_task(self._drain())
        return "accepted"

    async def _drain(self) -> None:
        if self._draining:
            return
        self._draining = True
        try:
            while self._queue:
                command, speaker, from_chat = self._queue.popleft()
                self._inflight_norm = _norm(command)
                if _HANDLER is None:
                    emit_status(self.bot_id, "error", why="no handler registered")
                    continue
                try:
                    await _HANDLER(self.bot_id, command, speaker, from_chat)
                except Exception as exc:  # one bad command must not kill the drain
                    emit_status(self.bot_id, "error", command=command[:60], exc=str(exc)[:120])
                finally:
                    self._inflight_norm = None
        finally:
            self._draining = False


_buses: dict[str, CommandBus] = {}


def get_bus(bot_id: str) -> CommandBus:
    bus = _buses.get(bot_id)
    if bus is None:
        bus = _buses[bot_id] = CommandBus(bot_id)
    return bus


def cleanup_bot(bot_id: str) -> None:
    _buses.pop(bot_id, None)


async def submit(bot_id: str, command: str, speaker: str, from_chat: bool = False) -> str:
    """Module-level entry point — the dispatch sites call this."""
    return await get_bus(bot_id).submit(command, speaker, from_chat)


async def _tier2_same_request(a: str, b: str) -> bool:
    """One yes/no from a small fast model: are these the same request re-heard, or two
    distinct requests? Fails OPEN (→ not-a-dup / accept) when Groq is unavailable — the
    old debounce erred toward dropping and swallowed real second questions; we'd rather
    occasionally double-answer than silently ignore a participant."""
    from clients import get_groq
    client = get_groq()
    if client is None:
        return False
    try:
        resp = await client.chat.completions.create(
            model=_TIER2_MODEL,
            temperature=0,
            max_tokens=1,
            messages=[
                {"role": "system", "content": (
                    "Two utterances were heard seconds apart in a meeting. Answer with a "
                    "single word: 'same' if the second is the same request re-heard (a "
                    "transcript echo or restated ask), or 'new' if it is a distinct "
                    "request. Answer only 'same' or 'new'."
                )},
                {"role": "user", "content": f"1: {a}\n2: {b}"},
            ],
        )
        ans = (resp.choices[0].message.content or "").strip().lower()
        return ans.startswith("same")
    except Exception as exc:
        print(f"[bus] tier2 dedup failed, treating as distinct: {exc}")
        return False


# ── self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    class _FakeRR:
        @staticmethod
        def _normalize_cmd(t):
            return " ".join((t or "").lower().split())

    sys.modules["realtime_routes"] = _FakeRR  # type: ignore

    async def _main():
        seen = []

        async def handler(bot_id, command, speaker, from_chat):
            seen.append(command)
            await asyncio.sleep(0.01)

        set_command_handler(handler)
        bus = get_bus("botself1")
        # Tier-1: near-identical re-fire within the window → dropped.
        assert await bus.submit("summarize the meeting", "A") == "accepted"
        assert await bus.submit("summarize the meeting", "A") == "dropped_dup"
        # Distinct command → accepted (this is the bug the old debounce caused).
        assert await bus.submit("send an email to Bob", "B") == "accepted"
        await asyncio.sleep(0.1)  # let the drain run
        assert seen == ["summarize the meeting", "send an email to Bob"], seen
        # Prefix/near-dup ratio check.
        assert SequenceMatcher(None, "summarize the meeting",
                               "summarize the meeting now").ratio() >= _DEDUP_AMBIG_RATIO
        print("bus self-check OK")

    asyncio.run(_main())

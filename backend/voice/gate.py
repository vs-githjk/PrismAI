"""Phase 4 — the ONE engagement gate. The only place that answers "does the bot speak now?"

Collapses four scattered decisions (wake-word detection, solo free-flow, the ambient
consent funnel, proactive/idea speaking) into two entry points:

  decide(bot_id, state, text, speaker) -> (speak: bool, command: str)
      Called once per finished human turn. Returns whether to engage and the command
      text to run (the voice channel then talks-or-dispatches it).

  propose(bot_id, state, candidate, kind) -> bool
      Called by the watchers (drifting-commitment checker, idea engine) with a CANDIDATE
      contribution. The gate — not the watcher — decides whether/when it's voiced, and
      voices at most one per quiet window so proposers never pile up.

Two behaviors, one toggle (fork ①, core decision #6):
  · Manual — wake-word only (even in a 1-on-1). Mode is user intent; it never auto-switches.
  · Auto (default) — an addressed bot always answers; solo (1 human) → free conversation;
    group (N humans) → NO per-utterance replies, selective interjection comes through
    propose() from the watchers (no "want it?" consent question — fork ①).

Signals (roster, wake patterns, mute, solo detection) are read from realtime_routes; the
gate owns the DECISION, not the signals. Lazy import avoids a cycle.

Built behind PRISM_ENGAGEMENT_GATE (default off) alongside the legacy detection; the old
wake/solo/ambient paths stay until a live meeting validates this. Demolition (§7) is the
follow-up commit.
"""

from __future__ import annotations

import os
import time

_ARM_WINDOW_S = 8.0            # bare-name "Prism." → next turn from that speaker is the command
_NUDGE_QUIET_WINDOW_S = float(os.getenv("PRISM_NUDGE_QUIET_WINDOW_S", "45"))


def _rr():
    import realtime_routes as rr
    return rr


def get_mode(state: dict) -> str:
    """'auto' | 'manual'. Reads the Phase-4 toggle, migrating legacy values in place:
    the old auto state machine's 'autonomous' → auto, 'utterance' → manual. Default auto,
    so a fresh solo meeting converses out of the box (core decision #6)."""
    m = state.get("engagement_mode")
    if m in ("auto", "manual"):
        return m
    legacy = state.get("manual_mode") or state.get("mode")
    migrated = "manual" if legacy == "utterance" else "auto"
    state["engagement_mode"] = migrated
    return migrated


def set_mode(state: dict, mode: str) -> str:
    """auto | manual, from /bot/{id}/mode. Anything else maps to auto."""
    state["engagement_mode"] = "manual" if mode == "manual" else "auto"
    return state["engagement_mode"]


async def decide(bot_id: str, state: dict, text: str, speaker: str) -> tuple[bool, str]:
    rr = _rr()
    text = (text or "").strip()
    if not text or state.get("muted"):
        return (False, "")
    # Never engage on the bot's own transcribed TTS (the solo self-feedback loop).
    if rr._looks_like_bot_participant(speaker, {}):
        return (False, "")

    now = time.time()

    # Bare-name arm: "Prism." then the next turn from the same speaker is the command.
    armed_speaker = state.get("_gate_armed_speaker")
    if armed_speaker and now - state.get("_gate_armed_ts", 0.0) < _ARM_WINDOW_S:
        if not armed_speaker or armed_speaker == speaker:
            state["_gate_armed_speaker"] = None
            return (True, text)
    else:
        state["_gate_armed_speaker"] = None

    # Wake word: an addressed bot answers in BOTH modes.
    wake_cmd = rr._detect_command(text, bot_id)
    if wake_cmd:
        return (True, wake_cmd)
    if rr._has_trigger_word(text, bot_id):
        # Bare trigger with no command yet → arm for the next turn.
        state["_gate_armed_speaker"] = speaker
        state["_gate_armed_ts"] = now
        return (False, "")

    if get_mode(state) == "manual":
        return (False, "")

    # Auto mode.
    if rr._solo_mode_active(state):
        if rr._solo_freeflow_text_eligible(text):
            return (True, text)   # 1 human → free conversation (absorbed solo free-flow)
        return (False, "")

    # Auto + group: no per-utterance reply. Selective interjection arrives via propose().
    return (False, "")


def might_engage(bot_id: str, state: dict, text: str, speaker: str) -> bool:
    """Read-only "would `decide()` plausibly say yes?" — the predicate the Phase-5
    speculative call (§3) asks at EagerEndOfTurn, before the turn is confirmed.

    Deliberately NOT `decide()`: that one arms and disarms the bare-name window, and a
    speculation must never consume state the real decision still needs. Deliberately
    permissive too — a false positive costs one discarded LLM call, a false negative costs
    the whole latency win. The gate remains the only thing that can actually speak."""
    rr = _rr()
    text = (text or "").strip()
    if not text or state.get("muted"):
        return False
    if rr._looks_like_bot_participant(speaker, {}):
        return False
    if state.get("_gate_armed_speaker") and time.time() - state.get("_gate_armed_ts", 0.0) < _ARM_WINDOW_S:
        return True
    if rr._detect_command(text, bot_id) or rr._has_trigger_word(text, bot_id):
        return True
    if get_mode(state) == "manual":
        return False
    return bool(rr._solo_mode_active(state) and rr._solo_freeflow_text_eligible(text))


async def propose(bot_id: str, state: dict, candidate: str, kind: str = "nudge", speak: bool = False) -> bool:
    """A watcher's candidate contribution (drift nudge, idea-engine insight). Voiced only
    if: not muted, mode is Auto, and no other nudge fired inside the quiet window — so
    proposers never pile up. Chat-only by default: today's proactive nudges are gentle
    meta-hints ('say Prism, summarize…') that read wrong spoken aloud. `speak=True` opts a
    genuine spoken contribution in; keep it off for meta-nudges. Spoken-proactive tuning is
    a `docs/future-ideas.md` item ('should I speak' judge)."""
    rr = _rr()
    candidate = (candidate or "").strip()
    if not candidate or state.get("muted"):
        return False
    if get_mode(state) == "manual":
        return False
    now = time.time()
    if now - state.get("_gate_last_nudge_ts", 0.0) < _NUDGE_QUIET_WINDOW_S:
        return False
    state["_gate_last_nudge_ts"] = now
    try:
        await rr._send_chat_response(bot_id, candidate)
    except Exception as exc:
        print(f"[gate] propose chat failed: {exc}")
    if speak:
        try:
            from voice import voice_channel
            await voice_channel._speak(bot_id, rr._spoken_condense(candidate))
        except Exception as exc:
            print(f"[gate] propose speak failed: {exc}")
    print(f"[gate] proposed bot={bot_id[:8]} kind={kind} speak={speak} text={candidate[:80]!r}")
    return True


# ── self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio, sys, types

    class _FakeRR(types.ModuleType):
        def _looks_like_bot_participant(self, name, raw): return name.lower() in ("prism", "prismai")
        def _detect_command(self, text, bot_id):
            low = text.lower()
            if low.startswith("prism"):
                rest = text.split(None, 1)
                return rest[1].lstrip(",. ") if len(rest) > 1 else None
            return None
        def _has_trigger_word(self, text, bot_id): return "prism" in text.lower()
        def _solo_mode_active(self, state): return state.get("_humans", 2) <= 1
        def _solo_freeflow_text_eligible(self, text): return len(text.split()) >= 3
    sys.modules["realtime_routes"] = _FakeRR("realtime_routes")

    async def _main():
        # Manual: only wake words.
        st = {"engagement_mode": "manual", "_humans": 1}
        assert await decide("b", st, "what did we decide", "A") == (False, "")
        assert (await decide("b", st, "Prism, summarize", "A"))[0] is True
        # Auto solo: free conversation.
        st = {"engagement_mode": "auto", "_humans": 1}
        assert (await decide("b", st, "what did we decide", "A"))[0] is True
        # Auto group: no per-utterance reply unless addressed.
        st = {"engagement_mode": "auto", "_humans": 3}
        assert await decide("b", st, "we should ship friday", "A") == (False, "")
        assert (await decide("b", st, "Prism what's the risk", "A"))[0] is True
        # Bare-name arm → next turn is the command.
        st = {"engagement_mode": "auto", "_humans": 3}
        assert await decide("b", st, "Prism.", "A") == (False, "")
        assert (await decide("b", st, "summarize the last point", "A"))[0] is True
        # Mute hard-stops.
        assert await decide("b", {"muted": True}, "Prism, help", "A") == (False, "")

        # might_engage mirrors decide's verdict WITHOUT consuming the arm window.
        st = {"engagement_mode": "auto", "_humans": 3}
        assert might_engage("b", st, "Prism what's the risk", "A") is True
        assert might_engage("b", st, "we should ship friday", "A") is False
        st = {"engagement_mode": "auto", "_humans": 1}
        assert might_engage("b", st, "what did we decide", "A") is True
        assert might_engage("b", {"engagement_mode": "manual", "_humans": 1},
                            "what did we decide", "A") is False
        assert might_engage("b", {"muted": True}, "Prism, help", "A") is False
        # The arm survives a speculation: decide() must still see it on the real turn.
        st = {"engagement_mode": "auto", "_humans": 3}
        await decide("b", st, "Prism.", "A")
        assert might_engage("b", st, "summarize the last point", "A") is True
        assert (await decide("b", st, "summarize the last point", "A"))[0] is True
        print("gate self-check OK")

    asyncio.run(_main())

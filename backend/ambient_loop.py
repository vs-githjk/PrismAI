"""Ambient response loop — no-wake-word autonomous mode for the live bot.

A staged cost funnel: free recall gate → 8B decider → (existing) 70B generator →
TTS, gated by a utterance⇄autonomous mode state machine. Pure logic + the decider
model call; the generator/idea-engine are injected as callables by realtime_routes
so this module never imports realtime_routes (no circular import).

Flags:
  PRISM_AUTONOMOUS=1         enables autonomous mode (utterance mode = current prod)
  PRISM_AUTONOMOUS_SHADOW=1  run the funnel + log decisions, but NEVER speak

Spec: docs/superpowers/specs/2026-06-07-ambient-response-loop-design.md
"""

from __future__ import annotations

import json
import os
import re
import time

from clients import get_groq
import meeting_memory
import perception_state
import cross_meeting_service
from agents.utils import strip_fences

# ── Tunable constants ─────────────────────────────────────────────────────────
ACTIVE_WINDOW_S = 20.0          # window for "active cross-talk" detection
ACTIVE_UTTERANCE_COUNT = 3      # utterances within the window ⇒ active cross-talk
MODERATE_NO_FLOOR = 0.4         # decider "no" at/above this conf ⇒ Idea Engine handoff


# ── Flags / env-tunable params ────────────────────────────────────────────────
def autonomous_enabled() -> bool:
    return os.getenv("PRISM_AUTONOMOUS") == "1"

def shadow_mode() -> bool:
    return os.getenv("PRISM_AUTONOMOUS_SHADOW") == "1"

def decider_model() -> str:
    return os.getenv("PRISM_DECIDER_MODEL", "llama-3.1-8b-instant")

def decider_threshold() -> float:
    return float(os.getenv("PRISM_DECIDER_THRESHOLD", "0.7"))

def cooldown_s() -> float:
    return float(os.getenv("PRISM_AMBIENT_COOLDOWN_S", "40"))

def pause_debounce_s() -> float:
    return float(os.getenv("PRISM_PAUSE_DEBOUNCE_S", "8"))

def lull_threshold_s() -> float:
    return float(os.getenv("PRISM_LULL_THRESHOLD_S", "35"))

def autonomy_cap_s() -> float:
    return float(os.getenv("PRISM_AUTONOMY_CAP_S", "300"))


# ── Mode state machine ────────────────────────────────────────────────────────
# Handoff: "prism" + a delegation verb. Reuses the wake-word cousins loosely.
_HANDOFF_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+"
    r"(?:run with (?:this|it)|take it from here|take over|take this|you (?:take|drive|handle|run)|"
    r"handle (?:this|it)|drive|go ahead and run)\b",
    re.IGNORECASE,
)
# Explicit stop addressed to prism (separate from perception_state.is_stop_command,
# which also catches "shut up"/"quiet"; we accept either).
_STOP_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+(?:stop|that'?s enough|we'?re good|stand down|back off)\b",
    re.IGNORECASE,
)


def _enter(state: dict, mode: str, reason: str, now: float, renew: bool) -> str:
    """Set mode + reason; bump the shift counter only on an actual mode change."""
    changed = state.get("mode") != mode
    state["mode"] = mode
    state["mode_entry_reason"] = reason
    if changed or renew:
        state["mode_since_ts"] = now
    if changed:
        perception_state.bump(state, "ambient_mode_shifts")
    return mode


# ── Stage 1: free recall gate ─────────────────────────────────────────────────
_REQUEST_RE = re.compile(
    r"\b(can|could|would|should|let'?s|we need|i need|do we|please|"
    r"how do|how should|what'?s the|any idea|anyone know)\b",
    re.IGNORECASE,
)


def recall_gate(state: dict, utterance_text: str, now: float) -> bool:
    """High-recall, ~free pre-filter. Fires the decider when an utterance plausibly
    contains an opening, OR on a debounced pause tick (so the decider gets a
    periodic shot at implicit openings). Tuned to over-fire; the decider is the
    precision stage.
    """
    text = utterance_text or ""
    low = text.lower()
    if "?" in text:
        return True
    if set(re.findall(r"\b\w+\b", low)) & meeting_memory._QUESTION_WORDS:
        return True
    if _REQUEST_RE.search(low):
        return True
    if cross_meeting_service.looks_like_blocker(text):
        return True
    if meeting_memory.DECISION_PATTERN.search(text) or meeting_memory.ACTION_ITEM_PATTERN.search(text):
        return True
    # Debounced pause tick — periodic shot at implicit openings.
    if (now - state.get("_ambient_last_gate_ts", 0.0)) >= pause_debounce_s():
        return True
    return False


def check_lull(state: dict, now: float) -> str | None:
    """Called from the accumulator tick loop (NOT on an utterance). If the
    meeting has been active but silent for > lull_threshold_s and we're in
    utterance mode, shift to autonomous (reason=lull). Returns the new mode
    on a shift, else None. The next utterance is then evaluated through the
    funnel; lull-entered autonomous reverts on active cross-talk (update_mode).
    """
    if state.get("manual_mode") in ("utterance", "autonomous"):
        return None
    if state.get("mode") != "utterance":
        return None
    if not state.get("meeting_start_ts"):
        return None
    last = state.get("last_activity_ts", 0.0)
    if last <= 0:
        return None
    if (now - last) <= lull_threshold_s():
        return None
    return _enter(state, "autonomous", "lull", now, renew=True)


def update_mode(state: dict, utterance_text: str, speaker_name: str, now: float) -> str:
    """Detect handoff / stop / cap / lull-revert on a completed utterance.
    Mutates + returns state['mode'] ('utterance' | 'autonomous'). Also records
    activity for lull/active-crosstalk tracking. Honors a manual override.
    """
    # Activity tracking (drives lull + active-cross-talk detection).
    state["last_activity_ts"] = now
    rec = state.setdefault("recent_utterance_ts", [])
    rec.append(now)
    cutoff = now - ACTIVE_WINDOW_S
    state["recent_utterance_ts"] = [t for t in rec if t >= cutoff]

    # Manual override wins unconditionally.
    manual = state.get("manual_mode")
    if manual in ("utterance", "autonomous"):
        return _enter(state, manual, "manual", now, renew=False)

    text = (utterance_text or "")
    mode = state.get("mode", "utterance")

    # Explicit stop → utterance.
    if _STOP_RE.search(text) or perception_state.is_stop_command(text):
        return _enter(state, "utterance", "", now, renew=False)

    # Explicit handoff → autonomous (renews the autonomy cap window).
    if _HANDOFF_RE.search(text):
        return _enter(state, "autonomous", "handoff", now, renew=True)

    # Autonomy cap → revert.
    if mode == "autonomous" and (now - state.get("mode_since_ts", now)) > autonomy_cap_s():
        return _enter(state, "utterance", "", now, renew=False)

    # Lull-entered autonomous reverts when active cross-talk resumes.
    if (
        mode == "autonomous"
        and state.get("mode_entry_reason") == "lull"
        and len(state["recent_utterance_ts"]) >= ACTIVE_UTTERANCE_COUNT
    ):
        return _enter(state, "utterance", "", now, renew=False)

    return mode

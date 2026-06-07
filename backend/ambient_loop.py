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

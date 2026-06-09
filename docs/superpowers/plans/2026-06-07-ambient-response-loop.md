# Ambient Response Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a no-wake-word "autonomous" mode to the live bot — a staged cost funnel (free recall gate → 8B decider → existing 70B generator → TTS) that decides on its own when to speak, gated by a utterance⇄autonomous mode state machine, shipped behind flags with a shadow-soak.

**Architecture:** One new pure-logic module `backend/ambient_loop.py` (mode machine, recall gate, decider, orchestration) wired into the existing accumulator flush callback `_emit_utterance` in `realtime_routes.py`. The generator, tools, verb-gate, TTS, memory, and Idea Engine are reused unchanged. The decider calls Groq's `llama-3.1-8b-instant` directly (because `agents.utils.llm_call` is hardcoded to the 70B model). Utterance mode = today's behavior with the ambient branch off; autonomous = ambient branch on.

**Tech Stack:** Python 3 / FastAPI / asyncio, Groq SDK (`clients.get_groq`), `unittest` (+ `IsolatedAsyncioTestCase` for async), pytest runner.

**Spec:** `docs/superpowers/specs/2026-06-07-ambient-response-loop-design.md`

---

## File structure

| File | Responsibility |
|------|----------------|
| `backend/ambient_loop.py` | **New.** Flags/params, mode state machine (`update_mode`, `check_lull`), free recall gate (`recall_gate`), decider (`parse_decider_output`, `_call_decider_model`, `decide`), orchestration (`evaluate`). No import of `realtime_routes` (avoids circular import; callables are injected). |
| `backend/meeting_memory.py` | **Modify.** Add ambient/mode bookkeeping fields to `get_initial_memory_state()`; surface `mode`/`mode_entry_reason` in `get_memory_snapshot()`. |
| `backend/perception_state.py` | **Modify.** Add ambient counter keys to `_DEFAULT_COUNTERS` + `_OPERATIONAL_KEYS`. |
| `backend/realtime_routes.py` | **Modify.** Ambient framing in `_process_command(..., ambient=False)`; `_ambient_on_utterance` + `_ambient_run_generator` + `_ambient_surface_idea` wrappers; hook in `_emit_utterance`; lull check in `_accumulator_tick_loop`; `POST /bot/{bot_id}/mode` override endpoint. |
| `backend/tests/test_ambient_loop.py` | **New.** Unit tests for the mode machine, recall gate, decider parser, decider (mocked), orchestration (mocked). |
| `backend/tests/test_ambient_wiring.py` | **New.** Routing tests for `_ambient_on_utterance`, the ambient framing helpers, and the override endpoint. |

**Test command (run from `backend/`):** `python -m pytest tests/test_ambient_loop.py tests/test_ambient_wiring.py -v`

---

## Task 1: Ambient state fields, counters, and snapshot surfacing

**Files:**
- Modify: `backend/meeting_memory.py` (`get_initial_memory_state`, `get_memory_snapshot`)
- Modify: `backend/perception_state.py` (`_DEFAULT_COUNTERS`, `_OPERATIONAL_KEYS`)
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ambient_loop.py`:

```python
"""Unit tests for ambient_loop: state, mode machine, recall gate, decider, orchestration."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import meeting_memory  # noqa: E402
import perception_state  # noqa: E402


class StateFieldTests(unittest.TestCase):
    def test_initial_state_has_ambient_fields(self):
        s = meeting_memory.get_initial_memory_state()
        self.assertEqual(s["mode"], "utterance")
        self.assertEqual(s["mode_entry_reason"], "")
        self.assertEqual(s["mode_since_ts"], 0.0)
        self.assertIsNone(s["manual_mode"])
        self.assertEqual(s["last_activity_ts"], 0.0)
        self.assertEqual(s["recent_utterance_ts"], [])
        self.assertEqual(s["ambient_last_spoke_ts"], 0.0)
        self.assertFalse(s["_ambient_evaluating"])

    def test_counters_include_ambient_keys(self):
        s = {}
        c = perception_state.ensure_counters(s)
        for key in (
            "ambient_gate_fires", "ambient_decider_yes", "ambient_decider_no",
            "ambient_spoke", "ambient_suppressed_decline", "ambient_mode_shifts",
            "ambient_shadow_would_speak", "ambient_idea_handoff",
        ):
            self.assertEqual(c[key], 0)
        ops = perception_state.operational_counters(s)
        self.assertIn("ambient_gate_fires", ops)

    def test_snapshot_surfaces_mode(self):
        s = meeting_memory.get_initial_memory_state()
        s["transcript_buffer"] = []
        s["mode"] = "autonomous"
        s["mode_entry_reason"] = "handoff"
        snap = meeting_memory.get_memory_snapshot(s)
        self.assertEqual(snap["mode"], "autonomous")
        self.assertEqual(snap["mode_entry_reason"], "handoff")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::StateFieldTests -v`
Expected: FAIL — `KeyError: 'mode'` (fields not yet added).

- [ ] **Step 3: Add the fields, counters, and snapshot keys**

In `backend/meeting_memory.py`, inside `get_initial_memory_state()`, add to the returned dict (after the `gaps_flagged` entry, before the closing `}`):

```python
        # ── Ambient response loop (mode machine + funnel) ─────────────────────
        "mode": "utterance",            # 'utterance' | 'autonomous'
        "mode_entry_reason": "",        # '' | 'lull' | 'handoff' | 'manual'
        "mode_since_ts": 0.0,           # wall-clock ts the current mode was entered
        "manual_mode": None,            # owner override: None | 'utterance' | 'autonomous'
        "last_activity_ts": 0.0,        # last utterance-flush ts (for lull detection)
        "recent_utterance_ts": [],      # rolling flush ts within ACTIVE_WINDOW_S
        "ambient_last_spoke_ts": 0.0,   # last unsolicited spoken response ts
        "_ambient_last_gate_ts": 0.0,   # last recall-gate pass (pause debounce)
        "_ambient_evaluating": False,   # mutex — one funnel eval at a time per bot
```

In `backend/meeting_memory.py`, inside `get_memory_snapshot()`, add to the top-level returned dict (alongside `memory_summary`):

```python
        "mode": state.get("mode") or "utterance",
        "mode_entry_reason": state.get("mode_entry_reason") or "",
```

In `backend/perception_state.py`, add to `_DEFAULT_COUNTERS` (after `"accumulator_evictions": 0,`):

```python
    # Ambient response loop
    "ambient_gate_fires": 0,
    "ambient_decider_yes": 0,
    "ambient_decider_no": 0,
    "ambient_spoke": 0,
    "ambient_suppressed_decline": 0,
    "ambient_mode_shifts": 0,
    "ambient_shadow_would_speak": 0,
    "ambient_idea_handoff": 0,
```

In `backend/perception_state.py`, append these keys to the `_OPERATIONAL_KEYS` tuple (before the closing `)`):

```python
    "ambient_gate_fires",
    "ambient_decider_yes",
    "ambient_decider_no",
    "ambient_spoke",
    "ambient_suppressed_decline",
    "ambient_mode_shifts",
    "ambient_shadow_would_speak",
    "ambient_idea_handoff",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::StateFieldTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/meeting_memory.py backend/perception_state.py backend/tests/test_ambient_loop.py
git commit -m "Add ambient-loop state fields, counters, and snapshot surfacing"
```

---

## Task 2: Create `ambient_loop.py` with flags and tunable params

**Files:**
- Create: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class FlagTests(unittest.TestCase):
    def test_flags_default_off(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ambient_loop.autonomous_enabled())
            self.assertFalse(ambient_loop.shadow_mode())

    def test_flags_on(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS": "1", "PRISM_AUTONOMOUS_SHADOW": "1"}):
            self.assertTrue(ambient_loop.autonomous_enabled())
            self.assertTrue(ambient_loop.shadow_mode())

    def test_param_defaults(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ambient_loop.decider_model(), "llama-3.1-8b-instant")
            self.assertEqual(ambient_loop.decider_threshold(), 0.7)
            self.assertEqual(ambient_loop.cooldown_s(), 40.0)
            self.assertEqual(ambient_loop.pause_debounce_s(), 8.0)
            self.assertEqual(ambient_loop.lull_threshold_s(), 35.0)
            self.assertEqual(ambient_loop.autonomy_cap_s(), 300.0)

    def test_param_override(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {"PRISM_DECIDER_THRESHOLD": "0.55"}):
            self.assertEqual(ambient_loop.decider_threshold(), 0.55)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::FlagTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ambient_loop'`.

- [ ] **Step 3: Create the module**

Create `backend/ambient_loop.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::FlagTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Create ambient_loop module with flags and tunable params"
```

---

## Task 3: Mode state machine (`update_mode`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class UpdateModeTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["meeting_start_ts"] = 1000.0

    def test_handoff_enters_autonomous(self):
        import ambient_loop
        mode = ambient_loop.update_mode(self.s, "Prism, take it from here", "Abhinav", 1100.0)
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "handoff")

    def test_plain_utterance_stays_utterance(self):
        import ambient_loop
        mode = ambient_loop.update_mode(self.s, "I think the numbers look fine", "Abhinav", 1100.0)
        self.assertEqual(mode, "utterance")

    def test_stop_reverts_to_utterance(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, run with this", "Abhinav", 1100.0)
        mode = ambient_loop.update_mode(self.s, "Prism, stop", "Abhinav", 1110.0)
        self.assertEqual(mode, "utterance")

    def test_manual_override_wins(self):
        import ambient_loop
        self.s["manual_mode"] = "autonomous"
        mode = ambient_loop.update_mode(self.s, "just a normal sentence", "Abhinav", 1100.0)
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "manual")

    def test_autonomy_cap_reverts(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, run with this", "Abhinav", 1100.0)
        mode = ambient_loop.update_mode(self.s, "still going", "Abhinav", 1100.0 + 400.0)
        self.assertEqual(mode, "utterance")

    def test_lull_entered_reverts_on_active_crosstalk(self):
        import ambient_loop
        # Simulate lull-entered autonomous
        self.s["mode"] = "autonomous"
        self.s["mode_entry_reason"] = "lull"
        self.s["mode_since_ts"] = 1100.0
        # 3 utterances within the active window ⇒ revert
        ambient_loop.update_mode(self.s, "a", "X", 1101.0)
        ambient_loop.update_mode(self.s, "b", "Y", 1102.0)
        mode = ambient_loop.update_mode(self.s, "c", "Z", 1103.0)
        self.assertEqual(mode, "utterance")

    def test_handoff_entered_persists_through_activity(self):
        import ambient_loop
        ambient_loop.update_mode(self.s, "Prism, take it from here", "Abhinav", 1100.0)
        ambient_loop.update_mode(self.s, "a", "X", 1101.0)
        ambient_loop.update_mode(self.s, "b", "Y", 1102.0)
        mode = ambient_loop.update_mode(self.s, "c", "Z", 1103.0)
        self.assertEqual(mode, "autonomous")  # handoff persists
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::UpdateModeTests -v`
Expected: FAIL — `AttributeError: module 'ambient_loop' has no attribute 'update_mode'`.

- [ ] **Step 3: Implement `update_mode`**

Append to `backend/ambient_loop.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::UpdateModeTests -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add ambient mode state machine (update_mode)"
```

---

## Task 4: Lull detection (`check_lull`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class CheckLullTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["meeting_start_ts"] = 1000.0
        self.s["last_activity_ts"] = 1000.0

    def test_lull_shifts_to_autonomous(self):
        import ambient_loop
        mode = ambient_loop.check_lull(self.s, 1000.0 + 40.0)  # > 35s silence
        self.assertEqual(mode, "autonomous")
        self.assertEqual(self.s["mode_entry_reason"], "lull")

    def test_no_lull_when_recent_activity(self):
        import ambient_loop
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 10.0))

    def test_no_lull_when_already_autonomous(self):
        import ambient_loop
        self.s["mode"] = "autonomous"
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))

    def test_no_lull_before_meeting_start(self):
        import ambient_loop
        self.s["meeting_start_ts"] = None
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))

    def test_manual_override_blocks_lull(self):
        import ambient_loop
        self.s["manual_mode"] = "utterance"
        self.assertIsNone(ambient_loop.check_lull(self.s, 1000.0 + 40.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::CheckLullTests -v`
Expected: FAIL — `AttributeError: ... has no attribute 'check_lull'`.

- [ ] **Step 3: Implement `check_lull`**

Append to `backend/ambient_loop.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::CheckLullTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add lull detection (check_lull) for ambient mode shift"
```

---

## Task 5: Free recall gate (`recall_gate`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class RecallGateTests(unittest.TestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()

    def test_question_mark_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "What was our Q3 revenue?", 100.0))

    def test_question_word_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "who owns the migration", 100.0))

    def test_request_phrase_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "can you pull up the doc", 100.0))

    def test_decision_pattern_fires(self):
        import ambient_loop
        self.assertTrue(ambient_loop.recall_gate(self.s, "we decided to ship Friday", 100.0))

    def test_plain_statement_misses_within_debounce(self):
        import ambient_loop
        self.s["_ambient_last_gate_ts"] = 100.0
        self.assertFalse(ambient_loop.recall_gate(self.s, "the weather is nice today", 101.0))

    def test_plain_statement_fires_after_debounce(self):
        import ambient_loop
        self.s["_ambient_last_gate_ts"] = 100.0
        self.assertTrue(ambient_loop.recall_gate(self.s, "the weather is nice today", 100.0 + 9.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::RecallGateTests -v`
Expected: FAIL — `AttributeError: ... has no attribute 'recall_gate'`.

- [ ] **Step 3: Implement `recall_gate`**

Append to `backend/ambient_loop.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::RecallGateTests -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add free recall gate (Stage 1) for ambient funnel"
```

---

## Task 6: Decider output parser (`parse_decider_output`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class ParseDeciderTests(unittest.TestCase):
    def test_clean_json(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('{"respond": true, "confidence": 0.82, "reason": "open question"}')
        self.assertTrue(out["respond"])
        self.assertEqual(out["confidence"], 0.82)
        self.assertEqual(out["reason"], "open question")

    def test_fenced_json(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('```json\n{"respond": false, "confidence": 0.1, "reason": "chit-chat"}\n```')
        self.assertFalse(out["respond"])

    def test_json_with_prose_around_it(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('Sure! {"respond": true, "confidence": 0.9, "reason": "x"} hope that helps')
        self.assertTrue(out["respond"])

    def test_garbage_fails_safe_silent(self):
        import ambient_loop
        for bad in ["", None, "respond yes", "{not json", "{}", '{"confidence": 0.9}']:
            out = ambient_loop.parse_decider_output(bad)
            self.assertFalse(out["respond"])
            self.assertEqual(out["confidence"], 0.0)

    def test_confidence_clamped(self):
        import ambient_loop
        out = ambient_loop.parse_decider_output('{"respond": true, "confidence": 5, "reason": "x"}')
        self.assertEqual(out["confidence"], 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::ParseDeciderTests -v`
Expected: FAIL — `AttributeError: ... has no attribute 'parse_decider_output'`.

- [ ] **Step 3: Implement `parse_decider_output`**

Append to `backend/ambient_loop.py`:

```python
# ── Stage 2: decider ──────────────────────────────────────────────────────────
def parse_decider_output(raw: str | None) -> dict:
    """Parse the decider's reply into {respond, confidence, reason}. ANY drift
    (empty, non-JSON, missing/!bool respond) fails safe to respond=False."""
    fallback = {"respond": False, "confidence": 0.0, "reason": "parse_failed"}
    if not raw or not isinstance(raw, str):
        return fallback
    s = strip_fences(raw).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return fallback
    try:
        obj = json.loads(s[start:end + 1])
    except Exception:
        return fallback
    if not isinstance(obj, dict) or not isinstance(obj.get("respond"), bool):
        return fallback
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "respond": obj["respond"],
        "confidence": conf,
        "reason": str(obj.get("reason", ""))[:200],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::ParseDeciderTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add fail-safe decider output parser"
```

---

## Task 7: Decider call (`decide`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class DecideTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["transcript_buffer"] = ["Abhinav: what's our Q3 number?"]

    async def test_decide_parses_model_output(self):
        import ambient_loop
        async def fake_call(system, user):
            return '{"respond": true, "confidence": 0.8, "reason": "open question"}'
        with mock.patch.object(ambient_loop, "_call_decider_model", fake_call):
            out = await ambient_loop.decide(self.s)
        self.assertTrue(out["respond"])
        self.assertEqual(out["confidence"], 0.8)

    async def test_decide_model_error_fails_safe(self):
        import ambient_loop
        async def boom(system, user):
            raise RuntimeError("groq down")
        with mock.patch.object(ambient_loop, "_call_decider_model", boom):
            out = await ambient_loop.decide(self.s)
        self.assertFalse(out["respond"])
        self.assertEqual(out["reason"], "decider_error")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::DecideTests -v`
Expected: FAIL — `AttributeError: ... has no attribute 'decide'`.

- [ ] **Step 3: Implement `_call_decider_model`, signal summary, and `decide`**

Append to `backend/ambient_loop.py`:

```python
_DECIDER_SYSTEM = (
    "You are the response gate for an AI meeting assistant that is listening "
    "silently. Decide ONLY whether the assistant should speak right now. Say yes "
    "only when there is a clear, helpful, NON-interrupting contribution: an "
    "unanswered question it can answer, a relevant fact to surface, or a real "
    "risk to flag. Default to staying silent for chit-chat, rhetorical questions, "
    "or anything already being handled by the people talking.\n"
    "Respond with JSON ONLY, no prose: "
    '{"respond": <true|false>, "confidence": <0.0-1.0>, "reason": "<short>"}'
)


def _signal_summary(state: dict) -> str:
    """Cheap structured signals fed to the decider alongside the memory context."""
    decisions = state.get("live_decisions") or []
    actions = state.get("live_action_items") or []
    entities = state.get("live_entities") or {}
    top = ", ".join(w for w, _ in entities.most_common(8)) if hasattr(entities, "most_common") else ""
    return (
        f"decisions_so_far={len(decisions)} action_items={len(actions)}\n"
        f"key_topics: {top}"
    )


async def _call_decider_model(system: str, user: str) -> str:
    """The only I/O in the decider. Calls Groq directly (llm_call is hardcoded to
    70B) so we can run the cheap 8B model. Isolated for easy test mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=decider_model(),
        temperature=0.1,
        max_tokens=120,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def decide(state: dict) -> dict:
    """Stage 2: should the assistant speak now? Returns {respond, confidence, reason}.
    Fed the rolling memory context + cheap signals — not a generated candidate."""
    context = meeting_memory.build_memory_context(state)
    user = (
        f"{context}\n\n[SIGNALS]\n{_signal_summary(state)}\n\n"
        "[TASK] Should the assistant speak now? JSON only."
    )
    try:
        raw = await _call_decider_model(_DECIDER_SYSTEM, user)
    except Exception as e:  # fail-safe silent on any model/transport error
        print(f"[ambient] decider error: {e}")
        return {"respond": False, "confidence": 0.0, "reason": "decider_error"}
    return parse_decider_output(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::DecideTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add ambient decider call (8B via direct Groq, fail-safe)"
```

---

## Task 8: Orchestration (`evaluate`)

**Files:**
- Modify: `backend/ambient_loop.py`
- Test: `backend/tests/test_ambient_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_loop.py`:

```python
class EvaluateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.s = meeting_memory.get_initial_memory_state()
        self.s["transcript_buffer"] = ["Abhinav: what's our Q3 number?"]
        self.spoke = []
        self.ideas = []

    async def _gen(self, bot_id, utterance, speaker):
        self.spoke.append((utterance, speaker))
        return "Our Q3 number was 4.2M."

    async def _gen_silent(self, bot_id, utterance, speaker):
        self.spoke.append((utterance, speaker))
        return None

    async def _idea(self, bot_id, state):
        self.ideas.append(bot_id)

    def _patch_decide(self, result):
        import ambient_loop
        async def fake(state):
            return result
        return mock.patch.object(ambient_loop, "decide", fake)

    async def test_gate_miss_returns_early(self):
        import ambient_loop
        self.s["_ambient_last_gate_ts"] = 100.0
        out = await ambient_loop.evaluate(
            "bot1", self.s, "nice weather", "X",
            run_generator=self._gen, surface_idea=self._idea, now=101.0,
        )
        self.assertEqual(out["action"], "gate_miss")
        self.assertEqual(self.spoke, [])

    async def test_yes_speaks(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": True, "confidence": 0.9, "reason": "q"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "spoke")
        self.assertEqual(len(self.spoke), 1)
        self.assertEqual(self.s["ambient_last_spoke_ts"], 200.0)

    async def test_below_threshold_silent(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": True, "confidence": 0.5, "reason": "meh"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "below_threshold")
        self.assertEqual(self.spoke, [])

    async def test_moderate_no_routes_to_idea_engine(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": False, "confidence": 0.5, "reason": "maybe"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "idea")
        self.assertEqual(self.ideas, ["bot1"])

    async def test_low_no_stays_silent(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": False, "confidence": 0.1, "reason": "chit-chat"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "silent")
        self.assertEqual(self.ideas, [])

    async def test_shadow_never_speaks(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS_SHADOW": "1"}, clear=True), \
             self._patch_decide({"respond": True, "confidence": 0.95, "reason": "q"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "shadow")
        self.assertEqual(self.spoke, [])

    async def test_cooldown_blocks_speak(self):
        import ambient_loop
        self.s["ambient_last_spoke_ts"] = 190.0  # 10s ago, < 40s cooldown
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": True, "confidence": 0.95, "reason": "q"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "cooldown")
        self.assertEqual(self.spoke, [])

    async def test_generator_decline_suppressed(self):
        import ambient_loop
        with mock.patch.dict(os.environ, {}, clear=True), \
             self._patch_decide({"respond": True, "confidence": 0.95, "reason": "q"}):
            out = await ambient_loop.evaluate(
                "bot1", self.s, "what's our Q3 number?", "Abhinav",
                run_generator=self._gen_silent, surface_idea=self._idea, now=200.0,
            )
        self.assertEqual(out["action"], "declined")
        self.assertNotEqual(self.s["ambient_last_spoke_ts"], 200.0)

    async def test_mutex_blocks_concurrent(self):
        import ambient_loop
        self.s["_ambient_evaluating"] = True
        out = await ambient_loop.evaluate(
            "bot1", self.s, "what's our Q3 number?", "Abhinav",
            run_generator=self._gen, surface_idea=self._idea, now=200.0,
        )
        self.assertEqual(out["action"], "busy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_loop.py::EvaluateTests -v`
Expected: FAIL — `AttributeError: ... has no attribute 'evaluate'`.

- [ ] **Step 3: Implement `evaluate`**

Append to `backend/ambient_loop.py`:

```python
# ── Orchestration ─────────────────────────────────────────────────────────────
async def evaluate(
    bot_id: str,
    state: dict,
    utterance_text: str,
    speaker: str,
    *,
    run_generator,        # async (bot_id, utterance, speaker) -> str | None (spoken text)
    surface_idea,         # async (bot_id, state) -> None
    now: float | None = None,
) -> dict:
    """Run the funnel for one utterance (autonomous mode only — caller checks mode).
    recall_gate → decide → guards → generator → TTS. Returns an action dict for
    observability/tests. Never raises into the caller's create_task."""
    now = time.time() if now is None else now
    if state.get("_ambient_evaluating"):
        return {"action": "busy"}
    if not recall_gate(state, utterance_text, now):
        return {"action": "gate_miss"}
    state["_ambient_last_gate_ts"] = now
    perception_state.bump(state, "ambient_gate_fires")

    state["_ambient_evaluating"] = True
    try:
        decision = await decide(state)
        conf = decision["confidence"]

        if not decision["respond"]:
            perception_state.bump(state, "ambient_decider_no")
            if conf >= MODERATE_NO_FLOOR:
                perception_state.bump(state, "ambient_idea_handoff")
                try:
                    await surface_idea(bot_id, state)
                except Exception as e:
                    print(f"[ambient] idea handoff error: {e}")
                return {"action": "idea", "confidence": conf}
            return {"action": "silent", "confidence": conf}

        # respond == True
        perception_state.bump(state, "ambient_decider_yes")
        if conf < decider_threshold():
            return {"action": "below_threshold", "confidence": conf}
        if shadow_mode():
            perception_state.bump(state, "ambient_shadow_would_speak")
            print(f"[ambient] SHADOW would speak bot={bot_id[:8]} conf={conf:.2f} reason={decision['reason']!r}")
            return {"action": "shadow", "confidence": conf}
        if (now - state.get("ambient_last_spoke_ts", 0.0)) < cooldown_s():
            return {"action": "cooldown", "confidence": conf}

        spoken = await run_generator(bot_id, utterance_text, speaker)
        if spoken:
            state["ambient_last_spoke_ts"] = now
            perception_state.bump(state, "ambient_spoke")
            return {"action": "spoke", "confidence": conf}
        perception_state.bump(state, "ambient_suppressed_decline")
        return {"action": "declined", "confidence": conf}
    finally:
        state["_ambient_evaluating"] = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_loop.py::EvaluateTests -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_loop.py
git commit -m "Add ambient funnel orchestration (evaluate)"
```

---

## Task 9: Wire into `realtime_routes` (framing helpers, hook, tick lull)

**Files:**
- Modify: `backend/realtime_routes.py` (imports; `_process_command` ambient framing; `_emit_utterance` hook; `_ambient_*` wrappers; `_accumulator_tick_loop` lull check)
- Test: `backend/tests/test_ambient_wiring.py`

- [ ] **Step 1: Write the failing test (framing helpers + routing)**

Create `backend/tests/test_ambient_wiring.py`:

```python
"""Wiring tests for the ambient loop in realtime_routes."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import realtime_routes  # noqa: E402


class AmbientSilentHelperTests(unittest.TestCase):
    def test_silent_detection(self):
        self.assertTrue(realtime_routes._is_ambient_silent("SILENT"))
        self.assertTrue(realtime_routes._is_ambient_silent("  silent.  "))
        self.assertFalse(realtime_routes._is_ambient_silent("Our Q3 number was 4.2M."))
        self.assertFalse(realtime_routes._is_ambient_silent(""))

    def test_preamble_nonempty(self):
        self.assertIn("SILENT", realtime_routes._AMBIENT_PREAMBLE)


class FakeUtterance:
    def __init__(self, text, speaker_name="Abhinav"):
        self.text = text
        self.speaker_name = speaker_name
        self.speaker_id = "sid"
        self.utterance_id = "uid"
        self.word_count = len(text.split())
        self.chunk_count = 1
        self.duration_ms = 1000
        self.flush_reason = "pause"


class AmbientOnUtteranceRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = realtime_routes.meeting_memory.get_initial_memory_state()
        self.state["transcript_buffer"] = []
        self.state["meeting_start_ts"] = 1000.0

    async def test_explicit_command_skips_ambient(self):
        # "prism, ..." is handled by the command path, not the ambient funnel.
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        self.state["mode"] = "autonomous"
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("Prism, send the email")
            )
        self.assertEqual(called, [])

    async def test_utterance_mode_skips_ambient(self):
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        # plain utterance keeps us in utterance mode → no ambient eval
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("the numbers look fine to me")
            )
        self.assertEqual(called, [])

    async def test_autonomous_mode_runs_ambient(self):
        called = []
        async def fake_eval(*a, **k):
            called.append(True)
            return {"action": "spoke"}
        self.state["mode"] = "autonomous"
        self.state["mode_entry_reason"] = "handoff"
        self.state["mode_since_ts"] = 1000.0
        with mock.patch.object(realtime_routes.ambient_loop, "evaluate", fake_eval):
            await realtime_routes._ambient_on_utterance(
                "bot1", self.state, FakeUtterance("what was our Q3 number")
            )
        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_wiring.py -v`
Expected: FAIL — `AttributeError: module 'realtime_routes' has no attribute '_is_ambient_silent'`.

- [ ] **Step 3a: Add the import and framing helpers**

In `backend/realtime_routes.py`, add to the imports block (near the other local imports, after `import think_loop`):

```python
import ambient_loop
```

Add the ambient framing helpers near the other module-level helpers (e.g., just below `_detect_command` / `_has_trigger_word`):

```python
_AMBIENT_PREAMBLE = (
    "You are listening silently to a live meeting. No one addressed you by name. "
    "You have determined you may have a brief, useful contribution. Speak ONLY if "
    "it is genuinely additive — answer an open question, surface a relevant fact, "
    "or flag a real risk. If on reflection you have nothing additive to add, reply "
    "with exactly: SILENT. Keep it to one or two sentences."
)


def _is_ambient_silent(reply: str) -> bool:
    """True if an ambient-mode generation declined to contribute."""
    return (reply or "").strip().upper().rstrip(".!") == "SILENT"
```

- [ ] **Step 3b: Add the ambient wrappers and the `_emit_utterance` hook**

In `backend/realtime_routes.py`, add the wrapper functions near `_dispatch_slow_path_command`:

```python
async def _ambient_on_utterance(bot_id: str, state: dict, u) -> None:
    """Ambient (no-wake-word) branch. Runs the mode machine, then — only in
    autonomous mode and only when there's no explicit 'prism' command — runs the
    ambient funnel. Explicit commands are handled by _dispatch_slow_path_command."""
    now = time.time()
    mode = ambient_loop.update_mode(state, u.text, u.speaker_name, now)
    if _detect_command(u.text):
        return  # explicit command path owns this utterance
    if mode != "autonomous":
        return
    try:
        await ambient_loop.evaluate(
            bot_id, state, u.text, u.speaker_name,
            run_generator=_ambient_run_generator,
            surface_idea=_ambient_surface_idea,
            now=now,
        )
    except Exception as e:
        print(f"[ambient] evaluate error bot={bot_id[:8]}: {e}")


async def _ambient_run_generator(bot_id: str, utterance: str, speaker: str):
    """Generator wrapper for the ambient funnel — reuses _process_command with
    ambient framing. Returns the spoken text, or None if it declined (SILENT)."""
    return await _process_command(bot_id, utterance, speaker, ambient=True)


async def _ambient_surface_idea(bot_id: str, state: dict) -> None:
    """Borderline-'no' handoff → existing Idea Engine (side panel, best-effort)."""
    await _maybe_generate_idea(bot_id, state)
```

In `backend/realtime_routes.py`, inside `_emit_utterance`, after the two existing `asyncio.create_task(...)` lines (the compress + slow-path dispatch), add:

```python
    if ambient_loop.autonomous_enabled():
        asyncio.create_task(_ambient_on_utterance(bot_id, state, u))
```

- [ ] **Step 3c: Add the `ambient` parameter to `_process_command`**

In `backend/realtime_routes.py`, change the `_process_command` signature:

```python
async def _process_command(bot_id: str, command: str, speaker: str = "", ambient: bool = False):
```

Make it return the spoken text on the ambient path. Two edits inside `_process_command`:

1. When building the system prefix/messages, when `ambient` is true, prepend the preamble. Locate where the static prefix is assembled for the command (the `_build_command_messages` / `_build_static_prefix` call) and inject the ambient preamble into the system content. The minimal, low-risk approach is to prepend it to the `command` framing passed to the model — add this near the top of `_process_command`, right after the function's existing setup and before the messages are built:

```python
    if ambient:
        command = f"{_AMBIENT_PREAMBLE}\n\n[LATEST UTTERANCE]\n{command}"
```

2. Find where `_process_command` produces the final `reply` text and dispatches voice/chat (the `_send_voice_response_streamed` / `_send_voice_response` / `_send_chat_response` call site near the end). Guard it for ambient SILENT and return the reply:

```python
        if ambient and _is_ambient_silent(reply):
            print(f"[ambient] generator declined (SILENT) bot={bot_id[:8]}")
            return None
        # ... existing voice/chat dispatch ...
        if ambient:
            return reply
```

> **Implementer note:** `_process_command` is a large function. Make ONLY these two insertions (the `command` reframing near the top, and the SILENT-guard + `return reply` at the reply-dispatch site). Do not restructure the rest. The existing `create_task(_process_command(...))` call sites ignore the return value, so adding a return is backward-compatible.

- [ ] **Step 3d: Add the lull check to the tick loop**

In `backend/realtime_routes.py`, inside `_accumulator_tick_loop`, after the `acc.tick()` call (inside the `async with perception_state.get_memory_lock(state):` block), add:

```python
                    if ambient_loop.autonomous_enabled():
                        if ambient_loop.check_lull(state, time.time()) == "autonomous":
                            print(f"[ambient] lull → autonomous bot={bot_id[:8]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_wiring.py -v`
Expected: PASS (`AmbientSilentHelperTests` 2 tests, `AmbientOnUtteranceRoutingTests` 3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_ambient_wiring.py
git commit -m "Wire ambient loop into realtime_routes (hook, framing, lull tick)"
```

---

## Task 10: Manual mode override endpoint

**Files:**
- Modify: `backend/realtime_routes.py` (add `POST /bot/{bot_id}/mode`)
- Test: `backend/tests/test_ambient_wiring.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ambient_wiring.py`:

```python
class ModeOverrideEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_manual_mode(self):
        bot_id = "bot-override-test"
        state = realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "autonomous"})
            self.assertEqual(res["mode"], "autonomous")
            self.assertEqual(state["manual_mode"], "autonomous")

            res = await realtime_routes.set_bot_mode(bot_id, {"mode": None})
            self.assertIsNone(state["manual_mode"])
        finally:
            realtime_routes.cleanup_bot_state(bot_id)

    async def test_invalid_mode_rejected(self):
        bot_id = "bot-override-test-2"
        realtime_routes._get_bot_state(bot_id)
        try:
            res = await realtime_routes.set_bot_mode(bot_id, {"mode": "bogus"})
            self.assertIn("error", res)
        finally:
            realtime_routes.cleanup_bot_state(bot_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ambient_wiring.py::ModeOverrideEndpointTests -v`
Expected: FAIL — `AttributeError: module 'realtime_routes' has no attribute 'set_bot_mode'`.

- [ ] **Step 3: Implement the endpoint**

In `backend/realtime_routes.py`, add near the other `@router.post` handlers:

```python
@router.post("/bot/{bot_id}/mode")
async def set_bot_mode(bot_id: str, body: dict):
    """Owner manual override of the live bot's mode. body={"mode": "utterance"
    |"autonomous"|null}. null clears the override (auto state machine resumes).
    Unauthenticated like the other bot endpoints (see CLAUDE.md Known Limitations)."""
    mode = body.get("mode")
    if mode not in (None, "utterance", "autonomous"):
        return {"error": "mode must be 'utterance', 'autonomous', or null"}
    state = _get_bot_state(bot_id)
    state["manual_mode"] = mode
    if mode in ("utterance", "autonomous"):
        ambient_loop.update_mode(state, "", "", time.time())
    print(f"[ambient] manual mode override bot={bot_id[:8]} → {mode!r}")
    return {"mode": state.get("mode"), "manual_mode": state.get("manual_mode")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ambient_wiring.py::ModeOverrideEndpointTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_ambient_wiring.py
git commit -m "Add manual mode override endpoint for the live bot"
```

---

## Task 11: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the new suites**

Run: `python -m pytest tests/test_ambient_loop.py tests/test_ambient_wiring.py -v`
Expected: ALL PASS.

- [ ] **Step 2: Run the touched-module regression suites**

Run: `python -m pytest tests/test_think_loop.py tests/test_realtime_persona.py tests/test_pre_perception.py tests/test_utterance_accumulator.py -v`
Expected: ALL PASS (no regressions in the modules adjacent to our edits).

- [ ] **Step 3: Import smoke test (catches circular-import / syntax errors)**

Run: `python -c "import ambient_loop, realtime_routes, meeting_memory, perception_state; print('ok')"`
Expected: prints `ok` with no ImportError.

- [ ] **Step 4: Commit (if any fixups were needed)**

```bash
git add -A
git commit -m "Fix regressions surfaced by ambient-loop integration" || echo "nothing to commit"
```

---

## Out of scope for this plan (deferred follow-ups)

- **Frontend mode chip + toggle UI.** The backend surfaces `mode`/`mode_entry_reason` via `get_memory_snapshot` (Task 1) and accepts overrides via `POST /bot/{bot_id}/mode` (Task 10). A small dashboard chip that reads the snapshot and POSTs the toggle is a thin follow-up; frontend has no test framework (project convention).
- **Distilled-classifier decider (v2).** Conditional on decider cost becoming a scale bottleneck; the shadow logs are the data source. Not built here.
- **Kimi 2.5 / DeepSeek V3.2 generator A/B.** Separate flag + spec.
- **Generate-but-don't-speak in shadow.** v1 shadow validates the *decision* only (logs decider output); measuring generator-decline rate happens once live.

---

## Self-review notes

- **Spec coverage:** mode machine (Tasks 3–4, 9), free recall gate (Task 5), 8B decider + fail-safe (Tasks 6–7), decider-first orchestration with read-auto/write-confirm via the reused generator + verb-gate (Task 8–9), Idea-Engine handoff (Task 8), explicit-prism fast-path preserved (Task 9 routing skips ambient on a detected command), shadow mode + flags (Tasks 2, 8), counters/observability (Task 1), manual override + mode visibility (Tasks 1, 10). The handoff-vs-lull revert distinction from the spec is implemented in `update_mode` (Task 3) and covered by `test_handoff_entered_persists_through_activity` / `test_lull_entered_reverts_on_active_crosstalk`.
- **Write-confirm:** autonomous writes inherit the existing `think_loop` verb-gate because the ambient path reuses `_process_command` unchanged for tool calls — no separate enforcement needed.
- **Active-speaker guard:** satisfied structurally (the funnel runs on *flushed* utterances, i.e., a pause already occurred) plus the existing speaking-session supersede/barge-in machinery in `_process_command`. No separate mid-utterance check is added.
- **Type consistency:** `evaluate` returns `{"action": str, ...}`; `decide`/`parse_decider_output` return `{"respond": bool, "confidence": float, "reason": str}`; `update_mode`/`check_lull` return the mode string (`check_lull` returns `None` when no shift). `_ambient_run_generator` returns `str | None` matching `evaluate`'s `run_generator` contract.

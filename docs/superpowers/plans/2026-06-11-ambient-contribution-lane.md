# Ambient Contribution Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the consent-interjection autonomous mode with the ambient contribution lane: content-based triggers (unanswered question / KB hit / blocker) → one grounded 70B call that prices its own contribution → tiered delivery (chat for mid-value, direct content-first voice for high-value) behind a speak-time timing gate, with speculative generation, a yield rule, and graceful entry prefaces.

**Architecture:** `ambient_loop.py` keeps mute/warmup/flags and gains the lane's pure logic (triggers, generator, parser, tiers, gate predicates). `realtime_routes.py` wires it: chunk-ingest stamps `last_audio_ts`, `_ambient_on_utterance` arms/clears the pending-question slot and fires B-triggers, the accumulator tick loop delivers expired questions, `knowledge_proactive` hands its hits to the lane in Automatic mode. The old consent/offer/mode-machine code is deleted at the end, after the new lane is live, so the suite stays green at every task boundary. No schema changes, no new dependencies.

**Tech Stack:** Python 3 / FastAPI / asyncio, Groq SDK via `clients.get_groq`, `unittest` (+ `IsolatedAsyncioTestCase`), pytest runner.

**Spec:** `docs/superpowers/specs/2026-06-11-ambient-contribution-lane-design.md`

---

## File structure

| File | Responsibility |
|------|----------------|
| `backend/ambient_loop.py` | Lane logic: env knobs, `is_question`, `question_window_s`, `parse_contribution_output`, `generate_contribution` (+ `_call_ambient_model`), `delivery_tier`, cooldown helpers, subject ledger, `last_utterance_terminal` + `gate_clear`, `AMBIENT_PREFACES`. Keeps `detect_mute_command`, `past_warmup`, `autonomous_enabled`, `shadow_mode`. Old funnel/consent/mode machinery deleted in Task 7. |
| `backend/meeting_memory.py` | New lane state fields in `get_initial_memory_state()`; snapshot keeps `mode`/`muted`, drops consent fields (Task 7). |
| `backend/perception_state.py` | New `ambient_*` counters; `offers_*`/`ambient_mode_shifts` removed in Task 7. |
| `backend/realtime_routes.py` | `last_audio_ts` stamping; `abort_check` param on `_send_voice_response_streamed`; new `_ambient_on_utterance` + `_ambient_speculate` + `_ambient_fire` + `_ambient_deliver` + `_ambient_deliver_voice` + `_ambient_kb_route` + `_speaker_names`; tick-loop question expiry; endpoint simplification (Task 7). |
| `backend/knowledge_proactive.py` | Automatic-mode branch hands matches to `_ambient_kb_route` instead of posting the snippet. |
| `backend/tests/test_ambient_lane.py` | **New.** All unit + wiring tests for the lane. |
| `backend/tests/test_ambient_loop.py` / `test_ambient_wiring.py` | Pruned/updated in Tasks 4 & 7 (consent-era tests removed; mute/warmup/flag/endpoint tests kept). |
| `backend/tests/test_consent_interjection.py` | **Deleted** (Task 7). |
| `frontend/src/components/DashboardPage.jsx` | Automatic-mode hint text update (Task 8). |

**Test commands (from `backend/`):**
- Lane only: `python -m pytest tests/test_ambient_lane.py -v`
- Touched files: `python -m pytest tests/test_ambient_lane.py tests/test_ambient_loop.py tests/test_ambient_wiring.py -v`
- Full suite: `python -m pytest tests/ -q`

---

## Task 1: Lane logic in `ambient_loop.py` (additive — nothing deleted yet)

**Files:**
- Modify: `backend/ambient_loop.py` (append new sections; do not touch existing code)
- Create: `backend/tests/test_ambient_lane.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ambient_lane.py`:

```python
"""Tests for the ambient contribution lane (spec 2026-06-11)."""

import os
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ambient_loop  # noqa: E402
import meeting_memory  # noqa: E402
import perception_state  # noqa: E402


class IsQuestionTests(unittest.TestCase):
    def test_question_mark_fires(self):
        self.assertTrue(ambient_loop.is_question("What was Q3 revenue?"))

    def test_question_word_start_fires_with_length(self):
        self.assertTrue(ambient_loop.is_question("does anyone know the vendor deadline"))

    def test_short_question_word_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question("what now"))

    def test_statement_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question("We shipped the build yesterday."))

    def test_empty_does_not_fire(self):
        self.assertFalse(ambient_loop.is_question(""))


class QuestionWindowTests(unittest.TestCase):
    def test_default_window(self):
        self.assertAlmostEqual(
            ambient_loop.question_window_s("What was Q3 revenue?", [], None), 6.0
        )

    def test_named_participant_lengthens(self):
        w = ambient_loop.question_window_s(
            "Vidyut, what do you think?", ["Vidyut Sriram", "Abhinav Dasari"], None
        )
        self.assertAlmostEqual(w, 9.0)

    def test_strong_kb_hit_shortens(self):
        w = ambient_loop.question_window_s("What was Q3 revenue?", [], 0.86)
        self.assertAlmostEqual(w, 4.2, places=1)

    def test_named_participant_wins_over_kb(self):
        w = ambient_loop.question_window_s(
            "Vidyut, what was Q3 revenue?", ["Vidyut Sriram"], 0.9
        )
        self.assertAlmostEqual(w, 9.0)


class ParseContributionTests(unittest.TestCase):
    def test_valid_payload(self):
        raw = '{"value": 8.5, "kind": "answer", "contribution": "Per the Q3 doc, revenue was 1.2M.", "subject": "Q3 revenue"}'
        out = ambient_loop.parse_contribution_output(raw)
        self.assertEqual(out["kind"], "answer")
        self.assertAlmostEqual(out["value"], 8.5)
        self.assertEqual(out["subject"], "Q3 revenue")

    def test_fenced_payload(self):
        raw = '```json\n{"value": 6, "kind": "fact", "contribution": "X.", "subject": "x"}\n```'
        out = ambient_loop.parse_contribution_output(raw)
        self.assertEqual(out["kind"], "fact")

    def test_kind_none_returns_silent_shape(self):
        out = ambient_loop.parse_contribution_output('{"value": 9, "kind": "none", "contribution": "", "subject": ""}')
        self.assertEqual(out, {"value": 0.0, "kind": "none", "contribution": "", "subject": ""})

    def test_drift_cases_return_none(self):
        for raw in (None, "", "no json here", '{"value": "high"}',
                    '{"value": 8, "kind": "poem", "contribution": "x", "subject": "s"}',
                    '{"value": 8, "kind": "answer", "contribution": "", "subject": "s"}'):
            self.assertIsNone(ambient_loop.parse_contribution_output(raw), raw)

    def test_value_clamped(self):
        out = ambient_loop.parse_contribution_output(
            '{"value": 99, "kind": "answer", "contribution": "x", "subject": "s"}'
        )
        self.assertEqual(out["value"], 10.0)


class DeliveryTierTests(unittest.TestCase):
    def test_high_value_is_voice(self):
        with mock.patch.dict(os.environ, {"PRISM_AMBIENT_VOICE": "1"}):
            self.assertEqual(ambient_loop.delivery_tier(8.5), "voice")

    def test_mid_value_is_chat(self):
        self.assertEqual(ambient_loop.delivery_tier(6.0), "chat")

    def test_low_value_is_drop(self):
        self.assertEqual(ambient_loop.delivery_tier(3.0), "drop")

    def test_chat_cap_demotes_high_value(self):
        self.assertEqual(ambient_loop.delivery_tier(9.0, max_tier="chat"), "chat")

    def test_voice_flag_off_demotes_to_chat(self):
        with mock.patch.dict(os.environ, {"PRISM_AMBIENT_VOICE": "0"}):
            self.assertEqual(ambient_loop.delivery_tier(9.0), "chat")


class CooldownAndLedgerTests(unittest.TestCase):
    def test_voice_cooldown(self):
        state = {"ambient_voice_last_ts": time.time()}
        self.assertFalse(ambient_loop.voice_cooldown_clear(state, time.time()))
        state["ambient_voice_last_ts"] = time.time() - 61
        self.assertTrue(ambient_loop.voice_cooldown_clear(state, time.time()))

    def test_chat_cooldown(self):
        state = {"ambient_chat_last_ts": time.time()}
        self.assertFalse(ambient_loop.chat_cooldown_clear(state, time.time()))
        state["ambient_chat_last_ts"] = time.time() - 26
        self.assertTrue(ambient_loop.chat_cooldown_clear(state, time.time()))

    def test_ledger_dedup_and_cap(self):
        state = {}
        ambient_loop.record_contributed_subject(state, "Q3 Revenue")
        self.assertTrue(ambient_loop.subject_already_contributed(state, "q3 revenue"))
        self.assertFalse(ambient_loop.subject_already_contributed(state, "vendor sla"))
        for i in range(30):
            ambient_loop.record_contributed_subject(state, f"subject {i}")
        self.assertLessEqual(len(state["contributed_subjects"]), 25)


class TimingGateTests(unittest.TestCase):
    def _state(self, last_line="Abhinav: We shipped it.", audio_age=5.0, pending=False):
        acc = types.SimpleNamespace(pending={"s1": object()} if pending else {})
        return {
            "transcript_buffer": [last_line] if last_line else [],
            "last_audio_ts": time.time() - audio_age,
            "accumulator": acc,
        }

    def test_clear_when_quiet_and_terminal(self):
        self.assertTrue(ambient_loop.gate_clear(self._state(), time.time()))

    def test_blocked_by_recent_audio(self):
        self.assertFalse(ambient_loop.gate_clear(self._state(audio_age=0.3), time.time()))

    def test_blocked_by_pending_partial(self):
        self.assertFalse(ambient_loop.gate_clear(self._state(pending=True), time.time()))

    def test_blocked_by_no_terminal_punct(self):
        s = self._state(last_line="Abhinav: I went to the store and")
        self.assertFalse(ambient_loop.gate_clear(s, time.time()))

    def test_blocked_by_trailing_connective(self):
        s = self._state(last_line="Abhinav: We could do that because.")
        self.assertFalse(ambient_loop.gate_clear(s, time.time()))

    def test_clear_with_no_accumulator(self):
        s = self._state()
        s["accumulator"] = None
        self.assertTrue(ambient_loop.gate_clear(s, time.time()))


class GenerateContributionTests(unittest.IsolatedAsyncioTestCase):
    def _state(self):
        s = meeting_memory.get_initial_memory_state()
        s["transcript_buffer"] = ["Abhinav: What was Q3 revenue?"]
        return s

    async def test_good_json_passes_through(self):
        raw = '{"value": 8, "kind": "answer", "contribution": "Per the Q3 doc, 1.2M.", "subject": "Q3 revenue"}'
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(return_value=raw)):
            out = await ambient_loop.generate_contribution(self._state(), "unanswered_question", "evidence", "Flash")
        self.assertEqual(out["kind"], "answer")

    async def test_drift_returns_none_and_counts(self):
        state = self._state()
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(return_value="garbage")):
            out = await ambient_loop.generate_contribution(state, "unanswered_question", "e", "Prism")
        self.assertIsNone(out)
        self.assertEqual(perception_state.get_counters(state)["ambient_parse_fail"], 1)

    async def test_model_exception_returns_none(self):
        with mock.patch.object(ambient_loop, "_call_ambient_model", new=mock.AsyncMock(side_effect=RuntimeError("429"))):
            out = await ambient_loop.generate_contribution(self._state(), "knowledge_match", "e", "Prism")
        self.assertIsNone(out)

    async def test_prompt_includes_evidence_and_ledger(self):
        state = self._state()
        ambient_loop.record_contributed_subject(state, "vendor sla")
        state["previous_idea_summaries"] = ["(idea) ownership gap"]
        captured = {}

        async def fake_call(system, user):
            captured["system"] = system
            captured["user"] = user
            return '{"value": 2, "kind": "none", "contribution": "", "subject": ""}'

        with mock.patch.object(ambient_loop, "_call_ambient_model", new=fake_call):
            await ambient_loop.generate_contribution(state, "unanswered_question", "EVIDENCE-XYZ", "Flash")
        self.assertIn("EVIDENCE-XYZ", captured["user"])
        self.assertIn("vendor sla", captured["user"])
        self.assertIn("ownership gap", captured["user"])
        self.assertIn("Flash", captured["system"])


if __name__ == "__main__":
    unittest.main()
```

Note on `GenerateContributionTests._state()`: `meeting_memory.get_initial_memory_state()` doesn't have the new fields until Task 2 — the ledger helper uses `setdefault`, so these tests pass without them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py -v`
Expected: FAIL / ERROR with `AttributeError: module 'ambient_loop' has no attribute 'is_question'` (and similar).

- [ ] **Step 3: Implement the lane logic**

Append to `backend/ambient_loop.py` (after the existing `recall_gate` section, before the consent state machine — exact position doesn't matter, keep it as one new block):

```python
# ══════════════════════════════════════════════════════════════════════════════
# Ambient contribution lane (spec 2026-06-11) — replaces the consent funnel.
# The sections above this line are deleted in the cleanup task once the lane
# is wired; do not build on them.
# ══════════════════════════════════════════════════════════════════════════════

AMBIENT_PREFACES = [
    "One thing worth adding — ",
    "Quick note — ",
    "If it helps — ",
]

def ambient_voice_on() -> bool:
    return os.getenv("PRISM_AMBIENT_VOICE", "1") == "1"

def ambient_model() -> str:
    return os.getenv("PRISM_AMBIENT_MODEL", "llama-3.3-70b-versatile")

def voice_min() -> float:
    return float(os.getenv("PRISM_AMBIENT_VOICE_MIN", "8"))

def chat_min() -> float:
    return float(os.getenv("PRISM_AMBIENT_CHAT_MIN", "5"))

def answer_wait_s() -> float:
    return float(os.getenv("PRISM_ANSWER_WAIT_S", "6"))

def quiet_gap_s() -> float:
    return float(os.getenv("PRISM_QUIET_GAP_S", "1.5"))

def gap_wait_s() -> float:
    return float(os.getenv("PRISM_GAP_WAIT_S", "8"))

def voice_cooldown_s() -> float:
    return float(os.getenv("PRISM_AMBIENT_VOICE_COOLDOWN_S", "60"))

def chat_cooldown_s() -> float:
    return float(os.getenv("PRISM_AMBIENT_CHAT_COOLDOWN_S", "25"))


# ── Trigger Q: question detection + addressee window ─────────────────────────
_QUESTION_START_RE = re.compile(
    r"^(what|who|when|where|how|why|did|does|do|is|are|was|were|which|can|"
    r"could|should|would|anyone|any)\b",
    re.IGNORECASE,
)

def is_question(text: str) -> bool:
    """Transcript-level question heuristic. Deepgram smart_format punctuates,
    so '?' is the primary signal; the question-word fallback needs >=4 words to
    avoid firing on fragments like 'what now'."""
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    return bool(_QUESTION_START_RE.match(t)) and len(t.split()) >= 4


def question_window_s(text: str, participant_names: list, kb_top_score) -> float:
    """Answer-wait window with addressee scaling (spec R3). Naming a human
    participant lengthens it (explicitly not ours); a strong KB hit or a
    past-decision/action shape shortens it (no human is the addressee of
    record). The named-human rule wins when both apply."""
    base = answer_wait_s()
    low = (text or "").lower()
    for name in participant_names or []:
        first = (name or "").strip().split(" ")[0].lower()
        if first and len(first) >= 3 and first in low:
            return base * 1.5
    if (kb_top_score or 0.0) >= 0.80:
        return base * 0.7
    if meeting_memory.DECISION_PATTERN.search(text or "") or meeting_memory.ACTION_ITEM_PATTERN.search(text or ""):
        return base * 0.7
    return base


# ── The contribution generator (one grounded call; the value IS the decider) ──
def parse_contribution_output(raw) -> dict | None:
    """Strict parse of the generator reply. None on ANY drift (fail-safe
    silent). kind='none' normalizes to a zero-value silent shape."""
    if not raw or not isinstance(raw, str):
        return None
    s = strip_fences(raw).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    kind = obj.get("kind")
    if kind not in ("answer", "fact", "risk", "none"):
        return None
    try:
        value = float(obj.get("value"))
    except Exception:
        return None
    if kind == "none":
        return {"value": 0.0, "kind": "none", "contribution": "", "subject": ""}
    contribution = obj.get("contribution")
    if not isinstance(contribution, str) or not contribution.strip():
        return None
    return {
        "value": max(0.0, min(10.0, value)),
        "kind": kind,
        "contribution": contribution.strip()[:600],
        "subject": str(obj.get("subject", "")).strip()[:80],
    }


def _contribution_system(bot_name: str) -> str:
    return (
        f"You are {bot_name}, an AI meeting assistant listening silently to a live "
        "meeting. You are given a TRIGGER (an unanswered question, a knowledge-base "
        "match, or a risk/decision moment) plus meeting memory and evidence. Draft the "
        "single best brief contribution you could make right now, then price its value "
        "honestly.\n"
        "Rules:\n"
        "- contribution: at most 2 sentences, spoken-style, direct. No preamble.\n"
        "- Use ONLY facts present in the evidence or meeting memory. If the evidence is "
        "thin or you would have to guess, set value <= 4.\n"
        "- When a fact comes from a document, name it (e.g. \"Per the Q3 forecast doc, ...\").\n"
        "- If the room already covered it, or it appears under ALREADY CONTRIBUTED, value <= 4.\n"
        "- value rubric: 8-10 = directly answers the open question with grounded info, or "
        "corrects a material error; 5-7 = relevant and helpful but not urgent; 0-4 = "
        "tangential, obvious, or ungrounded.\n"
        'Respond with JSON ONLY, no prose: {"value": <0-10>, "kind": "answer|fact|risk|none", '
        '"contribution": "<text>", "subject": "<2-5 words>"}'
    )


async def _call_ambient_model(system: str, user: str) -> str:
    """The lane's only LLM I/O. Direct Groq (no Haiku fallback — ambient is
    optional behavior; on 429/5xx the lane stays silent). Isolated for mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=ambient_model(),
        temperature=0.2,
        max_tokens=220,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def generate_contribution(state: dict, trigger_kind: str, evidence: str,
                                bot_name: str = "Prism") -> dict | None:
    """One grounded call: memory context + trigger evidence in, priced
    contribution out. None = stay silent (drift, error, or rate limit)."""
    context = meeting_memory.build_memory_context(state)
    already = list(state.get("contributed_subjects") or [])
    already += [s for s in (state.get("previous_idea_summaries") or [])]
    contributed = "; ".join(already) if already else "(none)"
    user = (
        f"{context}\n\n[TRIGGER: {trigger_kind}]\n{evidence}\n\n"
        f"[ALREADY CONTRIBUTED]: {contributed}\n\n"
        "[TASK] Draft and price your best contribution. JSON only."
    )
    perception_state.bump(state, "ambient_generations")
    try:
        raw = await _call_ambient_model(_contribution_system(bot_name), user)
    except Exception as e:
        print(f"[ambient] generator error: {e}")
        return None
    out = parse_contribution_output(raw)
    if out is None:
        perception_state.bump(state, "ambient_parse_fail")
    return out


# ── Delivery policy: tiers, cooldowns, subject ledger ─────────────────────────
def delivery_tier(value: float, max_tier: str = "voice") -> str:
    """'voice' | 'chat' | 'drop'. max_tier='chat' caps B-triggers; the voice
    flag off demotes voice-worthy values to chat (chat-only rollout stage)."""
    if value >= voice_min() and max_tier == "voice" and ambient_voice_on():
        return "voice"
    if value >= chat_min():
        return "chat"
    return "drop"


def voice_cooldown_clear(state: dict, now: float) -> bool:
    return (now - state.get("ambient_voice_last_ts", 0.0)) >= voice_cooldown_s()


def chat_cooldown_clear(state: dict, now: float) -> bool:
    return (now - state.get("ambient_chat_last_ts", 0.0)) >= chat_cooldown_s()


_MAX_CONTRIBUTED_SUBJECTS = 25

def subject_already_contributed(state: dict, subject: str) -> bool:
    key = (subject or "").strip().lower()
    return bool(key) and key in (state.get("contributed_subjects") or [])


def record_contributed_subject(state: dict, subject: str) -> None:
    key = (subject or "").strip().lower()
    if not key:
        return
    subs = state.setdefault("contributed_subjects", [])
    if key not in subs:
        subs.append(key)
        if len(subs) > _MAX_CONTRIBUTED_SUBJECTS:
            del subs[: len(subs) - _MAX_CONTRIBUTED_SUBJECTS]


# ── Speak-time timing gate (spec R2) ──────────────────────────────────────────
_TRAILING_CONNECTIVES = frozenset({"and", "but", "because", "um", "uh", "like"})

def last_utterance_terminal(state: dict) -> bool:
    """Semantic end-of-turn approximation on text: the last buffered utterance
    ends with terminal punctuation and not on a trailing connective. 'I went to
    the store and' is not a gap, even after 2s of silence."""
    buf = state.get("transcript_buffer") or []
    if not buf:
        return True
    line = buf[-1]
    text = line.split(":", 1)[1].strip() if ":" in line else line.strip()
    if not text:
        return True
    if text[-1] not in ".?!":
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return not (words and words[-1] in _TRAILING_CONNECTIVES)


def gate_clear(state: dict, now: float) -> bool:
    """All three speak-time conditions: audio-quiet >= quiet_gap_s, no pending
    partial utterance in the accumulator, last utterance semantically terminal."""
    if (now - state.get("last_audio_ts", 0.0)) < quiet_gap_s():
        return False
    acc = state.get("accumulator")
    if acc is not None and getattr(acc, "pending", None):
        return False
    return last_utterance_terminal(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the previously-existing ambient tests (nothing should break)**

Run: `cd backend && python -m pytest tests/test_ambient_loop.py tests/test_ambient_wiring.py tests/test_consent_interjection.py -q`
Expected: PASS (the old machinery is untouched so far).

- [ ] **Step 6: Commit**

```bash
git add backend/ambient_loop.py backend/tests/test_ambient_lane.py
git commit -m "Add ambient contribution lane logic (triggers, generator, tiers, timing gate)"
```

---

## Task 2: Lane state fields + observability counters (additive)

**Files:**
- Modify: `backend/meeting_memory.py` (`get_initial_memory_state`, ~line 92–127)
- Modify: `backend/perception_state.py` (`_DEFAULT_COUNTERS` ~line 224, `_OPERATIONAL_KEYS` ~line 291)
- Test: `backend/tests/test_ambient_lane.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ambient_lane.py`)

```python
class LaneStateFieldTests(unittest.TestCase):
    def test_initial_state_has_lane_fields(self):
        s = meeting_memory.get_initial_memory_state()
        self.assertIsNone(s["pending_question"])
        self.assertEqual(s["last_audio_ts"], 0.0)
        self.assertEqual(s["ambient_voice_last_ts"], 0.0)
        self.assertEqual(s["ambient_chat_last_ts"], 0.0)
        self.assertEqual(s["contributed_subjects"], [])
        self.assertFalse(s["_ambient_busy"])
        self.assertEqual(s["ambient_speaking_since"], 0.0)

    def test_lane_counters_exist(self):
        s = meeting_memory.get_initial_memory_state()
        counters = perception_state.get_counters(s)
        for key in ("ambient_q_triggers", "ambient_kb_triggers", "ambient_b_triggers",
                    "ambient_generations", "ambient_discarded_answered",
                    "ambient_low_value", "ambient_chat_posted", "ambient_spoken",
                    "ambient_demoted_no_gap", "ambient_yielded", "ambient_parse_fail"):
            self.assertIn(key, counters, key)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py::LaneStateFieldTests -v`
Expected: FAIL with `KeyError: 'pending_question'`.

- [ ] **Step 3: Implement**

In `backend/meeting_memory.py`, inside `get_initial_memory_state()`, after the `"muted": False,` line (end of the consent block), add:

```python
        # ── Ambient contribution lane (spec 2026-06-11) ───────────────────────
        "pending_question": None,       # {text, speaker_id, speaker_name, ts, window_s, candidate, candidate_done, delivered}
        "last_audio_ts": 0.0,           # last human transcript-chunk arrival (timing gate + yield rule)
        "ambient_voice_last_ts": 0.0,   # voice-tier cooldown anchor
        "ambient_chat_last_ts": 0.0,    # chat-tier cooldown anchor
        "contributed_subjects": [],     # normalized subjects already contributed (shared dedup ledger)
        "_ambient_busy": False,         # one in-flight generation per bot
        "ambient_speaking_since": 0.0,  # nonzero while ambient voice is playing (yield rule)
```

In `backend/perception_state.py`, inside `_DEFAULT_COUNTERS` (after the `"mutes": 0,` entry), add:

```python
    # Ambient contribution lane (spec 2026-06-11)
    "ambient_q_triggers": 0,
    "ambient_kb_triggers": 0,
    "ambient_b_triggers": 0,
    "ambient_generations": 0,
    "ambient_discarded_answered": 0,
    "ambient_low_value": 0,
    "ambient_chat_posted": 0,
    "ambient_spoken": 0,
    "ambient_demoted_no_gap": 0,
    "ambient_yielded": 0,
    "ambient_parse_fail": 0,
```

And append the same eleven key names as strings to `_OPERATIONAL_KEYS` (after `"mutes",`):

```python
    "ambient_q_triggers",
    "ambient_kb_triggers",
    "ambient_b_triggers",
    "ambient_generations",
    "ambient_discarded_answered",
    "ambient_low_value",
    "ambient_chat_posted",
    "ambient_spoken",
    "ambient_demoted_no_gap",
    "ambient_yielded",
    "ambient_parse_fail",
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/meeting_memory.py backend/perception_state.py backend/tests/test_ambient_lane.py
git commit -m "Add ambient-lane state fields and observability counters"
```

---

## Task 3: `last_audio_ts` stamping + yield hook in the streamed TTS sender

**Files:**
- Modify: `backend/realtime_routes.py` — webhook chunk ingest (~line 2525, inside `if text.strip():`) and `_send_voice_response_streamed` (~line 1321)
- Test: `backend/tests/test_ambient_lane.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ambient_lane.py`)

```python
import realtime_routes as rt  # noqa: E402


class StreamedSenderAbortTests(unittest.IsolatedAsyncioTestCase):
    async def test_abort_check_stops_uploads(self):
        uploads = []

        async def fake_tts(text):
            return b"audio"

        async def fake_upload(bot_id, audio):
            uploads.append(audio)
            return True

        flags = {"aborted": False}

        def abort_check():
            return len(uploads) >= 1  # talk-over detected after the first chunk

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_chunk_reply", return_value=["One.", "Two.", "Three."]), \
             mock.patch.object(rt, "_get_bot_state", return_value=meeting_memory.get_initial_memory_state()):
            await rt._send_voice_response_streamed("bot-1", "One. Two. Three.",
                                                   cmd_detected_ts=time.time(),
                                                   abort_check=abort_check)
        self.assertEqual(len(uploads), 1)  # second/third chunk never uploaded

    async def test_no_abort_check_uploads_all(self):
        uploads = []

        async def fake_tts(text):
            return b"audio"

        async def fake_upload(bot_id, audio):
            uploads.append(audio)
            return True

        with mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt, "text_to_speech", new=fake_tts), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload), \
             mock.patch.object(rt, "_chunk_reply", return_value=["One.", "Two."]), \
             mock.patch.object(rt, "_get_bot_state", return_value=meeting_memory.get_initial_memory_state()):
            await rt._send_voice_response_streamed("bot-1", "One. Two.",
                                                   cmd_detected_ts=time.time())
        self.assertEqual(len(uploads), 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py::StreamedSenderAbortTests -v`
Expected: FAIL with `TypeError: _send_voice_response_streamed() got an unexpected keyword argument 'abort_check'`.

- [ ] **Step 3: Implement**

(a) Change the signature at ~line 1321:

```python
async def _send_voice_response_streamed(bot_id: str, text: str, cmd_detected_ts: float,
                                        abort_check=None):
```

(b) In its upload loop, directly below the existing barge-in cancel check (the `if _barge_in_on() and _session_cancelled(state, "upload"):` block, ~line 1372), add a parallel check:

```python
        # Ambient yield rule (spec R4): a human spoke after this ambient
        # response started — stop sending audio, never re-take the floor.
        if abort_check is not None and abort_check():
            print(f"[realtime] ambient_yield bot={bot_id[:8]} at chunk {i}")
            for t in tts_tasks[i:]:
                t.cancel()
            break
```

(c) At the webhook chunk-ingest site (~line 2525), inside the existing `if text.strip():` block (the one that logs `extracted speaker=`), add the stamp — excluding the bot's own TTS feedback:

```python
            # Ambient lane: stamp human speech arrival for the speak-time
            # timing gate + yield rule. The bot's own TTS feedback (when
            # identified) must not look like human audio.
            if not (speaker_id and state.get("bot_self_speaker_id") == speaker_id):
                state["last_audio_ts"] = time.time()
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_ambient_lane.py
git commit -m "Stamp last_audio_ts at chunk ingest; add yield hook to streamed TTS sender"
```

---

## Task 4: Trigger arming/clearing — rewrite `_ambient_on_utterance` + add `_ambient_speculate`

**Files:**
- Modify: `backend/realtime_routes.py` (~lines 723–775: replace `_ambient_on_utterance`; add `_speaker_names`, `_ambient_speculate`; add `import random` and `import cross_meeting_service` if not present at top)
- Modify: `backend/tests/test_ambient_wiring.py` (`AmbientOnUtteranceRoutingTests` — rewrite for the new flow)
- Test: `backend/tests/test_ambient_lane.py`

**Note:** `_run_interject` / `interject` stay in the file until Task 7, now unreachable. `cross_meeting_service` is already imported by `ambient_loop`; `realtime_routes` needs its own import if missing (check top of file — it imports `cross_meeting_service` already for `_fetch_historical_blockers`-adjacent logic; verify with `grep -n "^import cross_meeting_service\|^from cross_meeting_service" backend/realtime_routes.py` and add `import cross_meeting_service` if absent).

- [ ] **Step 1: Write the failing tests** (append to `test_ambient_lane.py`)

```python
class FakeUtt:
    def __init__(self, text, speaker_name="Abhinav", speaker_id="sid-a"):
        self.text = text
        self.speaker_name = speaker_name
        self.speaker_id = speaker_id
        self.utterance_id = "u1"


def _auto_state(**over):
    s = meeting_memory.get_initial_memory_state()
    s["mode"] = "autonomous"
    s["meeting_start_ts"] = time.time() - 600
    s["live_decisions"] = [{"text": "ship it", "speaker": "A", "ts": 1.0}]  # past_warmup
    s["transcript_buffer"] = ["Abhinav: hello."]
    s.update(over)
    return s


class TriggerArmingTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_arms_pending_slot_and_speculates(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        self.assertIsNotNone(state["pending_question"])
        self.assertEqual(state["pending_question"]["text"], "What was Q3 revenue?")
        spec.assert_awaited()
        self.assertEqual(perception_state.get_counters(state)["ambient_q_triggers"], 1)

    async def test_different_speaker_substantive_reply_clears(self):
        state = _auto_state()
        state["pending_question"] = {"text": "q?", "speaker_id": "sid-a",
                                     "speaker_name": "Abhinav", "ts": time.time(),
                                     "window_s": 6.0, "candidate": None,
                                     "candidate_done": False, "delivered": False}
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("it was one point two million", "Vidyut", "sid-v"))
        self.assertIsNone(state["pending_question"])
        self.assertEqual(perception_state.get_counters(state)["ambient_discarded_answered"], 1)

    async def test_asker_continuation_does_not_clear(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "sid-a", "speaker_name": "Abhinav",
              "ts": time.time(), "window_s": 6.0, "candidate": None,
              "candidate_done": False, "delivered": False}
        state["pending_question"] = pq
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("I really cannot find it anywhere", "Abhinav", "sid-a"))
        self.assertIs(state["pending_question"], pq)

    async def test_short_reply_does_not_clear(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "sid-a", "speaker_name": "Abhinav",
              "ts": time.time(), "window_s": 6.0, "candidate": None,
              "candidate_done": False, "delivered": False}
        state["pending_question"] = pq
        with mock.patch.object(rt, "_detect_command", return_value=None):
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("yeah", "Vidyut", "sid-v"))
        self.assertIs(state["pending_question"], pq)

    async def test_blocker_fires_chat_capped(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_fire", new=mock.AsyncMock()) as fire:
            await rt._ambient_on_utterance(
                "bot-1", state, FakeUtt("we are blocked on the vendor SLA"))
        fire.assert_awaited()
        self.assertEqual(fire.await_args.kwargs.get("max_tier"), "chat")

    async def test_mute_command_sets_muted_and_clears_slot(self):
        state = _auto_state()
        state["pending_question"] = {"text": "q?", "speaker_id": "x", "speaker_name": "X",
                                     "ts": 0, "window_s": 6.0, "candidate": None,
                                     "candidate_done": False, "delivered": False}
        await rt._ambient_on_utterance("bot-1", state, FakeUtt("Prism, stay quiet"))
        self.assertTrue(state["muted"])
        self.assertIsNone(state["pending_question"])

    async def test_muted_state_blocks_triggers(self):
        state = _auto_state(muted=True)
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        self.assertIsNone(state["pending_question"])
        spec.assert_not_awaited()

    async def test_utterance_mode_blocks_triggers(self):
        state = _auto_state(mode="utterance")
        with mock.patch.object(rt, "_detect_command", return_value=None), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("What was Q3 revenue?"))
        spec.assert_not_awaited()

    async def test_explicit_command_skips_lane(self):
        state = _auto_state()
        with mock.patch.object(rt, "_detect_command", return_value="summarize"), \
             mock.patch.object(rt, "_ambient_speculate", new=mock.AsyncMock()) as spec:
            await rt._ambient_on_utterance("bot-1", state, FakeUtt("Prism, summarize?"))
        spec.assert_not_awaited()


class SpeculateTests(unittest.IsolatedAsyncioTestCase):
    async def test_speculate_attaches_candidate_and_window(self):
        state = _auto_state()
        pq = {"text": "What is the vendor SLA?", "speaker_id": "sid-a",
              "speaker_name": "Abhinav", "ts": time.time(), "window_s": 6.0,
              "candidate": None, "candidate_done": False, "delivered": False}
        matches = [{"doc_name": "Vendor contract", "content": "SLA is 99.9%",
                    "score": 0.91, "sensitivity": "public", "doc_id": "d1", "meeting_id": None}]
        good = {"value": 8.0, "kind": "answer", "contribution": "Per the Vendor contract, SLA is 99.9%.", "subject": "vendor SLA"}
        with mock.patch.object(rt, "bot_store", {"bot-1": {"user_id": "u-1", "meeting_id": None}}), \
             mock.patch.object(rt, "_ambient_kb_search", new=mock.AsyncMock(return_value=matches)), \
             mock.patch.object(rt.ambient_loop, "generate_contribution",
                               new=mock.AsyncMock(return_value=good)):
            await rt._ambient_speculate("bot-1", state, pq)
        self.assertTrue(pq["candidate_done"])
        self.assertEqual(pq["candidate"]["subject"], "vendor SLA")
        self.assertAlmostEqual(pq["window_s"], 4.2, places=1)  # strong KB hit shortened

    async def test_speculate_marks_done_on_failure(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "a", "speaker_name": "A", "ts": time.time(),
              "window_s": 6.0, "candidate": None, "candidate_done": False, "delivered": False}
        with mock.patch.object(rt, "bot_store", {"bot-1": {"user_id": None}}), \
             mock.patch.object(rt.ambient_loop, "generate_contribution",
                               new=mock.AsyncMock(return_value=None)):
            await rt._ambient_speculate("bot-1", state, pq)
        self.assertTrue(pq["candidate_done"])
        self.assertIsNone(pq["candidate"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py::TriggerArmingTests tests/test_ambient_lane.py::SpeculateTests -v`
Expected: FAIL (`AttributeError: ... has no attribute '_ambient_speculate'` and assertion failures in the old `_ambient_on_utterance` flow).

- [ ] **Step 3: Implement**

Replace `_ambient_on_utterance` (~line 723) and add the new helpers right after it. `_ambient_fire` is a stub here (full body in Task 5) so this task stands alone:

```python
async def _ambient_on_utterance(bot_id: str, state: dict, u) -> None:
    """Ambient contribution lane (spec 2026-06-11): per completed utterance,
    handle mute, then arm/clear the pending-question slot (trigger Q) or fire
    a blocker/decision trigger (B, chat-capped). Delivery happens from the
    tick loop (Q, on window expiry) or _ambient_fire (B/K)."""
    now = time.time()
    cmd = ambient_loop.detect_mute_command(u.text)
    if cmd == "mute":
        state["muted"] = True
        state["pending_question"] = None
        perception_state.bump(state, "mutes")
        print(f"[ambient] muted bot={bot_id[:8]}")
        return
    if cmd == "unmute":
        state["muted"] = False
        print(f"[ambient] unmuted bot={bot_id[:8]}")
        return
    if state.get("mode") != "autonomous" or state.get("muted"):
        return
    if _detect_command(u.text, bot_id):
        return  # the explicit wake-word path owns this utterance
    if not ambient_loop.past_warmup(state):
        return

    # Clear rule: a *different* speaker replying substantively (>=4 words, not
    # itself a question) means the humans handled it. The asker continuing
    # does not clear — the value scorer prices rhetorical openings low.
    pq = state.get("pending_question")
    if pq:
        same_speaker = (
            (u.speaker_id and pq.get("speaker_id") == u.speaker_id)
            or (not u.speaker_id and pq.get("speaker_name") == u.speaker_name)
        )
        if (not same_speaker and len((u.text or "").split()) >= 4
                and not ambient_loop.is_question(u.text)):
            state["pending_question"] = None
            perception_state.bump(state, "ambient_discarded_answered")

    # Trigger Q: arm (a newer question replaces an older one — the room moved on).
    if ambient_loop.is_question(u.text):
        slot = {
            "text": u.text,
            "speaker_id": u.speaker_id or "",
            "speaker_name": u.speaker_name,
            "ts": now,
            "window_s": ambient_loop.answer_wait_s(),  # refined by _ambient_speculate
            "candidate": None,
            "candidate_done": False,
            "delivered": False,
        }
        state["pending_question"] = slot
        perception_state.bump(state, "ambient_q_triggers")
        await _ambient_speculate(bot_id, state, slot)
        return

    # Trigger B: blocker / decision moment — chat-tier capped in v1.
    if cross_meeting_service.looks_like_blocker(u.text) or meeting_memory.DECISION_PATTERN.search(u.text or ""):
        perception_state.bump(state, "ambient_b_triggers")
        await _ambient_fire(bot_id, state, "blocker_or_decision",
                            f"{u.speaker_name}: {u.text}", max_tier="chat")


def _speaker_names(state: dict) -> list:
    """Participant names seen recently — 'Name: text' prefixes in the buffer."""
    names = set()
    for line in (state.get("transcript_buffer") or [])[-50:]:
        if ":" in line:
            head = line.split(":", 1)[0].strip()
            if head and len(head) <= 40:
                names.add(head)
    return list(names)


async def _ambient_kb_search(bot_id: str, query: str) -> list:
    """KB search for the lane, with the proactive-surfacing sensitivity rule
    applied (never speak confidential docs into a meeting). Empty list on any
    failure or for unauthenticated bots."""
    record = bot_store.get(bot_id) or {}
    user_id = record.get("user_id")
    if not user_id:
        return []
    try:
        from knowledge_service import search_knowledge
        from knowledge_proactive import _allowed_by_sensitivity
        matches = await search_knowledge(query, user_id,
                                         meeting_id=record.get("meeting_id"),
                                         k=3, min_score=0.6)
        return [m for m in matches if _allowed_by_sensitivity(m, record.get("meeting_id"))]
    except Exception as e:
        print(f"[ambient] KB search failed bot={bot_id[:8]}: {e}")
        return []


async def _ambient_speculate(bot_id: str, state: dict, pq: dict) -> None:
    """Speculative generation for a pending question (spec R1): one KB search
    (evidence + addressee window scaling), then the contribution generator.
    The candidate lands on the slot; the tick loop delivers it if the window
    expires unanswered. candidate_done=True with candidate=None means the
    generation failed — the tick loop just drops the slot."""
    try:
        evidence = f"Open question from {pq['speaker_name']}: {pq['text']}"
        kb_top = None
        matches = await _ambient_kb_search(bot_id, pq["text"])
        if matches:
            kb_top = max(float(m.get("score") or 0.0) for m in matches)
            chunks = "\n".join(
                f"- [{m.get('doc_name')}] {(m.get('content') or '')[:400]}" for m in matches
            )
            evidence += f"\n\n[KNOWLEDGE BASE EVIDENCE]\n{chunks}"
        pq["window_s"] = ambient_loop.question_window_s(
            pq["text"], _speaker_names(state), kb_top
        )
        if state.get("_ambient_busy"):
            return  # collision: leave candidate_done False; slot expires unused
        state["_ambient_busy"] = True
        try:
            bot_name = _BOT_WAKE_ALIAS.get(bot_id, "") or personas.DEFAULT_BOT_NAME
            pq["candidate"] = await ambient_loop.generate_contribution(
                state, "unanswered_question", evidence, bot_name
            )
        finally:
            state["_ambient_busy"] = False
    except Exception as e:
        print(f"[ambient] speculate error bot={bot_id[:8]}: {e}")
    finally:
        pq["candidate_done"] = True


async def _ambient_fire(bot_id: str, state: dict, trigger_kind: str, evidence: str,
                        *, max_tier: str) -> None:
    """Generate-then-deliver for K and B triggers. Full delivery in Task 5."""
    if state.get("_ambient_busy"):
        return
    state["_ambient_busy"] = True
    try:
        bot_name = _BOT_WAKE_ALIAS.get(bot_id, "") or personas.DEFAULT_BOT_NAME
        out = await ambient_loop.generate_contribution(state, trigger_kind, evidence, bot_name)
    finally:
        state["_ambient_busy"] = False
    if out:
        await _ambient_deliver(bot_id, state, out, max_tier=max_tier)
```

Also add a temporary stub so the module imports until Task 5 defines the real one (place directly below `_ambient_fire`):

```python
async def _ambient_deliver(bot_id: str, state: dict, out: dict, *, max_tier: str) -> None:
    """Implemented in the delivery task; stub keeps Task 4 self-contained."""
    print(f"[ambient] (stub) deliver tier-candidate value={out.get('value')} bot={bot_id[:8]}")
```

Check imports at the top of `realtime_routes.py`: `import cross_meeting_service` and `import personas` must be present (add if missing; `_BOT_WAKE_ALIAS` and `bot_store` are module-level already).

- [ ] **Step 4: Update `test_ambient_wiring.py`'s `AmbientOnUtteranceRoutingTests`**

The old tests patch `ambient_loop.interject` and assert it's called — the new flow never calls it. Replace that class with:

```python
class AmbientOnUtteranceRoutingTests(unittest.IsolatedAsyncioTestCase):
    def _auto_state(self):
        s = meeting_memory.get_initial_memory_state()
        s["mode"] = "autonomous"
        s["meeting_start_ts"] = time.time() - 600
        s["live_decisions"] = [{"text": "d", "speaker": "A", "ts": 1.0}]
        s["transcript_buffer"] = ["A: hello."]
        return s

    async def test_explicit_command_skips_ambient(self):
        state = self._auto_state()
        with mock.patch.object(realtime_routes, "_detect_command", return_value="summarize"), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance("b1", state, FakeUtterance("Prism, summarize?"))
        spec.assert_not_awaited()

    async def test_utterance_mode_skips_ambient(self):
        state = self._auto_state()
        state["mode"] = "utterance"
        with mock.patch.object(realtime_routes, "_detect_command", return_value=None), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance("b1", state, FakeUtterance("What is the SLA, again?"))
        spec.assert_not_awaited()

    async def test_autonomous_mode_arms_question(self):
        state = self._auto_state()
        with mock.patch.object(realtime_routes, "_detect_command", return_value=None), \
             mock.patch.object(realtime_routes, "_ambient_speculate",
                               new=mock.AsyncMock()) as spec:
            await realtime_routes._ambient_on_utterance("b1", state, FakeUtterance("What is the SLA, again?"))
        spec.assert_awaited()
        self.assertIsNotNone(state["pending_question"])

    async def test_mute_command_routes_to_lane(self):
        state = self._auto_state()
        await realtime_routes._ambient_on_utterance("b1", state, FakeUtterance("Prism, stay quiet"))
        self.assertTrue(state["muted"])
```

(`FakeUtterance` in that file needs a `speaker_id` attribute — add `self.speaker_id = "sid-x"` to its `__init__` if missing.)

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py tests/test_ambient_wiring.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_ambient_lane.py backend/tests/test_ambient_wiring.py
git commit -m "Wire ambient triggers: question arm/clear with speculative generation, chat-capped blocker trigger"
```

---

## Task 5: Delivery — tiers, timing gate, preface, yield, chat mirror, tick expiry

**Files:**
- Modify: `backend/realtime_routes.py` — replace the Task 4 `_ambient_deliver` stub; add `_ambient_deliver_voice`; replace the `check_lull` block in `_accumulator_tick_loop` (~line 806–809) with question expiry
- Test: `backend/tests/test_ambient_lane.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ambient_lane.py`)

```python
def _candidate(value=8.5, kind="answer", subject="q3 revenue",
               contribution="Per the Q3 doc, revenue was 1.2M."):
    return {"value": value, "kind": kind, "subject": subject, "contribution": contribution}


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_value_drops(self):
        state = _auto_state()
        with mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            await rt._ambient_deliver("b1", state, _candidate(value=3.0), max_tier="voice")
        chat.assert_not_awaited()
        self.assertEqual(perception_state.get_counters(state)["ambient_low_value"], 1)

    async def test_mid_value_posts_chat_and_records(self):
        state = _auto_state()
        with mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            await rt._ambient_deliver("b1", state, _candidate(value=6.0), max_tier="voice")
        chat.assert_awaited_once()
        self.assertIn("ℹ️", chat.await_args.args[1])
        self.assertTrue(ambient_loop.subject_already_contributed(state, "q3 revenue"))
        self.assertGreater(state["ambient_chat_last_ts"], 0)
        self.assertEqual(perception_state.get_counters(state)["ambient_chat_posted"], 1)

    async def test_high_value_speaks_and_mirrors(self):
        state = _auto_state()
        with mock.patch.object(rt, "_ambient_deliver_voice",
                               new=mock.AsyncMock(return_value=True)) as voice:
            await rt._ambient_deliver("b1", state, _candidate(value=9.0), max_tier="voice")
        voice.assert_awaited_once()

    async def test_voice_gate_failure_demotes_to_chat(self):
        state = _auto_state()
        with mock.patch.object(rt, "_ambient_deliver_voice",
                               new=mock.AsyncMock(return_value=False)), \
             mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            await rt._ambient_deliver("b1", state, _candidate(value=9.0), max_tier="voice")
        chat.assert_awaited_once()

    async def test_duplicate_subject_skipped(self):
        state = _auto_state()
        ambient_loop.record_contributed_subject(state, "q3 revenue")
        with mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            await rt._ambient_deliver("b1", state, _candidate(value=6.0), max_tier="voice")
        chat.assert_not_awaited()

    async def test_shadow_mode_emits_nothing(self):
        state = _auto_state()
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS_SHADOW": "1"}), \
             mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat, \
             mock.patch.object(rt, "_ambient_deliver_voice", new=mock.AsyncMock()) as voice:
            await rt._ambient_deliver("b1", state, _candidate(value=9.0), max_tier="voice")
        chat.assert_not_awaited()
        voice.assert_not_awaited()

    async def test_chat_cooldown_blocks(self):
        state = _auto_state()
        state["ambient_chat_last_ts"] = time.time()
        with mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            await rt._ambient_deliver("b1", state, _candidate(value=6.0), max_tier="voice")
        chat.assert_not_awaited()


class VoiceDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_gate_timeout_returns_false(self):
        state = _auto_state()
        state["last_audio_ts"] = time.time()  # room is loud, stays loud
        with mock.patch.dict(os.environ, {"PRISM_GAP_WAIT_S": "0.4", "PRISM_QUIET_GAP_S": "60"}), \
             mock.patch.object(rt, "_send_voice_response_streamed", new=mock.AsyncMock()) as tts:
            ok = await rt._ambient_deliver_voice("b1", state, _candidate())
        self.assertFalse(ok)
        tts.assert_not_awaited()
        self.assertEqual(perception_state.get_counters(state)["ambient_demoted_no_gap"], 1)

    async def test_quiet_room_speaks_with_preface_and_mirrors(self):
        state = _auto_state()
        state["last_audio_ts"] = time.time() - 10
        state["transcript_buffer"] = ["A: done."]
        with mock.patch.dict(os.environ, {"PRISM_STREAMED_TTS": "1"}), \
             mock.patch.object(rt, "_send_voice_response_streamed", new=mock.AsyncMock()) as tts, \
             mock.patch.object(rt, "_send_chat_response", new=mock.AsyncMock()) as chat:
            ok = await rt._ambient_deliver_voice("b1", state, _candidate())
        self.assertTrue(ok)
        spoken = tts.await_args.args[1]
        self.assertTrue(any(spoken.startswith(p) for p in ambient_loop.AMBIENT_PREFACES))
        self.assertIn("Per the Q3 doc", spoken)
        chat.assert_awaited_once()                      # mirror
        self.assertNotIn(spoken, chat.await_args.args)  # mirror is bare contribution
        self.assertGreater(state["ambient_voice_last_ts"], 0)
        self.assertEqual(perception_state.get_counters(state)["ambient_spoken"], 1)


class TickExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_slot_with_candidate_delivers(self):
        state = _auto_state()
        state["pending_question"] = {
            "text": "q?", "speaker_id": "a", "speaker_name": "A",
            "ts": time.time() - 10, "window_s": 6.0,
            "candidate": _candidate(), "candidate_done": True, "delivered": False,
        }
        with mock.patch.object(rt, "_ambient_deliver", new=mock.AsyncMock()) as deliver:
            fired = rt._ambient_tick_check("b1", state, time.time())
            if fired:
                await fired
        deliver.assert_awaited_once()
        self.assertIsNone(state["pending_question"])

    async def test_expired_slot_with_failed_candidate_drops(self):
        state = _auto_state()
        state["pending_question"] = {
            "text": "q?", "speaker_id": "a", "speaker_name": "A",
            "ts": time.time() - 10, "window_s": 6.0,
            "candidate": None, "candidate_done": True, "delivered": False,
        }
        with mock.patch.object(rt, "_ambient_deliver", new=mock.AsyncMock()) as deliver:
            fired = rt._ambient_tick_check("b1", state, time.time())
            if fired:
                await fired
        deliver.assert_not_awaited()
        self.assertIsNone(state["pending_question"])

    async def test_unexpired_slot_untouched(self):
        state = _auto_state()
        pq = {"text": "q?", "speaker_id": "a", "speaker_name": "A",
              "ts": time.time(), "window_s": 6.0,
              "candidate": _candidate(), "candidate_done": True, "delivered": False}
        state["pending_question"] = pq
        fired = rt._ambient_tick_check("b1", state, time.time())
        self.assertIsNone(fired)
        self.assertIs(state["pending_question"], pq)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py::DeliveryTests tests/test_ambient_lane.py::VoiceDeliveryTests tests/test_ambient_lane.py::TickExpiryTests -v`
Expected: FAIL (stub `_ambient_deliver` does nothing; `_ambient_deliver_voice` / `_ambient_tick_check` undefined).

- [ ] **Step 3: Implement**

Replace the Task 4 `_ambient_deliver` stub with the real implementation, and add the two new functions below it (`import random` at top of file if not present):

```python
async def _ambient_deliver(bot_id: str, state: dict, out: dict, *, max_tier: str) -> None:
    """Tiered delivery: drop / chat / voice-with-chat-fallback. Never raises."""
    try:
        if state.get("muted") or state.get("mode") != "autonomous":
            return
        tier = ambient_loop.delivery_tier(out["value"], max_tier=max_tier)
        if tier == "drop" or out["kind"] == "none":
            perception_state.bump(state, "ambient_low_value")
            print(f"[ambient] drop value={out['value']:.1f} subject={out['subject']!r} bot={bot_id[:8]}")
            return
        if ambient_loop.subject_already_contributed(state, out["subject"]):
            print(f"[ambient] dup subject={out['subject']!r} bot={bot_id[:8]}")
            return
        if ambient_loop.shadow_mode():
            print(
                f"[ambient] SHADOW would {tier}: value={out['value']:.1f} "
                f"subject={out['subject']!r} text={out['contribution'][:160]!r} bot={bot_id[:8]}"
            )
            return
        if tier == "voice" and ambient_loop.voice_cooldown_clear(state, time.time()):
            if await _ambient_deliver_voice(bot_id, state, out):
                return
            # no gap appeared — fall through to the chat tier (demotion)
        if not ambient_loop.chat_cooldown_clear(state, time.time()):
            return
        await _send_chat_response(bot_id, f"ℹ️ {out['contribution']}")
        state["ambient_chat_last_ts"] = time.time()
        ambient_loop.record_contributed_subject(state, out["subject"])
        state.setdefault("previous_idea_summaries", []).append(f"(ambient) {out['subject']}")
        state["previous_idea_summaries"] = state["previous_idea_summaries"][-5:]
        perception_state.bump(state, "ambient_chat_posted")
        print(f"[ambient] chat value={out['value']:.1f} subject={out['subject']!r} bot={bot_id[:8]}")
    except Exception as e:
        print(f"[ambient] deliver error bot={bot_id[:8]}: {e}")


async def _ambient_deliver_voice(bot_id: str, state: dict, out: dict) -> bool:
    """Voice tier: wait for a real gap (spec R2 gate), speak preface +
    contribution with the yield hook (R4), always mirror to chat. Returns False
    if no gap appeared within gap_wait_s (caller demotes to chat)."""
    gate_ok = False
    deadline = time.time() + ambient_loop.gap_wait_s()
    while time.time() < deadline:
        if ambient_loop.gate_clear(state, time.time()):
            gate_ok = True
            break
        await asyncio.sleep(0.2)
    if not gate_ok:
        perception_state.bump(state, "ambient_demoted_no_gap")
        print(f"[ambient] no_gap subject={out['subject']!r} bot={bot_id[:8]}")
        return False

    started = time.time()
    state["ambient_speaking_since"] = started
    speak_text = random.choice(ambient_loop.AMBIENT_PREFACES) + out["contribution"]

    def _talked_over() -> bool:
        return state.get("last_audio_ts", 0.0) > started

    try:
        if _streamed_tts_on():
            await _send_voice_response_streamed(
                bot_id, speak_text, cmd_detected_ts=started, abort_check=_talked_over
            )
        else:
            await _send_voice_response(bot_id, speak_text)
    except Exception as e:
        print(f"[ambient] voice delivery error bot={bot_id[:8]}: {e}")
    finally:
        state["ambient_speaking_since"] = 0.0

    if _talked_over():
        perception_state.bump(state, "ambient_yielded")

    # Mirror the bare contribution to chat so the content survives any yield.
    await _send_chat_response(bot_id, f"ℹ️ {out['contribution']}")
    state["ambient_voice_last_ts"] = time.time()
    state["ambient_chat_last_ts"] = time.time()
    ambient_loop.record_contributed_subject(state, out["subject"])
    state.setdefault("previous_idea_summaries", []).append(f"(ambient) {out['subject']}")
    state["previous_idea_summaries"] = state["previous_idea_summaries"][-5:]
    perception_state.bump(state, "ambient_spoken")
    print(f"[ambient] spoke value={out['value']:.1f} subject={out['subject']!r} bot={bot_id[:8]}")
    return True


def _ambient_tick_check(bot_id: str, state: dict, now: float):
    """Called from the accumulator tick loop. If the pending question's window
    expired: candidate ready → return the delivery coroutine for the caller to
    schedule; generation failed → drop the slot. Returns None when nothing to do.
    (Returning the coroutine instead of create_task makes this unit-testable.)"""
    pq = state.get("pending_question")
    if not pq or pq.get("delivered"):
        return None
    if (now - pq["ts"]) < pq.get("window_s", ambient_loop.answer_wait_s()):
        return None
    if not pq.get("candidate_done"):
        return None  # generation still in flight; check again next tick
    pq["delivered"] = True
    state["pending_question"] = None
    if pq.get("candidate") is None:
        return None
    return _ambient_deliver(bot_id, state, pq["candidate"], max_tier="voice")
```

In `_accumulator_tick_loop` (~line 806), replace:

```python
                    if ambient_loop.autonomous_enabled():
                        if ambient_loop.check_lull(state, time.time()) == "autonomous":
                            print(f"[ambient] lull -> autonomous bot={bot_id[:8]}")
```

with:

```python
                    if ambient_loop.autonomous_enabled():
                        _coro = _ambient_tick_check(bot_id, state, time.time())
                        if _coro is not None:
                            asyncio.create_task(_coro)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py tests/test_ambient_wiring.py tests/test_ambient_loop.py -q`
Expected: all PASS (`check_lull` itself still exists; only its tick-loop call is gone).

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_ambient_lane.py
git commit -m "Ambient delivery: value tiers, speak-time gate, preface, yield, chat mirror, tick expiry"
```

---

## Task 6: Trigger K — route proactive-KB hits through the lane in Automatic mode

**Files:**
- Modify: `backend/knowledge_proactive.py` (`maybe_proactive_knowledge_check`, the match loop ~line 112–132)
- Modify: `backend/realtime_routes.py` (add `_ambient_kb_route` near the other lane functions)
- Test: `backend/tests/test_ambient_lane.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ambient_lane.py`)

```python
class KbRouteTests(unittest.IsolatedAsyncioTestCase):
    def _match(self):
        return {"doc_id": "d1", "doc_name": "Vendor contract",
                "content": "SLA is 99.9%", "score": 0.9,
                "sensitivity": "public", "meeting_id": None}

    async def test_automatic_mode_owns_the_hit(self):
        state = _auto_state()
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS": "1"}), \
             mock.patch.dict(rt._bot_state, {"b1": state}, clear=False), \
             mock.patch.object(rt, "_ambient_fire", new=mock.AsyncMock()) as fire:
            owned = await rt._ambient_kb_route("b1", self._match())
        self.assertTrue(owned)
        fire.assert_awaited_once()
        self.assertEqual(fire.await_args.kwargs.get("max_tier"), "voice")
        self.assertEqual(perception_state.get_counters(state)["ambient_kb_triggers"], 1)

    async def test_utterance_mode_declines(self):
        state = _auto_state(mode="utterance")
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS": "1"}), \
             mock.patch.dict(rt._bot_state, {"b1": state}, clear=False):
            owned = await rt._ambient_kb_route("b1", self._match())
        self.assertFalse(owned)

    async def test_flag_off_declines(self):
        state = _auto_state()
        env = dict(os.environ)
        env.pop("PRISM_AUTONOMOUS", None)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.dict(rt._bot_state, {"b1": state}, clear=False):
            owned = await rt._ambient_kb_route("b1", self._match())
        self.assertFalse(owned)

    async def test_shadow_logs_but_does_not_own(self):
        state = _auto_state()
        with mock.patch.dict(os.environ, {"PRISM_AUTONOMOUS": "1", "PRISM_AUTONOMOUS_SHADOW": "1"}), \
             mock.patch.dict(rt._bot_state, {"b1": state}, clear=False), \
             mock.patch.object(rt, "_ambient_fire", new=mock.AsyncMock()) as fire:
            owned = await rt._ambient_kb_route("b1", self._match())
        self.assertFalse(owned)   # snippet path still posts during shadow
        fire.assert_awaited_once()  # lane still logs its would-be contribution
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py::KbRouteTests -v`
Expected: FAIL with `AttributeError: ... no attribute '_ambient_kb_route'`.

- [ ] **Step 3: Implement**

In `backend/realtime_routes.py`, below `_ambient_fire`:

```python
async def _ambient_kb_route(bot_id: str, match: dict) -> bool:
    """Trigger K: a proactive-KB hit becomes a generated, cited, value-priced
    contribution instead of a raw snippet — Automatic mode only. Returns True
    when the lane owns the hit (suppresses the snippet post). In shadow the
    lane logs its would-be contribution but the snippet still posts (live
    behavior unchanged while validating)."""
    if not ambient_loop.autonomous_enabled():
        return False
    state = _bot_state.get(bot_id)
    if not state or state.get("mode") != "autonomous" or state.get("muted"):
        return False
    if not ambient_loop.past_warmup(state):
        return False
    perception_state.bump(state, "ambient_kb_triggers")
    evidence = (
        f"[KNOWLEDGE BASE MATCH]\n"
        f"- [{match.get('doc_name')}] {(match.get('content') or '')[:600]}"
    )
    await _ambient_fire(bot_id, state, "knowledge_match", evidence, max_tier="voice")
    return not ambient_loop.shadow_mode()
```

In `backend/knowledge_proactive.py`, inside the match loop of `maybe_proactive_knowledge_check` — after the cooldown check passes and `_doc_cooldown[(bot_id, doc_id)] = now` is set, before `snippet = ...` — add:

```python
        # Automatic mode: the ambient contribution lane owns this hit (it
        # generates a cited, value-priced contribution instead of a snippet).
        try:
            from realtime_routes import _ambient_kb_route
            if await _ambient_kb_route(bot_id, m):
                return
        except Exception as exc:
            print(f"[proactive-knowledge] ambient route failed for {bot_id}: {exc}")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ambient_lane.py tests/test_knowledge_service.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/knowledge_proactive.py backend/tests/test_ambient_lane.py
git commit -m "Route proactive-KB hits through the ambient lane in Automatic mode (trigger K)"
```

---

## Task 7: Delete the superseded machinery + simplify endpoints/state

**Files:**
- Modify: `backend/ambient_loop.py`, `backend/realtime_routes.py`, `backend/meeting_memory.py`, `backend/perception_state.py`
- Delete: `backend/tests/test_consent_interjection.py`
- Modify: `backend/tests/test_ambient_loop.py`, `backend/tests/test_ambient_wiring.py`

- [ ] **Step 1: Delete from `ambient_loop.py`** (everything above the Task 1 banner except the keepers)

Delete: `ACTIVE_WINDOW_S`, `ACTIVE_UTTERANCE_COUNT`, `MODERATE_NO_FLOOR`; `decider_model`, `pause_debounce_s`, `lull_threshold_s`, `autonomy_cap_s`, `offer_decider_model`, `offer_cooldown_s`, `offer_consent_window_s`, `offer_threshold`; `_MAX_OFFERED_SUBJECTS`, `make_offer`, `subject_already_offered`, `record_offered_subject`; `_HANDOFF_RE`, `_STOP_RE`, `_enter`; `parse_decider_output`, `_DECIDER_SYSTEM`, `_signal_summary`, `_call_decider_model`, `decide`; `_OFFER_SYSTEM`, `parse_offer_output`, `_call_offer_model`, `offer_decider`; `_CONSENT_TOKEN_RE`, `_CONSENT_SYSTEM`, `parse_consent`, `_call_consent_model`, `classify_consent`; `_REQUEST_RE`, `recall_gate`; `interject`, `_handle_pending_offer`; `check_lull`, `update_mode`.

**Keep:** module docstring (rewrite to describe the lane), `autonomous_enabled`, `shadow_mode`, `WARMUP_MIN_ENTITIES`, `past_warmup`, `_MUTE_RE`/`_UNMUTE_RE`/`detect_mute_command`, and the whole Task 1 lane block. Remove now-unused imports (`cross_meeting_service` stays only if still referenced — after deletion it isn't; remove it. `get_groq`, `meeting_memory`, `perception_state`, `strip_fences`, `json`, `os`, `re`, `time` all remain used).

New module docstring:

```python
"""Ambient contribution lane — Automatic mode for the live bot.

Content-based triggers (unanswered question / KB hit / blocker) → one grounded
70B call that drafts and prices a contribution → tiered delivery (chat for
mid-value, direct voice for high-value) behind a speak-time timing gate.
Wiring lives in realtime_routes; this module is pure logic + the one model call.

Flags:
  PRISM_AUTONOMOUS=1         enables the lane (Utterance mode = current prod)
  PRISM_AUTONOMOUS_SHADOW=1  run + log every decision, never post or speak
  PRISM_AMBIENT_VOICE=0      chat-only rollout stage (voice tier demotes to chat)

Spec: docs/superpowers/specs/2026-06-11-ambient-contribution-lane-design.md
"""
```

- [ ] **Step 2: Delete from `realtime_routes.py`**

- `_AMBIENT_PREAMBLE` (~709), `_is_ambient_silent` (~718), `_run_interject` (~740), `_ambient_speak_offer` (~752), `_ambient_run_delivery` (~767).
- In `_process_command` (~1688): remove the `ambient: bool = False` parameter, the docstring sentence about it, the `if ambient:` preamble insert (~1856), and the `if ambient and _is_ambient_silent(reply):` block (~2145).
- In `_dispatch_slow_path_command` (~696): the mute-skip guard stays (mute is still lane-owned):
  `if ambient_loop.autonomous_enabled() and ambient_loop.detect_mute_command(u.text): return`
- In `_get_bot_state` (~884): replace the seeding block with:

```python
        # Seed the pre-join response mode (from /join-meeting) — a stable
        # choice for the whole meeting; changeable via POST /bot/{id}/mode.
        _initial_mode = (bot_store.get(bot_id) or {}).get("initial_mode")
        if _initial_mode in ("utterance", "autonomous"):
            _bot_state[bot_id]["mode"] = _initial_mode
```

- Replace the mode endpoint (~2717):

```python
@router.post("/bot/{bot_id}/mode")
async def set_bot_mode(bot_id: str, body: dict):
    """Switch the live bot's mode. body={"mode": "utterance"|"autonomous"}.
    Unauthenticated like the other bot endpoints (see CLAUDE.md Known Limitations)."""
    mode = body.get("mode")
    if mode not in ("utterance", "autonomous"):
        return {"error": "mode must be 'utterance' or 'autonomous'"}
    state = _get_bot_state(bot_id)
    state["mode"] = mode
    if mode == "utterance":
        state["pending_question"] = None
    print(f"[ambient] mode set via API bot={bot_id[:8]} -> {mode!r}")
    return {"mode": state["mode"]}
```

- Update the mute endpoint (~2733): drop the `interjection_state` / `pending_offer` lines, clear the question slot instead:

```python
@router.post("/bot/{bot_id}/mute")
async def set_bot_mute(bot_id: str, body: dict):
    """Mute / unmute the ambient lane. body={"muted": bool}. Wake-word
    requests still work while muted."""
    muted = bool(body.get("muted"))
    state = _get_bot_state(bot_id)
    state["muted"] = muted
    if muted:
        state["pending_question"] = None
        perception_state.bump(state, "mutes")
    print(f"[ambient] mute via API bot={bot_id[:8]} muted={muted}")
    return {"muted": state.get("muted")}
```

- [ ] **Step 3: Delete from `meeting_memory.py` and `perception_state.py`**

`get_initial_memory_state()`: delete the old ambient/consent blocks — `mode_entry_reason`, `mode_since_ts`, `manual_mode`, `last_activity_ts`, `recent_utterance_ts`, `ambient_last_spoke_ts`, `_ambient_last_gate_ts`, `_ambient_evaluating`, `interjection_state`, `pending_offer`, `offered_subjects`, `offer_last_ts`. **Keep** `mode` and `muted` (move them into the Task 2 lane block).

`get_memory_snapshot()` (~line 540): delete the `mode_entry_reason` and `interjection_state` lines; `mode` and `muted` stay.

`perception_state.py`: delete `ambient_mode_shifts`, `offers_made`, `offers_accepted`, `offers_declined`, `offers_expired`, `offers_talked_over` from `_DEFAULT_COUNTERS` **and** `_OPERATIONAL_KEYS` (`mutes` stays).

- [ ] **Step 4: Prune the test files**

- `git rm backend/tests/test_consent_interjection.py`
- `backend/tests/test_ambient_loop.py`: delete every test class/test touching `update_mode`, `check_lull`, `recall_gate`, `decide`/`parse_decider_output`, `offer_decider`/`parse_offer_output`, `classify_consent`/`parse_consent`, `interject`, `make_offer`, offer-subject helpers, and the old state-field assertions (`mode_entry_reason` etc.). **Keep** tests for `detect_mute_command`, `past_warmup`, `autonomous_enabled`/`shadow_mode` flag behavior. If fewer than ~3 tests survive, fold them into `test_ambient_lane.py` as a `KeptHelperTests` class and delete the file.
- `backend/tests/test_ambient_wiring.py`: update `ModeOverrideEndpointTests` (no more `manual_mode` in the response — assert `{"mode": "autonomous"}` and that `null` now returns the error message), `PreJoinModeSeedTests` (assert `state["mode"]` seeded, no `manual_mode` key), delete `AmbientSilentHelperTests` (helpers gone). `MuteEndpointTests`: assert muting clears `pending_question`.

- [ ] **Step 5: Grep for stragglers**

```bash
cd backend
grep -rn "interject\|offer_decider\|classify_consent\|make_offer\|check_lull\|update_mode\|recall_gate\|parse_decider\|manual_mode\|interjection_state\|pending_offer\|offered_subjects\|_ambient_evaluating\|ambient_last_spoke\|PRISM_OFFER\|PRISM_LULL\|PRISM_AUTONOMY_CAP\|PRISM_PAUSE_DEBOUNCE\|PRISM_DECIDER" --include="*.py" .
```
Expected: zero hits outside comments/spec references. Fix any hit.

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all PASS (596+ baseline minus deleted consent tests plus the new lane tests).

- [ ] **Step 7: Commit**

```bash
git add -A backend
git commit -m "Delete superseded consent-interjection + mode state machine; simplify mode/mute endpoints"
```

---

## Task 8: Frontend hint, docs, final verification

**Files:**
- Modify: `frontend/src/components/DashboardPage.jsx` (~line 295)
- Modify: `CLAUDE.md` (ambient paragraph)

- [ ] **Step 1: Update the Automatic-mode hint**

In `DashboardPage.jsx` (~line 295), change:

```jsx
{ id: 'autonomous', label: 'Automatic', hint: 'Decides on its own when to chime in' },
```

to:

```jsx
{ id: 'autonomous', label: 'Automatic', hint: 'Chimes in with relevant info — speaks only for high-value moments' },
```

Also check the conditional blurb at ~line 314 (`(props.joinMode || 'utterance') === 'autonomous' ? ...`) and align its copy with the same message if it still describes the old consent behavior.

- [ ] **Step 2: Verify the frontend builds**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Update `CLAUDE.md`**

In the backend-structure section (near the `realtime_routes.py` paragraph), add:

```markdown
`ambient_loop.py` is the ambient contribution lane (Automatic mode): content-based
triggers (unanswered question / KB hit / blocker) → one grounded 70B call that
drafts and prices a contribution → tiered delivery (chat ≥5, direct voice ≥8)
behind a speak-time timing gate with a yield rule. Gated by `PRISM_AUTONOMOUS`
(+ `PRISM_AUTONOMOUS_SHADOW` for log-only, `PRISM_AMBIENT_VOICE=0` for chat-only).
Utterance mode is byte-identical to the pre-lane bot. Spec:
`docs/superpowers/specs/2026-06-11-ambient-contribution-lane-design.md`.
```

- [ ] **Step 4: Full verification**

```bash
cd backend && python -m pytest tests/ -q
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DashboardPage.jsx CLAUDE.md
git commit -m "Update Automatic-mode hint and CLAUDE.md for the ambient contribution lane"
```

---

## Acceptance check (maps to spec criteria)

| Spec criterion | Verified by |
|---|---|
| 1. Flag off ⇒ byte-identical | `_emit_utterance` gate unchanged (`autonomous_enabled()`); full suite green |
| 2. Utterance mode ⇒ byte-identical | `test_utterance_mode_skips_ambient`, `test_utterance_mode_declines` (KB route) |
| 3. Spoken cited answer, no consent | `test_quiet_room_speaks_with_preface_and_mirrors` + `SpeculateTests` |
| 4. Human answer ⇒ silent + discard log | `test_different_speaker_substantive_reply_clears` |
| 5. Never speak into speech / demote | `TimingGateTests`, `test_gate_timeout_returns_false`, `test_voice_gate_failure_demotes_to_chat` |
| 6. Talk-over halts audio, chat keeps content | `StreamedSenderAbortTests`, mirror assertions in `VoiceDeliveryTests` |
| 7. No contributions during intros | `past_warmup` gate + `TriggerArmingTests` setup (warmup precondition) |
| 8. Mute blocks lane, wake word works | `test_mute_command_sets_muted_and_clears_slot`, `test_muted_state_blocks_triggers`, `MuteEndpointTests` |
| 9. Shadow emits nothing | `test_shadow_mode_emits_nothing`, `test_shadow_logs_but_does_not_own` |
| 10. Suite green, consent tests removed | Task 7 steps 4–6 |

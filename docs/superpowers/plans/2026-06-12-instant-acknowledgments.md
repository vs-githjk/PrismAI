# Instant Acknowledgments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill the awkward dead-air pause after a voice command: within ~1.2s of the command, the bot speaks a short, *category-aware* acknowledgment ("Let me pull up your calendar—") from pre-synthesized audio, then the real answer follows when ready.

**Architecture:** A new pure-logic module `ack_phrases.py` (keyword classifier → category → rotating phrase variants) + an in-memory pre-synthesized audio cache filled by the existing `warmup` machinery (edge-tts at ~2.7s/clip is why runtime synthesis is impossible — every ack phrase is fixed text synthesized once). `_process_command` arms a race timer: if no real audio has been uploaded for this command within `PRISM_ACK_DELAY_S` (1.2s), the cached ack audio is uploaded to Recall. The first real-audio upload cancels the pending ack. Conservative classification: when no category matches confidently, use the neutral ack — a wrong-category ack reads as misunderstanding, which is worse than a filler.

**Key UX decision (from design discussion):** cancellation is keyed to **first real-audio upload**, not LLM completion — so even fast no-tool replies (whose TTS still takes ~2.7s) get an ack at 1.2s, and the room never sits in silence past ~1.5s.

**Tech Stack:** Python 3 / FastAPI / asyncio, edge-tts via `tools.tts.text_to_speech`, Recall `_upload_audio_to_recall`, `unittest` + pytest.

**Scope guards:** Voice-path commands only (`_process_command` — covers both spoken wake-word commands and meeting-chat commands, since both reply by voice). The ambient lane is excluded (its entry prefaces already serve this role). Flag-gated `PRISM_ACK` (default on), `PRISM_ACK_DELAY_S` (default 1.2).

---

## The taxonomy (review this — it is the product-feel surface)

First confident match wins, top-to-bottom; no match → `generic`. Variants rotate per bot so back-to-back commands don't repeat.

| Category | Trigger keywords (case-insensitive) | Phrases |
|---|---|---|
| `email_write` | (send/draft/write/reply/forward) within 3 words of (email/mail/gmail/inbox) | "Drafting that email now—" / "Let me put that email together—" |
| `email_read` | email/inbox/mail/gmail (without a write verb) | "Let me check your inbox—" / "Looking at your email—" |
| `calendar_write` | (schedule/create/set up/add/book/move/reschedule) + (calendar/event/invite/meeting) | "Let me set that up on your calendar—" |
| `calendar_read` | calendar/schedule/event/invite, or "meeting(s)" + (tomorrow/today/next/this week) | "Let me pull up your calendar—" / "Checking your schedule—" |
| `meeting_recall` | "last meeting" / "previous meeting" / "earlier meeting" / "we talked" / "we discussed" / "we said" | "Let me look back through the meeting notes—" |
| `knowledge` | "knowledge base" / document(s) / doc(s) / file(s) / uploaded / pdf | "Let me go through your documents—" |
| `summary` | summarize/summary/recap | "Give me a moment to pull that together—" |
| `actions` | "action item(s)" / decisions / "task list" / todos | "Let me gather the action items—" |
| `web` | "look up" / "search" / weather / news / "latest" / price / stock | "Let me look that up—" / "Searching for that now—" |
| `generic` | everything else | "On it — one moment." / "Sure — give me a second." |

Notes:
- "meeting" alone is deliberately NOT a calendar trigger — in a live meeting people say "this meeting" constantly. It needs a temporal companion word.
- `meeting_recall` outranks `knowledge` and `web` because "check what we said about X in the last meeting" must not get "Searching for that now—".
- Total: 14 phrases ≈ 14 edge-tts clips at warmup (bounded concurrency 3, ~15s background, fire-and-forget).

---

## File structure

| File | Responsibility |
|------|----------------|
| `backend/ack_phrases.py` | **New.** Category regexes, `classify_command(text) -> str`, `PHRASES` dict, `pick_phrase(category, state) -> str` (per-bot rotation), env helpers `ack_on()` / `ack_delay_s()`. Pure logic, no I/O. |
| `backend/ack_audio.py` | **New.** In-memory phrase→bytes cache; `ensure_ack_audio()` synthesizes all phrases via `text_to_speech` (concurrency 3, failures logged + skipped); `get_ack_audio(phrase) -> bytes | None`. |
| `backend/warmup.py` | **Modify.** `warm_external_connections` also runs `ensure_ack_audio()` (replaces the `_warm_tts` "ok" ping — synthesizing real phrases IS the TTS warm-up). |
| `backend/realtime_routes.py` | **Modify.** `_arm_ack(bot_id, state, command)` in `_process_command` after the debounce/dedup guards; `_cancel_ack(state)` called at every first-real-upload site; ack task uploads cached audio if still armed at deadline. Counters: `ack_played`, `ack_cancelled_fast`. |
| `backend/perception_state.py` | **Modify.** Two new counters. |
| `backend/tests/test_ack.py` | **New.** Classifier, rotation, audio cache, arm/cancel/race wiring. |

**Test commands (from `backend/`):**
- Feature: `python -m pytest tests/test_ack.py -v`
- Full: `python -m pytest tests/ -q`

---

## Task 1: `ack_phrases.py` — classifier + phrases + rotation

**Files:** Create `backend/ack_phrases.py`, `backend/tests/test_ack.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ack.py`:

```python
"""Tests for instant acknowledgments (classifier, audio cache, wiring)."""

import asyncio
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ack_phrases  # noqa: E402


class ClassifierTests(unittest.TestCase):
    def _c(self, text):
        return ack_phrases.classify_command(text)

    def test_email_write(self):
        self.assertEqual(self._c("send an email to the team about the launch"), "email_write")
        self.assertEqual(self._c("draft a reply to that mail from finance"), "email_write")

    def test_email_read(self):
        self.assertEqual(self._c("can you check my inbox for anything urgent"), "email_read")

    def test_calendar_write(self):
        self.assertEqual(self._c("schedule a meeting with Vidyut next Tuesday"), "calendar_write")
        self.assertEqual(self._c("set up a calendar event for the review"), "calendar_write")

    def test_calendar_read(self):
        self.assertEqual(self._c("do I have any meetings tomorrow"), "calendar_read")
        self.assertEqual(self._c("what's on my calendar"), "calendar_read")

    def test_bare_meeting_is_not_calendar(self):
        # "this meeting" in live-meeting speech must not trigger calendar.
        self.assertEqual(self._c("what do you think about this meeting"), "generic")

    def test_meeting_recall_beats_web_and_knowledge(self):
        self.assertEqual(self._c("check the documents about what we discussed in the last meeting"),
                         "meeting_recall")

    def test_knowledge(self):
        self.assertEqual(self._c("look in the knowledge base for the vendor SLA"), "knowledge")

    def test_summary(self):
        self.assertEqual(self._c("summarize the meeting so far"), "summary")

    def test_actions(self):
        self.assertEqual(self._c("list the action items please"), "actions")

    def test_web(self):
        self.assertEqual(self._c("what's the weather tomorrow"), "web")
        self.assertEqual(self._c("look up the latest on the chip shortage"), "web")

    def test_generic_fallback(self):
        self.assertEqual(self._c("can you help us settle this"), "generic")
        self.assertEqual(self._c(""), "generic")


class PhraseTests(unittest.TestCase):
    def test_every_category_has_phrases(self):
        for cat in ack_phrases.CATEGORIES:
            self.assertTrue(ack_phrases.PHRASES[cat], cat)

    def test_pick_phrase_rotates_per_bot(self):
        state = {}
        seen = {ack_phrases.pick_phrase("generic", state) for _ in range(4)}
        self.assertEqual(len(seen), len(ack_phrases.PHRASES["generic"]))

    def test_all_phrases_iterable_for_presynthesis(self):
        phrases = ack_phrases.all_phrases()
        self.assertGreaterEqual(len(phrases), 10)
        self.assertEqual(len(phrases), len(set(phrases)))  # no duplicates

    def test_flags(self):
        import os
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(ack_phrases.ack_on())
            self.assertAlmostEqual(ack_phrases.ack_delay_s(), 1.2)
        with mock.patch.dict(os.environ, {"PRISM_ACK": "0", "PRISM_ACK_DELAY_S": "2"}):
            self.assertFalse(ack_phrases.ack_on())
            self.assertAlmostEqual(ack_phrases.ack_delay_s(), 2.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ack.py -v`
Expected: collection ERROR (`ModuleNotFoundError: ack_phrases`).

- [ ] **Step 3: Implement `backend/ack_phrases.py`**

```python
"""Instant-acknowledgment phrases: category classifier + rotating variants.

The ack must FEEL like comprehension, not filler — so classification is
deliberately conservative: a wrong-category ack ("Checking your calendar—"
for a web question) reads as MISunderstanding, which is worse than the
neutral fallback. First confident match wins, top-to-bottom.

Pure logic, no I/O. Audio pre-synthesis lives in ack_audio.py.
"""

import os
import re

def ack_on() -> bool:
    return os.getenv("PRISM_ACK", "1") == "1"

def ack_delay_s() -> float:
    return float(os.getenv("PRISM_ACK_DELAY_S", "1.2"))


_EMAIL_WORDS = r"(?:e-?mails?|mail|gmail|inbox)"
_WRITE_VERBS = r"(?:send|draft|write|reply|forward|compose)"
_CAL_WORDS = r"(?:calendar|schedule|events?|invites?)"
_CAL_WRITE = r"(?:schedule|create|set\s+up|add|book|move|reschedule)"

# Ordered: first match wins. meeting_recall outranks knowledge/web so
# "check the docs about what we discussed last meeting" acknowledges recall.
_RULES: list[tuple[str, re.Pattern]] = [
    ("meeting_recall", re.compile(
        r"\b(?:last|previous|earlier)\s+meeting\b|\bwe\s+(?:talked|discussed|said|decided)\b",
        re.IGNORECASE)),
    ("email_write", re.compile(
        rf"\b{_WRITE_VERBS}\b[\w\s,]{{0,20}}\b{_EMAIL_WORDS}\b|\b{_EMAIL_WORDS}\b[\w\s,]{{0,20}}\b{_WRITE_VERBS}\b",
        re.IGNORECASE)),
    ("email_read", re.compile(rf"\b{_EMAIL_WORDS}\b", re.IGNORECASE)),
    ("calendar_write", re.compile(
        rf"\b{_CAL_WRITE}\b[\w\s,]{{0,30}}\b(?:{_CAL_WORDS}|meeting)\b",
        re.IGNORECASE)),
    ("calendar_read", re.compile(
        rf"\b{_CAL_WORDS}\b|\bmeetings?\b[\w\s,]{{0,15}}\b(?:tomorrow|today|next|this\s+week)\b"
        rf"|\b(?:tomorrow|today|next\s+\w+)\b[\w\s,]{{0,15}}\bmeetings?\b",
        re.IGNORECASE)),
    ("knowledge", re.compile(
        r"\bknowledge\s*base\b|\bdocuments?\b|\bdocs?\b|\bfiles?\b|\buploaded\b|\bpdf\b",
        re.IGNORECASE)),
    ("summary", re.compile(r"\bsummar|recap\b", re.IGNORECASE)),
    ("actions", re.compile(
        r"\baction\s+items?\b|\bdecisions?\b|\btask\s+list\b|\bto-?dos?\b", re.IGNORECASE)),
    ("web", re.compile(
        r"\blook\s+up\b|\bsearch\b|\bweather\b|\bnews\b|\blatest\b|\bprice\b|\bstock\b",
        re.IGNORECASE)),
]

CATEGORIES = [name for name, _ in _RULES] + ["generic"]

PHRASES: dict[str, list[str]] = {
    "email_write":    ["Drafting that email now—", "Let me put that email together—"],
    "email_read":     ["Let me check your inbox—", "Looking at your email—"],
    "calendar_write": ["Let me set that up on your calendar—"],
    "calendar_read":  ["Let me pull up your calendar—", "Checking your schedule—"],
    "meeting_recall": ["Let me look back through the meeting notes—"],
    "knowledge":      ["Let me go through your documents—"],
    "summary":        ["Give me a moment to pull that together—"],
    "actions":        ["Let me gather the action items—"],
    "web":            ["Let me look that up—", "Searching for that now—"],
    "generic":        ["On it — one moment.", "Sure — give me a second."],
}


def classify_command(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "generic"
    for name, pattern in _RULES:
        if pattern.search(t):
            return name
    return "generic"


def pick_phrase(category: str, state: dict) -> str:
    """Rotate variants per bot so consecutive commands don't repeat."""
    variants = PHRASES.get(category) or PHRASES["generic"]
    counts = state.setdefault("_ack_rotation", {})
    i = counts.get(category, 0)
    counts[category] = i + 1
    return variants[i % len(variants)]


def all_phrases() -> list[str]:
    out: list[str] = []
    for variants in PHRASES.values():
        for p in variants:
            if p not in out:
                out.append(p)
    return out
```

- [ ] **Step 4: Run tests** — `python -m pytest tests/test_ack.py -v` → all PASS. Iterate on regexes until the classifier tests pass exactly (the tests are the taxonomy contract).

- [ ] **Step 5: Commit**

```bash
git add backend/ack_phrases.py backend/tests/test_ack.py
git commit -m "Add ack-phrase taxonomy: conservative classifier + rotating variants"
```

---

## Task 2: `ack_audio.py` — pre-synthesized audio cache, wired into warmup

**Files:** Create `backend/ack_audio.py`; Modify `backend/warmup.py`; Test `backend/tests/test_ack.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ack.py`)

```python
import ack_audio  # noqa: E402


class AckAudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ack_audio._CACHE.clear()

    async def test_ensure_synthesizes_all_phrases(self):
        synthesized = []

        async def fake_tts(text):
            synthesized.append(text)
            return b"audio:" + text.encode()

        with mock.patch.object(ack_audio, "text_to_speech", new=fake_tts):
            await ack_audio.ensure_ack_audio()
        self.assertEqual(sorted(synthesized), sorted(ack_phrases.all_phrases()))
        phrase = ack_phrases.PHRASES["generic"][0]
        self.assertEqual(ack_audio.get_ack_audio(phrase), b"audio:" + phrase.encode())

    async def test_ensure_is_idempotent(self):
        calls = []

        async def fake_tts(text):
            calls.append(text)
            return b"a"

        with mock.patch.object(ack_audio, "text_to_speech", new=fake_tts):
            await ack_audio.ensure_ack_audio()
            await ack_audio.ensure_ack_audio()
        self.assertEqual(len(calls), len(ack_phrases.all_phrases()))  # no re-synthesis

    async def test_failures_skipped_not_raised(self):
        async def flaky_tts(text):
            if "inbox" in text:
                raise RuntimeError("tts down")
            return b"a"

        with mock.patch.object(ack_audio, "text_to_speech", new=flaky_tts):
            await ack_audio.ensure_ack_audio()  # must not raise
        self.assertIsNone(ack_audio.get_ack_audio("Let me check your inbox—"))
        self.assertIsNotNone(ack_audio.get_ack_audio("On it — one moment."))
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_ack.py::AckAudioTests -v` → `ModuleNotFoundError: ack_audio`.

- [ ] **Step 3: Implement `backend/ack_audio.py`**

```python
"""Pre-synthesized acknowledgment audio. edge-tts costs ~2.7s per clip, so ack
audio MUST be synthesized ahead of time — this cache is filled by warmup
(startup + bot-join) and read by the ack timer in realtime_routes."""

import asyncio

import ack_phrases
from tools.tts import text_to_speech

_CACHE: dict[str, bytes] = {}
_SYNTH_CONCURRENCY = 3


async def ensure_ack_audio() -> None:
    """Synthesize any missing phrases. Idempotent; failures are skipped (the
    ack timer just stays silent for a phrase with no audio)."""
    missing = [p for p in ack_phrases.all_phrases() if p not in _CACHE]
    if not missing:
        return
    sem = asyncio.Semaphore(_SYNTH_CONCURRENCY)

    async def _one(phrase: str) -> None:
        async with sem:
            try:
                audio = await text_to_speech(phrase)
                if audio:
                    _CACHE[phrase] = audio
            except Exception as e:
                print(f"[ack] synthesis failed for {phrase!r}: {type(e).__name__}: {e}")

    await asyncio.gather(*(_one(p) for p in missing))
    print(f"[ack] audio cache ready: {len(_CACHE)}/{len(ack_phrases.all_phrases())} phrases")


def get_ack_audio(phrase: str):
    return _CACHE.get(phrase)
```

- [ ] **Step 4: Wire into `backend/warmup.py`** — replace `_warm_tts` (the "ok" ping) since synthesizing real phrases IS the TTS warm-up:

```python
async def _warm_tts() -> None:
    from ack_audio import ensure_ack_audio
    await ensure_ack_audio()
```

(The existing warmup tests patch `_warm_tts` by name, so they stay green.)

- [ ] **Step 5: Run tests** — `python -m pytest tests/test_ack.py tests/test_warmup.py -v` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/ack_audio.py backend/warmup.py backend/tests/test_ack.py
git commit -m "Pre-synthesize ack audio at warmup (edge-tts is too slow for runtime acks)"
```

---

## Task 3: Wiring — arm/cancel race timer in `_process_command`

**Files:** Modify `backend/realtime_routes.py`, `backend/perception_state.py`; Test `backend/tests/test_ack.py`

- [ ] **Step 1: Write the failing tests** (append to `test_ack.py`)

```python
import meeting_memory  # noqa: E402
import perception_state  # noqa: E402
import realtime_routes as rt  # noqa: E402


class AckWiringTests(unittest.IsolatedAsyncioTestCase):
    def _state(self):
        return meeting_memory.get_initial_memory_state()

    async def test_ack_fires_after_delay_when_no_real_audio(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.05"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=b"ack-bytes"), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox please")
            await asyncio.sleep(0.15)
        self.assertEqual(uploaded, [b"ack-bytes"])
        self.assertEqual(perception_state.ensure_counters(state)["ack_played"], 1)

    async def test_cancel_before_delay_suppresses_ack(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.2"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=b"ack-bytes"), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox please")
            await asyncio.sleep(0.02)
            rt._cancel_ack(state)
            await asyncio.sleep(0.3)
        self.assertEqual(uploaded, [])
        self.assertEqual(perception_state.ensure_counters(state)["ack_cancelled_fast"], 1)

    async def test_flag_off_never_arms(self):
        state = self._state()
        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK": "0"}):
            rt._arm_ack("b1", state, "check my inbox")
        self.assertIsNone(state.get("_ack_task"))

    async def test_missing_audio_is_silent_noop(self):
        state = self._state()
        uploaded = []

        async def fake_upload(bot_id, audio):
            uploaded.append(audio)
            return True

        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "0.05"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"), \
             mock.patch.object(rt.ack_audio, "get_ack_audio", return_value=None), \
             mock.patch.object(rt, "_upload_audio_to_recall", new=fake_upload):
            rt._arm_ack("b1", state, "check my inbox")
            await asyncio.sleep(0.15)
        self.assertEqual(uploaded, [])

    async def test_new_command_replaces_pending_ack(self):
        state = self._state()
        with mock.patch.dict(__import__("os").environ, {"PRISM_ACK_DELAY_S": "5"}), \
             mock.patch.object(rt, "RECALL_API_KEY", "k"):
            rt._arm_ack("b1", state, "first command")
            first_task = state["_ack_task"]
            rt._arm_ack("b1", state, "second command")
            await asyncio.sleep(0.01)
            self.assertTrue(first_task.cancelled() or first_task.done())
            state["_ack_task"].cancel()
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_ack.py::AckWiringTests -v` → `AttributeError: _arm_ack`.

- [ ] **Step 3: Implement in `realtime_routes.py`**

(a) Imports near the top: `import ack_phrases` and `import ack_audio`.

(b) New helpers (place near the voice-send functions):

```python
def _cancel_ack(state: dict) -> None:
    """Real audio is about to play (or did) — suppress any pending ack."""
    task = state.pop("_ack_task", None)
    if task is not None and not task.done():
        task.cancel()
        perception_state.bump(state, "ack_cancelled_fast")


def _arm_ack(bot_id: str, state: dict, command: str) -> None:
    """Race timer: if no real audio uploads within ack_delay_s, speak the
    pre-synthesized category acknowledgment. The first real upload cancels it."""
    if not ack_phrases.ack_on() or not RECALL_API_KEY:
        return
    _cancel_ack(state)  # a newer command supersedes any pending ack

    category = ack_phrases.classify_command(command)
    phrase = ack_phrases.pick_phrase(category, state)

    async def _fire():
        await asyncio.sleep(ack_phrases.ack_delay_s())
        audio = ack_audio.get_ack_audio(phrase)
        if not audio:
            return  # synthesis failed/unfinished — stay silent, never block
        if await _upload_audio_to_recall(bot_id, audio):
            perception_state.bump(state, "ack_played")
            print(f"[ack] played category={category} phrase={phrase!r} bot={bot_id[:8]}")
        state.pop("_ack_task", None)

    state["_ack_task"] = asyncio.create_task(_fire())
```

Note on `_cancel_ack` counter semantics: it bumps `ack_cancelled_fast` only when it actually cancels a live task — calls when nothing is pending are no-ops (the `_arm_ack` supersede path will bump once; acceptable signal noise, keep it simple).

(c) Arm it in `_process_command`, immediately after the debounce/dedup/processing guards pass (right before `state["processing"] = True` or equivalent — the command is now definitely going to be processed):

```python
        _arm_ack(bot_id, state, command)
```

(d) Cancel at every first-real-audio site:
- `_stream_llm_to_voice`: right before the first `_upload_audio_to_recall` succeeds — at the `first_upload_logged` site, call `_cancel_ack(state)` *before* the upload line so ack and answer can't race.
- `_send_voice_response_streamed`: same — at its `first_upload_logged` site.
- `_send_voice_response` (buffered): call `_cancel_ack(_get_bot_state(bot_id))` just before its upload.
- Also cancel on command failure (the `reply = "Sorry, I had trouble..."` paths and the end of `_process_command`'s exception handler) so a dead command doesn't ack into silence... actually an ack before an error reply is fine — the error reply IS real audio. Only cancel where no audio will ever come: if `_process_command` returns early before any reply (debounce path is before arming, so the only case is an exception with no voice reply — add `_cancel_ack(state)` in the final `except` branch if it returns without sending voice).

(e) `perception_state.py`: add `"ack_played": 0, "ack_cancelled_fast": 0` to `_DEFAULT_COUNTERS` and both names to `_OPERATIONAL_KEYS`.

- [ ] **Step 4: Run the feature tests + adjacent suites**

Run: `python -m pytest tests/test_ack.py tests/test_ambient_lane.py tests/test_ambient_wiring.py tests/test_sentinel_replies.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/perception_state.py backend/tests/test_ack.py
git commit -m "Arm instant-ack race timer on voice commands; cancel on first real audio"
```

---

## Task 4: Docs + full verification

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: CLAUDE.md** — append one sentence to the `realtime_routes.py` paragraph:

```markdown
Voice commands get an instant pre-synthesized acknowledgment ("Let me pull up
your calendar—") if real audio hasn't started within ~1.2s (`PRISM_ACK`,
`PRISM_ACK_DELAY_S`; taxonomy in `ack_phrases.py`, audio cache in
`ack_audio.py`, filled at warmup).
```

- [ ] **Step 2: Full suite** — `python -m pytest tests/ -q` → all PASS.

- [ ] **Step 3: Live verification checklist** (manual, next meeting):
- Restart backend → expect `[ack] audio cache ready: 14/14 phrases` shortly after `[warmup] connections warm (startup)`.
- Ask a calendar question → bot says "Let me pull up your calendar—" within ~1.5s, answer follows; log shows `[ack] played category=calendar_read`.
- Ask something trivially fast (if any) → no ack, `ack_cancelled_fast` increments.
- Ask two commands in a row → different ack phrasing (rotation).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Document instant acknowledgments"
```

---

## Self-review notes

- **Spec coverage:** ack-feels-understood → conservative classifier + taxonomy table (user-reviewable); both-run-at-once → race timer armed at command start, generation proceeds in parallel; per-case responses → 10 categories incl. email/calendar split read vs write.
- **Race safety:** ack upload and first-answer upload are both bounded (~1s ack clip); worst case they play back-to-back, never interleaved (Recall serializes uploads).
- **Failure modes:** no audio cached → silent no-op; flag off → no tasks created; new command → supersedes pending ack; bot teardown → task references dead state harmlessly (upload fails, logged).
- **Not in scope:** chat-message text acks ("⏳ checking…"), runtime-LLM-personalized acks (needs sub-second TTS first), ambient lane (has prefaces).

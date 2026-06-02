# Live-Bot Persona Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live meeting bot's replies adopt the bot owner's persona, by baking the resolved persona text into the cache-stable static system prefix.

**Architecture:** Resolve the owner's persona text from the `user_settings` row that `_get_settings_for_bot` *already* fetches (no extra DB call), and append it — through a tool-aware safety wrapper — to `_build_static_prefix`, so it rides Groq's prompt cache for the whole meeting. Command-reply path only.

**Tech Stack:** Python 3 / FastAPI backend, `unittest` tests run under pytest, Groq `llama-3.3-70b-versatile` (with a Claude Haiku fallback).

**Spec:** `docs/superpowers/specs/2026-06-02-live-bot-persona-wiring-design.md`

---

## Conventions for this plan

- **Run backend tests from the repo root** (`c:\Users\abhin\PrismAI`):
  `python -m pytest backend/tests/<file>.py -v`
  Test files self-insert `backend/` onto `sys.path`, so root invocation works.
- **Commit messages:** sentence-style to match repo history; **no `Co-Authored-By` trailer** (project owner takes sole authorship).
- Branch: continue on `fixed-changes` (the active branch).

## File structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/agents/utils.py` | Shared LLM helpers + persona wrappers | Factor out `persona_suffix`; add `persona_suffix_agentic`; `get_persona_suffix` delegates |
| `backend/personas.py` | Persona resolution + cache | Add `_resolve_user_persona` + `persona_text_from_settings`; refactor `_fetch` to reuse the helper |
| `backend/realtime_routes.py` | Live-meeting bot loop | Thread `persona_text` through `_build_static_prefix` / `_build_command_messages`; resolve it in `_get_settings_for_bot`; pass it in `_process_command` |
| `backend/tests/test_persona_wrappers.py` | NEW — wrapper unit tests | Create |
| `backend/tests/test_personas.py` | Existing resolver suite | Add `persona_text_from_settings` tests (also the `_fetch` refactor regression guard) |
| `backend/tests/test_prompt_structure.py` | Existing prefix-structure suite | Add persona-in-prefix tests |
| `backend/tests/test_realtime_persona.py` | NEW — settings→persona wiring test | Create |

---

## Task 1: Persona wrappers in `agents/utils.py`

**Files:**
- Modify: `backend/agents/utils.py:17-31`
- Test: `backend/tests/test_persona_wrappers.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_persona_wrappers.py`:

```python
# backend/tests/test_persona_wrappers.py
"""Persona suffix wrappers (canonical + tool-aware) and contextvar delegation."""
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.utils import (
    persona_suffix,
    persona_suffix_agentic,
    get_persona_suffix,
    _PERSONA_TEXT,
)


class PersonaWrapperTests(unittest.TestCase):
    def test_persona_suffix_empty_returns_empty(self):
        self.assertEqual(persona_suffix(""), "")

    def test_persona_suffix_whitespace_returns_empty(self):
        self.assertEqual(persona_suffix("   "), "")

    def test_persona_suffix_wraps_text(self):
        out = persona_suffix("Be terse.")
        self.assertIn("Be terse.", out)
        self.assertIn("Tone instruction", out)

    def test_agentic_empty_returns_empty(self):
        self.assertEqual(persona_suffix_agentic(""), "")
        self.assertEqual(persona_suffix_agentic("   "), "")

    def test_agentic_fences_tool_calls(self):
        out = persona_suffix_agentic("Be terse.")
        self.assertIn("Be terse.", out)
        # The distinguishing clause: persona must not change tool behavior.
        self.assertIn("your available tools", out)

    def test_get_persona_suffix_delegates_to_canonical(self):
        token = _PERSONA_TEXT.set("Be terse.")
        try:
            self.assertEqual(get_persona_suffix(), persona_suffix("Be terse."))
        finally:
            _PERSONA_TEXT.reset(token)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_persona_wrappers.py -v`
Expected: FAIL — `ImportError: cannot import name 'persona_suffix' from 'agents.utils'`

- [ ] **Step 3: Write minimal implementation**

In `backend/agents/utils.py`, replace the current `get_persona_suffix` block (lines 17-31):

```python
def get_persona_suffix() -> str:
    """Return the safety-wrapped persona suffix for the current context.
    Empty string when no persona is set (or when the active persona is the
    'default' preset, which has empty text).

    Use this from call sites that DON'T go through llm_call (e.g., the
    tool-calling chat path that hits Groq directly)."""
    persona = _PERSONA_TEXT.get()
    if not persona:
        return ""
    return (
        "\n\n"
        "Tone instruction (does not change facts, schema, scores, or JSON keys):\n"
        f"{persona}"
    )
```

with:

```python
def persona_suffix(text: str) -> str:
    """Canonical safety-wrapped tone suffix for an explicit persona string.
    Empty when text is empty/whitespace (or the 'default' preset, which has
    empty text). Used by the analysis agents via get_persona_suffix."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone instruction (does not change facts, schema, scores, or JSON keys):\n"
        f"{text}"
    )


def persona_suffix_agentic(text: str) -> str:
    """Tool-aware variant for agentic surfaces (the live meeting bot) that
    decide whether and which tools to call. Fences persona to wording only so
    a tone preset can't suppress or distort a real tool call."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone and style instruction (applies to your wording only — it does "
        "not change the facts, your available tools, or whether and how you "
        "call them):\n"
        f"{text}"
    )


def get_persona_suffix() -> str:
    """Safety-wrapped persona suffix for the current contextvar. Empty when no
    persona is set. Use from call sites that DON'T go through llm_call (e.g.,
    the tool-calling chat path that hits Groq directly)."""
    return persona_suffix(_PERSONA_TEXT.get())
```

(`llm_call` at line 86 still calls `get_persona_suffix()` — unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_persona_wrappers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Guard the refactor — run the existing contextvar suite**

Run: `python -m pytest backend/tests/test_personas_contextvar.py -v`
Expected: PASS (no regressions — `get_persona_suffix` behavior is preserved)

- [ ] **Step 6: Commit**

```bash
git add backend/agents/utils.py backend/tests/test_persona_wrappers.py
git commit -m "Add tool-aware persona wrapper; factor out persona_suffix"
```

---

## Task 2: `persona_text_from_settings` + `_fetch` refactor in `personas.py`

**Files:**
- Modify: `backend/personas.py:152-189` (refactor `_fetch`; add helpers above it)
- Test: `backend/tests/test_personas.py` (add a test class)

- [ ] **Step 1: Write the failing test**

Append this test class to `backend/tests/test_personas.py`, immediately before the
`if __name__ == "__main__":` block at the bottom:

```python
class PersonaTextFromSettingsTests(unittest.TestCase):
    """Row-only resolution used by the live bot (no DB call, user-portion only)."""

    def test_empty_row_returns_empty(self):
        import personas
        self.assertEqual(personas.persona_text_from_settings({}), "")

    def test_default_preset_returns_empty(self):
        import personas
        self.assertEqual(
            personas.persona_text_from_settings({"persona_preset": "default"}), ""
        )

    def test_preset_returns_preset_text(self):
        import personas
        out = personas.persona_text_from_settings({"persona_preset": "concise"})
        self.assertEqual(out, personas.PRESETS["concise"])

    def test_custom_returns_verbatim(self):
        import personas
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": "Talk like a pirate."}
        )
        self.assertEqual(out, "Talk like a pirate.")

    def test_custom_whitespace_falls_through_to_empty(self):
        import personas
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": "   "}
        )
        self.assertEqual(out, "")

    def test_custom_capped_at_max_chars(self):
        import personas
        long = "x" * (personas.CUSTOM_PROMPT_MAX_CHARS + 50)
        out = personas.persona_text_from_settings(
            {"persona_preset": "custom", "persona_custom_prompt": long}
        )
        self.assertEqual(len(out), personas.CUSTOM_PROMPT_MAX_CHARS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_personas.py::PersonaTextFromSettingsTests -v`
Expected: FAIL — `AttributeError: module 'personas' has no attribute 'persona_text_from_settings'`

- [ ] **Step 3: Write minimal implementation**

In `backend/personas.py`, replace the current `_fetch` function (lines 152-189):

```python
async def _fetch(sb, user_id: str, workspace_id: Optional[str]) -> Optional[ResolvedPersona]:
    """Returns the resolved persona on success, None on failure."""
    try:
        user_res = await _execute(
            sb.table("user_settings")
            .select("persona_preset, persona_custom_prompt")
            .eq("user_id", user_id)
            .maybe_single()
        )
        u = (user_res.data or {}) if user_res else {}
        preset = u.get("persona_preset") or "default"
        custom = (u.get("persona_custom_prompt") or "")[:CUSTOM_PROMPT_MAX_CHARS]

        if preset == "custom" and custom:
            return ResolvedPersona("custom", custom)
        if preset != "default" and preset in PRESETS:
            return ResolvedPersona(preset, PRESETS[preset])

        if workspace_id:
            ws_res = await _execute(
                sb.table("workspaces")
                .select("default_persona")
                .eq("id", workspace_id)
                .maybe_single()
            )
            ws = (ws_res.data or {}) if ws_res else {}
            ws_preset = ws.get("default_persona") or "default"
            if ws_preset != "default" and ws_preset in PRESETS:
                return ResolvedPersona(ws_preset, PRESETS[ws_preset])

        return ResolvedPersona("default", "")
    except Exception as exc:
        # Broad except mirrors caches.py — a transient DB blip mustn't lock
        # the user into "default" forever. But unlike caches.py we make two
        # DB calls here, doubling the failure surface — log so misconfigured
        # column names or chains don't disappear silently in prod.
        print(f"[personas] _fetch failed for user={user_id} ws={workspace_id}: {exc!r}")
        return None
```

with this — a shared user-portion resolver, a row-only public helper, and a
slimmed `_fetch` that reuses the resolver:

```python
def _resolve_user_persona(row: dict) -> Optional[ResolvedPersona]:
    """User-portion resolution from a user_settings row. Returns a
    ResolvedPersona for a non-default override, or None if the user is on
    'default' (caller decides the fallback — workspace default or system
    default). Single source of truth for preset→PRESETS + custom handling."""
    preset = (row or {}).get("persona_preset") or "default"
    custom = ((row or {}).get("persona_custom_prompt") or "")[:CUSTOM_PROMPT_MAX_CHARS]
    if preset == "custom" and custom.strip():
        return ResolvedPersona("custom", custom)
    if preset != "default" and preset in PRESETS:
        return ResolvedPersona(preset, PRESETS[preset])
    return None


def persona_text_from_settings(row: dict) -> str:
    """Live-bot entry point: raw persona text from an already-fetched
    user_settings row (no DB call), or '' for the 'default' preset. Workspace
    defaults are intentionally NOT consulted here (the live bot resolves the
    owner's personal persona only)."""
    hit = _resolve_user_persona(row)
    return hit.text if hit else ""


async def _fetch(sb, user_id: str, workspace_id: Optional[str]) -> Optional[ResolvedPersona]:
    """Returns the resolved persona on success, None on failure."""
    try:
        user_res = await _execute(
            sb.table("user_settings")
            .select("persona_preset, persona_custom_prompt")
            .eq("user_id", user_id)
            .maybe_single()
        )
        u = (user_res.data or {}) if user_res else {}
        hit = _resolve_user_persona(u)
        if hit is not None:
            return hit

        if workspace_id:
            ws_res = await _execute(
                sb.table("workspaces")
                .select("default_persona")
                .eq("id", workspace_id)
                .maybe_single()
            )
            ws = (ws_res.data or {}) if ws_res else {}
            ws_preset = ws.get("default_persona") or "default"
            if ws_preset != "default" and ws_preset in PRESETS:
                return ResolvedPersona(ws_preset, PRESETS[ws_preset])

        return ResolvedPersona("default", "")
    except Exception as exc:
        # Broad except mirrors caches.py — a transient DB blip mustn't lock
        # the user into "default" forever. But unlike caches.py we make two
        # DB calls here, doubling the failure surface — log so misconfigured
        # column names or chains don't disappear silently in prod.
        print(f"[personas] _fetch failed for user={user_id} ws={workspace_id}: {exc!r}")
        return None
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest backend/tests/test_personas.py::PersonaTextFromSettingsTests -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the FULL existing resolver suite (refactor regression guard)**

Run: `python -m pytest backend/tests/test_personas.py -v`
Expected: PASS (all pre-existing tests + the 6 new ones). This proves the `_fetch`
refactor preserved `resolve_persona` behavior.

- [ ] **Step 6: Commit**

```bash
git add backend/personas.py backend/tests/test_personas.py
git commit -m "Add persona_text_from_settings; share user-portion resolution"
```

---

## Task 3: Thread `persona_text` into the cached prefix

**Files:**
- Modify: `backend/realtime_routes.py:21` (import), `:252` (`_build_static_prefix`), `:288-336` (`_build_command_messages`)
- Test: `backend/tests/test_prompt_structure.py` (add a test class)

- [ ] **Step 1: Write the failing test**

Append this test class to `backend/tests/test_prompt_structure.py`, immediately
before the `if __name__ == "__main__":` block:

```python
class PersonaInPrefixTests(unittest.TestCase):
    """Persona belongs in the cached static prefix (msgs[0]), never the user
    turn — this locks in the chosen design (Approach A)."""

    def _msgs(self, persona_text):
        return rr._build_command_messages(
            has_gmail=False, has_calendar=False,
            now_str="t", memory_context="m",
            speaker="Alice", command="check the weather",
            prompt_cache_on=True, persona_text=persona_text,
        )

    def test_persona_lands_in_static_prefix(self):
        msgs = self._msgs("Be terse.")
        self.assertIn("Be terse.", msgs[0]["content"])      # static prefix
        self.assertNotIn("Be terse.", msgs[1]["content"])   # dynamic system
        self.assertNotIn("Be terse.", msgs[-1]["content"])  # user turn

    def test_prefix_uses_agentic_wrapper(self):
        msgs = self._msgs("Be terse.")
        self.assertIn("your available tools", msgs[0]["content"])

    def test_default_persona_prefix_byte_identical(self):
        # Empty persona must leave the prefix byte-identical to no-persona.
        with_default = self._msgs("")[0]["content"]
        without_arg = rr._build_command_messages(
            has_gmail=False, has_calendar=False,
            now_str="t", memory_context="m",
            speaker="Alice", command="check the weather",
            prompt_cache_on=True,
        )[0]["content"]
        self.assertEqual(_h(with_default), _h(without_arg))

    def test_persona_prefix_stable_across_commands(self):
        # Same persona, evolving per-call state → prefix byte-identical (cache).
        m1 = rr._build_command_messages(
            has_gmail=False, has_calendar=False, now_str="A",
            memory_context="X", speaker="A", command="c1",
            prompt_cache_on=True, persona_text="Be terse.",
        )
        m2 = rr._build_command_messages(
            has_gmail=False, has_calendar=False, now_str="B",
            memory_context="Y", speaker="A", command="c2",
            prompt_cache_on=True, persona_text="Be terse.",
        )
        self.assertEqual(_h(m1[0]["content"]), _h(m2[0]["content"]))

    def test_persona_in_legacy_single_system_message(self):
        msgs = rr._build_command_messages(
            has_gmail=False, has_calendar=False, now_str="t",
            memory_context="m", speaker="A", command="c",
            prompt_cache_on=False, persona_text="Be terse.",
        )
        self.assertEqual(len(msgs), 2)
        self.assertIn("Be terse.", msgs[0]["content"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_prompt_structure.py::PersonaInPrefixTests -v`
Expected: FAIL — `TypeError: _build_command_messages() got an unexpected keyword argument 'persona_text'`

- [ ] **Step 3a: Add the import**

In `backend/realtime_routes.py` line 21, change:

```python
from agents.utils import llm_call, strip_fences
```

to:

```python
from agents.utils import llm_call, strip_fences, persona_suffix_agentic
```

- [ ] **Step 3b: Extend `_build_static_prefix`**

Change the signature (line 252) from:

```python
def _build_static_prefix(has_gmail: bool, has_calendar: bool) -> str:
```

to:

```python
def _build_static_prefix(has_gmail: bool, has_calendar: bool, persona_text: str = "") -> str:
```

Then change the `return base` statement (line 285) from:

```python
    return base
```

to:

```python
    # Persona is the bot owner's tone preset. It rides the cached prefix so it
    # costs nothing per command after the first. Tool-aware wrapper fences it
    # off from tool-calling decisions. Empty persona → byte-identical prefix.
    return base + persona_suffix_agentic(persona_text)
```

- [ ] **Step 3c: Thread `persona_text` through `_build_command_messages`**

Change the signature (lines 288-299) to add `persona_text`:

```python
def _build_command_messages(
    *,
    has_gmail: bool,
    has_calendar: bool,
    now_str: str,
    memory_context: str,
    speaker: str,
    command: str,
    prompt_cache_on: bool,
    injection_guard_on: bool = False,
    is_owner: bool = True,
    persona_text: str = "",
) -> list[dict]:
```

Update BOTH `_build_static_prefix(...)` call sites inside this function. The
cache-on branch (line 317):

```python
            {"role": "system", "content": _build_static_prefix(has_gmail, has_calendar)},
```

becomes:

```python
            {"role": "system", "content": _build_static_prefix(has_gmail, has_calendar, persona_text)},
```

And the legacy branch (line 329):

```python
                _build_static_prefix(has_gmail, has_calendar)
```

becomes:

```python
                _build_static_prefix(has_gmail, has_calendar, persona_text)
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest backend/tests/test_prompt_structure.py::PersonaInPrefixTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the FULL prefix-structure suite (cache-stability regression guard)**

Run: `python -m pytest backend/tests/test_prompt_structure.py -v`
Expected: PASS — the pre-existing `StaticPrefixCacheStabilityTests` still pass
because `persona_text` defaults to `""` → no suffix → byte-identical prefix.

- [ ] **Step 6: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_prompt_structure.py
git commit -m "Thread owner persona into live-bot cached system prefix"
```

---

## Task 4: Resolve persona in `_get_settings_for_bot` and pass it in `_process_command`

**Files:**
- Modify: `backend/realtime_routes.py:765-811` (`_get_settings_for_bot`), `:1530-1596` (`_process_command`)
- Test: `backend/tests/test_realtime_persona.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_realtime_persona.py`:

```python
# backend/tests/test_realtime_persona.py
"""_get_settings_for_bot resolves the owner's persona from the row it already
fetches — no second DB query."""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

if "pysbd" not in sys.modules:
    _fake_pysbd = types.ModuleType("pysbd")
    class _FakeSegmenter:
        def __init__(self, *_a, **_k): pass
        def segment(self, text): return [text]
    _fake_pysbd.Segmenter = _FakeSegmenter
    sys.modules["pysbd"] = _fake_pysbd

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")

import personas
import realtime_routes as rr


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, row):
        self._row = row
    def select(self, *_a, **_k):
        return self
    def eq(self, *_a, **_k):
        return self
    def maybe_single(self):
        return self
    def execute(self):
        return _Result(self._row)


def _fake_sb(row):
    sb = types.SimpleNamespace()
    sb.table = lambda _name: _FakeQuery(row)
    return sb


class GetSettingsForBotPersonaTests(unittest.TestCase):
    def setUp(self):
        rr._bot_settings_cache.clear()
        self._orig_sb = rr.supabase
        self._orig_store = dict(rr.bot_store)

    def tearDown(self):
        rr.supabase = self._orig_sb
        rr.bot_store.clear()
        rr.bot_store.update(self._orig_store)
        rr._bot_settings_cache.clear()

    def test_persona_text_resolved_from_row(self):
        # Row has a persona but NO google token → no calendar import path.
        rr.supabase = _fake_sb({"persona_preset": "cheeky", "persona_custom_prompt": None})
        rr.bot_store["botX"] = {"user_id": "u1"}
        settings = asyncio.run(rr._get_settings_for_bot("botX"))
        self.assertEqual(settings["persona_text"], personas.PRESETS["cheeky"])

    def test_persona_text_empty_when_no_user(self):
        rr.supabase = _fake_sb({"persona_preset": "cheeky"})
        rr.bot_store["botY"] = {}  # no user_id → no fetch
        settings = asyncio.run(rr._get_settings_for_bot("botY"))
        self.assertEqual(settings["persona_text"], "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_realtime_persona.py -v`
Expected: FAIL — `KeyError: 'persona_text'` (the key isn't set yet)

- [ ] **Step 3a: Import the row resolver**

In `backend/realtime_routes.py`, add this import near the other top-level imports
(e.g., directly under the `from agents.utils import ...` line edited in Task 3):

```python
from personas import persona_text_from_settings
```

- [ ] **Step 3b: Set `persona_text` in `_get_settings_for_bot`**

Find the `settings = {}` line (line 776) and add a default immediately after it:

```python
    settings = {}
    settings["persona_text"] = ""
```

Then, inside the `if user_id and supabase:` block, find where the row is read
(line 790):

```python
            row = (resp.data if resp is not None else None) or {}
```

and add this line directly after it:

```python
            row = (resp.data if resp is not None else None) or {}
            settings["persona_text"] = persona_text_from_settings(row)
```

- [ ] **Step 3c: Read and pass `persona_text` in `_process_command`**

Find the line (1532):

```python
        user_settings = await _get_settings_for_bot(bot_id)
```

and add directly after it:

```python
        user_settings = await _get_settings_for_bot(bot_id)
        persona_text = user_settings.get("persona_text", "")
```

Then in the `_build_command_messages(...)` call (lines 1586-1596), add the
`persona_text` keyword argument. Change:

```python
        messages = _build_command_messages(
            has_gmail=has_gmail,
            has_calendar=has_calendar,
            now_str=now_str,
            memory_context=memory_context,
            speaker=speaker,
            command=command_for_prompt,
            prompt_cache_on=_prompt_cache_on(),
            injection_guard_on=injection_guard,
            is_owner=is_owner,
        )
```

to:

```python
        messages = _build_command_messages(
            has_gmail=has_gmail,
            has_calendar=has_calendar,
            now_str=now_str,
            memory_context=memory_context,
            speaker=speaker,
            command=command_for_prompt,
            prompt_cache_on=_prompt_cache_on(),
            injection_guard_on=injection_guard,
            is_owner=is_owner,
            persona_text=persona_text,
        )
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m pytest backend/tests/test_realtime_persona.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/realtime_routes.py backend/tests/test_realtime_persona.py
git commit -m "Resolve owner persona in bot settings and feed it to the command loop"
```

---

## Task 5: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m pytest backend/tests/ -q`
Expected: PASS — all pre-existing tests plus the 19 new tests across four files.
If anything fails, fix it before declaring done (do not edit tests to pass).

- [ ] **Step 2: Confirm no stray persona references leaked into the wrong path**

Run: `python -m pytest backend/tests/test_prompt_structure.py backend/tests/test_personas.py backend/tests/test_persona_wrappers.py backend/tests/test_realtime_persona.py -v`
Expected: PASS. This is the focused persona-wiring suite.

- [ ] **Step 3: Final commit (only if step 1 required a fix; otherwise skip)**

```bash
git add -A
git commit -m "Fix test fallout from live-bot persona wiring"
```

---

## Done criteria (from the spec)

1. A bot owner with a non-default preset hears the bot's in-meeting replies in that tone.
2. A bot owner on `default` (or unauthenticated/no-DB) sees no change — prefix byte-identical.
3. Persona lands in `messages[0]`, never the user turn; the Haiku fallback preserves it (it concatenates system messages).
4. The bot still calls tools correctly under a strong persona (tool-aware wrapper).
5. No second Supabase query added to the command path (resolved from the already-fetched row).
6. Full backend suite green.

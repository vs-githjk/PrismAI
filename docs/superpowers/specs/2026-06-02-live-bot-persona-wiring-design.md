# Live-Bot Persona Wiring — Design Spec

**Date:** 2026-06-02
**Branch:** `fixed-changes`
**Status:** Approved — ready for implementation plan
**Roadmap phase:** Phase 8 (Personas) — realtime extension
**Completes:** open item **D1** of `docs/superpowers/specs/2026-05-28-personas-design.md`
("Realtime in-meeting assist persona — deferred to a follow-up spec"). The open
question there — *"the bot is generally heard by multiple users; whose persona
applies?"* — is answered here: **the bot owner's**.

---

## Problem

Personas were built to change *how* the AI sounds. But the one surface where
that matters most for *"making discussions better"* — the **live meeting bot** —
never reads the persona. `backend/realtime_routes.py` has **zero** persona
references. The picker exists (`PersonaChip` in the chat header + account
dropdown), the value is saved (`user_settings.persona_preset` /
`persona_custom_prompt`), and the dashboard chat + the 8 analysis agents honor
it via the `_PERSONA_TEXT` contextvar — but the bot that actually *speaks in the
meeting* ignores it entirely.

**Goal:** the live bot's spoken/chat replies adopt the bot owner's persona,
implemented so it is cheap and fast on a latency-sensitive path.

---

## Decisions locked in this session

| ID | Decision | Rationale |
|----|----------|-----------|
| R1 | **Scope = bot owner's *personal* persona.** Resolve by `bot_store[bot_id]["user_id"]` with `workspace_id = None`. | The bot is the owner's agent. `bot_store` already carries `user_id`; it does **not** carry `workspace_id`, so honoring workspace defaults would need new plumbing for marginal benefit. |
| R2 | **Injection point = the cached static system prefix** (`_build_static_prefix`), not the per-call dynamic/user turn. | Persona is constant for a whole meeting; the live path is built around Groq prompt caching (byte-exact prefix). Prefix placement makes persona cost ≈ 0 per command after the first. See *Approaches* + *Efficiency proof*. |
| R3 | **Tool-aware wrapper for the bot**, distinct from the canonical JSON-agent wrapper. | The canonical wrapper fences *"facts, schema, scores, JSON keys"* — written for tool-less analysis agents. The agentic bot needs persona fenced off from *tool-calling decisions* so a `concise`/`cheeky` tone can't suppress or distort a real tool call. |
| R4 | **No extra DB query.** Resolve persona text from the `user_settings` row `_get_settings_for_bot` *already* fetches. | Avoids a second serial Supabase round-trip on the cold (first-command) path. Reuses the existing 60s settings cache. |
| R5 | **Scope = command-reply path only** (`_process_command`). Idea engine + timed nudges out of scope. | Idea engine (`_maybe_generate_idea`) is a secondary proactive surface; can be a fast follow-up. Timed nudges are hardcoded template strings (no LLM call) — persona is N/A. |

---

## Approaches considered

Let a meeting have **N** voice commands; persona = **P** tokens.

### A — Bake persona into the cached static prefix ✅ (chosen)
Append the persona instruction to `_build_static_prefix` (after `_STATIC_STYLE`).
- Persona tokens enter Groq's prompt cache once, then ride the ~50% cached-input
  discount and are excluded from the TPM rate-limit count for every subsequent
  command. Per-command marginal cost ≈ 0.
- No fresh tokens added to the hot path (this path feeds live TTS — TTFT matters).
- Semantically correct: persona is tone guidance; `_STATIC_STYLE` already lives
  in the prefix and is honored from that position.

### B — Append persona per-call (the dashboard `chat_routes` pattern)
Append `get_persona_suffix()` to the per-call dynamic message, closest to the user turn.
- Re-sends P tokens on **every** command (P×N at full price, no cache discount) for
  a value that never changes within the meeting.
- Would also be **silently lost in the Haiku fallback**, which rebuilds the user
  turn from scratch (see EDGE D). Only upside — tone recency — is marginal for a
  70B model and already demonstrated to work from the prefix by `_STATIC_STYLE`.

### C — Resolve once at bot-join, store on `bot_store`
- One resolution per meeting, but **misses mid-meeting persona changes** and adds
  join-path plumbing. No cost advantage over A (A's resolution is already free via
  the cached settings row).

**A wins**: cache-optimal, picks up changes within ≤60s, reuses canonical
resolution logic, and is the only option robust across the Haiku fallback.

---

## Architecture & data flow

```
_process_command(bot_id)
  → user_settings = await _get_settings_for_bot(bot_id)      # ONE fetch, 60s cache
        └─ settings["persona_text"] = persona_text_from_settings(row)   # 0 extra queries
  → _build_command_messages(..., persona_text=user_settings["persona_text"])
        └─ _build_static_prefix(has_gmail, has_calendar, persona_text)
              └─ base + persona_suffix_agentic(persona_text)
                    └─ lands in messages[0] → Groq prompt-cache-warm for the meeting
  → Groq call (llama-3.3-70b-versatile)
  → on transient error → Haiku fallback concatenates all system messages
                          → persona in messages[0] carries along for free
```

`workspace_id` is `None` (R1). `persona_text` is `""` for the `default` preset and
for unauthenticated/no-DB bots → the prefix is byte-identical to today (zero
behavior change for the demo path).

---

## Code changes

### `backend/personas.py` — share user-portion resolution (no new DB call helper)

Extract the user-portion resolution so the live path and `resolve_persona` cannot
drift, then expose a text-only entry point for the live path:

```python
def _resolve_user_persona(row: dict) -> Optional[ResolvedPersona]:
    """User-portion resolution from a user_settings row. Returns a
    ResolvedPersona for a non-default override, or None if the user is on
    'default' (caller decides the fallback)."""
    preset = (row or {}).get("persona_preset") or "default"
    custom = ((row or {}).get("persona_custom_prompt") or "")[:CUSTOM_PROMPT_MAX_CHARS]
    if preset == "custom" and custom.strip():
        return ResolvedPersona("custom", custom)
    if preset != "default" and preset in PRESETS:
        return ResolvedPersona(preset, PRESETS[preset])
    return None

def persona_text_from_settings(row: dict) -> str:
    """Live-bot entry point: raw persona text from an already-fetched
    user_settings row (no DB call), or '' for the 'default' preset."""
    hit = _resolve_user_persona(row)
    return hit.text if hit else ""
```

`_fetch` is refactored to call `_resolve_user_persona` for its user portion; the
workspace fallback is unchanged. This is a pure refactor — `resolve_persona`'s
behavior for the dashboard is identical.

### `backend/agents/utils.py` — factor out wrappers (+ strip guard, + tool-aware variant)

```python
def persona_suffix(text: str) -> str:
    """Canonical tone wrapper (analysis agents / get_persona_suffix)."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone instruction (does not change facts, schema, scores, or JSON keys):\n"
        f"{text}"
    )

def persona_suffix_agentic(text: str) -> str:
    """Tool-aware variant for agentic surfaces (the live bot). Fences persona
    to wording only so it cannot suppress or distort tool calls."""
    if not text or not text.strip():
        return ""
    return (
        "\n\n"
        "Tone and style instruction (applies to your wording only — it does not "
        "change the facts, your available tools, or whether and how you call "
        "them):\n"
        f"{text}"
    )

def get_persona_suffix() -> str:        # unchanged behavior
    return persona_suffix(_PERSONA_TEXT.get())
```

The `.strip()` guard (EDGE E) ensures a whitespace-only custom prompt produces no
suffix, keeping the prefix byte-identical to default.

### `backend/realtime_routes.py` — three threaded edits

1. **`_get_settings_for_bot`** — after the existing `row = ...` fetch, set
   `settings["persona_text"] = persona_text_from_settings(row)`. Default `""` when
   no `user_id`/`supabase`. Cached in the same 60s bundle; **no extra query**.
2. **`_build_static_prefix(has_gmail, has_calendar, persona_text="")`** — return
   `base + persona_suffix_agentic(persona_text)`. (Import `persona_suffix_agentic`
   from `agents.utils`.) Used by both the cache-on and cache-off layouts.
3. **`_build_command_messages(..., persona_text="")`** — pass through to
   `_build_static_prefix`. In `_process_command`, read
   `persona_text = user_settings.get("persona_text", "")` and pass it in.

New imports in `realtime_routes.py`: `from personas import persona_text_from_settings`
and `persona_suffix_agentic` added to the existing `from agents.utils import ...`
line (this file currently has **no** persona references — both are net-new).

---

## Edge cases & how the design handles them

### Design-shaping
- **EDGE A — double fetch (efficiency).** Naively calling `resolve_persona` in
  `_process_command` would re-query the same `user_settings` row
  `_get_settings_for_bot` already pulled — a second serial round-trip on the cold
  first-command path. **Fixed by R4** (resolve from the existing row; single 60s
  cache; ≤60s freshness, better than `resolve_persona`'s 300s cache).
- **EDGE B — tool-calling.** Canonical wrapper protects JSON keys, not tool
  decisions; persona lands *after* the Gmail/Calendar tool instructions in the
  prefix. **Fixed by R3** (`persona_suffix_agentic`).
- **EDGE C — second LLM voice.** `_maybe_generate_idea` (proactive 💡 ideas) goes
  through `llm_call` and is also personaless. **Out of scope (R5)**; if wired
  later it uses the `_PERSONA_TEXT` contextvar (task-isolated via `create_task`),
  not the prefix. Timed nudges (1451–1483) are hardcoded templates — N/A.

### Confirmed handled (no behavior change)
- **EDGE D — Haiku fallback.** Fallback rebuilds its system prompt by
  concatenating all system-role messages (`realtime_routes.py:1955-1957`) → persona
  in `messages[0]` carries free. It rebuilds the user turn fresh (`:1962`), so
  Approach B would *lose* persona here — a point for A. The fallback calls
  Anthropic directly (not `llm_call`), and the `_PERSONA_TEXT` contextvar is unset
  in the live path, so there is **no double-append**.
- **EDGE E — whitespace-only custom persona.** `.strip()` guard → no suffix.
- **EDGE F — security.** Persona is owner-authored, 500-char-capped, trusted
  *system* content. Non-owner participant utterances are handled on the **user**
  message by the existing spotlight / sanitize / owner-gate machinery — they never
  reach the prefix. No new injection surface from other attendees.
- **EDGE G — persona change mid-meeting.** Changes the prefix bytes → the static
  prefix cache entry is invalidated once (next command re-tokenizes the full
  prefix). Rare, one-time, ≤60s propagation. Acceptable.
- **EDGE I — prompt-cache flag OFF.** The legacy single-system-message layout also
  calls `_build_static_prefix`, so persona works in both layouts.
- **EDGE J/K — think_loop insert + taint-strip.** Both operate on `messages[-1]` /
  `tools`, never `messages[0]`; the cached persona prefix is undisturbed.
- **Rolling-summary call (`:1875`)** stays personaless by design — it is internal
  memory compression; persona must not distort it.

---

## Efficiency & cost

- **Resolution:** 0 extra Supabase queries (reuses the fetched row); cached 60s;
  dict-read on hit.
- **Tokenization:** persona in byte-stable `messages[0]` → ~50% cached-input
  discount + excluded from TPM rate-limit count after command 1; per-command
  marginal cost ≈ 0.
- **Latency:** no fresh tokens and no second round-trip on the hot path.
- **Cost safety:** "excluded from rate limits" is a *throughput* property (TPM
  throttle), not a billing one. Persona does not change *how often* the LLM is
  called — call volume is bounded by the 15s debounce + dedup + command detection,
  none of which persona touches. Caching the persona is **strictly cheaper** than
  re-sending it (Approach B); there is no scenario where it costs more. A hard
  money ceiling (provider budget, per-meeting call cap) is a separate, optional
  concern that predates this change and is **not** included here.

---

## Tests

| Test | Verifies |
|------|----------|
| `test_persona_text_from_settings_default` | `{}` / `{'persona_preset':'default'}` → `""` |
| `test_persona_text_from_settings_preset` | `{'persona_preset':'concise'}` → `PRESETS['concise']` |
| `test_persona_text_from_settings_custom` | `custom` + non-empty prompt → verbatim (capped 500) |
| `test_persona_text_from_settings_custom_whitespace_falls_through` | `custom` + whitespace prompt → `""` |
| `test_resolve_persona_unchanged_after_refactor` | `_fetch` regression: user override + workspace fallback still correct |
| `test_persona_suffix_empty_and_whitespace` | `""` / `"   "` → `""` |
| `test_persona_suffix_agentic_fences_tools` | non-empty text → contains the tool-aware clause |
| `test_get_persona_suffix_reads_contextvar` | contextvar path unchanged |
| `test_static_prefix_default_byte_identical` | `_build_static_prefix(...,"")` == today's output (regression) |
| `test_static_prefix_persona_stable_and_distinct` | persona prefix differs from default; two calls byte-identical (cache invariant) |
| `test_static_prefix_persona_uses_agentic_wrapper` | persona prefix contains the tool-aware clause |
| `test_command_messages_persona_in_system_not_user` | persona in `messages[0]` (cache-on) / single system (cache-off), **not** in the user turn — locks Approach A |
| `test_get_settings_for_bot_includes_persona_text` | mocked row → `settings["persona_text"]` populated without a second query |
| `test_get_settings_for_bot_no_user_persona_empty` | no `user_id`/`supabase` → `persona_text == ""` |

Frontend has no test framework (project convention) — none added.

---

## Files touched

| File | Change |
|------|--------|
| `backend/personas.py` | Add `_resolve_user_persona` + `persona_text_from_settings`; refactor `_fetch` to reuse `_resolve_user_persona` (pure refactor) |
| `backend/agents/utils.py` | Factor out `persona_suffix`; add `persona_suffix_agentic`; add `.strip()` guards; `get_persona_suffix` delegates to `persona_suffix` |
| `backend/realtime_routes.py` | `_get_settings_for_bot` sets `persona_text`; `_build_static_prefix` + `_build_command_messages` accept and thread `persona_text`; `_process_command` reads + passes it; new imports |

No schema, route, or frontend changes. No new env vars.

---

## Out of scope (deferred)

- **Idea-engine persona** (`_maybe_generate_idea`) — fast follow-up via the
  contextvar if desired (R5).
- **Workspace-default persona for the bot** — needs `workspace_id` plumbed into
  the join flow + `bot_store` (R1).
- **Per-meeting persona override UI** at the join/bot panel.
- **App-side per-meeting cost cap / provider budget** — separate concern.

---

## Acceptance criteria

1. A bot owner with `persona_preset = 'concise'` (or `formal`/`cheeky`/etc.) hears
   the bot's in-meeting replies adopt that tone.
2. A bot owner on `default` (or unauthenticated/no-DB) sees **no** change — the
   static prefix is byte-identical to today.
3. Persona text lands in `messages[0]` (cached prefix), never in the user turn;
   the Haiku fallback preserves it.
4. The bot still calls tools correctly under a strong persona (tool-aware wrapper).
5. No second Supabase query is added to the command path.
6. Backend test suite stays green and gains the tests above.

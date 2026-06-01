# Personas — Design Spec

**Date:** 2026-05-28
**Branch:** `fixed-changes`
**Status:** Approved — ready for implementation plan
**Roadmap phase:** Phase 8 (post smart-RAG)
**Supersedes/extends:** `docs/superpowers/specs/2026-05-25-personas-handoff.md` (the paused brainstorm; this spec is its completion)

---

## Goal

Let each user — and each workspace — shape *how* the AI sounds (concise, formal, cheeky, socratic, or a free-text custom prompt) without changing *what* it says (facts, scores, JSON schema, decisions, action items). Persona affects free-text phrasing across chat replies and all 8 post-analysis agents.

---

## High-level decisions (locked in prior brainstorm + this session)

| ID | Decision |
|----|----------|
| Q1 | **Scope:** chat (both `/chat` and `/chat/global`) + all 8 post-analysis agents |
| Q2 | **Customization:** 5 fixed presets + per-user custom prompt (workspace-level customs are out of scope) |
| Q3 | **UI placement:** chip in chat header + Persona entry in account dropdown + Default persona row in workspace settings modal |
| Q4 | **Persistence:** bake the recorder's persona into the saved meeting result at analyze-time; resolve viewer's persona live for chat and `/agent` re-runs |
| D1 | **Realtime in-meeting assist:** out of scope for v1 — defer to a follow-up spec |
| D2 | **Chip vs ⚙:** chip = personal override only; workspace default lives in workspace settings modal |
| D3 | **Stale custom prompt:** PATCH endpoint auto-nulls `persona_custom_prompt` whenever `persona_preset != 'custom'` |

### Precedence

```
effective_persona =
    user_personal_override (preset or custom)
    OR workspace_default (preset only)
    OR "default" (system fallback)
```

In personal mode (no `workspace_id`), the middle term drops out.

---

## Architecture overview

The persona is plumbed through the system as **state + a contextvar**:

```
At analyze-time (POST /analyze-stream):
  frontend sends payload.persona_preset (resolved client-side from local user state)
  → orchestrator writes state["persona_preset"] into LangGraph state
  → resolve_persona_node (new) is a no-op for analyze (preset already in state),
    used only as a hook for symmetry with chat-time
  → each agent dispatch wrapper applies AGENT_PERSONA_WHITELIST, sets
    contextvars._PERSONA_TEXT = PRESETS[allowed_preset] for the duration of
    that agent's call
  → llm_call (in agents/utils.py) reads the contextvar and prepends a
    safety-wrapped persona to the system prompt
  → meetings.persona_used = state["persona_preset"] on save

At chat-time (POST /chat or /chat/global):
  chat_routes calls await resolve_persona(sb, user_id, active_workspace_id)
  → contextvars._PERSONA_TEXT.set(resolved.text) for the request lifetime
  → llm_call picks it up automatically (same path as analyze)

At /agent re-run:
  same as chat-time — viewer's persona, live (not the meeting's persona_used)
```

**Safety preamble wrapping every persona injection:**

```
Tone instruction (does not change facts, schema, scores, or JSON keys):
<persona_text>
```

The preamble is appended to the agent's existing `SYSTEM_PROMPT` inside `llm_call`. Agent files themselves are unchanged.

---

## Section 1 — Preset prompt strings + whitelist

### PRESETS

| Preset | Prompt string |
|--------|---------------|
| `default` | *(empty string — no modifier appended)* |
| `concise` | `Be terse. Cut filler, hedges, and throat-clearing. Prefer short sentences and bulleted lists over paragraphs. Skip preambles like "Sure!" or "Great question".` (157 chars) |
| `formal` | `Use an executive register: measured, precise, and polished. No contractions, no slang, no emoji. Default to declarative statements; qualify only where uncertainty is real.` (172 chars) |
| `cheeky` | `Have a dry wit. Add light sarcasm or playful jabs where they fit naturally — never at the user's expense. Humor decorates the answer; it never replaces substance.` (162 chars) |
| `socratic` | `Surface the user's assumptions by asking pointed questions. Where a direct answer exists, give it; where the request is ambiguous, name the ambiguity and pose one or two clarifying questions.` (191 chars) |

`custom` is not a string — it's a flag value indicating the prompt comes from `user_settings.persona_custom_prompt`. Custom prompts are capped at **500 characters** (enforced in DB CHECK constraint + frontend validation).

### AGENT_PERSONA_WHITELIST

Defines which presets each agent will honor. If a user's preset isn't in an agent's whitelist, the dispatch wrapper falls back to `default` for that agent only.

```python
AGENT_PERSONA_WHITELIST = {
    "summarizer":         {"default", "concise", "formal", "cheeky", "socratic", "custom"},
    "decisions":          {"default", "concise", "formal"},
    "action_items":       {"default", "concise", "formal"},
    "sentiment":          {"default", "concise", "formal"},
    "speaker_coach":      {"default", "concise", "formal"},
    "email_drafter":      {"default", "concise", "formal", "cheeky", "socratic", "custom"},
    "health_score":       {"default", "concise", "formal"},
    "calendar_suggester": {"default", "concise", "formal"},
}
# Chat (both /chat and /chat/global) is NOT in this map — chat always
# receives the full effective persona including custom.
```

**Rationale.** Free-text agents (summarizer, email_drafter) tolerate any tone. Structured-output agents (decisions, action_items, scores) can have their data model distorted by `cheeky`/`socratic`/`custom` even when the JSON schema stays intact — e.g., a socratic action_items agent might phrase tasks as questions. The whitelist constrains the blast radius.

### Injection mechanism

A new contextvar in `backend/agents/utils.py`:

```python
import contextvars
_PERSONA_TEXT: contextvars.ContextVar[str] = contextvars.ContextVar("persona_text", default="")

async def llm_call(system_prompt: str, user_msg: str, **kwargs):
    persona = _PERSONA_TEXT.get()
    if persona:
        system_prompt = (
            f"{system_prompt}\n\n"
            f"Tone instruction (does not change facts, schema, scores, or JSON keys):\n"
            f"{persona}"
        )
    # ... existing Groq call ...
```

Zero changes to the 8 agent files. The dispatch wrapper in `analysis_service.py` and the entry points in `chat_routes.py` / `agent_routes.py` set the contextvar before each LLM-using call.

---

## Section 2 — `resolve_persona` + cache

New file: `backend/personas.py`. Mirrors the `caches.py` pattern exactly — flag-gated, env-tunable TTL, transient failures don't poison the cache, `cache_stats()` for `/health`, `_reset_for_tests()` helper.

```python
"""Persona resolution + in-process cache. Mirrors caches.py shape."""

import os
import time
from dataclasses import dataclass
from typing import Optional

PRESETS: dict[str, str] = {
    "default":  "",
    "concise":  "Be terse. ...",          # full strings from Section 1
    "formal":   "Use an executive ...",
    "cheeky":   "Have a dry wit. ...",
    "socratic": "Surface the user's ...",
}

CUSTOM_PROMPT_MAX_CHARS = 500


def _cache_on() -> bool:
    return os.getenv("PRISM_PERSONA_CACHE", "1") == "1"

_CACHE_TTL_S = int(os.getenv("PRISM_PERSONA_CACHE_TTL_S", "300"))


@dataclass(frozen=True)
class ResolvedPersona:
    preset: str   # 'default' | 'concise' | 'formal' | 'cheeky' | 'socratic' | 'custom'
    text:   str   # raw instruction (no safety wrapper); empty for 'default'


_cache: dict[tuple[str, Optional[str]], tuple[ResolvedPersona, float]] = {}
_stats = {"hits": 0, "misses": 0, "failures": 0}


async def resolve_persona(sb, user_id: str, workspace_id: Optional[str]) -> ResolvedPersona:
    """User override → workspace default → 'default'. Returns the raw text;
    caller wraps it in the safety preamble (llm_call does this automatically
    via the _PERSONA_TEXT contextvar)."""
    if not _cache_on():
        return await _fetch(sb, user_id, workspace_id) or ResolvedPersona("default", "")

    now = time.monotonic()
    key = (user_id, workspace_id)
    cached = _cache.get(key)
    if cached is not None and now < cached[1]:
        _stats["hits"] += 1
        return cached[0]

    _stats["misses"] += 1
    fresh = await _fetch(sb, user_id, workspace_id)
    if fresh is None:
        _stats["failures"] += 1
        return ResolvedPersona("default", "")  # safe fallback, NOT cached
    _cache[key] = (fresh, now + _CACHE_TTL_S)
    return fresh


def invalidate_persona(user_id: Optional[str] = None, workspace_id: Optional[str] = None) -> None:
    """Drop cached entries after settings mutation."""
    if user_id is None and workspace_id is None:
        _cache.clear()
        return
    drop = [k for k in _cache
            if (user_id is not None and k[0] == user_id)
            or (workspace_id is not None and k[1] == workspace_id)]
    for k in drop:
        del _cache[k]


def cache_stats() -> dict:
    return {**_stats, "size": len(_cache), "enabled": _cache_on(), "ttl_s": _CACHE_TTL_S}


async def _fetch(sb, user_id: str, workspace_id: Optional[str]) -> Optional[ResolvedPersona]:
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
    except Exception:
        return None


def _reset_for_tests() -> None:
    _cache.clear()
    _stats["hits"] = 0
    _stats["misses"] = 0
    _stats["failures"] = 0
```

**Call sites:**

- `chat_routes.py` (both `/chat` and `/chat/global`): resolve at request entry, `_PERSONA_TEXT.set(resolved.text)`.
- `agent_routes.py` (`/agent`): same — viewer's persona, live.
- `analysis_service.py` (`run_full_analysis`): no resolution at server (preset arrives in payload). The dispatch wrapper sets the contextvar per-agent using the whitelist.
- `storage_routes.save_meeting`: writes `meetings.persona_used = entry.persona_used` (sent from the frontend, recorded in state during analyze).

**Invalidation hooks:**

- `POST /user-settings` (`storage_routes.py`): after upsert, `invalidate_persona(user_id=user_id)`.
- `PATCH /workspaces/{id}` (`workspace_routes.py`): after update of `default_persona`, `invalidate_persona(workspace_id=id)`.

**Worst-case staleness:** 5 minutes between changing your persona in settings and seeing it in chat — only if both the cache TTL AND the explicit invalidator silently failed. Acceptable.

---

## Section 3 — Schema

Migration file: `supabase/personas_migration.sql`.

```sql
-- supabase/personas_migration.sql
-- Personas feature: per-user override + workspace default + audit on meetings.
-- Apply in the Supabase SQL editor BEFORE deploying backend code that references these columns.

-- 1. User-level persona override.
alter table user_settings
  add column if not exists persona_preset text default 'default',
  add column if not exists persona_custom_prompt text;

alter table user_settings
  drop constraint if exists user_settings_persona_preset_check;
alter table user_settings
  add constraint user_settings_persona_preset_check
  check (persona_preset in ('default', 'concise', 'formal', 'cheeky', 'socratic', 'custom'));

alter table user_settings
  drop constraint if exists user_settings_persona_custom_len;
alter table user_settings
  add constraint user_settings_persona_custom_len
  check (persona_custom_prompt is null or char_length(persona_custom_prompt) <= 500);

-- 2. Workspace-level default. Preset-only — no 'custom' allowed.
alter table workspaces
  add column if not exists default_persona text default 'default';

alter table workspaces
  drop constraint if exists workspaces_default_persona_check;
alter table workspaces
  add constraint workspaces_default_persona_check
  check (default_persona in ('default', 'concise', 'formal', 'cheeky', 'socratic'));

-- 3. Audit field on meetings: which persona was baked into result.
--    Nullable — legacy meetings (pre-feature) stay NULL.
--    No CHECK constraint — preset names may evolve; frontend handles unknowns
--    gracefully (renders as "<name> (legacy)").
alter table meetings
  add column if not exists persona_used text;
```

### Why these shapes

- **CHECK constraints, not enum types** — easier to evolve when adding a 6th preset later.
- **No CHECK on `meetings.persona_used`** — a meeting analyzed today should remain queryable in 2027 even if a preset is renamed.
- **Different constraint sets for `user_settings` vs `workspaces`** — workspaces can't pick `custom` (Q2 decision: workspace-level customs are out of scope).

---

## Section 4 — UI

### 4a. Chat chip — `frontend/src/components/ChatPanel.jsx:266`

The chat header already has a chip group containing `agent-aware`. `<PersonaChip />` slots into the same `<div className="flex items-center gap-1.5">` group, immediately after `agent-aware`.

```
┌─ ChatPanel header ──────────────────────────────────────────────┐
│  Chat                  [agent-aware]  [👤 Persona: Cheeky ▾]    │
└──────────────────────────────────────────────────────────────────┘
```

Icon prefix (only meaningful in workspace mode):

| Prefix | Meaning |
|--------|---------|
| `👤` | User's personal override active |
| `🏢` | Inherited from workspace default |
| *(none)* | System default |

In personal mode (`activeWorkspaceId === null`) the prefix is omitted.

### 4b. Picker popover (internal to `PersonaChip.jsx`)

Mirrors the existing history-popover pattern from `ChatPanel.jsx:274` (outside-click dismissal via `useRef`).

```
┌──────────────────────────────────┐
│ Persona                          │
│                                  │
│  ○  Default                      │
│  ●  Concise                      │
│  ○  Formal                       │
│  ○  Cheeky                       │
│  ○  Socratic                     │
│  ○  Custom…                      │
│  ────────────                    │
│  ○  Use workspace default        │
│     (Acme Inc → Formal)          │
│                                  │
│  Some agents (action items,      │
│  decisions, scores) ignore       │
│  tonal personas to preserve      │
│  accuracy.                       │
│                                  │
│           [Cancel]   [Save]      │
└──────────────────────────────────┘
```

`Custom…` reveals an inline textarea (500 char cap with a live counter).

`Use workspace default` is hidden in personal mode and disabled if the workspace's default is already `default`.

On **Save**: `POST /user-settings` with `persona_preset` and (if applicable) `persona_custom_prompt`. After 200 OK, the frontend updates local state from the response and the chip label updates immediately.

**Stale custom prompt (D3):** when the user saves any preset other than `custom`, the backend PATCH handler nulls `persona_custom_prompt` server-side (`storage_routes.save_user_settings`). Frontend mirrors this — clear the local state for `persona_custom_prompt` when preset changes off `custom`.

### 4c. Workspace ⚙ modal — `frontend/src/components/dashboard/DashboardSidebar.jsx:583`

The existing workspace settings live in a shadcn `<Dialog>` modal opened via the ⚙ button in the workspace dropdown. The new **Default persona** section slots between **Invite link** (lines 555–582) and **Members** (line 584):

```
┌── Workspace settings (modal) ─────────────────────────────┐
│                                                            │
│   Invite link    https://...   [Copy]                      │
│   Regenerate link                                          │
│                                                            │
│   Default persona       [← NEW section]                    │
│    ○ Default   ●  Formal   ○ Concise   ○ Cheeky   ○ Socratic│
│    Members inherit this unless they set their own.         │
│                                                            │
│   Members (N)                                              │
│    alice@acme.com    [Remove]                              │
│    ...                                                     │
│                                                            │
│   [Leave workspace]                  [Delete workspace]    │
└────────────────────────────────────────────────────────────┘
```

No `Custom…` option here (workspace-level customs out of scope). Owner-only edit; non-owners see the section as read-only.

Save handler: `PATCH /workspaces/{id}` with `{ default_persona }`. Backend calls `invalidate_persona(workspace_id=...)` after the update.

### 4d. Persona entry in account dropdown — `DashboardSidebar.jsx:597-621`

The existing account dropdown footer has `Integrations` and a `Settings (Soon)` placeholder. Replace the placeholder with a working **Persona** entry:

```jsx
<DropdownMenuItem
  onSelect={() => setShowPersonaPicker(true)}
  className="cursor-pointer gap-3 px-3 py-2 text-xs font-semibold text-white/84 focus:bg-cyan-300/[0.08]"
>
  <Sparkles className="h-4 w-4 shrink-0 text-white/62" aria-hidden="true" />
  Persona
  <span className="ml-auto text-[10px] font-medium text-white/40">
    {personaPreset === 'custom' ? 'Custom' : capitalize(personaPreset)}
  </span>
</DropdownMenuItem>
```

Opens the same picker the chat chip opens. Makes persona reachable from Home, Knowledge, or any screen where no meeting is currently open.

### State management

- `App.jsx` owns `personaPreset` and `personaCustomPrompt` state.
- Loaded on sign-in via `GET /user-settings` (already called for `linear_api_key`/`slack_bot_token`).
- Persisted on change via `POST /user-settings` (same endpoint, new fields).
- Passed down to `ChatPanel` and `DashboardSidebar` via props.

### API surface

- **No new backend routes.** Extend `GET /user-settings` + `POST /user-settings` (`storage_routes.py:53,66`) by adding `persona_preset` and `persona_custom_prompt` to the `UserToolSettings` Pydantic model.
- **Extend** `PATCH /workspaces/{id}` (`workspace_routes.py`) to accept `default_persona`. Existing endpoint signature stays compatible.

---

## Section 5 — Migration & backfill

### Application order

1. Apply `supabase/personas_migration.sql` in the Supabase SQL editor.
2. Then deploy backend (Render auto-deploys from `main`).
3. Then deploy frontend (Vercel auto-deploys from `main`).

Reversing the order breaks the backend immediately on first `resolve_persona` call. The same constraint already exists for every PrismAI migration; document the ordering note in CLAUDE.md's deployment section.

### Backfill behavior

Automatic via column defaults:

- Existing `user_settings` rows → `persona_preset = 'default'`, `persona_custom_prompt = NULL`.
- Existing `workspaces` rows → `default_persona = 'default'`.
- Existing `meetings` rows → `persona_used = NULL` (intentional — these meetings were analyzed without persona, NULL is the honest record).

No backfill script needed.

### Verification queries (run after apply)

```sql
-- Columns exist with expected defaults.
select column_name, data_type, column_default
from information_schema.columns
where (table_name = 'user_settings' and column_name like 'persona%')
   or (table_name = 'workspaces' and column_name = 'default_persona')
   or (table_name = 'meetings' and column_name = 'persona_used');
-- Expect 4 rows.

-- Constraints in place.
select conname from pg_constraint where conname like '%persona%';
-- Expect: user_settings_persona_preset_check, user_settings_persona_custom_len,
--         workspaces_default_persona_check.
```

### Rollback

The migration is purely additive (`ADD COLUMN` + `ADD CONSTRAINT`). To roll back:

1. Revert the backend deploy.
2. Optionally drop the columns later (low priority — old code ignores unknown columns).
3. To drop: `alter table {user_settings, workspaces, meetings} drop column ...`.

---

## Files touched

### New

| File | Responsibility |
|------|----------------|
| `backend/personas.py` | `PRESETS`, `ResolvedPersona`, `resolve_persona`, `invalidate_persona`, `cache_stats`, `_reset_for_tests` |
| `frontend/src/components/PersonaChip.jsx` | Chip + picker popover + custom textarea + "Use workspace default" option |
| `supabase/personas_migration.sql` | Schema migration |

### Modified

| File | Change |
|------|--------|
| `backend/agents/utils.py` | Add `_PERSONA_TEXT` contextvar; modify `llm_call` to read it and prepend safety-wrapped persona |
| `backend/analysis_service.py` | Add `state["persona_preset"]` to LangGraph state TypedDict; dispatch wrapper applies `AGENT_PERSONA_WHITELIST` and sets `_PERSONA_TEXT` per agent |
| `backend/chat_routes.py` | Resolve persona at request entry for `/chat`, `/chat/global`, AND `/agent` (line 203 — same file). Set `_PERSONA_TEXT` per request. |
| `backend/storage_routes.py` | Extend `UserToolSettings` (lines 25-27) with `persona_preset` + `persona_custom_prompt`; in `POST /user-settings`: if `persona_preset != 'custom'`, null `persona_custom_prompt` server-side (D3); then `invalidate_persona(user_id=user_id)`. In `POST /meetings`: read `payload.persona_used` and write to `meetings.persona_used` |
| `backend/workspace_routes.py` | Extend `PATCH /workspaces/{id}` to accept `default_persona`; `invalidate_persona(workspace_id=id)` after write |
| `backend/main.py` | `/health` lives at line 64 — surface `personas.cache_stats()` alongside `caches.cache_stats()` |
| `frontend/src/App.jsx` | Add `personaPreset` + `personaCustomPrompt` state; load via `GET /user-settings`; persist via `POST /user-settings`; pass to `ChatPanel` + `DashboardSidebar` |
| `frontend/src/components/ChatPanel.jsx` | Mount `<PersonaChip />` in the existing chip group at line ~266 |
| `frontend/src/components/dashboard/DashboardSidebar.jsx` | (a) Default persona section in the workspace settings modal (line ~583); (b) Replace `Settings (Soon)` placeholder in account dropdown (line ~613) with working `Persona` entry |
| `frontend/src/components/DashboardPage.jsx` | Track per-workspace `default_persona` in `wsDetails`; PATCH on owner edit |
| `frontend/src/lib/api.js` | (No change — existing `apiFetch` is sufficient) |

---

## Tests

| Test | What it verifies |
|------|------------------|
| `test_personas_resolve_user_override` | User preset wins over workspace default |
| `test_personas_resolve_workspace_fallback` | No user override → workspace default used |
| `test_personas_resolve_system_default` | No user override, no workspace → empty string |
| `test_personas_resolve_custom_prompt` | preset=custom + non-empty custom text → returned verbatim |
| `test_personas_resolve_custom_empty_falls_through` | preset=custom + empty custom → falls to workspace then default |
| `test_personas_cache_hit_miss_failure_stats` | Cache stats reflect hits, misses, failures |
| `test_personas_invalidate_by_user` | After PATCH, next resolve hits DB |
| `test_personas_invalidate_by_workspace` | After workspace PATCH, all members' entries drop |
| `test_personas_cache_flag_disabled` | `PRISM_PERSONA_CACHE=0` bypasses cache, queries every call |
| `test_personas_transient_failure_not_cached` | DB error returns default, doesn't poison cache |
| `test_llm_call_appends_safety_preamble_when_persona_set` | Contextvar populated → llm_call wraps system prompt |
| `test_llm_call_no_op_when_persona_empty` | Contextvar empty → system prompt unchanged |
| `test_contextvar_isolation_in_parallel_gather` | Two `asyncio.gather`-launched agents see their own contextvar values |
| `test_dispatch_wrapper_applies_whitelist` | action_items with `cheeky` falls back to `default` text |
| `test_dispatch_wrapper_custom_constrained_like_cheeky` | `custom` allowed for summarizer + email_drafter, not for action_items |
| `test_save_meeting_records_persona_used` | `POST /meetings` writes `persona_used` from payload |
| `test_user_settings_patch_invalidates_cache` | After POST `/user-settings`, cache for that user is dropped |
| `test_user_settings_patch_clears_custom_when_preset_off` | Save preset=concise + existing custom prompt → custom is nulled (D3) |
| `test_workspace_patch_default_persona_accepts_5_presets_only` | `default_persona='custom'` is rejected by DB constraint |

Frontend tests are out of scope for this spec (project convention: backend has pytest, frontend has no test framework yet).

---

## Open items deferred to future specs

- **Realtime in-meeting assist persona** (D1) — needs its own ergonomic story (the bot is generally heard by multiple users; whose persona applies?).
- **Persona preview / "show me what cheeky looks like"** — requires a mini-render endpoint or canned examples.
- **Persona telemetry** — count preset usage to inform future tuning. v2 scope.
- **Custom prompt sharing across workspaces** — explicitly out of scope per Q2.

---

## Acceptance criteria

1. A user can pick any of the 5 presets from the chat chip; the next chat reply reflects the tone.
2. A user can switch to `Custom`, write a 500-char prompt, save, and see it applied to chat + summarizer + email_drafter.
3. Workspace owners can set the workspace default from the workspace ⚙ modal; non-owner members inherit it.
4. A meeting analyzed with `persona_preset=formal` has `meetings.persona_used = 'formal'` and the summary/decisions/etc. reflect that tone.
5. A teammate with personal override `cheeky` opens the same meeting; their chat replies are cheeky, but the saved summary card stays in the recorder's formal voice.
6. Toggling persona settings invalidates the cache (next request resolves fresh).
7. Action items, decisions, scores, and calendar suggestions do not flex on `cheeky`, `socratic`, or `custom` — they silently use `default` for those agents.
8. Backend test suite (currently 396 passing) gains ~19 new tests and stays green.

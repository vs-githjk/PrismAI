# Personas — Brainstorm Handoff (PAUSED)

**Date:** 2026-05-25
**Status:** WIP — paused after Section 1 of the design (architecture sketch) to prioritize smart-RAG Phases 1–5
**Resume target:** After smart-RAG ships
**Branch where paused:** `fixed-changes`

---

## Why this exists

Brainstorming session for the Personas feature (Phase 8 of the roadmap) was started but paused so the team could focus on smart-RAG first. This doc captures every decision and open item so the design can resume cold without losing context.

When picking this up, re-invoke the `superpowers:brainstorming` skill, point it at this doc, and continue from **Section 2: Persona presets** (the next unstarted section in the design presentation).

---

## Background

PrismAI Phase 8 from the roadmap:
> 4–5 system prompt variants (Default, Concise, Formal/Executive, Cheeky/Sarcastic, Socratic). Workspace-level default + personal override. Persona chip indicator in chat. Small surface area — ~1-day project. Mostly prompt engineering + a settings UI.

---

## Decisions locked in (from 4 clarifying questions)

### Q1 — Scope of effect → **Chat + all agents**

Persona affects:
- Both chat endpoints: `POST /chat` (meeting Q&A) and `POST /chat/global` (cross-history)
- All 8 analysis agents: `summarizer`, `decisions`, `action_items`, `sentiment`, `speaker_coach`, `email_drafter`, `health_score`, `calendar_suggester`

Persona only influences **free-text phrasing** (summary wording, task copy, decision text, email body, chat voice). It must NOT change:
- JSON schemas / keys returned by agents
- Numerical scores (health_score, sentiment score)
- Factual extractions (who owns what, what was decided)

### Q2 — Customization → **Presets + per-user custom prompt**

- 5 fixed presets live in code (no DB write needed to tune):
  - `default` — system default, no modifier
  - `concise` — tight, minimal, no filler
  - `formal` — executive register
  - `cheeky` — dry wit, light sarcasm (still useful)
  - `socratic` — probes with questions, surfaces assumptions
- Each user can additionally write a **custom prompt** that overrides the preset
- Workspace owners can only pick a preset (no custom at workspace level — keeps owner UI simple and reduces prompt-injection blast radius across a team)

### Q3 — UI placement → **Workspace settings ⚙ + chat header chip**

- Workspace owners set the workspace default persona in the existing `wsSettings` panel inside `DashboardPage.jsx` (alongside invite link / member list / delete).
- Every user gets a **persona chip** in the `ChatPanel` header (next to the existing `agent-aware` chip) that opens a small picker:
  - 5 preset radio buttons
  - "Custom…" option that reveals a textarea
  - "Use workspace default" option that clears the personal override

### Q4 — Persistence model → **Bake recorder's persona into the saved meeting result**

- At analyze-time: resolve the **recorder's** effective persona, pass it through the LangGraph state, apply to all 8 agents. Save the result + `meetings.persona_used` (audit column) to Supabase.
- At chat-time: resolve the **viewer's** effective persona live. No caching needed (chat is fast).
- Side effect: workspace teammates see the same wording for cards (which feels right — a single shared meeting record), but each person's chat replies match their own persona.

### Precedence

```
effective_persona =
    user_personal_override (preset or custom)
    OR workspace_default (preset)
    OR "default" (system fallback)
```

In personal mode (no `workspace_id`), the middle term drops out.

---

## Architecture sketch (Section 1 — already approved-in-progress)

```
At analyze-time (POST /analyze-stream):
  resolve_persona(recorder_user_id, workspace_id)
  → effective persona text
  → analysis_service passes persona_text into LangGraph state
  → tier1_barrier merges persona_text into the context dict for Tier 2
  → each agent appends persona_text to its SYSTEM_PROMPT
  → result is stored in meetings.result + meetings.persona_used (audit)

At chat-time (POST /chat or /chat/global):
  resolve_persona(caller_user_id, active_workspace_id)
  → chat_routes appends persona_text to system_content
  → returns response (no caching needed — chat is live)
```

**Safety preamble** wrapping every persona injection (prevents persona from subverting agent contracts):

```
Tone instruction (does not change facts, schema, scores, or JSON keys):
<persona_text>
```

---

## Sections still to design (resume here)

When the brainstorm resumes, present these one at a time and get approval for each:

1. **Persona preset prompt strings** — write out the actual ≤200-char prompts for `concise`, `formal`, `cheeky`, `socratic`. `default` = empty string. Stress-test phrasings against the safety preamble.
2. **Resolution & precedence** — pseudocode for `resolve_persona(user_id, workspace_id)` including the cache strategy. Mirror `caches.py` pattern (in-process TTL, flag-gated, invalidate on settings change).
3. **Schema changes** — DB migration. Proposed:
   - `user_settings.persona_preset` text — one of `'default'|'concise'|'formal'|'cheeky'|'socratic'|'custom'`
   - `user_settings.persona_custom_prompt` text — only used when preset = `'custom'`; cap at 500 chars
   - `workspaces.default_persona` text — one of the 5 preset keys
   - `meetings.persona_used` text — audit trail (which persona was baked into this row's `result`)
4. **UI mockup** — chip placement, picker dropdown layout, workspace ⚙ persona row design.
5. **Migration & backfill** — existing rows: `user_settings.persona_preset` defaults to `'default'`; `workspaces.default_persona` defaults to `'default'`; `meetings.persona_used` left null for pre-feature rows.

---

## Open questions to revisit

- **Custom prompt length cap** — proposed 500 chars. Reasonable for tone instructions, prevents prompt injection at scale. Confirm.
- **Should `speaker_coach` persona-flex?** — It already gives candid feedback. A "Cheeky" version could feel mean. Maybe whitelist `speaker_coach` to only flex on `concise` and `formal`, and ignore `cheeky` and `socratic`. Decide during Section 2 design.
- **Re-run path** — when a user invokes `/agent` (re-run a specific agent via the chat "redraft email more formally" pattern), do we use the viewer's persona or the saved `persona_used`? Probably viewer's — that's the whole point of "redraft more formally."
- **Telemetry** — should we count persona usage to inform future preset tuning? Out of scope for v1, but worth a note.

---

## Files this feature will touch (rough scope estimate)

**Backend:**
- New: `backend/personas.py` — `PERSONAS` dict + `resolve_persona()` + cache
- New: `backend/user_settings_routes.py` (or extend an existing route file) — GET/PATCH for persona settings
- Modify: `backend/workspace_routes.py` — extend PATCH `/workspaces/{id}` to accept `default_persona`
- Modify: `backend/chat_routes.py` — inject persona into both `/chat` and `/chat/global` system prompts
- Modify: `backend/analysis_service.py` — resolve recorder persona, propagate through graph state
- Modify: `backend/storage_routes.py` — save `persona_used` on `POST /meetings`
- Modify: all 8 files in `backend/agents/` — accept optional `persona` parameter, append to `SYSTEM_PROMPT`
- New: SQL migration adding 3 columns

**Frontend:**
- New: `frontend/src/components/PersonaChip.jsx` — chat-header chip + picker dropdown
- Modify: `frontend/src/components/ChatPanel.jsx` — mount the chip
- Modify: `frontend/src/components/DashboardPage.jsx` — add persona row to `wsSettings` panel
- Modify: `frontend/src/App.jsx` — load/persist personal persona override into user_settings

**Tests:**
- Unit tests for `resolve_persona` (precedence cases, cache invalidation)
- Integration test: meeting saved with workspace persona = `'formal'` → result JSON keys unchanged, summary phrasing reflects formal register
- Integration test: chat with personal override = `'cheeky'` → response tone reflects, schema unchanged for any tool calls

---

## How to resume

1. Read this doc.
2. Re-invoke the `superpowers:brainstorming` skill.
3. Tell the agent: *"Resume the personas brainstorm from Section 2 — start with proposing preset prompt strings."*
4. Continue through the remaining sections listed above.
5. End by invoking `superpowers:writing-plans` to produce the implementation plan.

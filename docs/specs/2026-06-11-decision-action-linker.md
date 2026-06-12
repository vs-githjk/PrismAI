# Proposal: Decision ↔ Action Item Linker (potential 8th agent)

**Status:** ✅ SHIPPED (Jun 11 2026) — implemented as a "Tier 1.5" barrier agent
(`backend/agents/decision_linker.py`), full bidirectional UI, and unactioned
decisions feed the follow-up agenda. See CLAUDE.md analysis_service section.
**Origin:** Surfaced during the agent-by-agent review while improving `decisions`.

Implemented as approach **B (index-based, runs in `_tier1_barrier`)** + the
"feed the agenda" wiring — chose the barrier over a Tier 2 node so calendar_suggester
could receive `unactioned_decisions` in its context (both are Tier 2, can't link
in parallel). No IDs needed (indices reference the original arrays). Below is the
original design exploration, retained for context.

## Problem

`decisions` and `action_items` are both Tier 1 agents that run in parallel and
never see each other. The app produces two flat, disconnected lists even though
an action item usually exists *because of* a decision. This hides two high-value
signals:

1. **Decisions with no follow-through** — a decision was made but no action item
   references it. A decision at risk of never happening. (Highest-value signal.)
2. **Orphan action items** — tasks with no decision behind them.

It also prevents showing the chain: under a decision, "↳ 2 action items"; under
an action item, "from decision: X".

## Approaches (simplest → richest)

- **A. Deterministic matching** — fuzzy-match by shared owner + text overlap in
  `tier1_barrier` (no LLM). Cheap but brittle; misses semantic links.
- **B. Tier 2 linker agent** ⭐ — a small agent in Tier 2 (which already receives
  both `decisions` + `action_items` in its context dict) that returns
  `action_item → decision` mappings + a list of unactioned decisions. One extra
  parallel LLM call; matches semantically. Cleanest fit with the two-tier graph.
- **C. Shared IDs** — stable ids on each decision/action so the linker emits
  `action_item.decision_id` for precise click-through. Needs id plumbing through
  storage + frontend.
- **D. Merge into one agent** — extract decisions and their actions together.
  Best accuracy, but collapses two agents and breaks the parallel Tier 1 + result
  schema. Too invasive.

**Recommendation:** B + C. Tier-2 "decision linker" mapping actions→decisions and
flagging unactioned decisions, with lightweight ids for click-through. The
"decided but no action" alert is the headline feature.

## Cost (why it's not a quick win)

- New agent → full add-an-agent checklist: `AGENT_MAP`, `TIER2_AGENTS`,
  `AGENT_RESULT_KEY`, `DEFAULT_RESULT`, `_state_to_result`, graph construction,
  `context: dict = {}` on `run()`.
- New result key (e.g. `unactioned_decisions` / `decision_links`) + frontend
  rendering in the decisions and action-items cards.
- Fuzzy matching needs a confidence threshold + graceful "no link" default.
- Latency: one extra Tier-2 call (parallel with email/health/calendar → minimal).

Estimate: ~1-2 hours. Strong candidate for an 8th agent once the existing 7 are
reviewed.

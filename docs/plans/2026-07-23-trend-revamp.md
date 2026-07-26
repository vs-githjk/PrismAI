# Trend / Cross-Meeting Intelligence Revamp — B1 + B2

**Goal:** turn the Trend page from "counting dressed as understanding" into a genuinely useful cross-meeting intelligence surface. B1 = surgical bug-fixes so it stops looking broken. B2 = the semantic rebuild (the moat).

## Where the data comes from
- Backend: `cross_meeting_service.derive_cross_meeting_insights(history, user_id)` → served by `GET /insights` (storage_routes:234). Pure lexical aggregation today.
- Frontend: `IntelligenceView.jsx` renders cards from `lib/insights.normalizeInsights(serverInsights, history)`, which prefers the server payload and falls back to a **client re-derivation** (`deriveInsights`) that duplicates the same lexical logic.

## Diagnosis

### What genuinely works (KEEP)
- **HealthTrend** — real per-meeting health score over time (the proof the surface CAN be good).
- **DecisionMemory (recent decisions)** — real P1 decisions + owner + date.
- **StatsHero metrics** — meeting count, avg/latest score, completion rate, decision velocity (real counts).
- **OwnerLoad / open_owner_load** (workspace) — real open-item load per owner.

### Broken → B1 (surgical fixes)
1. **Blank decision-loop titles.** Backend sends `unresolved_decisions[].latest_title / latest_owner / meeting_ids` (snake). The cards read `decision.latestTitle / latestOwner / meetings` (camel + expects meeting *objects*). `normalizeInsights` (insights.js:263) passes the server array through **unmapped** → `latestTitle` is `undefined` → "Resurfaced in N meetings" with NO title, and the meeting chips break (`meeting_ids` are ids, not `{id,title}`). Hits **both** `UnresolvedDecisionsCard` (IntelligenceView) and `DecisionMemory` (line 56).
2. **"Unassigned" flagged as an overloaded contributor.** Owner aggregation counts whatever string the LLM put in `owner`, incl. "Unassigned"/"Unowned"/"team"/"everyone". Ownership drift then names it a person carrying load. Hygiene signal masquerading as a person.
3. **Blocker garbage.** `looks_like_blocker` substring-matches keywords ("risk","concern",…) against the **full summary + sentiment.notes** → surfaces summary *fragments* ("The meeting, led by Vidyut…") as "recurring blockers."
4. **Scope heading wrong.** `StatsHero` shows **"Workspace overview"** in Personal scope (should read "Personal / your meetings").

### Shallow by design → B2 (rebuild)
- **Recurring themes / "Recurring language"** = raw word frequency (`extract_significant_terms` → `theme_counts[w]++`). Top "themes" are the user's own **name** (vidyut, sriram) + generic verbs. STOP_WORDS can't keep up.
- **Decision loops** = grouping by the **first 3 long words** (`build_decision_key`) → false loops (unrelated decisions sharing 3 words) and misses real ones (same decision, different words).
- **Resurfacing decision themes** = word-freq of decision terms (same problem).
- **Metrics have no interpretation** — counts with no "so what."

---

## B1 — Quick bug-fix tier (surgical, ~half a day, low risk)

All backend + the `lib/insights.js` mapping; no new deps, no migration.

1. **Fix the snake→camel decision mapping.** In `normalizeInsights`, transform the server `unresolved_decisions` into the card shape:
   - `latest_title → latestTitle`, `latest_owner → latestOwner`.
   - `meeting_ids → meetings` by resolving each id against `history` (`{id, title, date}`); drop ids not in history.
   - Do the same wherever the server shape ≠ card shape. Fixes blank titles + broken chips in both cards.
2. **Junk-owner filter.** A shared `_is_real_owner(name)` that rejects `{unassigned, unowned, tbd, none, n/a, team, everyone, all, attendees, group, ""}` (case-insensitive). Apply to `owner_counts`, `top_owners`, `ownership_drift`, `open_owner_load` (backend) + the mirror in `deriveInsights` (frontend).
3. **Blocker sources = structured only.** Stop deriving blockers from `summary` / `sentiment.notes` prose. Derive only from: (a) action-item `task`s that look like blockers, (b) `sentiment.tension_moments` with `status == "carried_over"` (already structured, already meaningful). Kills the summary-fragment noise.
4. **Scope heading.** `StatsHero`: Personal → "Your meetings" / "Personal overview"; workspace → "Team · {name}". (Already has `workspaceName`; just fix the null branch.)
5. **(cheap win) Theme name-filter** — until B2 replaces themes, exclude known participant names (union of `owner` + `sentiment.speakers[].name` across meetings) from `recurring_themes` so the user's own name stops topping the list.

---

## B2 — Semantic synthesis rebuild (the moat, multi-day)

**Thesis:** replace lexical aggregation with ONE cheap, cached LLM synthesis pass over recent meetings. Counting → understanding.

### Backend — `cross_meeting_synthesis.py`
`synthesize_cross_meeting(meetings, scope) -> dict`
- **Input (bounded):** a compact digest per meeting for the last ~30–40 — `{meeting_id, date, title, summary, decisions[], open_action_items[], sentiment_arc}`. **No transcripts** (keeps it ~6–8k tokens).
- **One `llm_call` (Haiku)** → strict JSON:
  - `narrative`: 2–3 sentences — "what's actually happening across your meetings."
  - `topics`: `[{topic, status: active|stalled|resolved, meeting_ids[], gist}]` — real recurring subjects, semantically clustered (not word counts).
  - `open_threads`: `[{thread, first_seen, last_seen, meeting_ids[], why_open, suggested_next_step}]` — **"discussed X in 3 meetings, never closed"** (the killer feature).
  - `decision_evolution`: `[{topic, timeline: [{meeting_id, date, what_changed}]}]` — how a decision moved over time.
- **Anti-hallucination:** every item must cite `meeting_ids` from the input; instruct to use ONLY provided digests; drop any item whose citations don't resolve. (Mirror the RAG trust-layer discipline.)
- **Caching:** key = `(scope, hash(sorted meeting_ids))`. Recompute only when the meeting set changes (a new meeting). [Decision #1: durable table vs in-memory LRU.]
- **Wiring:** `derive_cross_meeting_insights` keeps all the CHEAP deterministic metrics (health trend, completion, velocity, decision memory, owner load) computed instantly, and attaches the cached semantic block. [Decision #2: compute lazily on load vs eagerly at save.]
- **Flag:** `PRISM_CROSS_MEETING_SEMANTIC` (default ON once proven). Below a min-meeting count [Decision #4], skip synthesis and show an "unlocks after N meetings" state.

### Frontend
- **Replace** ThemeChips ("Recurring language") → **Topics** card (semantic topics + status pill + meeting chips).
- **Replace** `UnresolvedDecisionsCard` + `resurfacingDecisionThemes` → **Open Threads** card ("discussed but never closed" + first→last timeline + click-through + a "resolve/dismiss" affordance) and **Decision Evolution** (timeline of how a decision changed).
- **Add** the `narrative` line at the top of the page.
- **Keep** HealthTrend, DecisionMemory (recent decisions), StatsHero metrics, OwnerLoad.
- **Scope-aware:** Personal = "your threads / your backlog"; team-only cards (leaderboard, topics-without-a-decision) stay workspace-gated.

### B2 decisions — LOCKED (Jul 23)
1. **Cache store: durable table** `cross_meeting_cache` (1 migration; survives restart/cold-start → no wasted recompute, instant loads). Key = `(scope_id, meeting_set_hash)`, payload jsonb, generated_at. Follow the manual-migration convention (RLS enabled, no policies — service-role only) like `custom_keyterms`.
2. **Compute: lazy on load.** `/insights` returns cheap deterministic metrics instantly; the semantic block is served from cache, and (on a cache miss / changed meeting set) computed on that request — cheap metrics never wait on the LLM. No save-path work.
3. **First slice: all three** — `topics` + `open_threads` + `decision_evolution` (+ `narrative`) in one B2 pass.
4. **Min-meetings gate: under 3** → skip synthesis, show "Cross-meeting insights unlock after 3 meetings."

---

## Sequencing
B1 first (surgical, ships in one pass, immediately stops the page looking broken) → then B2 (the real work). B1 does not block B2; B2 replaces the shallow cards B1 patched.

"""
Three-layer memory system for live PrismAI meeting sessions.

Layer 1 — Raw recent window (RECENT_WINDOW=60 lines):
    Last 60 verbatim lines, always injected into every LLM command call.
    Covers the last ~5-10 minutes of conversation.

Layer 2 — Rolling compressed summary:
    LLM-condensed narrative of everything before the recent window.
    Triggered asynchronously every COMPRESS_EVERY=20 new lines via asyncio.create_task
    so it NEVER blocks command processing. Persisted to Supabase after each run.

Layer 3 — Structured live state (zero LLM cost):
    Regex-extracted decisions, action items, and named-entity frequencies.
    Updated synchronously on every transcript segment.
    Also drives the proactive intervention counters in realtime_routes.py.

Memory budget per command call (vs. previous 30-line-only system):
    Layer 2 summary    ~500 tokens   (was 0)
    Layer 3 structured ~200 tokens   (was 0)
    Layer 1 recent     ~1500 tokens  (was ~700 for 30 lines)
    Semantic search    ~300 tokens   (was 0, question-type commands only)
    System overhead    ~300 tokens
    ─────────────────  ─────────────
    Total              ~2800 tokens  vs. ~1000 tokens before
    Groq Llama 3.3-70b context: 128k tokens — no budget concern.

Thread safety:
    Designed for FastAPI / asyncio: single event-loop thread.
    The _compressing flag is a plain bool because asyncio never preempts between
    awaits, making the flag check-and-set atomic within a single event-loop tick.
"""

import re
import time
from collections import Counter

# ── Constants ─────────────────────────────────────────────────────────────────

RECENT_WINDOW = 60      # raw lines always fed to the LLM on every command call
COMPRESS_EVERY = 20     # trigger compression each time this many new lines accumulate past the cursor
MAX_SUMMARY_WORDS = 700 # condense the summary itself when it exceeds this word count (one extra pass)
MAX_BUFFER_LINES = 2000 # hard cap on transcript_buffer size; trim to TRIM_TO when exceeded
TRIM_TO = 1800          # target length after trim (old lines are already compressed into summary)

# ── Regex patterns ─────────────────────────────────────────────────────────────
# Canonical definitions — realtime_routes.py imports these instead of defining its own.

DECISION_PATTERN = re.compile(
    r"\b(decided|decision|agreed?|going with|resolved|confirmed|conclusion|finalized|"
    r"chosen|we(?:'re| are) going to go with|we'll go with|we(?:'ve| have) decided|"
    r"let's go with|the plan is|we're moving forward with|we've agreed)\b",
    re.IGNORECASE,
)

ACTION_ITEM_PATTERN = re.compile(
    r"\b(action item|follow[- ]?up|will handle|will take care|i'll|they'll|he'll|she'll|"
    r"you'll|we'll|by (?:monday|tuesday|wednesday|thursday|friday|next week|eod|eow|end of day)|"
    r"needs to|need to|is responsible for)\b",
    re.IGNORECASE,
)

# Matches "John will", "I will", "Sarah is going to", etc.
OWNER_PATTERN = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)?|I) "
    r"(?:will|'ll|is going to|am going to|are going to|needs? to)\b"
)

_ENTITY_SKIP = frozenset({
    "The", "We", "So", "But", "And", "For", "Our", "This", "That", "When",
    "What", "Let", "Also", "Just", "Yes", "No", "Ok", "Okay", "Right",
    "Well", "Like", "Know", "Think", "Have", "Been", "Very", "More",
    "Than", "With", "Some", "From", "They", "Their", "Are", "Has", "Had",
    "Get", "Got", "Put", "Set", "Run", "See", "Say", "Now", "Not",
})

# Command words that signal a question → triggers semantic search across full buffer
_QUESTION_WORDS = frozenset({
    "what", "who", "when", "where", "how", "why", "did", "does",
    "was", "were", "which", "tell", "remind", "recap", "earlier", "before",
})


# ── State initialiser ─────────────────────────────────────────────────────────

def get_initial_memory_state() -> dict:
    """
    Memory-specific fields merged into each new bot state dict in _get_bot_state().
    The host dict also contains: transcript_buffer, last_command_ts, processing,
    pending_trigger_ts, meeting_start_ts, decisions_detected, action_items_detected, etc.
    """
    return {
        # Layer 2 — rolling compressed summary
        "memory_summary": "",       # LLM-compressed narrative of lines before compression_cursor
        "compression_cursor": 0,    # index in transcript_buffer through which lines are compressed
        "_compressing": False,      # mutex flag — prevents concurrent compressions per bot

        # Layer 3 — zero-cost structured extraction
        "live_decisions": [],       # list[{text:str, speaker:str, ts:float}], capped at 25
        "live_action_items": [],    # list[{task:str, owner:str, ts:float, drift_flagged:bool}], capped at 25
        "live_entities": Counter(), # word → mention count for named entities

        # Idea Engine — proactive insight generation
        "idea_history": [],               # list[{type, message, confidence, ts}], capped at 20; exposed via API
        "idea_last_check_ts": 0.0,        # timestamp of last idea check; enforces 8-min inter-check cooldown
        "_idea_generating": False,        # mutex flag — prevents concurrent idea generation per bot
        "previous_idea_summaries": [],    # last 5 one-line summaries of posted ideas; injected to prevent repeats
        "gaps_flagged": set(),            # set[str]: gap categories already surfaced this meeting (cost, timeline…)
    }


# ── Idea Engine: Guard ────────────────────────────────────────────────────────

def _should_run_ideas(state: dict, now: float) -> bool:
    """
    Guard for the idea engine. All conditions must pass before a Groq idea call fires.
    Pure logic, no I/O — called synchronously before spawning the async idea generator.

    Conditions:
        _idea_generating  — mutex: only one generation per bot at a time
        meeting_start_ts  — no ideas before the meeting has real transcript
        elapsed < 12 min  — need enough context to reason about
        idea_last_check_ts— 8-minute cooldown between checks (regardless of idea outcome)
        live_entities     — meeting must have substance (> 4 distinct named entities)
        processing        — never fire while a user command is being handled
    """
    if state.get("_idea_generating"):
        return False
    start_ts = state.get("meeting_start_ts")
    if start_ts is None:
        return False
    if (now - start_ts) / 60 < 12:
        return False
    if now - state.get("idea_last_check_ts", 0.0) < 480:
        return False
    if len(state.get("live_entities") or {}) <= 4:
        return False
    if state.get("processing"):
        return False
    return True


# ── Layer 3: Structured extraction (sync) ────────────────────────────────────

def update_structured_state(text: str, speaker: str, state: dict) -> None:
    """
    Update all structured memory fields and proactive-trigger counters from one segment.

    Pure regex, O(len(text)), no I/O. Call synchronously on every transcript segment.
    Replaces the inline detection blocks previously scattered in realtime_routes.py.

    Writes to state:
        live_decisions, live_action_items, live_entities    ← new memory fields
        decisions_detected, action_items_detected, owners_detected  ← proactive counters
    """
    # ── Decisions ─────────────────────────────────────────────────────────────
    if DECISION_PATTERN.search(text):
        state["decisions_detected"] = state.get("decisions_detected", 0) + 1
        state["live_decisions"].append(
            {"text": text.strip()[:250], "speaker": speaker, "ts": time.time()}
        )
        if len(state["live_decisions"]) > 25:
            state["live_decisions"] = state["live_decisions"][-25:]

    # ── Action items ──────────────────────────────────────────────────────────
    if ACTION_ITEM_PATTERN.search(text):
        state["action_items_detected"] = state.get("action_items_detected", 0) + 1
        state["live_action_items"].append(
            {"task": text.strip()[:250], "owner": _extract_owner(text, speaker), "ts": time.time()}
        )
        if len(state["live_action_items"]) > 25:
            state["live_action_items"] = state["live_action_items"][-25:]

    # ── Owner detection (separate counter for proactive trigger) ──────────────
    if OWNER_PATTERN.search(text):
        state["owners_detected"] = state.get("owners_detected", 0) + 1

    # ── Named entities ────────────────────────────────────────────────────────
    for word in re.findall(r"\b[A-Z][a-z]{2,}\b", text):
        if word not in _ENTITY_SKIP:
            state["live_entities"][word] += 1


def _extract_owner(text: str, fallback_speaker: str) -> str:
    """Return the responsible person from an action-item line."""
    m = OWNER_PATTERN.search(text)
    if not m:
        return fallback_speaker
    first_word = m.group(0).split()[0]
    return fallback_speaker if first_word.lower() == "i" else first_word


# ── Layer 2: Rolling compression (async) ─────────────────────────────────────

async def maybe_compress(bot_id: str, state: dict) -> None:
    """
    Compress lines that have moved past the RECENT_WINDOW into a rolling LLM summary.

    Always called via asyncio.create_task() — never awaited by the command processor,
    so it cannot block a response even if the LLM call takes 2 seconds.

    Guards:
        _compressing flag: exits immediately if another compression is already running.
        COMPRESS_EVERY threshold: exits if fewer than COMPRESS_EVERY new lines are ready.

    On success:  state["memory_summary"] and state["compression_cursor"] are updated.
    On failure:  exception logged, state unchanged, next call retries from same cursor.
    """
    buf = state["transcript_buffer"]
    cursor = state["compression_cursor"]
    # Lines eligible for compression: everything older than the recent window
    compressible_end = max(0, len(buf) - RECENT_WINDOW)

    if compressible_end - cursor < COMPRESS_EVERY:
        return  # not enough new lines past the cursor
    if state["_compressing"]:
        return  # compression already in progress for this bot

    state["_compressing"] = True
    try:
        segment = buf[cursor:compressible_end]
        new_summary = await _compress_segment(segment, state["memory_summary"])
        state["memory_summary"] = new_summary
        state["compression_cursor"] = compressible_end
        print(
            f"[memory] bot={bot_id[:8]} compressed lines {cursor}→{compressible_end} "
            f"({len(segment)} lines), summary={len(new_summary.split())} words"
        )
    except Exception as exc:
        print(f"[memory] compression failed for bot {bot_id}: {exc}")
    finally:
        state["_compressing"] = False


async def _compress_segment(lines: list[str], existing_summary: str) -> str:
    """
    Integrate new transcript lines into the running summary via LLM.
    Uses agents.utils.llm_call (lazy import) which auto-falls back to Claude Haiku on Groq 429/503.
    temperature=0.1 for deterministic, fact-preserving output.

    If the existing summary is already over MAX_SUMMARY_WORDS, it is condensed first
    (one level of recursion only — the recursive call passes empty existing_summary).
    """
    from agents.utils import llm_call  # local import avoids circular dependency at module load

    segment_text = "\n".join(lines)

    # Condense the summary if it has grown too long (runs once; the recursive call
    # passes "" as existing_summary so it cannot recurse again).
    if len((existing_summary or "").split()) > MAX_SUMMARY_WORDS:
        existing_summary = await _compress_segment(existing_summary.splitlines(), "")

    if existing_summary.strip():
        system = (
            "You are updating running notes for a live meeting that an AI assistant uses. "
            "Integrate the new transcript segment into the existing summary.\n"
            "Rules:\n"
            "1. Keep EVERY decision, action item, commitment, name, number, and date from "
            "the existing summary — never drop a fact.\n"
            "2. Add new facts from the new segment.\n"
            "3. Write in past tense, third person, dense prose (no bullet points).\n"
            "4. Keep output under 650 words."
        )
        user = (
            f"EXISTING SUMMARY:\n{existing_summary}\n\n"
            f"NEW TRANSCRIPT SEGMENT TO INTEGRATE:\n{segment_text}"
        )
    else:
        system = (
            "You are writing dense meeting notes from a transcript segment for a live AI assistant. "
            "Capture every decision, action item, commitment, person, number, date, and key fact. "
            "Write in past tense, third person, dense prose (no bullet points). "
            "Record only what was said — do not editorialize. "
            "Keep output under 500 words."
        )
        user = f"TRANSCRIPT SEGMENT:\n{segment_text}"

    return await llm_call(system, user, temperature=0.1)


# ── Layer 1: Semantic search ──────────────────────────────────────────────────

def search_transcript(state: dict, query: str, top_k: int = 4) -> list[str]:
    """
    Keyword search across the FULL transcript buffer (all lines, not just the recent window).
    Enables answering questions about things said much earlier in the meeting without
    requiring a vector database.

    Scoring: intersection of 3+ character words between query and each buffer line.
    Returns up to top_k result chunks, each with ±2 surrounding lines for context.
    Complexity: O(n × q), n = buffer size, q = unique query words.
    """
    buf = state.get("transcript_buffer") or []
    if not buf or not query.strip():
        return []

    query_words = {w.lower() for w in re.findall(r"\b\w{3,}\b", query)}
    if not query_words:
        return []

    scored: list[tuple[int, int]] = []  # (overlap_count, line_index)
    for i, line in enumerate(buf):
        overlap = len(query_words & {w.lower() for w in re.findall(r"\b\w{3,}\b", line)})
        if overlap > 0:
            scored.append((overlap, i))

    if not scored:
        return []

    scored.sort(reverse=True)

    # Collect top-k unique indices, then sort chronologically
    seen: set[int] = set()
    top_indices: list[int] = []
    for _, idx in scored:
        if idx not in seen:
            seen.add(idx)
            top_indices.append(idx)
        if len(top_indices) >= top_k:
            break
    top_indices.sort()

    chunks: list[str] = []
    for idx in top_indices:
        start = max(0, idx - 2)
        end = min(len(buf), idx + 3)
        chunks.append("\n".join(buf[start:end]))

    return chunks


# ── Context assembly ──────────────────────────────────────────────────────────

def build_memory_context(state: dict, command: str = "") -> str:
    """
    Assemble the complete memory context string injected into the LLM system prompt.
    Synchronous — all data is already in memory; no I/O.

    Injection order (top → bottom):
        LLMs attend more strongly to content at the start of context, so the historical
        summary comes first (most important for answering about past events), followed by
        structured state, then the verbatim recent window at the end (highest recency salience).

        [MEETING MEMORY]       ← Layer 2: rolling summary (minute 0 → compression cursor)
        [DECISIONS]            ← Layer 3: regex-extracted structured list
        [ACTION ITEMS]         ← Layer 3: regex-extracted structured list
        [KEY ENTITIES]         ← Layer 3: most-mentioned names and topics
        [RELEVANT EARLIER]     ← Layer 1: semantic search hits (question commands only)
        [RECENT TRANSCRIPT]    ← Layer 1: verbatim RECENT_WINDOW lines (always last)
    """
    parts: list[str] = []

    # ── Layer 2 ───────────────────────────────────────────────────────────────
    summary = (state.get("memory_summary") or "").strip()
    if summary:
        parts.append(
            f"[MEETING MEMORY — everything discussed before the last {RECENT_WINDOW} transcript lines]\n"
            f"{summary}"
        )

    # ── Layer 3: Decisions ────────────────────────────────────────────────────
    decisions = state.get("live_decisions") or []
    if decisions:
        items = "\n".join(f"  • {d['speaker']}: {d['text']}" for d in decisions[-10:])
        parts.append(f"[DECISIONS CAPTURED SO FAR]\n{items}")

    # ── Layer 3: Action items ─────────────────────────────────────────────────
    action_items = state.get("live_action_items") or []
    if action_items:
        items = "\n".join(f"  • Owner: {a['owner']} → {a['task']}" for a in action_items[-10:])
        parts.append(f"[ACTION ITEMS CAPTURED SO FAR]\n{items}")

    # ── Layer 3: Top entities ─────────────────────────────────────────────────
    entities: Counter = state.get("live_entities") or Counter()
    if entities:
        top = [w for w, _ in entities.most_common(10)]
        parts.append(f"[KEY PEOPLE/TOPICS IN THIS MEETING]: {', '.join(top)}")

    # ── Layer 1: Semantic search (only for question-type commands) ────────────
    cmd_words = set((command or "").lower().split())
    buf_len = len(state.get("transcript_buffer") or [])
    # Only search if this looks like a recall question AND enough history exists past the window
    if (cmd_words & _QUESTION_WORDS) and buf_len > RECENT_WINDOW + COMPRESS_EVERY:
        hits = search_transcript(state, command)
        if hits:
            parts.append(
                "[RELEVANT EARLIER SEGMENTS — may help answer the question]\n"
                + "\n---\n".join(hits)
            )

    # ── Layer 1: Recent raw window (always last) ──────────────────────────────
    recent = (state.get("transcript_buffer") or [])[-RECENT_WINDOW:]
    if recent:
        parts.append(
            f"[RECENT TRANSCRIPT — last {len(recent)} lines]\n" + "\n".join(recent)
        )

    return "\n\n".join(parts)


# ── Idea Engine: Context assembly ─────────────────────────────────────────────

def build_idea_context(
    state: dict,
    elapsed_min: float,
    drifting_item: dict | None = None,
) -> str:
    """
    Assemble the LLM context for the idea engine.

    Unlike build_memory_context (query-driven, for command responses), this provides a
    holistic view of the whole meeting optimised for insight generation:

        [MEETING MEMORY]              ← Layer 2: rolling summary (full history)
        [DECISIONS CAPTURED]          ← Layer 3: what's been agreed
        [ACTION ITEMS]                ← Layer 3: commitments + elapsed age (drift detection)
        [DRIFTING COMMITMENT]         ← rule-found drift candidate; only present when detected
        [KEY TOPICS / PEOPLE]         ← Layer 3: named-entity frequency
        [RECENT TRANSCRIPT]           ← Layer 1: last 30 lines (current discussion)
        [UNRESOLVED FROM PAST MTGS]   ← historical blockers for pattern detection
        [IDEAS ALREADY SHARED]        ← dedup: what this engine has already surfaced
        [GAP CATEGORIES ALREADY FLAGGED] ← prevents re-flagging the same gap type
        [MEETING DURATION]            ← elapsed time for age-dependent guards in the prompt
    """
    parts: list[str] = []
    now_ts = time.time()

    # Layer 2: historical narrative
    summary = (state.get("memory_summary") or "").strip()
    if summary:
        parts.append(
            f"[MEETING MEMORY — everything before the last {RECENT_WINDOW} lines]\n{summary}"
        )

    # Layer 3: decisions
    decisions = state.get("live_decisions") or []
    if decisions:
        lines = "\n".join(f"  • {d['speaker']}: {d['text']}" for d in decisions[-12:])
        parts.append(f"[DECISIONS CAPTURED]\n{lines}")

    # Layer 3: action items with elapsed age — the LLM uses age for drift detection
    action_items = state.get("live_action_items") or []
    if action_items:
        lines = "\n".join(
            "  • {owner}: {task} [{age} min ago]{flag}".format(
                owner=a["owner"],
                task=a["task"],
                age=int((now_ts - a["ts"]) / 60),
                flag=" [already flagged]" if a.get("drift_flagged") else "",
            )
            for a in action_items[-12:]
        )
        parts.append(f"[ACTION ITEMS]\n{lines}")

    # Feature 2: If rule-based detection found a drifting commitment, highlight it explicitly
    # so the LLM doesn't have to discover it — more reliable than pure LLM reasoning on ages.
    if drifting_item is not None:
        age_min = int((now_ts - drifting_item["ts"]) / 60)
        parts.append(
            f"[DRIFTING COMMITMENT — rule-based detection found this item needs follow-up]\n"
            f"  • Owner: {drifting_item['owner']} → {drifting_item['task']} "
            f"(captured {age_min} min ago, owner has not spoken recently)\n"
            f"  This is a strong drift signal — prioritise type=drift if confidence is high."
        )

    # Layer 3: named-entity frequency
    entities: Counter = state.get("live_entities") or Counter()
    if entities:
        top = [w for w, _ in entities.most_common(10)]
        parts.append(f"[KEY TOPICS / PEOPLE]: {', '.join(top)}")

    # Layer 1: recent transcript — shorter than command context; ideas are holistic
    recent = (state.get("transcript_buffer") or [])[-30:]
    if recent:
        parts.append(f"[RECENT TRANSCRIPT — last {len(recent)} lines]\n" + "\n".join(recent))

    # Historical blockers fetched from past meetings by _run_proactive_checker
    blockers = state.get("historical_blockers") or []
    if blockers:
        bl = "\n".join(
            f"  • {b['date']}: {', '.join(b['keywords'][:5])}"
            for b in blockers[:5]
        )
        parts.append(f"[UNRESOLVED TOPICS FROM PAST MEETINGS]\n{bl}")

    # Deduplication: what the engine already surfaced this session
    prev = state.get("previous_idea_summaries") or []
    if prev:
        parts.append(
            "[IDEAS ALREADY SHARED — do not repeat these]\n"
            + "\n".join(f"  • {s}" for s in prev)
        )

    # Feature 1: Gap category deduplication — prevents the LLM from re-flagging a gap
    # that was already surfaced earlier this meeting.
    gaps: set = state.get("gaps_flagged") or set()
    if gaps:
        parts.append(
            f"[GAP CATEGORIES ALREADY FLAGGED — do not flag these again]: {', '.join(sorted(gaps))}"
        )

    parts.append(f"[MEETING DURATION]: {int(elapsed_min)} minutes")

    return "\n\n".join(parts)


# ── Persistence helpers ───────────────────────────────────────────────────────

def get_memory_snapshot(state: dict) -> dict:
    """
    Extract memory fields for Supabase persistence and /live endpoint API responses.
    memory_summary is stored in its own TEXT column; everything else goes into live_state JSONB.
    """
    entities: Counter = state.get("live_entities") or Counter()
    return {
        # Top-level fields returned by the /live API endpoint
        "memory_summary": state.get("memory_summary") or "",
        "live_decisions": state.get("live_decisions") or [],
        "live_action_items": state.get("live_action_items") or [],
        "top_entities": [w for w, _ in entities.most_common(10)],
        "idea_history": state.get("idea_history") or [],
        # JSONB payload persisted to bot_sessions.live_state
        "live_state_payload": {
            "live_decisions": state.get("live_decisions") or [],
            "live_action_items": state.get("live_action_items") or [],
            "live_entities": dict(state.get("live_entities") or {}),
            "compression_cursor": state.get("compression_cursor") or 0,
            "idea_history": state.get("idea_history") or [],
            "previous_idea_summaries": state.get("previous_idea_summaries") or [],
            # sets are JSON-unserializable — store as a sorted list, restore as set
            "gaps_flagged": sorted(state.get("gaps_flagged") or []),
        },
    }


def restore_memory_state(db_row: dict, state: dict) -> None:
    """
    Restore memory fields from a Supabase bot_sessions row into a bot state dict.
    Called by recall_routes._db_load() when recovering after a server restart.
    Idempotent — safe to call multiple times on the same state dict.
    """
    live_state = db_row.get("live_state") or {}
    state["memory_summary"] = db_row.get("memory_summary") or ""
    state["live_decisions"] = live_state.get("live_decisions") or []
    state["live_action_items"] = live_state.get("live_action_items") or []
    state["compression_cursor"] = live_state.get("compression_cursor") or 0
    # Restore Counter from the {word: count} dict stored in JSONB
    raw_entities = live_state.get("live_entities") or {}
    state["live_entities"] = Counter(raw_entities)
    # Restore idea engine state
    state["idea_history"] = live_state.get("idea_history") or []
    state["previous_idea_summaries"] = live_state.get("previous_idea_summaries") or []
    state["gaps_flagged"] = set(live_state.get("gaps_flagged") or [])

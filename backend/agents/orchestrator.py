"""Deterministic agent router.

Previously an LLM call chose which agents to run. But once most agents became
mandatory and sentiment moved to a speaker-count gate, the LLM was left deciding
essentially nothing — a full-transcript round-trip on the critical path for no
real pruning. Routing is now pure, deterministic logic: every agent runs, except
sentiment on single-speaker recordings (its vocabulary needs >=2 participants).
No LLM call, no JSON-parse failure mode, consistent across short and long meetings.
"""

# Agents the StateGraph can run. (decision_linker runs inside _tier1_barrier,
# not as a graph node, so it is intentionally absent here.)
ALL_AGENTS = [
    "summarizer", "action_items", "decisions", "sentiment",
    "email_drafter", "calendar_suggester", "health_score", "speaker_coach",
]


def _count_speakers(transcript: str) -> int:
    """Distinct 'Speaker:' prefixes in the transcript. Same heuristic the
    sentiment agent uses for talk distribution (short, no sentence punctuation)."""
    speakers: set[str] = set()
    for raw_line in (transcript or "").split("\n"):
        line = raw_line.strip()
        if ":" not in line:
            continue
        head = line.split(":", 1)[0].strip()
        if not head or len(head) > 40 or any(c in head for c in ".?!"):
            continue
        speakers.add(head.lower())
    return len(speakers)


def run_orchestrator(transcript: str) -> list[str]:
    """Decide which agents to run — deterministically.

    All agents run; sentiment is gated to multi-speaker meetings (a solo recording
    has no interpersonal dynamic to characterize). calendar_suggester always runs
    and self-decides whether a follow-up is recommended.
    """
    agents = list(ALL_AGENTS)
    if _count_speakers(transcript) < 2:
        agents = [a for a in agents if a != "sentiment"]
    return agents

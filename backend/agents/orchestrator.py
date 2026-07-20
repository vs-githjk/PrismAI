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
# content_analyst always routes but early-returns (no LLM) for standard meetings;
# meeting_classifier only runs when the type is auto-detected (see run_orchestrator).
ALL_AGENTS = [
    "summarizer", "action_items", "decisions", "sentiment",
    "email_drafter", "calendar_suggester", "health_score", "speaker_coach",
    "action_executor", "content_analyst",
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


def run_orchestrator(transcript: str, meeting_type: str | None = None) -> list[str]:
    """Decide which agents to run — deterministically.

    All agents run; sentiment is gated to multi-speaker meetings (a solo recording
    has no interpersonal dynamic to characterize). calendar_suggester always runs
    and self-decides whether a follow-up is recommended.

    meeting_classifier runs only when the type is auto-detected (falsy / 'auto') —
    when the user pre-picks a type there's nothing to classify. content_analyst is
    always routed (it self-gates on the resolved type, no LLM for standard).
    """
    agents = list(ALL_AGENTS)
    mt = (meeting_type or "").strip().lower()
    if mt == "article":
        # A single-authored article/report has no speakers → the interpersonal
        # agents are meaningless (sentiment = per-speaker tone, speaker_coach =
        # talk-time balance). The Article/Report lens (content_analyst) carries the
        # analysis instead. Skipping them also avoids the "13 speakers" false read
        # from a report's colon-prefixed headings ("Verdict:", "Weakest:", …).
        agents = [a for a in agents if a not in ("sentiment", "speaker_coach")]
    elif _count_speakers(transcript) < 2:
        agents = [a for a in agents if a != "sentiment"]
    if mt in ("", "auto"):
        agents.append("meeting_classifier")
    return agents

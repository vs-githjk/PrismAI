import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    'You are a meeting analysis orchestrator. Read this transcript and decide which agents are needed. '
    'Return ONLY valid JSON: { "agents": [...], "reasoning": "" }. '
    'Always include: summarizer, action_items, email_drafter, decisions, health_score, speaker_coach. '
    'Only include calendar_suggester if a follow-up meeting was discussed. '
    '(Sentiment is decided separately by speaker count — you do not need to choose it.)'
)

ALL_AGENTS = ["summarizer", "action_items", "decisions", "sentiment", "email_drafter", "calendar_suggester", "health_score", "speaker_coach"]


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


async def run_orchestrator(transcript: str) -> list[str]:
    try:
        raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}", temperature=0.1)
        cleaned = strip_fences(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            raw2 = await llm_call(
                SYSTEM_PROMPT,
                f"Transcript:\n{transcript}\n\nReturn ONLY raw JSON, no markdown.",
                temperature=0.1,
            )
            data = json.loads(strip_fences(raw2))

        agents = data.get("agents", ALL_AGENTS)
        # Always ensure core agents are included
        if "summarizer" not in agents:
            agents.insert(0, "summarizer")
        if "decisions" not in agents:
            agents.append("decisions")
        if "health_score" not in agents:
            agents.append("health_score")
        if "speaker_coach" not in agents:
            agents.append("speaker_coach")

        # Sentiment gating is deterministic, not an LLM judgment call: run it for
        # any real multi-speaker meeting (its vocabulary covers POSITIVE dynamics
        # too — collaborative/aligned — so the old "only if tension" trigger
        # wrongly skipped healthy meetings). Skip only true solo recordings.
        if _count_speakers(transcript) >= 2:
            if "sentiment" not in agents:
                agents.append("sentiment")
        else:
            agents = [a for a in agents if a != "sentiment"]
        return agents
    except Exception:
        # fail open — run all agents
        return ALL_AGENTS

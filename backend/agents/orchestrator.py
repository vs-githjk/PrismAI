import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    'You are a meeting analysis orchestrator. Read this transcript and decide which agents are needed. '
    'Return ONLY valid JSON: { "agents": [...], "reasoning": "" }. '
    'Always include: summarizer, action_items, email_drafter, decisions, health_score, speaker_coach. '
    'Only include calendar_suggester if a follow-up meeting was discussed. '
    'Only include sentiment if there is tension, conflict, or strong emotion.'
)

ALL_AGENTS = ["summarizer", "action_items", "decisions", "sentiment", "email_drafter", "calendar_suggester", "health_score", "speaker_coach"]


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
        return agents
    except Exception:
        # fail open — run all agents
        return ALL_AGENTS

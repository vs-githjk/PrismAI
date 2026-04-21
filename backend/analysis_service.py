import asyncio

from agents import (
    action_items,
    calendar_suggester,
    decisions,
    email_drafter,
    health_score,
    orchestrator,
    sentiment,
    summarizer,
)


AGENT_MAP = {
    "summarizer": summarizer.run,
    "action_items": action_items.run,
    "decisions": decisions.run,
    "sentiment": sentiment.run,
    "email_drafter": email_drafter.run,
    "calendar_suggester": calendar_suggester.run,
    "health_score": health_score.run,
}


DEFAULT_RESULT = {
    "summary": "",
    "action_items": [],
    "decisions": [],
    "sentiment": {"overall": "neutral", "score": 50, "arc": "stable", "notes": "", "speakers": [], "tension_moments": []},
    "follow_up_email": {"subject": "", "body": ""},
    "calendar_suggestion": {"recommended": False, "reason": "", "suggested_timeframe": "", "resolved_date": "", "resolved_day": ""},
    "health_score": {"score": 0, "verdict": "", "badges": [], "breakdown": {"clarity": 0, "action_orientation": 0, "engagement": 0}},
    "agents_run": [],
}


AGENT_RESULT_KEY = {
    "summarizer": "summary",
    "action_items": "action_items",
    "decisions": "decisions",
    "sentiment": "sentiment",
    "email_drafter": "follow_up_email",
    "calendar_suggester": "calendar_suggestion",
    "health_score": "health_score",
}


def build_analysis_transcript(transcript: str, speakers: list | None = None, owner_name: str | None = None) -> str:
    speakers = speakers or []
    lines = []
    if owner_name and owner_name.strip():
        lines.append(f"[Meeting owner: {owner_name.strip()}]")
    if speakers:
        lines.append("Meeting participants:")
        for speaker in speakers:
            name = (speaker.get("name") or "").strip()
            role = (speaker.get("role") or "").strip()
            if name:
                lines.append(f"  - {name}: {role}" if role else f"  - {name}")
    if not lines:
        return transcript
    return "\n".join(lines) + "\n\n" + transcript


def merge_agent_results(valid_agents: list[str], results: list) -> dict:
    result = dict(DEFAULT_RESULT)
    result["agents_run"] = valid_agents

    for agent_name, agent_result in zip(valid_agents, results):
        if isinstance(agent_result, Exception):
            continue
        if agent_name == "summarizer":
            result["summary"] = agent_result.get("summary", "")
        elif agent_name == "action_items":
            result["action_items"] = agent_result.get("action_items", [])
        elif agent_name == "decisions":
            result["decisions"] = agent_result.get("decisions", [])
        elif agent_name == "sentiment":
            result["sentiment"] = agent_result.get("sentiment", DEFAULT_RESULT["sentiment"])
        elif agent_name == "email_drafter":
            result["follow_up_email"] = agent_result.get("follow_up_email", DEFAULT_RESULT["follow_up_email"])
        elif agent_name == "calendar_suggester":
            result["calendar_suggestion"] = agent_result.get("calendar_suggestion", DEFAULT_RESULT["calendar_suggestion"])
        elif agent_name == "health_score":
            result["health_score"] = agent_result.get("health_score", DEFAULT_RESULT["health_score"])

    return result


async def run_full_analysis(transcript: str) -> dict:
    agents_to_run = await orchestrator.run_orchestrator(transcript)
    valid_agents = [agent for agent in agents_to_run if agent in AGENT_MAP]
    tasks = [AGENT_MAP[agent](transcript) for agent in valid_agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return merge_agent_results(valid_agents, results)

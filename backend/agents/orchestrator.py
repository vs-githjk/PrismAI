import json
import os
from groq import AsyncGroq

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    'You are a meeting analysis orchestrator. Read this transcript and decide which agents are needed. '
    'Return ONLY valid JSON: { "agents": [...], "reasoning": "" }. '
    'Always include: summarizer, action_items, email_drafter, decisions, health_score. '
    'Only include calendar_suggester if a follow-up meeting was discussed. '
    'Only include sentiment if there is tension, conflict, or strong emotion.'
)

ALL_AGENTS = ["summarizer", "action_items", "decisions", "sentiment", "email_drafter", "calendar_suggester", "health_score"]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # remove first and last fence lines
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


async def run_orchestrator(transcript: str) -> list[str]:
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
        )
        raw = response.choices[0].message.content
        cleaned = _strip_fences(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # retry once
            response2 = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Transcript:\n{transcript}\n\nReturn ONLY raw JSON, no markdown."},
                ],
            )
            raw2 = response2.choices[0].message.content
            data = json.loads(_strip_fences(raw2))

        agents = data.get("agents", ALL_AGENTS)
        # Always ensure core agents are included
        if "summarizer" not in agents:
            agents.insert(0, "summarizer")
        if "decisions" not in agents:
            agents.append("decisions")
        if "health_score" not in agents:
            agents.append("health_score")
        return agents
    except Exception:
        # fail open — run all agents
        return ALL_AGENTS

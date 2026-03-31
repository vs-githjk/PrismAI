import json
import os
from groq import AsyncGroq

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a meeting quality analyst. Rate this meeting transcript on effectiveness. "
    "Return ONLY valid JSON:\n"
    "{\n"
    '  "health_score": {\n'
    '    "score": <integer 0-100>,\n'
    '    "verdict": "<one concise sentence about meeting quality and outcome>",\n'
    '    "badges": ["<badge1>", "<badge2>"],\n'
    '    "breakdown": { "clarity": <0-100>, "action_orientation": <0-100>, "engagement": <0-100> }\n'
    "  }\n"
    "}\n"
    "Score guide: 80-100=excellent, 60-79=good, 40-59=fair, 0-39=poor. "
    "Pick 2-3 badges that best describe the meeting from: "
    "Clear Decisions, Action-Oriented, Well-Facilitated, Concise, Engaged Team, "
    "Inclusive, Ran Overtime, Unresolved Tension, No Clear Owners, Off-Track, Vague Outcomes."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


async def run(transcript: str) -> dict:
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
        data = json.loads(_strip_fences(raw))
        return data
    except Exception:
        return {
            "health_score": {
                "score": 50,
                "verdict": "Unable to analyze meeting quality.",
                "badges": [],
                "breakdown": {"clarity": 50, "action_orientation": 50, "engagement": 50},
            }
        }

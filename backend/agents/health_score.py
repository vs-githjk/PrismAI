import json
from .utils import strip_fences, llm_call

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

_DEFAULT = {
    "health_score": {
        "score": 50,
        "verdict": "Unable to analyze meeting quality.",
        "badges": [],
        "breakdown": {"clarity": 50, "action_orientation": 50, "engagement": 50},
    }
}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}", temperature=0.1)
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

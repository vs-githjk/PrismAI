import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting sentiment analyzer. Analyze the emotional tone of the meeting transcript in detail. "
    "Return ONLY valid JSON matching this exact shape:\n"
    '{ "sentiment": { "overall": "positive|neutral|tense|unresolved", "score": 0-100, "arc": "improving|stable|declining|unresolved", "notes": "1-2 sentence summary", '
    '"speakers": [ { "name": "string", "tone": "collaborative|neutral|resistant|frustrated", "score": 0-100 } ], '
    '"tension_moments": ["string", ...] } }\n'
    "Rules:\n"
    "- overall: overall tone of the meeting\n"
    "- score: 100=very positive, 50=neutral, 0=very negative/tense\n"
    "- arc: did the meeting mood improve, stay stable, decline, or end unresolved?\n"
    "- speakers: one entry per identified speaker with their individual tone and score\n"
    "- tension_moments: array of 1-3 specific moments where tone shifted or conflict arose (empty array if none). Be specific, e.g. 'Mike challenged the Q2 timeline estimate'."
)


_DEFAULT = {"sentiment": None}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

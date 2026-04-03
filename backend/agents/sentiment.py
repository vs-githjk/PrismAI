import json
import os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

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


async def run(transcript: str) -> dict:
    for attempt in range(2):
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript:\n{transcript}"},
            ],
        )
        raw = response.choices[0].message.content
        try:
            return json.loads(strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise HTTPException(status_code=500, detail="sentiment: failed to parse JSON after retry")
    return {"sentiment": {"overall": "neutral", "score": 50, "notes": ""}}

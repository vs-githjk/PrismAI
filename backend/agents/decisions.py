import json
import os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a meeting decisions extractor. Identify every explicit decision made during the meeting. "
    "Rank them by importance (1 = most important). "
    "Return ONLY valid JSON: { \"decisions\": [ { \"decision\": \"\", \"owner\": \"\", \"importance\": 1 } ] }. "
    "Rules:\n"
    "- A decision is something that was agreed upon or resolved, not just discussed.\n"
    "- importance: 1=critical/strategic, 2=significant, 3=minor/procedural.\n"
    "- owner: the person or team accountable for carrying it out, or 'Team' if collective.\n"
    "- Return an empty array if no decisions were made."
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
                raise HTTPException(status_code=500, detail="decisions: failed to parse JSON after retry")
    return {"decisions": []}

import json
import os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a calendar scheduling assistant. Based on the meeting transcript, determine if a follow-up meeting is needed. "
    'Return ONLY valid JSON: { "calendar_suggestion": { "recommended": true|false, "reason": "", "suggested_timeframe": "" } }. '
    "If no follow-up is needed, set recommended to false and leave suggested_timeframe empty. "
    "If the transcript contains a [User instruction: ...] line, follow it exactly — especially any specific date or timeframe the user requests."
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
                raise HTTPException(status_code=500, detail="calendar_suggester: failed to parse JSON after retry")

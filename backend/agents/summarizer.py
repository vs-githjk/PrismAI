import json
import os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are a meeting summarizer. Given a meeting transcript, produce a concise 2-3 sentence TL;DR summary. "
    'Return ONLY valid JSON: { "summary": "..." }'
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
                raise HTTPException(status_code=500, detail="summarizer: failed to parse JSON after retry")

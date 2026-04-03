import json
import os
from groq import AsyncGroq
from fastapi import HTTPException
from .utils import strip_fences

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = (
    "You are an email drafter. Based on the meeting transcript, write a follow-up email "
    "summarizing key decisions and action items. "
    'Return ONLY valid JSON: { "follow_up_email": { "subject": "", "body": "" } }. '
    "If the transcript contains a [User instruction: ...] line, follow it exactly — "
    "including any requested tone, style, length, or content changes."
)


async def run(transcript: str) -> dict:
    for attempt in range(2):
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.7,
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
                raise HTTPException(status_code=500, detail="email_drafter: failed to parse JSON after retry")

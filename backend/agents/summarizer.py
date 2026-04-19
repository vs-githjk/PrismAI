import json
from fastapi import HTTPException
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting summarizer. Given a meeting transcript, produce a concise 2-3 sentence TL;DR summary. "
    'Return ONLY valid JSON: { "summary": "..." }'
)


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise HTTPException(status_code=500, detail="summarizer: failed to parse JSON after retry")

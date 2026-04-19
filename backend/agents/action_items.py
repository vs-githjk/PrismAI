import json
from fastapi import HTTPException
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting action items extractor. Extract all action items from the transcript. "
    'Return ONLY valid JSON: { "action_items": [{ "task": "", "owner": "", "due": "" }] }. '
    "If no due date is mentioned, use 'TBD'. If no owner is mentioned, use 'Unassigned'."
)


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except json.JSONDecodeError:
            if attempt == 1:
                raise HTTPException(status_code=500, detail="action_items: failed to parse JSON after retry")

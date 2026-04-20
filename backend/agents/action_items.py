import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting action items extractor. Extract all action items from the transcript. "
    'Return ONLY valid JSON: { "action_items": [{ "task": "", "owner": "", "due": "" }] }. '
    "If no due date is mentioned, use 'TBD'. If no owner is mentioned, use 'Unassigned'."
)

_DEFAULT = {"action_items": []}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

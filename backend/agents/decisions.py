import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting decisions extractor. Identify every explicit decision made during the meeting. "
    "Rank them by importance (1 = most important). "
    "Return ONLY valid JSON: { \"decisions\": [ { \"decision\": \"\", \"owner\": \"\", \"importance\": 1, \"rationale\": \"\" } ] }. "
    "Rules:\n"
    "- A decision is something that was agreed upon or resolved, not just discussed.\n"
    "- importance: 1=critical/strategic, 2=significant, 3=minor/procedural.\n"
    "- owner: the person or team accountable for carrying it out, or 'Team' if collective.\n"
    "- rationale: a short phrase capturing WHY this was decided (the reasoning or context), "
    "ONLY if a reason was actually stated in the meeting. If no reason was given, use an empty string. "
    "Do NOT invent or infer a rationale that wasn't expressed.\n"
    "- Return an empty array if no decisions were made."
)


_DEFAULT = {"decisions": []}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

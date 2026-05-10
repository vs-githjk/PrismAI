import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting summarizer. Given a meeting transcript, produce a clear summary that covers: "
    "who was in the meeting, what was discussed, key insights or advice shared, and any outcomes or takeaways. "
    "Scale length to the meeting: short meetings (under 500 words) get 2-3 sentences; "
    "medium meetings (500-2000 words) get a short paragraph; "
    "long meetings (2000+ words) get 3-5 sentences covering all major topics. "
    "Also produce a title: 4-7 words that capture the core topic or purpose of the meeting "
    "(e.g. 'Q3 Budget Alignment', 'Onboarding Research Readout', 'API Integration Planning'). "
    "Do not start the title with 'The meeting' or 'A meeting'. "
    'Return ONLY valid JSON: { "title": "...", "summary": "..." }'
)

_DEFAULT = {"title": "", "summary": ""}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

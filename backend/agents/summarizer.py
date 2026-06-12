import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting summarizer. Given a meeting transcript, produce a structured summary.\n"
    "Return ONLY valid JSON: "
    '{ "title": "...", "tldr": "...", "summary": "...", "topics": ["...", "..."] }\n'
    "Fields:\n"
    "- title: 4-7 words capturing the core topic or purpose (e.g. 'Q3 Budget Alignment', "
    "'Onboarding Research Readout', 'API Integration Planning'). Do NOT start with 'The meeting' or 'A meeting'.\n"
    "- tldr: ONE punchy sentence — the single most important takeaway or outcome of the meeting. "
    "This is the headline a busy reader sees first.\n"
    "- summary: a clear prose summary covering who was there, what was discussed, key insights/advice, "
    "and outcomes. Scale length to the meeting: short (<500 words) → 2-3 sentences; medium (500-2000) → "
    "a short paragraph; long (2000+) → 3-5 sentences covering all major topics.\n"
    "- topics: 3-6 short scannable bullet points (a few words each) naming what was actually covered. "
    "Each is a topic/decision area, not a full sentence. Empty array only if the transcript is too thin."
)

_DEFAULT = {"title": "", "tldr": "", "summary": "", "topics": []}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

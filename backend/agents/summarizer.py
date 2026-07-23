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

# Article/Report lens: the input is a single-authored WRITTEN piece (essay, report,
# article), not a meeting transcript. The generic meeting prompt titles these things
# "Not a Meeting" and summarizes them as "...not a meeting transcript" — because it's
# looking for participants and decisions that don't exist. Describe the PIECE instead.
ARTICLE_SYSTEM_PROMPT = (
    "You summarize written pieces — essays, reports, articles, memos. Given the text of "
    "ONE such piece, produce a structured summary OF THE PIECE ITSELF. It is a document, "
    "not a meeting: there are no participants, no decisions, no action items — do not look "
    "for or mention them, and never say 'this is not a meeting'.\n"
    "Return ONLY valid JSON: "
    '{ "title": "...", "tldr": "...", "summary": "...", "topics": ["...", "..."] }\n'
    "Fields:\n"
    "- title: 4-7 words naming what the piece is ABOUT — its subject or headline "
    "(e.g. 'Reflection on a Dog's Fifth Birthday', 'Q3 Market Expansion Analysis', "
    "'The Case for Remote-First'). NEVER 'Not a Meeting' or anything about meetings.\n"
    "- tldr: ONE sentence — the piece's central point, claim, or takeaway.\n"
    "- summary: a clear prose summary of what the piece says and its through-line — its "
    "argument or narrative, key points, and any conclusion. Scale to length: short (<500 "
    "words) → 2-3 sentences; medium → a short paragraph; long → 3-5 sentences.\n"
    "- topics: 3-6 short scannable bullets (a few words each) naming the themes or sections "
    "the piece actually covers. Empty array only if the text is too thin."
)

_DEFAULT = {"title": "", "tldr": "", "summary": "", "topics": []}


async def run(transcript: str, meeting_type: str = "") -> dict:
    # An Article/Report is a written document, not a meeting — use the piece-aware prompt
    # so the title/summary describe the writing instead of judging it as a non-meeting.
    is_article = (meeting_type or "").strip().lower() == "article"
    system = ARTICLE_SYSTEM_PROMPT if is_article else SYSTEM_PROMPT
    label = "Document" if is_article else "Transcript"
    for attempt in range(2):
        try:
            raw = await llm_call(system, f"{label}:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

import json
from .utils import strip_fences, llm_call

# The vocabulary the whole content-analysis feature keys on. Keep in sync with
# content_analyst.RUBRICS and the frontend meeting-type selector.
VALID_TYPES = ("standard", "pitch", "interview_content", "interview_job")

SYSTEM_PROMPT = (
    "You classify a recorded conversation into exactly one type so the right analysis "
    "lens is applied. Read the transcript and choose ONE:\n"
    "- 'pitch': one person (or a team) presents/sells an idea, product, or plan to an "
    "audience — a demo, sales pitch, investor pitch, or presentation. Mostly one-directional.\n"
    "- 'interview_content': a research/podcast/journalistic interview where a host asks a "
    "guest questions to draw OUT their story, expertise, or opinions (the value is the guest's answers).\n"
    "- 'interview_job': a hiring/job interview where an interviewer EVALUATES a candidate for a role "
    "(the value is judging the candidate's fit, skills, and answers).\n"
    "- 'standard': anything else — a normal working meeting, standup, 1-on-1, brainstorm, "
    "sync, or discussion among peers.\n"
    "Default to 'standard' unless the transcript clearly matches one of the specialized types. "
    'Return ONLY valid JSON: { "meeting_type": "standard", "confidence": 0.0, "reason": "one short phrase" }. '
    "confidence is 0.0-1.0."
)

_DEFAULT = {"meeting_type": "standard"}


async def run(transcript: str) -> dict:
    # The agent's product is the resolved TYPE. confidence/reason are diagnostics
    # only — logged, never returned, so the streamed result stays identical to the
    # non-stream _state_to_result shape (no stray top-level keys leaking via the
    # frontend's chunk merge).
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            data = json.loads(strip_fences(raw))
            mt = str(data.get("meeting_type", "standard")).strip().lower()
            if mt not in VALID_TYPES:
                mt = "standard"
            print(f"[classifier] type={mt} conf={data.get('confidence')} — {str(data.get('reason', ''))[:80]}")
            return {"meeting_type": mt}
        except Exception:
            if attempt == 1:
                return dict(_DEFAULT)
    return dict(_DEFAULT)

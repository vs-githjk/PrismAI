import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are an email drafter. Based on the meeting transcript, write a follow-up email "
    "summarizing key decisions and action items. "
    "If the transcript begins with '[Meeting owner: NAME]', write the email FROM that person's perspective — "
    "they are the sender, and the email should be addressed TO the other participant(s). "
    "If no meeting owner is specified, infer the sender as the attendee (not the advisor or facilitator). "
    'Return ONLY valid JSON: { "follow_up_email": { "subject": "", "body": "" } }. '
    "If the transcript contains a [User instruction: ...] line, follow it exactly — "
    "including any requested tone, style, length, or content changes."
)


_DEFAULT = {"follow_up_email": {"subject": "", "body": ""}}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}", temperature=0.7)
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

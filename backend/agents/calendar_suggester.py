import json
from datetime import datetime
from calendar_resolution import resolve_relative_date
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a calendar scheduling assistant. Based on the meeting transcript, determine if a follow-up meeting is needed. "
    'Return ONLY valid JSON: { "calendar_suggestion": { "recommended": true|false, "reason": "", "suggested_timeframe": "", "resolved_date": "", "resolved_day": "" } }. '
    "If no follow-up is needed, set recommended to false and leave suggested_timeframe empty. "
    "Keep suggested_timeframe as the natural language phrase from the meeting whenever possible. "
    "If the transcript contains a [User instruction: ...] line, follow it exactly — especially any specific date or timeframe the user requests."
)


_DEFAULT = {"calendar_suggestion": {"recommended": False, "reason": "", "suggested_timeframe": "", "resolved_date": "", "resolved_day": ""}}


async def run(transcript: str) -> dict:
    reference_date = datetime.now().date()
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Reference date: {reference_date.isoformat()}\nTranscript:\n{transcript}")
            payload = json.loads(strip_fences(raw))
            suggestion = payload.get("calendar_suggestion", {}) or {}
            phrase = suggestion.get("suggested_timeframe") or suggestion.get("reason") or ""
            resolved = resolve_relative_date(phrase, reference_date=reference_date)
            suggestion["resolved_date"] = resolved["resolved_date"]
            suggestion["resolved_day"] = resolved["resolved_day"]
            payload["calendar_suggestion"] = suggestion
            return payload
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

import json
from datetime import datetime, timezone

from calendar_resolution import resolve_relative_date
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting action items extractor. Extract all action items from the transcript. "
    'Return ONLY valid JSON: { "action_items": [{ "task": "", "owner": "", "due": "" }] }. '
    "If no due date is mentioned, use 'TBD'. If no owner is mentioned, use 'Unassigned'."
)

_DEFAULT = {"action_items": []}


def _resolve_due_dates(payload: dict) -> dict:
    """Turn each item's free-text `due` ('Thursday', 'end of week') into a
    concrete `due_date` (ISO) so the app can flag overdue / due-soon. Keeps the
    original `due` as the display label. Empty when TBD/unparseable."""
    ref = datetime.now(timezone.utc).date()
    for item in payload.get("action_items", []) or []:
        due = (item.get("due") or "").strip()
        if due and due.upper() != "TBD":
            item["due_date"] = resolve_relative_date(due, reference_date=ref).get("resolved_date", "")
        else:
            item["due_date"] = ""
    return payload


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return _resolve_due_dates(json.loads(strip_fences(raw)))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

import json
from datetime import datetime, timedelta, timezone
from calendar_resolution import resolve_relative_date
from .utils import strip_fences, llm_call


def _default_followup_slot(reference_date):
    """A sensible future slot for a recommended follow-up when the meeting named no
    concrete time: the next business day at 10:00. Avoids the old failure where an
    unresolved follow-up showed no date and Add-to-Calendar fell back to 'now'."""
    d = reference_date + timedelta(days=1)
    while d.weekday() >= 5:  # skip Sat (5) / Sun (6)
        d += timedelta(days=1)
    return d.isoformat(), d.strftime("%A"), "10:00"

SYSTEM_PROMPT = (
    "You are a calendar scheduling assistant. Based on the meeting, determine if a follow-up meeting is needed "
    "and, if so, propose a concrete plan for it.\n"
    "Return ONLY valid JSON in this exact shape:\n"
    '{ "calendar_suggestion": {\n'
    '  "recommended": true|false,\n'
    '  "reason": "one sentence on why a follow-up is (or is not) needed",\n'
    '  "suggested_timeframe": "the natural-language timing from the meeting, e.g. \'next Tuesday at 3pm\' — empty if none",\n'
    '  "suggested_time": "specific clock time if one was mentioned, e.g. \'3pm\' — empty otherwise",\n'
    '  "agenda": ["2-4 short bullet points for the follow-up, drawn from OPEN action items and unresolved decisions"],\n'
    '  "attendees": ["names of the participants who should attend the follow-up"]\n'
    "} }\n"
    "Rules:\n"
    "- If no follow-up is needed, set recommended=false, leave suggested_timeframe/suggested_time empty, and agenda/attendees empty.\n"
    "- Ground the agenda in unfinished work: prefer open action items and decisions that still need follow-through. "
    "Do not invent topics that weren't discussed.\n"
    "- Keep suggested_timeframe as the natural-language phrase actually used in the meeting whenever possible.\n"
    "- For attendees, use the participant names that appear in the transcript/context; do not guess emails.\n"
    "- If the input contains a [User instruction: ...] line, follow it exactly — especially any specific date or time requested."
)


_DEFAULT = {"calendar_suggestion": {
    "recommended": False, "reason": "", "suggested_timeframe": "", "suggested_time": "",
    "agenda": [], "attendees": [], "resolved_date": "", "resolved_day": "", "resolved_time": "",
}}


def _build_user_content(transcript: str, context: dict, reference_date) -> str:
    parts = [f"Reference date: {reference_date.isoformat()}"]
    if context.get("decisions"):
        decisions_text = "\n".join(
            f"- {d.get('decision', str(d))}" for d in context["decisions"]
        )
        parts.append(f"Decisions from this meeting:\n{decisions_text}")
    if context.get("action_items"):
        # Open (incomplete) action items are the strongest signal for why a
        # follow-up is needed and what its agenda should be.
        open_items = [a for a in context["action_items"] if not a.get("completed")]
        if open_items:
            items_text = "\n".join(
                f"- {a.get('task', str(a))} (owner: {a.get('owner', 'Unassigned')}, due: {a.get('due', 'n/a')})"
                for a in open_items
            )
            parts.append(f"Open action items:\n{items_text}")
    # Tensions left unresolved are a strong reason to meet again — surface them
    # so the agenda can name what still needs to be worked out.
    sentiment = context.get("sentiment") or {}
    carried = [
        t for t in (sentiment.get("tension_moments") or [])
        if isinstance(t, dict) and t.get("status") == "carried_over" and t.get("moment")
    ]
    if carried:
        tensions_text = "\n".join(f"- {t['moment']}" for t in carried)
        parts.append(f"Unresolved tensions to address in a follow-up:\n{tensions_text}")
    # Decisions made but with no action item to carry them out — prime follow-up
    # material (someone needs to own the next step).
    unactioned = [d for d in (context.get("unactioned_decisions") or []) if d]
    if unactioned:
        dtxt = "\n".join(f"- {d}" for d in unactioned)
        parts.append(f"Decisions made with no action item yet (need follow-through):\n{dtxt}")
    if transcript:
        parts.append(f"Transcript:\n{transcript}")
    return "\n\n---\n\n".join(parts)


async def run(transcript: str, context: dict = {}) -> dict:
    reference_date = datetime.now(timezone.utc).date()
    user_content = _build_user_content(transcript, context, reference_date)

    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_content)
            payload = json.loads(strip_fences(raw))
            suggestion = payload.get("calendar_suggestion", {}) or {}

            # Resolve a concrete date + time. The timeframe phrase is the primary
            # source; fall back to any explicit time the model surfaced separately.
            phrase = suggestion.get("suggested_timeframe") or suggestion.get("reason") or ""
            resolved = resolve_relative_date(phrase, reference_date=reference_date)
            if not resolved.get("resolved_time") and suggestion.get("suggested_time"):
                t = resolve_relative_date(suggestion["suggested_time"], reference_date=reference_date)
                resolved["resolved_time"] = t.get("resolved_time", "")

            # A recommended follow-up with no concrete time the meeting agreed on still
            # needs a usable proposed slot — otherwise the card shows no date and
            # Add-to-Calendar defaults to "now". Fill a sensible future default.
            if suggestion.get("recommended"):
                if not resolved.get("resolved_date"):
                    rd, rday, rt = _default_followup_slot(reference_date)
                    resolved["resolved_date"], resolved["resolved_day"], resolved["resolved_time"] = rd, rday, rt
                elif not resolved.get("resolved_time"):
                    resolved["resolved_time"] = "10:00"

            suggestion.setdefault("agenda", [])
            suggestion.setdefault("attendees", [])
            suggestion.setdefault("suggested_time", "")
            suggestion["resolved_date"] = resolved["resolved_date"]
            suggestion["resolved_day"] = resolved["resolved_day"]
            suggestion["resolved_time"] = resolved.get("resolved_time", "")
            payload["calendar_suggestion"] = suggestion
            return payload
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

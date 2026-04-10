from __future__ import annotations

from datetime import date, datetime, timedelta
import re


WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTH_INDEX = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _next_weekday(reference_date: date, weekday: int, include_current_week: bool) -> date:
    current_weekday = reference_date.weekday()
    delta = (weekday - current_weekday) % 7
    if delta == 0 and not include_current_week:
        delta = 7
    return reference_date + timedelta(days=delta)


def _parse_month_day(reference_date: date, phrase: str) -> date | None:
    pattern = re.search(
        r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\b",
        phrase,
        re.IGNORECASE,
    )
    if not pattern:
        return None

    month = MONTH_INDEX[pattern.group("month").lower()]
    day = int(pattern.group("day"))
    year = reference_date.year

    for offset in (0, 1):
        try:
            candidate = date(year + offset, month, day)
        except ValueError:
            return None
        if candidate >= reference_date:
            return candidate

    return None


def resolve_relative_date(text: str, reference_date: date | None = None) -> dict:
    phrase = (text or "").strip()
    if not phrase:
        return {"resolved_date": "", "resolved_day": ""}

    reference_date = reference_date or datetime.now().date()
    lowered = phrase.lower()

    for weekday_name, weekday_index in WEEKDAY_INDEX.items():
        if f"this {weekday_name}" in lowered:
            resolved = _next_weekday(reference_date, weekday_index, include_current_week=True)
            return {
                "resolved_date": resolved.isoformat(),
                "resolved_day": resolved.strftime("%A"),
            }
        if f"next {weekday_name}" in lowered:
            resolved = _next_weekday(reference_date + timedelta(days=7), weekday_index, include_current_week=True)
            return {
                "resolved_date": resolved.isoformat(),
                "resolved_day": resolved.strftime("%A"),
            }
        if re.search(rf"\b{weekday_name}\b", lowered):
            resolved = _next_weekday(reference_date, weekday_index, include_current_week=True)
            return {
                "resolved_date": resolved.isoformat(),
                "resolved_day": resolved.strftime("%A"),
            }

    WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                   "six": 6, "seven": 7, "a": 1, "an": 1}

    if match := re.search(r"\bin\s+(?P<count>\d+)\s+day", lowered):
        resolved = reference_date + timedelta(days=int(match.group("count")))
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    if match := re.search(r"\bin\s+(?P<count>\d+)\s+week", lowered):
        resolved = reference_date + timedelta(weeks=int(match.group("count")))
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    # "one week from now", "a week from now", "two weeks from now"
    if match := re.search(r"\b(?P<word>a|an|one|two|three|four|five|six|seven|\d+)\s+week(?:s)?\s+from\s+(?:now|today)", lowered):
        w = match.group("word")
        count = int(w) if w.isdigit() else WORD_TO_NUM.get(w, 1)
        resolved = reference_date + timedelta(weeks=count)
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    # "one day from now", "a couple days from now"
    if match := re.search(r"\b(?P<word>a|an|one|two|three|four|five|six|seven|\d+)\s+day(?:s)?\s+from\s+(?:now|today)", lowered):
        w = match.group("word")
        count = int(w) if w.isdigit() else WORD_TO_NUM.get(w, 1)
        resolved = reference_date + timedelta(days=count)
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    # "next week"
    if "next week" in lowered:
        resolved = reference_date + timedelta(weeks=1)
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    if "tomorrow" in lowered:
        resolved = reference_date + timedelta(days=1)
        return {"resolved_date": resolved.isoformat(), "resolved_day": resolved.strftime("%A")}

    if "today" in lowered:
        return {"resolved_date": reference_date.isoformat(), "resolved_day": reference_date.strftime("%A")}

    explicit_date = _parse_month_day(reference_date, lowered)
    if explicit_date:
        return {"resolved_date": explicit_date.isoformat(), "resolved_day": explicit_date.strftime("%A")}

    return {"resolved_date": "", "resolved_day": ""}

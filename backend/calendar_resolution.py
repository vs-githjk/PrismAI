from __future__ import annotations

from datetime import date, datetime, timedelta
import calendar as _calendar
import re

try:  # Broad natural-language fallback. Optional so the module still imports
    import dateparser  # if the dependency isn't installed yet (graceful degrade).
except Exception:  # pragma: no cover - exercised only when dep missing
    dateparser = None


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

WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "a": 1, "an": 1}

# Named parts of the day → a sensible default clock time (24h "HH:MM").
TIME_OF_DAY = {
    "morning": "09:00",
    "noon": "12:00",
    "midday": "12:00",
    "afternoon": "14:00",
    "evening": "17:00",
    "night": "19:00",
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


def _parse_numeric_date(reference_date: date, phrase: str) -> date | None:
    """'6/15', '6-15', '6/15/2026' → date (rolls to next year if already past)."""
    m = re.search(r"\b(?P<month>\d{1,2})[/\-](?P<day>\d{1,2})(?:[/\-](?P<year>\d{2,4}))?\b", phrase)
    if not m:
        return None
    month, day = int(m.group("month")), int(m.group("day"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if m.group("year"):
        year = int(m.group("year"))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for offset in (0, 1):
        try:
            candidate = date(reference_date.year + offset, month, day)
        except ValueError:
            return None
        if candidate >= reference_date:
            return candidate
    return None


def _resolve_date_handrolled(lowered: str, reference_date: date) -> date | None:
    """Deterministic rules for the common phrasings. Returns None if no match."""
    # "this Tuesday" / "next Tuesday" / bare "tuesday"
    for weekday_name, weekday_index in WEEKDAY_INDEX.items():
        if f"this {weekday_name}" in lowered:
            return _next_weekday(reference_date, weekday_index, include_current_week=True)
        if f"next {weekday_name}" in lowered:
            # "next Monday" = the COMING Monday (not the Monday of next week).
            # Only roll forward a week if today already IS that weekday.
            return _next_weekday(reference_date, weekday_index, include_current_week=False)
        if re.search(rf"\b{weekday_name}\b", lowered):
            return _next_weekday(reference_date, weekday_index, include_current_week=True)

    # "end of (the) week" → upcoming Friday
    if re.search(r"\bend of (?:the )?week\b", lowered):
        return _next_weekday(reference_date, WEEKDAY_INDEX["friday"], include_current_week=True)

    # "start/beginning of next week" → next Monday
    if re.search(r"\b(?:start|beginning|early) of next week\b", lowered) or "early next week" in lowered:
        return _next_weekday(reference_date + timedelta(days=7), WEEKDAY_INDEX["monday"], include_current_week=True)

    # "end of (the) month" → last day of current month (or next if today is the last day)
    if re.search(r"\bend of (?:the )?month\b", lowered):
        last_day = _calendar.monthrange(reference_date.year, reference_date.month)[1]
        candidate = date(reference_date.year, reference_date.month, last_day)
        if candidate <= reference_date:
            ny, nm = (reference_date.year + (reference_date.month // 12), (reference_date.month % 12) + 1)
            last_day = _calendar.monthrange(ny, nm)[1]
            candidate = date(ny, nm, last_day)
        return candidate

    # "in N day(s)"
    if match := re.search(r"\bin\s+(?P<count>\d+)\s+day", lowered):
        return reference_date + timedelta(days=int(match.group("count")))

    # "in N week(s)"
    if match := re.search(r"\bin\s+(?P<count>\d+)\s+week", lowered):
        return reference_date + timedelta(weeks=int(match.group("count")))

    # "in a month" / "in N months"
    if match := re.search(r"\bin\s+(?P<word>a|an|one|two|three|four|five|six|\d+)\s+month", lowered):
        w = match.group("word")
        count = int(w) if w.isdigit() else WORD_TO_NUM.get(w, 1)
        month0 = reference_date.month - 1 + count
        year = reference_date.year + month0 // 12
        month = month0 % 12 + 1
        day = min(reference_date.day, _calendar.monthrange(year, month)[1])
        return date(year, month, day)

    # "one/two/a week(s) from now"
    if match := re.search(r"\b(?P<word>a|an|one|two|three|four|five|six|seven|\d+)\s+week(?:s)?\s+from\s+(?:now|today)", lowered):
        w = match.group("word")
        count = int(w) if w.isdigit() else WORD_TO_NUM.get(w, 1)
        return reference_date + timedelta(weeks=count)

    # "one/a day(s) from now"
    if match := re.search(r"\b(?P<word>a|an|one|two|three|four|five|six|seven|\d+)\s+day(?:s)?\s+from\s+(?:now|today)", lowered):
        w = match.group("word")
        count = int(w) if w.isdigit() else WORD_TO_NUM.get(w, 1)
        return reference_date + timedelta(days=count)

    if "next week" in lowered:
        return reference_date + timedelta(weeks=1)
    if "tomorrow" in lowered:
        return reference_date + timedelta(days=1)
    if "today" in lowered:
        return reference_date

    if explicit := _parse_month_day(reference_date, lowered):
        return explicit
    if numeric := _parse_numeric_date(reference_date, lowered):
        return numeric
    return None


def _parse_time(lowered: str) -> str:
    """Extract a clock time as 24h 'HH:MM', or '' if none found."""
    # "at 3pm", "3:30 pm", "10 am", "15:00"
    m = re.search(r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)\b", lowered)
    if m:
        hour = int(m.group("h")) % 12
        if m.group("ampm") == "pm":
            hour += 12
        minute = int(m.group("m") or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    # 24h "at 15:00" / "15:30" (avoid matching dates like 6/15 — require a colon)
    m = re.search(r"\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)\b", lowered)
    if m:
        return f"{int(m.group('h')):02d}:{m.group('m')}"
    # Named parts of the day
    for word, clock in TIME_OF_DAY.items():
        if re.search(rf"\b{word}\b", lowered):
            return clock
    return ""


def resolve_relative_date(text: str, reference_date: date | None = None) -> dict:
    """Resolve a natural-language scheduling phrase to a concrete date + (optional) time.

    Returns {resolved_date: 'YYYY-MM-DD'|'', resolved_day: 'Weekday'|'', resolved_time: 'HH:MM'|''}.
    Strategy: deterministic hand-rolled rules first (fast, predictable), then a
    `dateparser` fallback for anything they miss.
    """
    phrase = (text or "").strip()
    if not phrase:
        return {"resolved_date": "", "resolved_day": "", "resolved_time": ""}

    reference_date = reference_date or datetime.now().date()
    lowered = phrase.lower()

    resolved = _resolve_date_handrolled(lowered, reference_date)
    resolved_time = _parse_time(lowered)

    # Fallback: let dateparser try when the hand-rolled rules found no date
    # (or no time but the phrase clearly has one).
    if (resolved is None or not resolved_time) and dateparser is not None:
        try:
            base = datetime(reference_date.year, reference_date.month, reference_date.day)
            parsed = dateparser.parse(
                phrase,
                settings={
                    "RELATIVE_BASE": base,
                    "PREFER_DATES_FROM": "future",
                    "RETURN_AS_TIMEZONE_AWARE": False,
                },
            )
            if parsed:
                if resolved is None:
                    resolved = parsed.date()
                if not resolved_time and (parsed.hour or parsed.minute):
                    resolved_time = f"{parsed.hour:02d}:{parsed.minute:02d}"
        except Exception:
            pass

    if resolved is None:
        return {"resolved_date": "", "resolved_day": "", "resolved_time": resolved_time}

    return {
        "resolved_date": resolved.isoformat(),
        "resolved_day": resolved.strftime("%A"),
        "resolved_time": resolved_time,
    }

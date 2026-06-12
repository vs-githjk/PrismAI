"""Instant-acknowledgment phrases: category classifier + rotating variants.

The ack must FEEL like comprehension, not filler — so classification is
deliberately conservative: a wrong-category ack ("Checking your calendar—"
for a web question) reads as MISunderstanding, which is worse than the
neutral fallback. First confident match wins, top-to-bottom.

Pure logic, no I/O. Audio pre-synthesis lives in ack_audio.py.
"""

import os
import re

def ack_on() -> bool:
    return os.getenv("PRISM_ACK", "1") == "1"

def ack_delay_s() -> float:
    return float(os.getenv("PRISM_ACK_DELAY_S", "1.2"))


_EMAIL_WORDS = r"(?:e-?mails?|mail|gmail|inbox)"
_WRITE_VERBS = r"(?:send|draft|write|reply|forward|compose)"
_CAL_WORDS = r"(?:calendar|schedule|events?|invites?)"
_CAL_WRITE = r"(?:schedule|create|set\s+up|add|book|move|reschedule)"

# Ordered: first match wins. meeting_recall outranks knowledge/web so
# "check the docs about what we discussed last meeting" acknowledges recall.
_RULES: list[tuple[str, re.Pattern]] = [
    ("meeting_recall", re.compile(
        r"\b(?:last|previous|earlier)\s+meeting\b|\bwe\s+(?:talked|discussed|said|decided)\b",
        re.IGNORECASE)),
    ("email_write", re.compile(
        rf"\b{_WRITE_VERBS}\b[\w\s,]{{0,20}}\b{_EMAIL_WORDS}\b|\b{_EMAIL_WORDS}\b[\w\s,]{{0,20}}\b{_WRITE_VERBS}\b",
        re.IGNORECASE)),
    ("email_read", re.compile(rf"\b{_EMAIL_WORDS}\b", re.IGNORECASE)),
    ("calendar_write", re.compile(
        rf"\b{_CAL_WRITE}\b[\w\s,]{{0,30}}\b(?:{_CAL_WORDS}|meeting)\b",
        re.IGNORECASE)),
    ("calendar_read", re.compile(
        rf"\b{_CAL_WORDS}\b|\bmeetings?\b[\w\s,]{{0,15}}\b(?:tomorrow|today|next|this\s+week)\b"
        rf"|\b(?:tomorrow|today|next\s+\w+)\b[\w\s,]{{0,15}}\bmeetings?\b",
        re.IGNORECASE)),
    ("knowledge", re.compile(
        r"\bknowledge\s*base\b|\bdocuments?\b|\bdocs?\b|\bfiles?\b|\buploaded\b|\bpdf\b",
        re.IGNORECASE)),
    ("summary", re.compile(r"\bsummar|recap\b", re.IGNORECASE)),
    ("actions", re.compile(
        r"\baction\s+items?\b|\bdecisions?\b|\btask\s+list\b|\bto-?dos?\b", re.IGNORECASE)),
    ("web", re.compile(
        r"\blook\s+up\b|\bsearch\b|\bweather\b|\bnews\b|\blatest\b|\bprice\b|\bstock\b",
        re.IGNORECASE)),
]

CATEGORIES = [name for name, _ in _RULES] + ["generic"]

PHRASES: dict[str, list[str]] = {
    "email_write":    ["Drafting that email now—", "Let me put that email together—"],
    "email_read":     ["Let me check your inbox—", "Looking at your email—"],
    "calendar_write": ["Let me set that up on your calendar—"],
    "calendar_read":  ["Let me pull up your calendar—", "Checking your schedule—"],
    "meeting_recall": ["Let me look back through the meeting notes—"],
    "knowledge":      ["Let me go through your documents—"],
    "summary":        ["Give me a moment to pull that together—"],
    "actions":        ["Let me gather the action items—"],
    "web":            ["Let me look that up—", "Searching for that now—"],
    "generic":        ["On it — one moment.", "Sure — give me a second."],
}


def classify_command(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "generic"
    for name, pattern in _RULES:
        if pattern.search(t):
            return name
    return "generic"


def pick_phrase(category: str, state: dict) -> str:
    """Rotate variants per bot so consecutive commands don't repeat."""
    variants = PHRASES.get(category) or PHRASES["generic"]
    counts = state.setdefault("_ack_rotation", {})
    i = counts.get(category, 0)
    counts[category] = i + 1
    return variants[i % len(variants)]


def all_phrases() -> list[str]:
    out: list[str] = []
    for variants in PHRASES.values():
        for p in variants:
            if p not in out:
                out.append(p)
    return out

"""Deterministic verb pre-gate for the bot's on-screen presentation (computer use).

The `computer_use` tool (presents=True) is only ADDED to the model's tool list for
an utterance when `presents_gate_matches()` returns True. No match -> the model
cannot choose the screen, so an informational ask ("how did the presentation go?")
answers from knowledge and never spins up a sandbox share.

Design (spec 2026-07-07, ADR 0002):
  - Conservative visual-intent regex, VERB-ONLY (no audience check). The listed
    phrases themselves encode audience where relevant ("show us", "walk us
    through"); we do NOT require an extra audience noun elsewhere.
  - False positives should be structurally impossible; a false negative costs one
    rephrase. The phrase list is the single tuning knob.
  - Pure logic, no I/O. Precedents: ack_phrases._RULES, realtime_routes._STANDIN_QUERY_RE,
    perception_state._STOP_PATTERN.

Three helpers:
  - presents_gate_matches(utterance)  -> add computer_use to the tool list?
  - is_walkthrough_request(utterance) -> narration mode (model narrates what it sees)?
  - is_stop_sharing(utterance, extra_aliases=None) -> kill phrase during a present?
"""

import re

# "on screen" / "on the screen" locative cue — the anchor for put/open forms.
_ON_SCREEN = r"on(?:\s+the)?\s+screen"

# Bounded filler between a verb and the "on screen" cue (e.g. "put the dashboard on screen").
_FILLER = r"[\w\s,'-]{0,40}?"

# ── Visual-intent phrases (verb-only). First match wins; order is irrelevant. ──
_PRESENT_PATTERNS = [
    # "pull up <X>" — but NOT the social idiom "pull up a chair/seat/stool".
    r"\bpull\s+up\b(?!\s+a\s+(?:chair|seat|stool|pew))",
    # "bring up <X>" on the shared screen.
    r"\bbring\s+up\b",
    # "put / throw / get / toss <...> on (the) screen".
    r"\b(?:put|throw|get|toss|slap)\b" + _FILLER + r"\b" + _ON_SCREEN + r"\b",
    # "open <...> on (the) screen".
    r"\bopen\b" + _FILLER + r"\b" + _ON_SCREEN + r"\b",
    # "... up on (the) screen" (e.g. "get that up on screen").
    r"\bup\s+" + _ON_SCREEN + r"\b",
    # "show us / show everyone / show the room|team|group|meeting".
    r"\bshow\s+(?:us|everyone|everybody|the\s+(?:room|team|group|meeting|others))\b",
    # "walk / take us|everyone through" — visual walkthrough (audience form only;
    # "walk me through" is pure-explanation and stays out of the trigger gate).
    r"\b(?:walk|take)\s+(?:us|everyone|everybody|the\s+(?:team|room|group|others))\s+through\b",
    # "share your/my/the screen", "screen-share", "screenshare".
    r"\bshare\s+(?:your|my|the|his|her|their)?\s*screen\b",
    r"\bscreen[\s-]?shar",
]

_PRESENT_RE = re.compile("|".join(_PRESENT_PATTERNS), re.IGNORECASE)


def presents_gate_matches(utterance: str) -> bool:
    """True if the utterance shows clear visual/on-screen intent, so the
    `computer_use` (presents=True) tool should be offered to the model."""
    return bool(utterance) and bool(_PRESENT_RE.search(utterance))


# ── Walkthrough narration mode ────────────────────────────────────────────────
# Broader than the trigger gate: consulted only AFTER a present is triggered, to
# decide whether the CU model should narrate the content it sees (vs. drive silently).
# Includes "explain" and "walk me through" since being permissive here is harmless.
_WALKTHROUGH_RE = re.compile(
    r"\b(?:walk|take|talk)\s+(?:us|everyone|everybody|me|the\s+(?:team|room|group|others))\s+through\b"
    r"|\bwalk[\s-]?through\b"
    r"|\bexplain\b"
    r"|\bgive\s+(?:us|me|everyone|everybody)\s+(?:a\s+)?(?:rundown|walk[\s-]?through|tour|overview|breakdown)\b",
    re.IGNORECASE,
)


def is_walkthrough_request(utterance: str) -> bool:
    """True if the ask wants a narrated walkthrough (model explains what it sees)."""
    return bool(utterance) and bool(_WALKTHROUGH_RE.search(utterance))


# ── Stop / kill phrase ────────────────────────────────────────────────────────
# "stop sharing" and close variants. Persona-name variants (e.g. "Flash, stop")
# are opted in by the caller via extra_aliases — this base pattern stays generic.
_STOP_SHARE_RE = re.compile(
    r"\b(?:stop|end|quit|cease|kill|cut|halt)\b\s+"
    r"(?:the\s+|your\s+|this\s+|that\s+)?"
    r"(?:shar(?:e|ing)|screen[\s-]?shar(?:e|ing)?|present(?:ing|ation)?|show(?:ing)?)\b"
    r"|\bthat'?s\s+enough\s+(?:shar(?:e|ing)|present(?:ing|ation)?)\b"
    r"|\byou\s+can\s+stop\s+(?:shar(?:e|ing)|present(?:ing|ation)?|now)\b",
    re.IGNORECASE,
)


def is_stop_sharing(utterance: str, extra_aliases: list[str] | None = None) -> bool:
    """True if the utterance is a stop-the-presentation directive.

    `extra_aliases` (optional) are the bot's spoken names (persona name + Prism
    aliases) supplied by the caller who knows the bot; when present, "<alias>, stop"
    and "stop <alias>" forms also count as a kill phrase.
    """
    t = utterance or ""
    if not t:
        return False
    if _STOP_SHARE_RE.search(t):
        return True
    for alias in extra_aliases or []:
        a = re.escape((alias or "").strip())
        if not a:
            continue
        # "<alias>, stop" / "<alias> stop [it/that/now]"  or  "stop <alias>"
        if re.search(rf"\b{a}\b[,\s]+stop\b", t, re.IGNORECASE):
            return True
        if re.search(rf"\bstop\b[,\s]+{a}\b", t, re.IGNORECASE):
            return True
    return False

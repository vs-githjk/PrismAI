import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting quality analyst. Rate this transcript on how well it served "
    "ITS OWN purpose — not against an idealized formal business meeting. "
    "Return ONLY valid JSON:\n"
    "{\n"
    '  "health_score": {\n'
    '    "score": <integer 0-100, or null when there is nothing to grade>,\n'
    '    "verdict": "<one concise sentence about quality and outcome>",\n'
    '    "improvement_tip": "<one concrete, specific thing that would make the NEXT meeting better>",\n'
    '    "badges": ["<badge>", ...],\n'
    '    "breakdown": { "clarity": <0-100 or null>, "action_orientation": <0-100 or null>, "engagement": <0-100 or null> }\n'
    "  }\n"
    "}\n"
    "NOTHING TO GRADE: if the transcript is not a real meeting — a lone person issuing "
    "commands to an AI assistant, a connection test, or a fragmentary exchange with no "
    "substantive discussion — set score AND every breakdown value to null, badges to [], "
    "and write a verdict that plainly says what the recording was (e.g. 'A quick solo "
    "session commanding the assistant — not a meeting to grade.'). Do NOT assign a low "
    "score to something that never tried to be a meeting.\n"
    "CALIBRATION for real meetings (two-plus people, or a substantive solo briefing):\n"
    "- Grade against the meeting's own goal. A casual check-in that answered its question, "
    "a working session that found the bugs it was hunting, a catch-up that kept a team "
    "connected: these accomplished their purpose and belong at 55-75 even with zero "
    "formal decisions.\n"
    "- 76-100: crisp outcomes — clear decisions and/or owned next steps beyond what the "
    "format required.\n"
    "- 35-54: the meeting had a purpose it only partly served (main question left "
    "hanging, ownership fuzzy, meandering that cost real time).\n"
    "- Below 35: genuine dysfunction ONLY — unresolved conflict, talking past each "
    "other, a stated goal abandoned. Never for brevity or informality alone.\n"
    "- Do NOT penalize missing action items or decisions when the meeting's purpose "
    "didn't call for them.\n"
    "Badges: pick UP TO 3 that clearly apply, from: "
    "Clear Decisions, Action-Oriented, Well-Facilitated, Concise, Engaged Team, "
    "Inclusive, Ran Overtime, Unresolved Tension, No Clear Owners, Off-Track, Vague Outcomes. "
    "Return [] when none genuinely fit — badges are observations, not a quota. "
    "Never use 'Ran Overtime' (there is no duration data unless stated in the transcript). "
    "Only use 'No Clear Owners' when tasks were actually assigned ambiguously — not when "
    "there were simply no tasks.\n"
    "Only use the 'Unresolved Tension' badge if the input's Tension line says tensions were left "
    "UNRESOLVED/carried over. If it says all tensions were RESOLVED, do NOT use that badge.\n"
    "improvement_tip: ONE actionable suggestion grounded in the weakest dimension or a negative badge "
    "(e.g. 'Assign owners to the 3 unowned action items before closing' or 'Timebox the budget topic'). "
    "Reference specifics from the meeting, not generic advice. Use an empty string when the meeting "
    "was excellent, or when there was nothing to grade."
)

# Failure fallback: NO score, not a fake one. A stored 50 from a crashed analysis
# rendered as a real "Fair" meeting for months — null renders as "no score".
_DEFAULT = {
    "health_score": {
        "score": None,
        "verdict": "Unable to analyze meeting quality.",
        "improvement_tip": "",
        "badges": [],
        "breakdown": {"clarity": None, "action_orientation": None, "engagement": None},
    }
}


def _as_score(value):
    """Coerce a score to a clamped int, or None for anything non-numeric."""
    try:
        if value is None:
            return None
        n = int(round(float(value)))
        return max(0, min(100, n))
    except (TypeError, ValueError):
        return None


def _normalize(data: dict) -> dict:
    """Force the parsed payload into the exact shape the app stores — score/breakdown
    numeric-or-null, badges a list — so a creative model can't leak a string score."""
    hs = data.get("health_score") or {}
    bd = hs.get("breakdown") or {}
    return {
        "health_score": {
            "score": _as_score(hs.get("score")),
            "verdict": str(hs.get("verdict") or ""),
            "improvement_tip": str(hs.get("improvement_tip") or ""),
            "badges": [str(b) for b in (hs.get("badges") or []) if b],
            "breakdown": {
                "clarity": _as_score(bd.get("clarity")),
                "action_orientation": _as_score(bd.get("action_orientation")),
                "engagement": _as_score(bd.get("engagement")),
            },
        }
    }


async def run(transcript: str, context: dict = {}) -> dict:
    user_content = f"Transcript:\n{transcript}"

    if context:
        parts = []
        mt = context.get("meeting_type")
        if mt:
            parts.append(f"Meeting type (classified): {mt}")
        hs_count = context.get("human_speakers")
        wc = context.get("word_count")
        if hs_count is not None:
            parts.append(
                f"Human speakers: {hs_count} (the AI assistant's own lines are not a participant)"
            )
        if wc:
            parts.append(f"Transcript length: ~{wc} words")
        sentiment = context.get("sentiment") or {}
        if sentiment.get("overall"):
            parts.append(
                f"Pre-analyzed sentiment: {sentiment['overall']} (score: {sentiment.get('score', 'N/A')}/100)"
            )
            # Ground the 'Unresolved Tension' badge in sentiment's actual analysis
            # so health doesn't contradict it.
            tensions = sentiment.get("tension_moments") or []
            if tensions:
                carried = sum(1 for t in tensions if isinstance(t, dict) and t.get("status") == "carried_over")
                if carried:
                    parts.append(f"Tension: {carried} of {len(tensions)} tension moment(s) were left UNRESOLVED (carried over).")
                else:
                    parts.append(f"Tension: all {len(tensions)} tension moment(s) were RESOLVED within the meeting.")
        action_items = context.get("action_items")
        if action_items:
            parts.append(f"Action items extracted: {len(action_items)}")
        decisions = context.get("decisions")
        if decisions:
            parts.append(f"Decisions made: {len(decisions)}")
        if parts:
            user_content = "\n".join(parts) + "\n\n---\n\n" + user_content

    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_content, temperature=0.1)
            return _normalize(json.loads(strip_fences(raw)))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

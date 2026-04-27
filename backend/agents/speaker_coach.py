import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a speaker coaching analyst. Read the transcript (lines in 'Speaker: text' format) "
    "and produce speaker-level stats and constructive coaching insights. "
    "For each named speaker calculate: "
    "word_count (count of their words across all their lines), "
    "talk_percent (their share of total words, 0-100 int, all speakers must sum to 100), "
    "decisions_owned (count of decisions explicitly attributed to them or that they agreed to own), "
    "action_items_owned (count of tasks they volunteered for or were assigned), "
    "coaching_note (1 sentence — constructive, specific advice on participation balance, ownership, or listening). "
    "balance_score: 100 if all speakers talked equally, 0 if one person spoke entirely "
    "(use: 100 minus the Gini coefficient of talk_percents scaled to 0-100). "
    'Return ONLY valid JSON: { "speaker_coach": { "speakers": [...], "balance_score": 0 } }. '
    "If fewer than 2 named speakers appear in the transcript, return: "
    '{ "speaker_coach": { "speakers": [], "balance_score": 100 } }'
)

_DEFAULT = {"speaker_coach": {"speakers": [], "balance_score": 100}}


async def run(transcript: str) -> dict:
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, f"Transcript:\n{transcript}")
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

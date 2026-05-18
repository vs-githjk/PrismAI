import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You are a meeting dynamics analyst. Characterize how this meeting actually felt — "
    "not just whether it was 'positive' or 'negative'. Commit to a label that names a real "
    "pattern in the transcript. Default to the strongest signal you observe. Only use "
    "'neutral' when the transcript truly contains no tonal signal across content and dynamics — "
    "most meetings are not neutral.\n\n"
    "Vocabulary for `overall` (pick exactly one):\n"
    "- collaborative: speakers build on each other's ideas; ownership is shared; energy is open\n"
    "- aligned: strong consensus; shared direction; agreement is loud\n"
    "- decision-making: focused, action-oriented; choices being committed to\n"
    "- exploratory: open-ended brainstorming; productive uncertainty\n"
    "- frictional: disagreement is surfaced; pushback or tension that may or may not resolve\n"
    "- divergent: speakers pulling in different directions; no agreement reached\n"
    "- rushed: short on time; surface-level coverage; items deferred or skipped\n"
    "- draining: low energy; one-sided; unproductive; going in circles\n"
    "- neutral: genuinely informational/routine; no clear dynamic — use only when other labels do not fit\n\n"
    "Signals to anchor your judgment (cite what you actually see in `notes` and `tension_moments`):\n"
    "- Hedging language ('I think maybe', 'kind of') vs assertion ('we will')\n"
    "- Interruptions or talking over each other\n"
    "- Repeated questions that go unanswered\n"
    "- Enthusiasm markers ('yes!', 'great point') vs flat acknowledgments\n"
    "- One speaker dominating word share (see Talk distribution input below)\n"
    "- Decisions being committed to vs deferred\n\n"
    "Return ONLY valid JSON matching this exact shape:\n"
    '{ "sentiment": { '
    '"overall": "<one label from vocabulary>", '
    '"score": 0-100, '
    '"arc": "improving|stable|declining|unresolved", '
    '"notes": "1-2 sentence summary citing specific speakers or moments", '
    '"speakers": [ { "name": "string", "tone": "collaborative|neutral|resistant|frustrated|enthusiastic|reserved", "score": 0-100 } ], '
    '"tension_moments": ["string", ...] } }\n\n'
    "Rules:\n"
    "- score: 100 = highly productive/positive dynamic; 50 = neutral; 0 = highly unproductive/tense\n"
    "- arc: did the meeting's energy improve, stay stable, decline, or end unresolved?\n"
    "- speakers: one entry per identified speaker; tone reflects their individual participation pattern\n"
    "- tension_moments: 0-3 specific moments where tone shifted or conflict surfaced. Each must name a speaker and what happened. Empty array if truly none.\n"
    "- notes: anchor in evidence — name specific speakers or specific moments. Do not generalize."
)


_DEFAULT = {"sentiment": None}


def _compute_talk_distribution(transcript: str) -> str:
    """Parse 'Speaker: text' lines and return a compact distribution like 'Mike 45%, Sarah 30%, ...'.
    This gives the LLM hard evidence to anchor 'draining' (one dominator) or 'collaborative' (balanced) labels."""
    speakers: dict[str, int] = {}
    for raw_line in transcript.split("\n"):
        line = raw_line.strip()
        if ":" not in line:
            continue
        head, body = line.split(":", 1)
        name = head.strip()
        # Heuristic for a speaker name: short, no sentence-end punctuation
        if not name or len(name) > 40 or any(c in name for c in ".?!"):
            continue
        words = body.split()
        if words:
            speakers[name] = speakers.get(name, 0) + len(words)
    total = sum(speakers.values())
    if total == 0:
        return "Unable to parse speaker turns from transcript format."
    parts = sorted(speakers.items(), key=lambda x: -x[1])[:8]
    return ", ".join(f"{name} {round(w / total * 100)}%" for name, w in parts)


async def run(transcript: str) -> dict:
    talk_dist = _compute_talk_distribution(transcript)
    user_msg = f"Talk distribution: {talk_dist}\n\nTranscript:\n{transcript}"
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_msg)
            return json.loads(strip_fences(raw))
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

"""Deep content-analysis agent (Tier 2).

For pitch / interview meetings the standard working-meeting agents (action items,
decisions, health score) are the wrong lens — a pitch has no "action items" and the
health-score triangle (clarity/engagement/action) unfairly tanks a strong one-way
presentation. This agent applies a type-specific rubric and emits its OWN headline
score that the UI shows in place of the health ring for these meetings.

Standard meetings early-return with no LLM call, so the common path pays nothing.
"""

import json
from .utils import strip_fences, llm_call

# Per-type rubric config. `dimensions` seed the model; it scores each 0-100 with a
# short note + supporting quote. `score_label`/`type_label` drive the UI headline.
RUBRICS = {
    "pitch": {
        "type_label": "Pitch / Presentation",
        "score_label": "Pitch strength",
        "role": "a pitch and presentation coach",
        "dimensions": [
            "Value proposition clarity — is the core idea and who-it's-for unmistakable",
            "Structure & flow — problem → solution → evidence → ask, in a logical arc",
            "Persuasiveness & evidence — proof, data, examples, and credibility that make it land",
            "The ask — is there a clear, specific call to action / next step",
            "Delivery & pacing — concision, filler, confidence, and momentum",
        ],
    },
    "interview_content": {
        "type_label": "Content Interview",
        "score_label": "Interview quality",
        "role": "an editorial interview coach analyzing a research/podcast interview",
        "dimensions": [
            "Question quality — open, sharp, and well-sequenced questions",
            "Follow-up & probing — did the host dig deeper on interesting threads",
            "Substance extracted — how much insight, story, or expertise the guest revealed",
            "Narrative arc — does the conversation build and cover the ground it should",
            "Balance & flow — the host draws the guest out without dominating",
        ],
    },
    "interview_job": {
        "type_label": "Job Interview",
        "score_label": "Candidate readiness",
        "role": "a hiring interview evaluator assessing the CANDIDATE",
        "dimensions": [
            "Communication — clear, structured, concise answers",
            "Competence & role knowledge — demonstrated skill and depth for the role",
            "Specificity & examples (STAR) — concrete situations, actions, and measurable results",
            "Problem-solving — reasoning, structure, and how they work through questions",
            "Confidence & composure — poise, ownership, and handling of hard questions",
            "Role fit & motivation — alignment with the role and genuine interest",
        ],
    },
}


def _build_prompt(cfg: dict) -> str:
    dims = "\n".join(f"  - {d}" for d in cfg["dimensions"])
    return (
        f"You are {cfg['role']}. Give a rigorous, specific, evidence-grounded breakdown. "
        "Be candid — praise what works, name what doesn't, and cite the transcript. "
        "Score each dimension 0-100 and compute a single headline score (a weighted sense "
        "of the whole, NOT a rote average — the most important dimensions matter more).\n\n"
        f"Score these dimensions:\n{dims}\n\n"
        "For each dimension give: a 0-100 score, a ONE-sentence note (concrete, actionable), "
        "and a short supporting quote from the transcript (evidence — empty string if none fits). "
        "Then give overall strengths, weaknesses, and up to 4 key moments (a labelled turning "
        "point with a quote and why it mattered — strong or weak). Keep every string tight.\n\n"
        "CRITICAL: respond with ONLY the raw JSON object — no markdown fences, no commentary, "
        "no text before the opening brace or after the closing brace:\n"
        "{\n"
        f'  "type_label": "{cfg["type_label"]}",\n'
        f'  "score_label": "{cfg["score_label"]}",\n'
        '  "headline_score": 0,\n'
        '  "verdict": "1-2 sentence overall assessment",\n'
        '  "rubric": [{ "dimension": "short name", "score": 0, "notes": "…", "evidence": "quote or empty" }],\n'
        '  "strengths": ["…"],\n'
        '  "weaknesses": ["…"],\n'
        '  "key_moments": [{ "label": "…", "quote": "…", "note": "why it mattered" }]\n'
        "}"
    )


def _clamp_score(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except Exception:
        return 0


def _parse_json(raw: str) -> dict:
    """Parse the model's JSON, tolerating prose the model sometimes wraps around
    it (leading 'Here is…' or trailing markdown commentary → json.loads 'Extra
    data'). Falls back to slicing the outermost {...} object."""
    txt = strip_fences(raw)
    try:
        return json.loads(txt)
    except Exception:
        start, end = txt.find("{"), txt.rfind("}")
        if start != -1 and end > start:
            return json.loads(txt[start:end + 1])
        raise


async def run(transcript: str, context: dict | None = None) -> dict:
    context = context or {}
    mtype = str(context.get("meeting_type", "standard")).strip().lower()

    # Common path: a normal working meeting needs no deep-dive — return the type
    # marker only, with NO LLM call.
    if mtype not in RUBRICS:
        return {"content_analysis": {"type": "standard"}}

    cfg = RUBRICS[mtype]
    system = _build_prompt(cfg)
    for attempt in range(2):
        try:
            raw = await llm_call(system, f"Transcript:\n{transcript}")
            data = _parse_json(raw)
            rubric = []
            for row in (data.get("rubric") or [])[:8]:
                rubric.append({
                    "dimension": str(row.get("dimension", ""))[:80],
                    "score": _clamp_score(row.get("score")),
                    "notes": str(row.get("notes", ""))[:400],
                    "evidence": str(row.get("evidence", ""))[:300],
                })
            moments = []
            for m in (data.get("key_moments") or [])[:4]:
                moments.append({
                    "label": str(m.get("label", ""))[:80],
                    "quote": str(m.get("quote", ""))[:300],
                    "note": str(m.get("note", ""))[:300],
                })
            return {"content_analysis": {
                "type": mtype,
                "type_label": data.get("type_label") or cfg["type_label"],
                "score_label": data.get("score_label") or cfg["score_label"],
                "headline_score": _clamp_score(data.get("headline_score")),
                "verdict": str(data.get("verdict", ""))[:500],
                "rubric": rubric,
                "strengths": [str(s)[:300] for s in (data.get("strengths") or [])[:6]],
                "weaknesses": [str(w)[:300] for w in (data.get("weaknesses") or [])[:6]],
                "key_moments": moments,
            }}
        except Exception:
            if attempt == 1:
                # Signal type so the UI can still badge it, without a broken card.
                return {"content_analysis": {"type": mtype, "type_label": cfg["type_label"],
                                             "score_label": cfg["score_label"], "headline_score": 0,
                                             "verdict": "", "rubric": [], "strengths": [],
                                             "weaknesses": [], "key_moments": []}}
    return {"content_analysis": {"type": mtype}}

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents import (
    action_items,
    calendar_suggester,
    decisions,
    email_drafter,
    health_score,
    orchestrator,
    sentiment,
    speaker_coach,
    summarizer,
)


AGENT_MAP = {
    "summarizer": summarizer.run,
    "action_items": action_items.run,
    "decisions": decisions.run,
    "sentiment": sentiment.run,
    "email_drafter": email_drafter.run,
    "calendar_suggester": calendar_suggester.run,
    "health_score": health_score.run,
    "speaker_coach": speaker_coach.run,
}

TIER1_AGENTS = frozenset({"summarizer", "decisions", "action_items", "sentiment", "speaker_coach"})
TIER2_AGENTS = frozenset({"email_drafter", "health_score", "calendar_suggester"})

DEFAULT_RESULT = {
    "title": "",
    "summary": "",
    "action_items": [],
    "decisions": [],
    "sentiment": {"overall": "neutral", "score": 50, "arc": "stable", "notes": "", "speakers": [], "tension_moments": []},
    "follow_up_email": {"subject": "", "body": ""},
    "calendar_suggestion": {"recommended": False, "reason": "", "suggested_timeframe": "", "resolved_date": "", "resolved_day": ""},
    "health_score": {"score": 0, "verdict": "", "badges": [], "breakdown": {"clarity": 0, "action_orientation": 0, "engagement": 0}},
    "speaker_coach": {"speakers": [], "balance_score": 100},
    "agents_run": [],
}

AGENT_RESULT_KEY = {
    "summarizer": "summary",
    "action_items": "action_items",
    "decisions": "decisions",
    "sentiment": "sentiment",
    "email_drafter": "follow_up_email",
    "calendar_suggester": "calendar_suggestion",
    "health_score": "health_score",
    "speaker_coach": "speaker_coach",
}


class AnalysisState(TypedDict):
    transcript: str
    agents_to_run: list[str]
    results: Annotated[dict, operator.or_]
    context: dict


def build_analysis_transcript(transcript: str, speakers: list | None = None, owner_name: str | None = None) -> str:
    speakers = speakers or []
    lines = []
    if owner_name and owner_name.strip():
        lines.append(f"[Meeting owner: {owner_name.strip()}]")
    if speakers:
        lines.append("Meeting participants:")
        for speaker in speakers:
            name = (speaker.get("name") or "").strip()
            role = (speaker.get("role") or "").strip()
            if name:
                lines.append(f"  - {name}: {role}" if role else f"  - {name}")
    if not lines:
        return transcript
    return "\n".join(lines) + "\n\n" + transcript


# ── Graph nodes ────────────────────────────────────────────────────

async def _orchestrator_node(state: AnalysisState) -> dict:
    agents = await orchestrator.run_orchestrator(state["transcript"])
    return {"agents_to_run": [a for a in agents if a in AGENT_MAP]}


def _route_tier1(state: AnalysisState) -> list[Send] | str:
    tier1 = [a for a in state["agents_to_run"] if a in TIER1_AGENTS]
    if not tier1:
        return "tier1_barrier"
    return [Send(f"t1_{a}", state) for a in tier1]


def _make_tier1_node(agent_name: str):
    async def node(state: AnalysisState) -> dict:
        try:
            result = await AGENT_MAP[agent_name](state["transcript"])
        except Exception:
            result = {}
        return {"results": {agent_name: result}}
    return node


async def _tier1_barrier(state: AnalysisState) -> dict:
    r = state.get("results", {})
    return {
        "context": {
            "summary": r.get("summarizer", {}).get("summary", ""),
            "decisions": r.get("decisions", {}).get("decisions", []),
            "action_items": r.get("action_items", {}).get("action_items", []),
            "sentiment": r.get("sentiment", {}).get("sentiment", {}),
        }
    }


def _route_tier2(state: AnalysisState) -> list[Send] | str:
    tier2 = [a for a in state["agents_to_run"] if a in TIER2_AGENTS]
    if not tier2:
        return END
    return [Send(f"t2_{a}", state) for a in tier2]


def _make_tier2_node(agent_name: str):
    async def node(state: AnalysisState) -> dict:
        try:
            result = await AGENT_MAP[agent_name](state["transcript"], state.get("context", {}))
        except Exception:
            result = {}
        return {"results": {agent_name: result}}
    return node


# ── Graph construction ─────────────────────────────────────────────

def _build_graph():
    g = StateGraph(AnalysisState)

    g.add_node("orchestrator", _orchestrator_node)
    g.add_conditional_edges("orchestrator", _route_tier1)

    for name in TIER1_AGENTS:
        g.add_node(f"t1_{name}", _make_tier1_node(name))
        g.add_edge(f"t1_{name}", "tier1_barrier")

    g.add_node("tier1_barrier", _tier1_barrier)
    g.add_conditional_edges("tier1_barrier", _route_tier2)

    for name in TIER2_AGENTS:
        g.add_node(f"t2_{name}", _make_tier2_node(name))
        g.add_edge(f"t2_{name}", END)

    g.add_edge(START, "orchestrator")
    return g.compile()


_GRAPH = _build_graph()


# ── Result assembly ────────────────────────────────────────────────

def _state_to_result(state: AnalysisState) -> dict:
    result = dict(DEFAULT_RESULT)
    succeeded = []
    raw = state.get("results", {})

    sr = raw.get("summarizer", {})
    if sr.get("title") or sr.get("summary"):
        result["title"] = sr.get("title", "")
        result["summary"] = sr.get("summary", "")
        succeeded.append("summarizer")

    ar = raw.get("action_items", {})
    if ar.get("action_items") is not None:
        result["action_items"] = ar["action_items"]
        succeeded.append("action_items")

    dr = raw.get("decisions", {})
    if dr.get("decisions") is not None:
        result["decisions"] = dr["decisions"]
        succeeded.append("decisions")

    sentr = raw.get("sentiment", {})
    if sentr.get("sentiment"):
        result["sentiment"] = sentr["sentiment"]
        succeeded.append("sentiment")

    er = raw.get("email_drafter", {})
    if er.get("follow_up_email"):
        result["follow_up_email"] = er["follow_up_email"]
        succeeded.append("email_drafter")

    cr = raw.get("calendar_suggester", {})
    if cr.get("calendar_suggestion"):
        result["calendar_suggestion"] = cr["calendar_suggestion"]
        succeeded.append("calendar_suggester")

    hr = raw.get("health_score", {})
    if hr.get("health_score"):
        result["health_score"] = hr["health_score"]
        succeeded.append("health_score")

    scr = raw.get("speaker_coach", {})
    if scr.get("speaker_coach"):
        result["speaker_coach"] = scr["speaker_coach"]
        succeeded.append("speaker_coach")

    result["agents_run"] = succeeded
    return result


async def run_full_analysis(transcript: str) -> dict:
    final_state = await _GRAPH.ainvoke(
        {"transcript": transcript, "agents_to_run": [], "results": {}, "context": {}}
    )
    return _state_to_result(final_state)

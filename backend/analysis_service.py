import operator
import os
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents import (
    action_items,
    calendar_suggester,
    decision_linker,
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

# Tier-2 agents that don't need the full transcript — they synthesize from
# context (summary + decisions + action_items + sentiment) which tier-1 has
# already produced. The token saving per meeting is roughly transcript_tokens
# × len(this set). health_score and calendar_suggester are NOT here because
# they read transcript-specific signal (engagement patterns, date mentions).
TIER2_CONTEXT_ONLY = frozenset({"email_drafter"})

# Per-agent allowlist of personas. Structured-output agents (decisions,
# action_items, sentiment, scores) are restricted to register-only presets
# (default/concise/formal) so 'cheeky' or 'socratic' tone can't distort the
# data model (e.g., action items phrased as questions). Free-text agents
# (summarizer, email_drafter) take any preset including custom.
AGENT_PERSONA_WHITELIST: dict[str, set[str]] = {
    "summarizer":         {"default", "concise", "formal", "cheeky", "socratic", "custom"},
    "decisions":          {"default", "concise", "formal"},
    "action_items":       {"default", "concise", "formal"},
    "sentiment":          {"default", "concise", "formal"},
    "speaker_coach":      {"default", "concise", "formal"},
    "email_drafter":      {"default", "concise", "formal", "cheeky", "socratic", "custom"},
    "health_score":       {"default", "concise", "formal"},
    "calendar_suggester": {"default", "concise", "formal"},
}


def _persona_text_for_agent(agent_name: str, state: "AnalysisState") -> str:
    """Resolve the persona text to inject for this specific agent, honoring
    AGENT_PERSONA_WHITELIST. Returns empty string when:
      - no persona_preset in state
      - preset is 'default'
      - preset is not in the agent's whitelist (silent fallback)
      - preset is 'custom' but persona_custom_prompt is empty
    """
    from personas import PRESETS  # local import to avoid module-load cycle

    preset = state.get("persona_preset") or "default"
    if preset == "default":
        return ""
    if preset not in AGENT_PERSONA_WHITELIST.get(agent_name, set()):
        return ""
    if preset == "custom":
        return (state.get("persona_custom_prompt") or "").strip()
    return PRESETS.get(preset, "")


def _email_from_context_on() -> bool:
    """Read at call time so tests can flip the flag mid-run."""
    return os.getenv("PRISM_EMAIL_FROM_CONTEXT", "1") == "1"


DEFAULT_RESULT = {
    "title": "",
    "tldr": "",
    "summary": "",
    "topics": [],
    "action_items": [],
    "decisions": [],
    "sentiment": {"overall": "neutral", "score": 50, "arc": "stable", "notes": "", "speakers": [], "tension_moments": []},
    "follow_up_email": {"subject": "", "body": ""},
    "calendar_suggestion": {"recommended": False, "reason": "", "suggested_timeframe": "", "suggested_time": "", "agenda": [], "attendees": [], "resolved_date": "", "resolved_day": "", "resolved_time": ""},
    "health_score": {"score": 0, "verdict": "", "improvement_tip": "", "badges": [], "breakdown": {"clarity": 0, "action_orientation": 0, "engagement": 0}},
    "speaker_coach": {"speakers": [], "balance_score": 100},
    "decision_links": [],
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
    "decision_linker": "decision_links",
}


class AnalysisState(TypedDict, total=False):
    transcript: str
    agents_to_run: list[str]
    results: Annotated[dict, operator.or_]
    context: dict
    persona_preset: str           # 'default' | 'concise' | 'formal' | 'cheeky' | 'socratic' | 'custom'
    persona_custom_prompt: str    # only when persona_preset == 'custom'


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
    # Routing is now deterministic (no LLM call) — see agents/orchestrator.py.
    agents = orchestrator.run_orchestrator(state["transcript"] or "")
    return {"agents_to_run": [a for a in agents if a in AGENT_MAP]}


def _route_tier1(state: AnalysisState) -> list[Send] | str:
    tier1 = [a for a in state["agents_to_run"] if a in TIER1_AGENTS]
    if not tier1:
        return "tier1_barrier"
    return [Send(f"t1_{a}", state) for a in tier1]


def _make_tier1_node(agent_name: str):
    async def node(state: AnalysisState) -> dict:
        from agents.utils import _PERSONA_TEXT
        token = _PERSONA_TEXT.set(_persona_text_for_agent(agent_name, state))
        try:
            result = await AGENT_MAP[agent_name](state["transcript"])
        except Exception:
            result = {}
        finally:
            _PERSONA_TEXT.reset(token)
        return {"results": {agent_name: result}}
    return node


async def _tier1_barrier(state: AnalysisState) -> dict:
    r = state.get("results", {})
    decisions_list = r.get("decisions", {}).get("decisions", [])
    action_items_list = r.get("action_items", {}).get("action_items", [])

    # Decision↔action linker runs here (between tiers) so its output can both
    # enrich the Tier-2 context (calendar uses unactioned decisions) and stream
    # to the UI. Only fires when there's something to link.
    if decisions_list and action_items_list:
        link_out = await decision_linker.run(decisions_list, action_items_list)
    else:
        link_out = {"decision_links": [], "unactioned_decisions": []}

    unactioned_texts = [
        decisions_list[i].get("decision", "")
        for i in link_out.get("unactioned_decisions", [])
        if 0 <= i < len(decisions_list)
    ]

    # Surface the meeting owner (parsed from the transcript header set by
    # build_analysis_transcript) into the Tier-2 context. email_drafter runs
    # context-only (no transcript), so without this it can't know whose voice to
    # write the follow-up FROM — critical for stand-in meetings, where the bot spoke
    # for the owner and the only human name in the transcript is the OTHER attendee.
    owner_m = re.match(r"\[Meeting owner:\s*([^\]]+)\]", state.get("transcript", "") or "")
    owner_name = owner_m.group(1).strip() if owner_m else ""

    return {
        "results": {"decision_linker": link_out},
        "context": {
            "summary": r.get("summarizer", {}).get("summary", ""),
            "decisions": decisions_list,
            "action_items": action_items_list,
            "sentiment": r.get("sentiment", {}).get("sentiment", {}),
            "unactioned_decisions": unactioned_texts,
            "owner_name": owner_name,
        },
    }


def _route_tier2(state: AnalysisState) -> list[Send] | str:
    tier2 = [a for a in state["agents_to_run"] if a in TIER2_AGENTS]
    if not tier2:
        return END
    return [Send(f"t2_{a}", state) for a in tier2]


def _make_tier2_node(agent_name: str):
    async def node(state: AnalysisState) -> dict:
        from agents.utils import _PERSONA_TEXT
        token = _PERSONA_TEXT.set(_persona_text_for_agent(agent_name, state))
        try:
            ctx = state.get("context", {})
            # Token efficiency: agents in TIER2_CONTEXT_ONLY synthesize from
            # tier-1's output (summary + decisions + action_items + sentiment)
            # rather than re-reading the full transcript. Saves transcript-sized
            # tokens per such agent. Flag-gated so quality regressions can be
            # rolled back without redeploy.
            if agent_name in TIER2_CONTEXT_ONLY and _email_from_context_on():
                transcript_in = ""
            else:
                transcript_in = state["transcript"]
            result = await AGENT_MAP[agent_name](transcript_in, ctx)
        except Exception:
            result = {}
        finally:
            _PERSONA_TEXT.reset(token)
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
        result["tldr"] = sr.get("tldr", "")
        result["summary"] = sr.get("summary", "")
        result["topics"] = sr.get("topics", []) or []
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

    dlr = raw.get("decision_linker", {})
    if dlr.get("decision_links") is not None:
        result["decision_links"] = dlr["decision_links"]

    result["agents_run"] = succeeded
    return result


async def run_full_analysis(
    transcript: str,
    persona_preset: str | None = None,
    persona_custom_prompt: str | None = None,
) -> dict:
    initial: dict = {
        "transcript": transcript,
        "agents_to_run": [],
        "results": {},
        "context": {},
    }
    if persona_preset:
        initial["persona_preset"] = persona_preset
    if persona_custom_prompt:
        initial["persona_custom_prompt"] = persona_custom_prompt
    final_state = await _GRAPH.ainvoke(initial)
    return _state_to_result(final_state)

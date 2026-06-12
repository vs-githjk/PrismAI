import json
from .utils import strip_fences, llm_call

SYSTEM_PROMPT = (
    "You link meeting decisions to the action items that carry them out. "
    "You are given a numbered list of DECISIONS and a numbered list of ACTION ITEMS.\n"
    "For each decision, identify which action items (if any) implement, execute, or directly "
    "follow through on it. An action item links to a decision if doing it carries out that "
    "decision. An action may link to one decision or none; a decision may have several actions "
    "or none.\n"
    'Return ONLY valid JSON: { "decision_links": [ { "decision": <index>, "actions": [<index>, ...] } ] }. '
    "Include exactly ONE entry per decision, in order, using the exact indices shown. "
    "Use an empty actions array for a decision with no follow-through. Never invent indices."
)

_EMPTY = {"decision_links": [], "unactioned_decisions": []}


async def run(decisions: list, action_items: list) -> dict:
    """Map decisions → the action items that execute them. Returns
    {decision_links: [{decision, actions}], unactioned_decisions: [decision_index]}.
    Indices reference the ORIGINAL order of the passed lists (frontend re-sorts
    copies but keeps original order, so indices stay valid)."""
    if not decisions or not action_items:
        return dict(_EMPTY)

    dec_text = "\n".join(f"[{i}] {d.get('decision', str(d))}" for i, d in enumerate(decisions))
    act_text = "\n".join(
        f"[{i}] {a.get('task', str(a))} (owner: {a.get('owner', 'Unassigned')})"
        for i, a in enumerate(action_items)
    )
    user_content = f"DECISIONS:\n{dec_text}\n\nACTION ITEMS:\n{act_text}"

    n_dec, n_act = len(decisions), len(action_items)
    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_content, temperature=0.1)
            payload = json.loads(strip_fences(raw))
            # Merge by decision index (dedupe duplicate entries, union actions).
            merged: dict[int, set] = {}
            for entry in payload.get("decision_links", []) or []:
                di = entry.get("decision")
                if not isinstance(di, int) or not (0 <= di < n_dec):
                    continue  # drop hallucinated decision indices
                bucket = merged.setdefault(di, set())
                for a in (entry.get("actions") or []):
                    if isinstance(a, int) and 0 <= a < n_act:
                        bucket.add(a)
            clean = [{"decision": di, "actions": sorted(acts)} for di, acts in sorted(merged.items())]
            # Only decisions the linker explicitly returned with zero actions are
            # "unactioned" — omissions are not treated as unactioned (avoids false alarms).
            unactioned = [e["decision"] for e in clean if not e["actions"]]
            return {"decision_links": clean, "unactioned_decisions": unactioned}
        except Exception:
            if attempt == 1:
                return dict(_EMPTY)
    return dict(_EMPTY)

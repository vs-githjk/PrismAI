"""Tier-2 'action_executor' agent — turns the meeting owner's OWN action items into
ready-to-run, one-click actions (a draft email, a calendar event, a tracker ticket,
a chat post). It only PREPARES: each suggestion carries a fully pre-filled, editable
payload that the user approves before anything touches an external system (approve-
first — see SuggestedActions card in the frontend). It never sends/files on its own.

Design notes:
- Owner-scoped: only items the meeting owner owns become suggestions (the bot works
  on YOUR plate, not everyone's). When no owner is known (e.g. a pasted transcript),
  every actionable item is a candidate and `owned` is left true.
- Tool-type, not tool-instance: the agent picks an action_type (email/calendar/task/
  chat); the frontend resolves task→Jira-or-Linear and chat→Slack-or-Teams based on
  what the user actually has connected, and greys out unconnected ones.
- Names, not emails: like the other agents it never guesses email addresses — it names
  recipients; the card resolves them from the attendee-suggestion chips.
"""
import json
from .utils import strip_fences, llm_call


SYSTEM_PROMPT = (
    "You are an executive assistant that turns a meeting's action items into ready-to-run actions. "
    "For each action item OWNED BY THE MEETING OWNER that can be carried out with a tool, prepare a "
    "fully drafted, one-click action the owner can approve. Do the actual work (write the email, draft "
    "the message, compose the ticket) — not a description of it.\n\n"
    "Available action types:\n"
    "- email: the item is 'send / follow up with / share / email <someone> ...'. Draft a real subject + body.\n"
    "- calendar: the item is 'schedule / book / set up a meeting/call with ...'. Give an event title + timing.\n"
    "- task: the item is 'file / create a ticket / log a bug / track ...'. Write a PROPER Jira-style ticket: a "
    "clear title, then a 'body' that follows this exact structure with these literal section headings:\n"
    "    Context:\n    <1-2 sentences of background from the meeting — why this ticket exists>\n"
    "    Details:\n    - <specific point>\n    - <specific point>\n"
    "    Acceptance Criteria:\n    - <a concrete, checkable condition for 'done'>\n    - <another>\n"
    "  Ground every point in what was actually said; do not invent scope. Keep it detailed but real.\n"
    "- chat: the item is 'post / message / update the team/channel ...'. Write the message.\n"
    "Skip items that need no tool (e.g. 'think about X', 'review the doc yourself') — do not emit them.\n\n"
    "Return ONLY valid JSON in this exact shape:\n"
    '{ "suggested_actions": [ {\n'
    '  "task": "the original action item text, verbatim",\n'
    '  "owner": "the owner string from the item",\n'
    '  "action_type": "email|calendar|task|chat",\n'
    '  "title": "subject (email) / event title (calendar) / issue title (task) / short label (chat)",\n'
    '  "body": "the drafted email body / message / issue description — real, complete, ready to send",\n'
    '  "recipients": ["names of the people involved — NEVER email addresses, names only"],\n'
    '  "when": "natural-language timing for calendar items, e.g. \'next Tuesday at 3pm\' — empty otherwise",\n'
    '  "confidence": 0.0,\n'
    '  "rationale": "one short clause: why this action carries out the item"\n'
    "} ] }\n"
    "Rules:\n"
    "- Only the OWNER's items. If an [Meeting owner: NAME] is given, an item counts as the owner's when its "
    "owner name matches NAME (allow partial/first-name matches). If NO owner is given, treat every actionable item as a candidate.\n"
    "- If a '[Meeting owner: NAME]' line is present, write emails/messages FROM that person (their voice, signed by them).\n"
    "- Ground every draft in what the meeting actually decided — do not invent commitments, names, or numbers.\n"
    "- recipients are NAMES only, drawn from the meeting. Never fabricate an email address.\n"
    "- confidence reflects how clearly the item maps to the action (1.0 = explicit 'email Jane the deck', 0.4 = a stretch).\n"
    "- If nothing is executable, return an empty list."
)


_DEFAULT = {"suggested_actions": []}

_ALLOWED_TYPES = {"email", "calendar", "task", "chat"}


def _build_user_content(transcript: str, context: dict) -> str:
    parts: list[str] = []
    owner = (context.get("owner_name") or "").strip()
    if owner:
        parts.append(f"[Meeting owner: {owner}]")
    if context.get("summary"):
        parts.append(f"Meeting summary:\n{context['summary']}")
    items = [a for a in (context.get("action_items") or []) if not a.get("completed")]
    if items:
        items_text = "\n".join(
            f"- {a.get('task', str(a))} (owner: {a.get('owner', 'Unassigned')}, due: {a.get('due', 'n/a')})"
            for a in items
        )
        parts.append(f"Action items:\n{items_text}")
    if context.get("decisions"):
        decisions_text = "\n".join(
            f"- {d.get('decision', str(d)) if isinstance(d, dict) else d}" for d in context["decisions"]
        )
        parts.append(f"Decisions:\n{decisions_text}")
    if transcript:
        parts.append(f"Transcript:\n{transcript}")
    return "\n\n---\n\n".join(parts) if parts else "No action items."


def _clean(actions: list, owner: str) -> list:
    """Validate + normalise the model's output; drop malformed/non-executable rows."""
    cleaned = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        atype = (a.get("action_type") or "").strip().lower()
        task = (a.get("task") or "").strip()
        if atype not in _ALLOWED_TYPES or not task:
            continue
        recipients = a.get("recipients") or []
        if not isinstance(recipients, list):
            recipients = [str(recipients)]
        try:
            conf = float(a.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        cleaned.append({
            "task": task,
            "owner": (a.get("owner") or owner or "").strip(),
            "action_type": atype,
            "title": (a.get("title") or "").strip(),
            "body": (a.get("body") or "").strip(),
            "recipients": [str(r).strip() for r in recipients if str(r).strip()],
            "when": (a.get("when") or "").strip(),
            "confidence": max(0.0, min(1.0, conf)),
            "rationale": (a.get("rationale") or "").strip(),
            "owned": True,
        })
    # Strongest mappings first so the card leads with the obvious wins.
    cleaned.sort(key=lambda x: -x["confidence"])
    return cleaned


async def run(transcript: str, context: dict = {}) -> dict:
    # Nothing to do if the meeting produced no open action items.
    open_items = [a for a in (context.get("action_items") or []) if not a.get("completed")]
    if not open_items:
        return _DEFAULT

    user_content = _build_user_content(transcript, context)
    owner = (context.get("owner_name") or "").strip()

    for attempt in range(2):
        try:
            raw = await llm_call(SYSTEM_PROMPT, user_content)
            payload = json.loads(strip_fences(raw))
            actions = payload.get("suggested_actions", []) or []
            return {"suggested_actions": _clean(actions, owner)}
        except Exception:
            if attempt == 1:
                return _DEFAULT
    return _DEFAULT

"""Phase 3 — the single home for both channels' prompt assembly.

This module is the concrete realization of the prompt-dissection table in
`developers/voice-agent-build-plan-phase3.md` §3. Every prompt feature that
`_process_command` fused into one system prompt gets an EXPLICIT home here —
voice, agent, or deliberately both. Nothing is silently dropped.

  Feature                         Voice channel        Agent channel
  ──────────────────────────────  ───────────────────  ─────────────────────
  Persona (identity/name/tone)    full                 slim (name/owner facts)
  Spoken style (≤3 sentences)     yes (relaxed)        no (mouth concern)
  Tool policy                     NONE — "to act,      full (the tool loop)
                                  describe the req"
  Gmail/Calendar availability     one-line awareness   authoritative
  Owner email injection           can say it           tool args
  Participant-utterance wrap      yes (non-negotiable) yes (non-negotiable)
  Recent-turn history             full conversational  slim (trigger + ctx)
  Memory snapshot                 yes                  yes
  Static-prefix caching           per-channel prefix   per-channel prefix

Shared logic (injection wrap + history shaping) is imported from `realtime_routes`
so there's exactly ONE implementation — the guard text is safety-critical and must
never fork. The gmail/calendar/tool-policy text for the AGENT channel is likewise
reused verbatim from realtime's `_STATIC_*` (long, carefully tuned) via a lazy import
that avoids an import cycle. The VOICE channel's prompt is genuinely different
(tool-less, dispatch-or-talk) and is written fresh below.
"""

from __future__ import annotations

from typing import Optional

# The token the voice LLM emits (alone, as its whole reply) when the utterance needs
# the agent channel — a tool/action or external/document lookup. The voice channel
# parses this off the stream's first delta and routes the command to the bus instead
# of speaking. Kept short + upper-case so it's unambiguous against conversational text.
DISPATCH_TOKEN = "ACT"


def _shared():
    """Lazy import of realtime_routes — avoids an import cycle (realtime_routes pulls
    in the whole live stack and imports voice.* lazily itself)."""
    import realtime_routes as rr
    return rr


# ── VOICE CHANNEL prompt (tool-less, streaming, conversational) ───────────────

_VOICE_PERSONA_BASE = (
    "You are PrismAI, an AI participant speaking live in this meeting. You are having a "
    "natural spoken conversation — a participant just addressed you. You have the full "
    "meeting memory below; use it to answer anything discussed, however long ago. "
)

# The load-bearing split: the voice channel has NO tools. It either talks, or it hands
# the request to the agent channel by emitting the dispatch token and nothing else.
_VOICE_NO_TOOLS = (
    f"You have NO tools of your own. If — and only if — the participant is asking you to "
    f"DO something that touches an external system (send or draft an email, schedule / "
    f"move / check a calendar event, create a ticket or issue, post to Slack) OR to look "
    f"up current real-world facts (weather, news, scores, prices) or something in the "
    f"user's uploaded documents, then reply with EXACTLY the single word {DISPATCH_TOKEN} "
    f"and nothing else — a colleague will carry it out and I'll report back. "
    f"For everything else — questions about this meeting, general knowledge you already "
    f"have, or plain conversation — just answer directly. Never say {DISPATCH_TOKEN} "
    f"together with other words; it's either {DISPATCH_TOKEN} alone, or a normal reply."
)

_VOICE_STYLE = (
    "Speak concisely and naturally, as if talking. A sentence or two is plenty; the full "
    "detail goes to the chat separately, so you never need to read out long lists or URLs."
)


def _voice_capability_line(has_gmail: bool, has_calendar: bool) -> str:
    """One-line capability awareness so the voice channel can answer 'can you email?'
    without dispatching. Authoritative availability lives on the agent channel."""
    bits = []
    bits.append("email" if has_gmail else "no email")
    bits.append("calendar" if has_calendar else "no calendar")
    if has_gmail or has_calendar:
        return (
            "When asked what you can do: yes, you can " +
            " and ".join(b for b in ("send emails" if has_gmail else "",
                                     "manage the calendar" if has_calendar else "") if b) +
            " (a colleague runs it) — answer in words, don't emit the dispatch token just "
            "to describe a capability. "
        )
    return (
        "You currently have no email or calendar access connected — say so plainly if asked. "
    )


def build_voice_prefix(
    has_gmail: bool,
    has_calendar: bool,
    persona_text: str = "",
    bot_name: str = "",
    owner_name: str = "",
    owner_email: str = "",
) -> str:
    """Cache-stable static system prompt for the voice channel. Mirrors
    `_build_static_prefix`'s caching contract: no per-call values here."""
    rr = _shared()
    parts = [
        _VOICE_PERSONA_BASE,
        _VOICE_NO_TOOLS,
        " ",
        _voice_capability_line(has_gmail, has_calendar),
        _VOICE_STYLE,
    ]
    prefix = "".join(parts)
    if bot_name and bot_name != rr.DEFAULT_BOT_NAME:
        prefix += (
            f"\n\nYour name in this meeting is {bot_name}. When someone addresses you, "
            f"refers to you, or asks who you are, respond as {bot_name}."
        )
    if owner_name:
        prefix += f"\n\nYou are attending on behalf of {owner_name}, who could not attend."
        if owner_email:
            prefix += f" Their email address is {owner_email} if anyone asks."
    # Persona tone rides the cached prefix (same as the fused path).
    from agents.utils import persona_suffix_agentic
    return prefix + persona_suffix_agentic(persona_text)


def build_voice_messages(
    *,
    has_gmail: bool,
    has_calendar: bool,
    now_str: str,
    memory_context: str,
    speaker: str,
    command: str,
    is_owner: bool = True,
    persona_text: str = "",
    bot_name: str = "",
    owner_name: str = "",
    owner_email: str = "",
    recent_turns: Optional[list] = None,
) -> list[dict]:
    """Messages for the voice-channel (talk) LLM call. Full conversational history —
    the voice channel is a conversation, not a job runner."""
    rr = _shared()
    user_content = rr._wrap_participant_utterance(speaker, command, is_owner)
    return [
        {"role": "system", "content": build_voice_prefix(
            has_gmail, has_calendar, persona_text, bot_name, owner_name, owner_email)},
        {"role": "system", "content": f"Current date and time: {now_str}.\n\n{memory_context}"},
        *rr._recent_turn_messages(recent_turns),
        {"role": "user", "content": user_content},
    ]


# ── AGENT CHANNEL prompt (all tools, job runner) ──────────────────────────────

_AGENT_PERSONA_SLIM = (
    "You are PrismAI's action runner for a live meeting. A participant asked for something "
    "that needs a tool. Carry it out and report the outcome in one plain sentence. "
    "You have the meeting memory below for context (recipients, decisions, names). "
)


def build_agent_prefix(
    has_gmail: bool,
    has_calendar: bool,
    persona_text: str = "",
    bot_name: str = "",
    owner_name: str = "",
    owner_email: str = "",
) -> str:
    """Cache-stable static system prompt for the agent channel. Reuses realtime's
    carefully-tuned gmail/calendar/tool-policy text verbatim (the agent channel is the
    heir to the fused tool loop), minus the spoken-style line (a mouth concern)."""
    rr = _shared()
    base = (
        _AGENT_PERSONA_SLIM
        + (rr._STATIC_GMAIL_ON if has_gmail else rr._STATIC_GMAIL_OFF)
        + (rr._STATIC_CALENDAR_ON if has_calendar else rr._STATIC_CALENDAR_OFF)
        + rr._STATIC_TOOL_POLICY
    )
    name_line = ""
    if bot_name and bot_name != rr.DEFAULT_BOT_NAME:
        name_line = f"\n\nYour name in this meeting is {bot_name}."
    owner_line = ""
    if owner_name:
        owner_line = f"\n\nYou are acting on behalf of {owner_name}, who could not attend."
        if owner_email:
            owner_line += (
                f" If asked to email/relay something TO {owner_name} (or 'the owner'/'them'), "
                f"the address is {owner_email}. Use exactly that — never invent one."
            )
        else:
            owner_line += (
                f" You do NOT have {owner_name}'s email — if asked to email them, say so and "
                f"ask for it. Never invent an address."
            )
    from agents.utils import persona_suffix_agentic
    return base + name_line + owner_line + persona_suffix_agentic(persona_text)


def build_agent_messages(
    *,
    has_gmail: bool,
    has_calendar: bool,
    now_str: str,
    memory_context: str,
    speaker: str,
    command: str,
    is_owner: bool = True,
    persona_text: str = "",
    bot_name: str = "",
    owner_name: str = "",
    owner_email: str = "",
    recent_turns: Optional[list] = None,
    image_urls: Optional[list] = None,
) -> list[dict]:
    """Messages for the agent-channel tool-loop LLM call. Slim history — the agent is a
    job runner, so it gets the triggering command plus minimal context, not the full chat."""
    rr = _shared()
    user_content = rr._wrap_participant_utterance(speaker, command, is_owner)
    imgs = [u for u in (image_urls or []) if u][:3]
    if imgs:
        user_msg = {"role": "user", "content": (
            [{"type": "text", "text": user_content}]
            + [{"type": "image_url", "image_url": {"url": u}} for u in imgs]
        )}
    else:
        user_msg = {"role": "user", "content": user_content}
    # Slim history: only the last 2 turns (vs the voice channel's full 4) — enough to
    # resolve a follow-up ("send it") without dragging the whole conversation into a job.
    history = rr._recent_turn_messages((recent_turns or [])[-2:])
    return [
        {"role": "system", "content": build_agent_prefix(
            has_gmail, has_calendar, persona_text, bot_name, owner_name, owner_email)},
        {"role": "system", "content": f"Current date and time: {now_str}.\n\n{memory_context}"},
        *history,
        user_msg,
    ]

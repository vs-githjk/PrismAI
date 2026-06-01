"""Think + Loop: lightweight intent gating for the realtime command path.

Design goals (see PRISM_AI_CONTEXT.md > Think+Loop notes):
  1. Model thinks before acting via a <thinking>...</thinking> block — stripped
     from the spoken reply but kept in logs.
  2. The existing agentic tool loop (max 3 iterations) handles multi-tool and
     hybrid-source requests natively. No second LLM "classifier" pass.
  3. A single regex verb-gate fires AFTER the model emits a tool call but
     BEFORE the side-effect executes. Catches the gmail_send-without-SEND-verb
     class of misfires that the prompt alone may miss.
  4. Per-bot artifact store carries the last COMPOSE draft into a follow-up
     ACT turn ("draft email" → "now send it") without re-asking for body.

Flag: PRISM_THINK_LOOP=1 enables verb-gating + artifact handoff. The thinking
directive in the system prompt is always on once the prompt patch ships,
because the prompt is cache-stable and harmless when disabled downstream.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

# ── Verb taxonomy ─────────────────────────────────────────────────────────────
#
# DESTRUCTIVE_TOOLS maps tool name → set of verbs that authorize that tool.
# These are the side-effect tools (`confirm=True` in the registry). For each,
# a command that uses one of these verbs is the explicit user authorization.
#
# Verbs are matched case-insensitively against whole words. Multi-word phrases
# ("mail it", "ship it") are matched as substring tokens.

DESTRUCTIVE_TOOLS: dict[str, set[str]] = {
    "gmail_send": {
        # Imperatives
        "send", "mail", "email", "email it", "shoot", "fire it", "fire off",
        "forward", "reply", "respond", "ship it", "ship",
        # Inflected forms ("sending", "mailing") — common when user re-asks
        "sending", "mailing", "emailing", "forwarding", "replying", "shooting",
        # Multi-word patterns the user actually types in production
        "send a mail", "send an email", "send this", "send that",
        "shoot a mail", "shoot an email", "fire off an email",
    },
    "slack_send_message": {
        "post", "send", "share in", "drop in", "ping", "tell the channel",
        "shoot", "shout", "posting", "sending", "sharing", "pinging",
        "post in", "post to", "send to the channel",
    },
    # The legacy + canonical names used in the codebase
    "slack_post_message": {
        "post", "send", "share in", "drop in", "ping", "tell the channel",
        "shoot", "shout", "posting", "sending", "sharing", "pinging",
        "post in", "post to", "send to the channel",
    },
    "linear_create_issue": {
        "create a ticket", "file a ticket", "open an issue", "make a linear",
        "log it", "log a ticket", "log an issue", "ticket it", "file",
        "create the ticket", "add a ticket", "filing", "logging",
        "open a linear", "open the ticket",
    },
    "calendar_create_event": {
        "schedule", "book", "set up", "create a meeting", "create an event",
        "add to my calendar", "put on my cal", "put on the calendar",
        "block off", "add a meeting", "to my calendar", "to my cal",
        "on my calendar", "on my cal", "scheduling", "booking",
    },
    "calendar_update_event": {
        "reschedule", "move", "shift", "change my", "update my", "push",
        "rescheduling", "moving", "shifting",
    },
    "calendar_delete_event": {
        "cancel", "delete", "remove", "drop", "cancelling", "canceling",
        "deleting", "removing", "dropping",
    },
}

# Words that signal the user wants a text artifact, NOT an external action.
# Presence of one of these without a destructive verb above → COMPOSE intent.
COMPOSE_INDICATORS: set[str] = {
    "draft", "write me", "write a", "compose", "prepare", "sketch",
    "outline", "type out", "type up", "wording", "phrase",
    "what would i say", "what should i say", "how would i say",
    "give me wording",
}

# Short follow-up phrases that imply "act on the previous artifact". When the
# previous turn produced a COMPOSE artifact and the current command matches
# one of these, we allow the destructive tool through and inject the artifact.
FOLLOWUP_ACT_PHRASES: set[str] = {
    # Bare followups
    "send it", "send that", "send the draft", "send this draft",
    "go ahead", "go for it", "do it", "yes do it", "yes send", "yep send",
    "ship it", "fire it", "now send", "okay send", "ok send", "approve",
    # Forms with recipient ("send to bob@x.com", "send a mail to ...")
    "send to", "send a mail", "send an email", "mail it", "email it to",
    # Explicit references to the prior artifact
    "use the draft", "use this draft", "use that draft", "use your draft",
    "use the template", "use this template", "use that template",
    "use what you wrote", "use what you composed", "use what you drafted",
    "with the draft", "with this draft", "with that draft",
    "from the draft", "based on the draft", "based on that draft",
    "the draft you created", "the draft you wrote", "the draft you made",
    "what you just drafted", "what you just wrote",
    # Slack/Linear variants
    "post that in", "post this in", "share that", "share this",
    "post it", "post that", "ship that",
    "file that", "file it", "log that", "log this",
}

# Phrases where "draft" / "template" / "email" / "message" appear as NOUNS
# referring to the prior artifact, not as COMPOSE imperatives. When any of
# these match, _compose_appears_first is suppressed so a destructive verb
# elsewhere in the command wins.
_DRAFT_NOUN_REFS = re.compile(
    r"\b(use|with|from|based on|using|reuse|take|grab)\s+"
    r"(the|this|that|your|my|its|a)\s+"
    r"(draft|template|email|message|reply|note|ticket|issue|writeup)\b",
    re.IGNORECASE,
)

# Simple negation detector: "don't send", "do not post", "no, don't email",
# "skip the send". Fires when a negation token appears within 12 chars
# BEFORE any destructive verb. Caller treats this as an explicit block.
_NEGATION_RE = re.compile(
    r"\b(don'?t|do not|never|skip|hold off|do n't)\b",
    re.IGNORECASE,
)


# ── Public flag check ────────────────────────────────────────────────────────

def think_loop_on() -> bool:
    return os.getenv("PRISM_THINK_LOOP", "0") == "1"


# ── Thinking-tag stripper ────────────────────────────────────────────────────

_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> tuple[str, str]:
    """Split a model reply into (visible, hidden_thinking).

    `visible` is what goes to TTS / the user. `hidden_thinking` is logged for
    debug + observability. If no <thinking> block is present, hidden is empty.

    Robust to:
      - missing close tag (returns text unchanged, hidden=text-after-open)
      - multiple blocks (concatenates hidden, removes all)
      - case differences in tag name
    """
    if not text:
        return "", ""
    hidden_parts = _THINKING_RE.findall(text)
    visible = _THINKING_RE.sub("", text).strip()
    # Handle an unclosed <thinking> at the start by stripping it through end-of-string
    unclosed = re.match(r"\s*<thinking>(.*)$", visible, re.DOTALL | re.IGNORECASE)
    if unclosed:
        hidden_parts.append(unclosed.group(1))
        visible = ""
    return visible, "\n---\n".join(p.strip() for p in hidden_parts).strip()


# ── Verb gate ────────────────────────────────────────────────────────────────

def _has_verb(command_lower: str, verb: str) -> bool:
    """Check whether `verb` is present in `command_lower` as a word/phrase.

    Single tokens use \\b word boundaries; multi-word phrases use substring.
    """
    if " " in verb:
        return verb in command_lower
    return re.search(rf"\b{re.escape(verb)}\b", command_lower) is not None


def _has_any_compose_indicator(command_lower: str) -> bool:
    return any(_has_verb(command_lower, w) for w in COMPOSE_INDICATORS)


def _has_any_destructive_verb_for(tool_name: str, command_lower: str) -> bool:
    verbs = DESTRUCTIVE_TOOLS.get(tool_name, set())
    return any(_has_verb(command_lower, v) for v in verbs)


def _is_followup_act(command_lower: str) -> bool:
    return any(p in command_lower for p in FOLLOWUP_ACT_PHRASES)


# How early in the command a COMPOSE indicator must appear to override a
# destructive verb. "outline what i should post" → outline at pos 0 wins.
# "send the draft to bob" → send at pos 0, draft at pos 9 — outside the
# window so the destructive verb wins.
_COMPOSE_PRECEDENCE_WINDOW = 25


def _compose_appears_first(command_lower: str) -> bool:
    """True when a COMPOSE indicator appears within the first N chars AND
    precedes any destructive verb. Signals the user's imperative is COMPOSE
    even if a destructive verb appears later as part of the artifact target
    (e.g. 'outline what i should post').

    Suppressed when the command contains a NOUN reference like 'use the
    draft' — there 'draft' is a pointer to the prior artifact, not a
    COMPOSE imperative.
    """
    if _DRAFT_NOUN_REFS.search(command_lower):
        return False
    earliest_compose = -1
    for w in COMPOSE_INDICATORS:
        if " " in w:
            idx = command_lower.find(w)
        else:
            m = re.search(rf"\b{re.escape(w)}\b", command_lower)
            idx = m.start() if m else -1
        if idx < 0:
            continue
        if earliest_compose < 0 or idx < earliest_compose:
            earliest_compose = idx
    return 0 <= earliest_compose <= _COMPOSE_PRECEDENCE_WINDOW


def _negated_destructive(command_lower: str, tool_name: str) -> bool:
    """True when the command tells the bot NOT to act ('don't send').

    Looks for a negation token within 12 chars BEFORE the first destructive
    verb for this tool. Conservative window — 'don't worry, just send it'
    has the negation 25+ chars before 'send', so it doesn't trigger.
    """
    neg = _NEGATION_RE.search(command_lower)
    if not neg:
        return False
    verbs = DESTRUCTIVE_TOOLS.get(tool_name, set())
    neg_end = neg.end()
    for w in verbs:
        if " " in w:
            idx = command_lower.find(w, neg_end)
        else:
            m = re.search(rf"\b{re.escape(w)}\b", command_lower[neg_end:])
            idx = (m.start() + neg_end) if m else -1
        if 0 <= idx - neg_end <= 12:
            return True
    return False


def verb_gate(
    *,
    command: str,
    tool_name: str,
    has_prior_artifact: bool,
) -> Optional[str]:
    """Decide whether a tool call should be allowed.

    Returns None if the call is allowed. Returns a string explaining the block
    if the call should be refused — the caller appends this as a tool-result
    error so the LLM sees the refusal and re-plans.

    Only gates `DESTRUCTIVE_TOOLS`. Read tools (gmail_read, calendar_list_events,
    slack_read_channel, knowledge_lookup, web_search) are never blocked here;
    they're cheap and rarely a misfire risk.
    """
    if tool_name not in DESTRUCTIVE_TOOLS:
        return None
    cmd = (command or "").lower()

    # Path 0: negation — "don't send", "do not post" — block before anything
    # else. The model may still emit the tool call if the prompt didn't
    # convince it; this gate is the last line of defense.
    if _negated_destructive(cmd, tool_name):
        return (
            f"Refused: the user explicitly negated this action "
            f"('don't', 'skip', 'hold off'). Do NOT call {tool_name}. "
            f"Acknowledge the negation in your reply."
        )

    # Path A: command is a short follow-up AND prior turn produced an artifact.
    # E.g., "send it" / "use this draft and send" after a COMPOSE turn. Allow
    # — caller will have injected the artifact as context. Checked first so
    # "send it" with a fresh draft beats compose-precedence.
    if has_prior_artifact and _is_followup_act(cmd):
        return None

    # Path B: COMPOSE indicator appears at the start of the command — the
    # user's imperative is COMPOSE, even if a destructive verb appears later
    # as part of the artifact target ("outline what i should post in #X").
    # Suppressed when the command says 'use the draft' etc. (noun reference).
    if _compose_appears_first(cmd):
        return (
            f"Refused: the user asked you to compose/draft, not to perform "
            f"{tool_name}. Output the requested text as your reply instead "
            f"of calling this tool. Do not call {tool_name} again this turn."
        )

    # Path C: command contains an authorizing destructive verb. Allow.
    if _has_any_destructive_verb_for(tool_name, cmd):
        return None

    # Path D: COMPOSE indicator anywhere (later in command) — still block.
    if _has_any_compose_indicator(cmd):
        return (
            f"Refused: the user asked you to compose/draft, not to perform "
            f"{tool_name}. Output the requested text as your reply instead "
            f"of calling this tool. Do not call {tool_name} again this turn."
        )

    # Path D: ambiguous command (no compose indicator, no destructive verb).
    # Block destructive tools by default — the model can recover by asking
    # the user to confirm. Better to ask once than to send the wrong email.
    return (
        f"Refused: the user did not explicitly authorize {tool_name}. "
        f"No send/post/schedule/cancel verb was used in the command. "
        f"Either ask the user to confirm in plain words, or output a draft "
        f"instead."
    )


# ── Artifact extraction + handoff ────────────────────────────────────────────

_ARTIFACT_TTL_S = 300

# A reply qualifies as a draft artifact if any of these patterns hit. The
# detection is intentionally loose — false positives are harmless because
# the artifact only matters when the NEXT turn is a follow-up ACT.
# Patterns handle: bare drafts (Dear Bob), quoted drafts ("Dear Bob"),
# code-fenced drafts (```Dear Bob...```), email headers (Subject:), and
# Linear-style ticket headers. The salutation pattern also allows a leading
# quote or backtick so 'Here's a draft: "Dear Bob..."' is recognized.
_ARTIFACT_PATTERNS = (
    re.compile(r"(?im)^[\s\"'`>*\-]*subject\s*:"),
    re.compile(r"(?im)^[\s\"'`>*\-]*(dear|hi|hey|hello|good (morning|afternoon|evening))\s+[A-Z]"),
    re.compile(r"(?im)^[\s\"'`>*\-]*(title|ticket|issue|to|body)\s*:"),
    # Framing phrases that indicate a draft is in the reply, even if the
    # salutation never made it to a line start (e.g. inlined in prose).
    re.compile(r"(?i)\b(here'?s? (a|the|your|my) (draft|template|email|message)|"
               r"draft (email|message|reply|response)|"
               r"how about this|something like this|try this|"
               r"you (could|can) (say|use|try))\b"),
)


def looks_like_artifact(reply: str) -> bool:
    if not reply or len(reply) < 40:
        return False
    return any(p.search(reply) for p in _ARTIFACT_PATTERNS)


def looks_like_compose_command(command: str) -> bool:
    return _has_any_compose_indicator((command or "").lower())


def make_artifact(reply: str, command: str) -> dict:
    """Build the artifact dict to stash in bot state."""
    return {
        "type": "draft",
        "text": reply,
        "from_command": command,
        "ts": time.time(),
    }


def get_fresh_artifact(state: dict) -> Optional[dict]:
    """Return the last artifact if still within TTL, else None."""
    art = state.get("last_artifact")
    if not art:
        return None
    if time.time() - art.get("ts", 0) > _ARTIFACT_TTL_S:
        state.pop("last_artifact", None)
        return None
    return art


def set_artifact(state: dict, reply: str, command: str) -> None:
    state["last_artifact"] = make_artifact(reply, command)


def clear_artifact(state: dict) -> None:
    state.pop("last_artifact", None)


def artifact_system_hint(artifact: dict) -> str:
    """System message body reminding the model of the prior draft so it can
    feed the body into a follow-up gmail_send / slack_post call without
    asking the user to repeat themselves."""
    text = artifact.get("text", "")
    return (
        "PRIOR_DRAFT: the user previously asked you to compose the following. "
        "If the current command is a follow-up to send/post/share it, reuse "
        "this body verbatim. Do not ask the user to restate the body.\n"
        "---\n"
        f"{text}\n"
        "---"
    )


# ── System-prompt patches ────────────────────────────────────────────────────

# DEPRECATED 2026-05-23. The directive was removed from the live realtime prefix
# because it destabilised Groq + Llama 3.3-70b tool calls — the model started
# emitting malformed `<function=name:"web_search" ...>` shapes (capture group
# becomes "name", recovery parser drops it as not-in-tools). All three of the
# directive's intended jobs are covered elsewhere:
#   - compose-vs-send: _STATIC_PERSONA, _STATIC_GMAIL_ON, tool descriptions.
#   - verb gating: verb_gate() after the model emits a tool call.
#   - artifact handoff: artifact_system_hint() injected at message-build time.
# The constant is retained for reference (and so any external import still works)
# but is no longer appended to the system prompt.

THINKING_DIRECTIVE = (
    "Before responding, briefly think inside a <thinking>...</thinking> block. "
    "In the block, write 1-3 short lines: (a) what is the user asking, "
    "(b) is this an ANSWER (no tool), COMPOSE (text artifact, no tool), "
    "LOOKUP (read tool), or ACT (write tool)?, "
    "(c) which tools — if any — will you call. "
    "Then close the </thinking> tag and produce your actual reply. "
    "Important: ACT mode (gmail_send, slack_post_message, linear_create_issue, "
    "calendar_create_event, calendar_update_event, calendar_delete_event) "
    "requires the user to have used an explicit send/post/schedule/cancel verb "
    "in the current command. If they said 'draft', 'write', 'compose', or "
    "'prepare', that is COMPOSE — output the text directly, no tool call. "
    "If multiple tools are needed (e.g. look up then send), call them in "
    "sequence across the loop. The <thinking> block is stripped before the "
    "user hears your reply."
)

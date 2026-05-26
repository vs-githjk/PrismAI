"""Diagnostic feedback loop for the web_search malformed-tool-call bug.

Sends a small scenario matrix through three system-prefix variants and
reports per-cell PASS/FAIL. Run from backend/:

    python tests/diagnose_web_search.py

Variants:
  A) Current THINKING_DIRECTIVE (production state with PRISM_THINK_LOOP=1)
  B) No directive at all (baseline)
  C) Candidate sanitized directive (no tool-name enumeration)

Scenarios cover the failure (web_search), the original Think+Loop wins
(compose=blocked, send=allowed), and a second LOOKUP (weather) to confirm
the fix isn't web_search-keyword-specific.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from groq import Groq  # type: ignore

import think_loop  # noqa: E402

# Inline copy of the production recovery parser (realtime_routes.py) so the
# diagnostic doesn't need to import the full FastAPI module graph.
import re as _re
import json as _json

_FUNCTION_TAG_RE = _re.compile(r"<function\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*", _re.IGNORECASE)


def _find_matching_brace(s, start):
    depth, in_string, escape = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _recover(text, valid):
    if not text:
        return []
    out, pos = [], 0
    while pos < len(text):
        m = _FUNCTION_TAG_RE.search(text, pos)
        if not m:
            break
        name = m.group(1)
        body_start = m.end()
        while body_start < len(text) and text[body_start].isspace():
            body_start += 1
        if body_start < len(text) and text[body_start] == "{":
            body_end = _find_matching_brace(text, body_start)
            if body_end == -1:
                pos = m.end()
                continue
            args = text[body_start:body_end]
            try:
                _json.loads(args)
            except _json.JSONDecodeError:
                args = "{}"
            pos = body_end
        else:
            args = "{}"
            pos = body_start if body_start > m.end() else m.end()
        if name in valid:
            out.append({"name": name, "arguments": args})
    return out


# ── Tools (subset of the live realtime route's tool list) ────────────────────

def make_tool(name: str, desc: str, params: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}


T_WEB_SEARCH = make_tool(
    "web_search",
    "Search the web for current information. Use for news, weather, or real-time data.",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)
T_GMAIL_SEND = make_tool(
    "gmail_send",
    "Send an email. ONLY when the user explicitly says to SEND (send/forward/reply/ship). "
    "Do NOT call for draft/write/compose/prepare requests.",
    {
        "type": "object",
        "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
        "required": ["to", "subject", "body"],
    },
)

TOOLS_BY_NAME = {"web_search": T_WEB_SEARCH, "gmail_send": T_GMAIL_SEND}


# ── Scenarios ────────────────────────────────────────────────────────────────

SCENARIOS = [
    # (label, command, tools_offered, expected)
    ("web_search/news",  "can you search for the latest news regarding google's I/O",  ["web_search"],                 "tool:web_search"),
    ("web_search/weather", "can you check the weather for today",                       ["web_search"],                 "tool:web_search"),
    ("compose/email",    "draft me an email to my professor about my grades",          ["gmail_send"],                 "no_tool"),
    ("send/email",       "send an email to bob@x.com about the q4 report",             ["gmail_send"],                 "tool:gmail_send"),
    ("mixed_lookup",     "search the web for google IO news",                          ["web_search", "gmail_send"],   "tool:web_search"),
]


# ── Prompt variants ──────────────────────────────────────────────────────────

BASE_PERSONA = (
    "You are PrismAI, an AI meeting assistant that is LIVE in this meeting. "
    "A participant just gave you a command. "
    "NEVER call a tool unless the user is explicitly asking you to perform that action right now. "
    "Be concise — responses will be spoken aloud. Keep responses under 3 sentences."
)

CURRENT_DIRECTIVE = think_loop.THINKING_DIRECTIVE

SANITIZED_DIRECTIVE = (
    "Before responding, briefly think inside a <thinking>...</thinking> block. "
    "Write 1-3 short lines about what the user is asking and whether their command "
    "contains an explicit action verb. Then close </thinking> and reply. "
    "Rules: if the user said 'draft', 'write', 'compose', 'prepare', or 'outline' "
    "without an action verb like 'send'/'post'/'schedule'/'cancel'/'file', output "
    "the requested text directly and do not call any write/send tool. "
    "If the user asks a question or wants information, answer it or look it up. "
    "The <thinking> block is stripped before the user hears your reply."
)

FULL_PROD_PERSONA = (
    "You are PrismAI, an AI meeting assistant that is LIVE in this meeting. "
    "A participant just gave you a command. "
    "You have access to the full meeting memory below — use it to answer questions "
    "about anything discussed during the meeting, no matter how long ago it was said. "
    "Answer directly from the meeting memory or your knowledge whenever possible. "
    "NEVER call a tool unless the user is explicitly asking you to perform that action right now "
    "(e.g. 'send an email to X', 'check my calendar', 'create a ticket'). "
    "Questions about your capabilities, access, or what you can do must be answered in words — never by calling a tool. "
    "You have Gmail access. Only call gmail_send when the user explicitly says to send an email and "
    "provides a recipient and intent. If asked whether you can send emails, answer YES directly — "
    "do not call a tool just to answer that question. "
    "You have full Google Calendar access: use calendar_list_events to read/check upcoming events, "
    "calendar_create_event to schedule (only if the user provides title AND date/time), "
    "and calendar_update_event to reschedule. "
    "If asked whether you can access the calendar, answer YES directly — do not call a tool just to answer that question. "
    "Be concise — responses will be spoken aloud. Keep responses under 3 sentences."
)

VARIANTS = [
    ("A_current_w_directive", FULL_PROD_PERSONA + "\n\n" + CURRENT_DIRECTIVE),
    ("B_minimal_no_directive", BASE_PERSONA),
    ("C_sanitized",            BASE_PERSONA + "\n\n" + SANITIZED_DIRECTIVE),
    ("D_full_prod_no_directive", FULL_PROD_PERSONA),  # the post-fix state
]


# ── Runner ───────────────────────────────────────────────────────────────────

def call_groq(system: str, command: str, tool_names: list[str]) -> dict:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    tools = [TOOLS_BY_NAME[n] for n in tool_names]
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"[Abhinav]: {command}"},
            ],
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
            max_tokens=400,
        )
        msg = resp.choices[0].message
        tcs = msg.tool_calls or []
        return {
            "ok_format": True,
            "tool_calls": [tc.function.name for tc in tcs],
            "content_snippet": (msg.content or "")[:160].replace("\n", " | "),
            "failed_generation": None,
        }
    except Exception as e:
        body = getattr(e, "body", None) or {}
        err = (body.get("error") or {}) if isinstance(body, dict) else {}
        return {
            "ok_format": False,
            "tool_calls": [],
            "content_snippet": "",
            "failed_generation": (err.get("failed_generation") or "")[:200].replace("\n", " | "),
        }


def matches_expected(result: dict, expected: str, tool_names: list[str]) -> tuple[bool, str]:
    """Returns (pass, channel) where channel is 'direct', 'recovered', or 'none'."""
    if expected == "no_tool":
        if result["ok_format"] and result["tool_calls"] == []:
            return True, "direct"
        return False, "none"
    if expected.startswith("tool:"):
        want = expected.split(":", 1)[1]
        if result["ok_format"] and want in result["tool_calls"]:
            return True, "direct"
        # Production recovery path
        fg = result.get("failed_generation") or ""
        recovered = _recover(fg, set(tool_names))
        if any(c["name"] == want for c in recovered):
            return True, "recovered"
        return False, "none"
    return False, "none"


def main() -> None:
    if not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY missing", file=sys.stderr)
        sys.exit(1)

    rows = []
    for variant_label, system in VARIANTS:
        for scen_label, command, tool_names, expected in SCENARIOS:
            r = call_groq(system, command, tool_names)
            ok, channel = matches_expected(r, expected, tool_names)
            rows.append((variant_label, scen_label, expected, ok, channel, r))

    by_variant: dict[str, list] = {}
    for v, s, exp, ok, ch, r in rows:
        by_variant.setdefault(v, []).append((s, exp, ok, ch, r))

    for v, items in by_variant.items():
        passed = sum(1 for *_x, ok, _ch, _r in items if ok)
        passed_recovered = sum(1 for *_x, ok, ch, _r in items if ok and ch == "recovered")
        total = len(items)
        print(f"\n== {v}: {passed}/{total} pass ({passed_recovered} via recovery) ==")
        for s, exp, ok, ch, r in items:
            mark = "PASS" if ok else "FAIL"
            if ok and ch == "recovered":
                mark = "PASS*"
            calls = ",".join(r["tool_calls"]) if r["tool_calls"] else "(none)"
            line = f"  [{mark:5s}] {s:24s} exp={exp:20s} got={calls}"
            if not r["ok_format"]:
                line += f" fg='{(r['failed_generation'] or '')[:120]}'"
            print(line)


if __name__ == "__main__":
    main()

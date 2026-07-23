"""`computer_use` tool — Phase 3 of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("New tool") +
ADR docs/adr/0002.

This is the ONLY `presents=True` tool. It does not do the driving itself: the
open-ended computer-use loop (sandbox/computer_use.run_computer_use) is long and
must run as a BACKGROUND task so it never blocks the live-bot command path (which
would deafen the "stop sharing" kill phrase). See the spec's hard rule:

  > The handler MUST NOT run the loop inline — inline blocks _process_command,
  > making the bot deaf to the kill-phrase. Background task + cancel event.

WIRING (documented decision): the real routing lives in
`realtime_routes._process_command`'s presents-branch, NOT in this handler. That
branch is the only place with the full context the presentation manager needs —
the live `state`, the resolved `is_owner` trust bit, the workspace scope, and the
bot owner's `user_settings` — so it spawns `presentation.start_presentation(...)`
as an `asyncio.create_task` and appends this tool's fast result to the LLM thread.
Threading all of that through `execute_tool` into the handler would have meant
leaking command-context into the tool-settings dict; routing from the command
path is the least-invasive path (the brief's stated preference).

So this handler is registration + a defensive fast-return: it makes the tool a
real registered tool (so `get_available_tools` can surface it and
`registry.is_presents` reports True), and if it is EVER dispatched directly via
`execute_tool` (e.g. a future dashboard `/agent` path with no meeting/bot), it
validates the goal and returns fast WITHOUT starting a share — there is no
meeting to present into from that context.
"""

from tools.registry import register_tool

_TOOL_DESCRIPTION = (
    "Put something on the shared screen for the meeting: open, pull up, bring up, "
    "or walk the room through a web page, app, dashboard, document, PR, or file on "
    "the bot's own desktop, streamed live as its screenshare. Use ONLY when the "
    "speaker clearly wants something SHOWN on screen (e.g. 'pull up the auth PR', "
    "'put the dashboard on screen', 'walk us through the staging build'). Do not "
    "use it to answer a question in text — for that, just reply."
)

_PARAMETERS = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": (
                "What to reach and show, in one line, from the speaker's request — "
                "e.g. 'open the auth PR on GitHub and show the diff' or 'walk us "
                "through the staging dashboard'. Include the target and, if the "
                "speaker asked to be walked through it, say so."
            ),
        }
    },
    "required": ["goal"],
}


async def handler(args, user_settings=None):
    """Defensive fast-return (see module docstring). NEVER runs the loop.

    The live-meeting path routes `presents=True` tools through the presentation
    manager before this handler is ever reached, so in practice this only runs if
    the tool is dispatched from a context with no meeting to present into."""
    goal = ""
    if isinstance(args, dict):
        goal = (args.get("goal") or "").strip()
    if not goal:
        return {"success": False, "error": "A 'goal' describing what to show is required."}
    # No bot/meeting context here → nothing to present into. Report the intent
    # without spinning up a sandbox share.
    return {"success": True, "summary": f"presenting: {goal}"}


register_tool(
    name="computer_use",
    description=_TOOL_DESCRIPTION,
    parameters=_PARAMETERS,
    handler=handler,
    requires="sandbox_id",   # only offered when the bot OWNER has a sandbox set up
    confirm=False,
    presents=True,           # command loop routes this through the presentation manager
)

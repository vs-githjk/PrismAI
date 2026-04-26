"""
Tool registry: defines available tools, checks availability per-user, dispatches execution.
"""

import json
import time
from collections import defaultdict
from typing import Any, Callable, Awaitable

# Each registered tool: { name, description, parameters, handler, requires, confirm }
_TOOLS: dict[str, dict] = {}

# Rate limiting: user_id -> list of timestamps
_rate_log: dict[str, list[float]] = defaultdict(list)
MAX_CALLS_PER_TURN = 3
MAX_CALLS_PER_MINUTE = 10


def register_tool(
    name: str,
    description: str,
    parameters: dict,
    handler: Callable[..., Awaitable[Any]],
    requires: str | None = None,
    confirm: bool = False,
):
    """Register a tool. `requires` is an env/setting key that must be present for the tool to be available."""
    _TOOLS[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "requires": requires,
        "confirm": confirm,
    }


def get_available_tools(user_settings: dict | None = None, exclude_confirm: bool = False) -> list[dict]:
    """Return Groq-compatible tool definitions for tools the user has access to."""
    settings = user_settings or {}
    tools = []
    for tool in _TOOLS.values():
        # Check if required credential is present
        if tool["requires"] and not settings.get(tool["requires"]):
            continue
        # In live meeting context, skip tools that require human confirmation
        if exclude_confirm and tool.get("confirm"):
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        })
    return tools


async def execute_tool(name: str, arguments: str | dict, user_id: str, user_settings: dict | None = None) -> dict:
    """Execute a tool by name. Returns result dict or error."""
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name}"}

    tool = _TOOLS[name]

    # Rate limiting
    now = time.time()
    _rate_log[user_id] = [t for t in _rate_log[user_id] if now - t < 60]
    if len(_rate_log[user_id]) >= MAX_CALLS_PER_MINUTE:
        return {"error": "Rate limit exceeded — max 10 tool calls per minute"}
    _rate_log[user_id].append(now)

    # Parse arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments: {arguments}"}

    # Check if confirmation is required
    if tool["confirm"]:
        return {
            "requires_confirmation": True,
            "tool": name,
            "preview": arguments,
            "message": f"Please confirm: {tool['description']}",
        }

    # Execute
    try:
        result = await tool["handler"](arguments, user_settings=user_settings or {})
        # Inject external_ref for resource-creating tools so callers can store the ref
        if result.get("success"):
            if result.get("issue_id"):
                result["external_ref"] = {"tool": name, "external_id": str(result["issue_id"])}
            elif result.get("event_id"):
                result["external_ref"] = {"tool": name, "external_id": str(result["event_id"])}
        return result
    except Exception as exc:
        return {"error": f"Tool '{name}' failed: {str(exc)}"}


def get_tool(name: str) -> dict | None:
    return _TOOLS.get(name)


async def confirm_and_execute(name: str, arguments: str | dict, user_settings: dict | None = None) -> dict:
    """Execute a tool that was previously held for confirmation."""
    if name not in _TOOLS:
        return {"error": f"Unknown tool: {name}"}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments: {arguments}"}
    tool = _TOOLS[name]
    try:
        result = await tool["handler"](arguments, user_settings=user_settings or {})
        return result
    except Exception as exc:
        return {"error": f"Tool '{name}' failed: {str(exc)}"}

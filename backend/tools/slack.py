"""Slack tools: read channels, post messages, search."""

import os

import httpx

from .registry import register_tool

SLACK_API = "https://slack.com/api"
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")


def _get_token(user_settings: dict) -> str:
    # Use per-user token if available, fall back to env
    token = user_settings.get("slack_bot_token") or SLACK_BOT_TOKEN
    if not token:
        raise Exception("Slack not connected — add SLACK_BOT_TOKEN")
    return token


async def slack_read_channel(args: dict, user_settings: dict | None = None) -> dict:
    token = _get_token(user_settings)
    channel = args.get("channel", "")
    limit = min(args.get("limit", 20), 50)

    # Resolve channel name to ID if needed
    channel_id = channel
    if not channel.startswith("C"):
        channel_id = await _resolve_channel(token, channel)
        if not channel_id:
            return {"error": f"Channel '{channel}' not found"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SLACK_API}/conversations.history",
            headers={"Authorization": f"Bearer {token}"},
            params={"channel": channel_id, "limit": limit},
            timeout=15,
        )

    if resp.status_code != 200:
        return {"error": f"Slack API error {resp.status_code}"}

    data = resp.json()
    if not data.get("ok"):
        return {"error": f"Slack error: {data.get('error', 'unknown')}"}

    messages = []
    for msg in data.get("messages", []):
        messages.append({
            "user": msg.get("user", ""),
            "text": msg.get("text", ""),
            "ts": msg.get("ts", ""),
        })

    return {"messages": messages, "channel": channel, "summary": f"Read {len(messages)} messages from {channel}"}


async def slack_post_message(args: dict, user_settings: dict | None = None) -> dict:
    token = _get_token(user_settings)
    channel = args.get("channel", "")
    text = args.get("text", "")

    # Resolve channel name to ID if needed
    channel_id = channel
    if not channel.startswith("C"):
        channel_id = await _resolve_channel(token, channel)
        if not channel_id:
            return {"error": f"Channel '{channel}' not found"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SLACK_API}/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"channel": channel_id, "text": text},
            timeout=15,
        )

    data = resp.json()
    if data.get("ok"):
        return {"success": True, "summary": f"Posted message to {channel}"}
    else:
        return {"error": f"Slack error: {data.get('error', 'unknown')}"}


async def slack_search(args: dict, user_settings: dict | None = None) -> dict:
    token = _get_token(user_settings)
    query = args.get("query", "")
    limit = min(args.get("limit", 10), 20)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SLACK_API}/search.messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": query, "count": limit},
            timeout=15,
        )

    data = resp.json()
    if not data.get("ok"):
        return {"error": f"Slack search error: {data.get('error', 'unknown')}"}

    matches = data.get("messages", {}).get("matches", [])
    results = []
    for m in matches[:limit]:
        results.append({
            "text": m.get("text", ""),
            "user": m.get("username", ""),
            "channel": m.get("channel", {}).get("name", ""),
            "ts": m.get("ts", ""),
        })

    return {"results": results, "summary": f"Found {len(results)} messages matching '{query}'"}


async def _resolve_channel(token: str, name: str) -> str | None:
    """Resolve a channel name (with or without #) to its Slack ID."""
    name = name.lstrip("#").lower()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SLACK_API}/conversations.list",
            headers={"Authorization": f"Bearer {token}"},
            params={"types": "public_channel,private_channel", "limit": 200},
            timeout=15,
        )
    if resp.status_code != 200:
        return None
    data = resp.json()
    for ch in data.get("channels", []):
        if ch.get("name", "").lower() == name:
            return ch["id"]
    return None


# Register tools
register_tool(
    name="slack_read_channel",
    description="Read recent messages from a Slack channel",
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name (e.g. '#engineering') or ID"},
            "limit": {"type": "integer", "description": "Number of messages to fetch (max 50)", "default": 20},
        },
        "required": ["channel"],
    },
    handler=slack_read_channel,
    requires="slack_bot_token",
    confirm=False,
)

register_tool(
    name="slack_post_message",
    description="Post a message to a Slack channel",
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name (e.g. '#engineering') or ID"},
            "text": {"type": "string", "description": "Message text to post"},
        },
        "required": ["channel", "text"],
    },
    handler=slack_post_message,
    requires="slack_bot_token",
    confirm=True,
)

register_tool(
    name="slack_search",
    description="Search Slack messages across all channels",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (max 20)", "default": 10},
        },
        "required": ["query"],
    },
    handler=slack_search,
    requires="slack_bot_token",
    confirm=False,
)

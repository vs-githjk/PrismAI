"""Gmail tools: send and read emails using the user's Google OAuth token."""

import base64
from email.mime.text import MIMEText

import httpx

from .registry import register_tool

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


async def _get_google_token(user_settings: dict) -> str:
    token = user_settings.get("google_access_token")
    if not token:
        raise Exception("Google not connected — connect Google Calendar first to enable Gmail")
    return token


async def gmail_send(args: dict, user_settings: dict | None = None) -> dict:
    token = await _get_google_token(user_settings)

    to = args.get("to", [])
    if isinstance(to, str):
        to = [to]
    subject = args.get("subject", "")
    body = args.get("body", "")

    msg = MIMEText(body)
    msg["to"] = ", ".join(to)
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GMAIL_API}/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=15,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        return {"success": True, "message_id": data.get("id"), "summary": f"Sent email '{subject}' to {', '.join(to)}"}
    else:
        return {"error": f"Gmail API error {resp.status_code}: {resp.text[:200]}"}


async def gmail_read(args: dict, user_settings: dict | None = None) -> dict:
    token = await _get_google_token(user_settings)

    query = args.get("query", "")
    max_results = min(args.get("max_results", 5), 10)

    async with httpx.AsyncClient() as client:
        # List messages
        params = {"maxResults": max_results}
        if query:
            params["q"] = query
        resp = await client.get(
            f"{GMAIL_API}/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=15,
        )

    if resp.status_code != 200:
        return {"error": f"Gmail list error {resp.status_code}: {resp.text[:200]}"}

    message_ids = [m["id"] for m in resp.json().get("messages", [])]
    if not message_ids:
        return {"emails": [], "summary": "No emails found"}

    # Fetch each message
    emails = []
    async with httpx.AsyncClient() as client:
        for mid in message_ids[:max_results]:
            resp = await client.get(
                f"{GMAIL_API}/messages/{mid}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
                emails.append({
                    "id": mid,
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": data.get("snippet", ""),
                })

    return {"emails": emails, "summary": f"Found {len(emails)} email(s)"}


# Register tools
register_tool(
    name="gmail_send",
    description="Send an email on behalf of the user",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text"},
        },
        "required": ["to", "subject", "body"],
    },
    handler=gmail_send,
    requires="google_access_token",
    confirm=True,
)

register_tool(
    name="gmail_read",
    description="Read recent emails, optionally filtered by sender or subject",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query (e.g. 'from:alice@co.com' or 'subject:Q2 planning')"},
            "max_results": {"type": "integer", "description": "Max emails to return (1-10)", "default": 5},
        },
        "required": [],
    },
    handler=gmail_read,
    requires="google_access_token",
    confirm=False,
)

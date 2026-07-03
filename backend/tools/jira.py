"""Jira tools: create issues via the Jira Cloud REST API v3.

Mirrors tools/linear.py. Jira Cloud auth is HTTP Basic with the user's
account email + an API token (https://id.atlassian.com/manage-profile/security/api-tokens),
scoped to a site base URL (e.g. https://yoursite.atlassian.net). Issues need a
project key; we use the per-tool `project` arg, else the user's saved default.
"""

import base64
import os

import httpx

from .registry import register_tool

JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")


def _creds(user_settings: dict) -> tuple[str, str, str]:
    """Return (base_url, email, token) or raise with a clear message."""
    s = user_settings or {}
    base_url = (s.get("jira_base_url") or "").strip().rstrip("/")
    email = (s.get("jira_email") or "").strip()
    token = (s.get("jira_api_token") or JIRA_API_TOKEN or "").strip()
    if not base_url or not email or not token:
        raise Exception("Jira not connected — add your site URL, email, and API token in Integrations")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    return base_url, email, token


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _to_adf(text: str) -> dict:
    """Render the description into Atlassian Document Format (what Jira Cloud REST v3
    expects). Lightweight markdown-ish handling so a Prism-drafted ticket reads like a
    real Jira ticket, not a wall of text:
      - a short line ending in ':'  → bold section heading (e.g. 'Acceptance Criteria:')
      - lines starting '- ', '* ', '• ' → bulleted list
      - everything else            → a paragraph
    """
    lines = (text or "").split("\n")
    content: list = []
    bullets: list = []

    def _flush_bullets():
        if bullets:
            content.append({
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": b}]}
                    ]} for b in bullets
                ],
            })
            bullets.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped[:2] in ("- ", "* ") or stripped[:2] == "• " or stripped.startswith("•"):
            bullets.append(stripped.lstrip("-*• ").strip())
            continue
        _flush_bullets()
        if not stripped:
            content.append({"type": "paragraph", "content": []})
        elif len(stripped) <= 40 and stripped.endswith(":"):
            content.append({"type": "paragraph", "content": [
                {"type": "text", "text": stripped, "marks": [{"type": "strong"}]}
            ]})
        else:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": stripped}]})
    _flush_bullets()

    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}


async def jira_create_issue(args: dict, user_settings: dict | None = None) -> dict:
    base_url, email, token = _creds(user_settings or {})

    project_key = (args.get("project") or (user_settings or {}).get("jira_project_key") or "").strip()
    if not project_key:
        return {"error": "No Jira project key — set a default project in Integrations or pass one"}

    summary = args.get("title", "Untitled Issue")
    description = args.get("description", "")
    issue_type = args.get("issue_type") or "Task"

    # Prism identifier so these tickets are never lost in the backlog: a "[Prism]"
    # title prefix (visible on any board) + a `prism` label (filterable via JQL:
    # labels = prism) + a provenance footer in the description.
    if not summary.lstrip().lower().startswith("[prism]"):
        summary = f"[Prism] {summary}"
    description = (description or "").rstrip() + "\n\n—\n_Created by PrismAI from a meeting._"

    payload = {
        "fields": {
            "project": {"key": project_key.upper()},
            "summary": summary,
            "description": _to_adf(description),
            "issuetype": {"name": issue_type},
            "labels": ["prism"],
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/rest/api/3/issue",
                headers={
                    "Authorization": _auth_header(email, token),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=15,
            )
    except httpx.HTTPError as exc:
        return {"error": f"Jira request failed: {exc}"}

    if resp.status_code in (200, 201):
        data = resp.json()
        key = data.get("key")
        return {
            "success": True,
            "issue_id": key,
            "url": f"{base_url}/browse/{key}" if key else None,
            "summary": f"Created Jira issue {key}: {summary}",
        }

    # Surface Jira's own error text (e.g. bad project key, invalid issue type)
    detail = resp.text[:300]
    return {"error": f"Jira API error {resp.status_code}: {detail}"}


register_tool(
    name="jira_create_issue",
    description=(
        "Create a Jira issue. ONLY call this when the user explicitly uses a "
        "CREATE/FILE/OPEN/LOG verb for a ticket (create a ticket, file a Jira, log "
        "this in Jira, open an issue). Do NOT call this when the user asks to draft, "
        "outline, or describe a ticket — output the ticket text directly instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Issue summary/title"},
            "description": {"type": "string", "description": "Issue description (plain text; newlines preserved)"},
            "project": {"type": "string", "description": "Project key, e.g. 'PRISM' (optional, defaults to the saved project)"},
            "issue_type": {"type": "string", "description": "Issue type name (optional, defaults to 'Task')"},
        },
        "required": ["title"],
    },
    handler=jira_create_issue,
    requires="jira_api_token",
    confirm=True,
)

"""Linear tools: create issues via GraphQL API."""

import os

import httpx

from .registry import register_tool

LINEAR_API = "https://api.linear.app/graphql"
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")


def _get_key(user_settings: dict) -> str:
    key = user_settings.get("linear_api_key") or LINEAR_API_KEY
    if not key:
        raise Exception("Linear not connected — add LINEAR_API_KEY")
    return key


async def _get_team_id(key: str, team_name: str | None = None) -> str | None:
    """Get the first team ID, or match by name."""
    query = "{ teams { nodes { id name } } }"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            LINEAR_API,
            headers={"Authorization": key, "Content-Type": "application/json"},
            json={"query": query},
            timeout=10,
        )
    if resp.status_code != 200:
        return None
    teams = resp.json().get("data", {}).get("teams", {}).get("nodes", [])
    if not teams:
        return None
    if team_name:
        for t in teams:
            if t["name"].lower() == team_name.lower():
                return t["id"]
        return None
    return teams[0]["id"]


async def linear_create_issue(args: dict, user_settings: dict | None = None) -> dict:
    key = _get_key(user_settings)

    team_id = await _get_team_id(key, args.get("team"))
    if not team_id:
        return {"error": "No teams found in Linear workspace"}

    title = args.get("title", "Untitled Issue")
    description = args.get("description", "")
    priority = args.get("priority")

    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
        issueCreate(input: $input) {
            success
            issue {
                id
                identifier
                url
                title
            }
        }
    }
    """

    variables = {
        "input": {
            "teamId": team_id,
            "title": title,
            "description": description,
        }
    }
    if priority is not None:
        variables["input"]["priority"] = priority

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            LINEAR_API,
            headers={"Authorization": key, "Content-Type": "application/json"},
            json={"query": mutation, "variables": variables},
            timeout=15,
        )

    if resp.status_code != 200:
        return {"error": f"Linear API error {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    result = data.get("data", {}).get("issueCreate", {})
    if result.get("success"):
        issue = result.get("issue", {})
        return {
            "success": True,
            "issue_id": issue.get("identifier"),
            "url": issue.get("url"),
            "summary": f"Created Linear issue {issue.get('identifier')}: {title}",
        }
    else:
        errors = data.get("errors", [])
        return {"error": f"Linear create failed: {errors}"}


async def linear_validate(user_settings: dict | None = None) -> dict:
    """Cheap credential check (no writes): GraphQL `viewer` query. Returns
    {ok, account_name, error?} so the Integrations UI can confirm the Linear key
    works before a ticket fails. Accepts just-typed creds (same shape as create)."""
    try:
        key = _get_key(user_settings or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                LINEAR_API,
                headers={"Authorization": key, "Content-Type": "application/json"},
                json={"query": "{ viewer { name email } }"},
                timeout=12,
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Couldn't reach Linear: {exc}"}
    if resp.status_code in (401, 400):
        return {"ok": False, "error": "Invalid Linear API key."}
    if resp.status_code != 200:
        return {"ok": False, "error": f"Linear returned {resp.status_code}."}
    data = resp.json() or {}
    if data.get("errors"):
        return {"ok": False, "error": "Invalid Linear API key."}
    viewer = (data.get("data") or {}).get("viewer") or {}
    return {"ok": True, "account_name": viewer.get("name") or viewer.get("email") or "your account"}


# Register tool
register_tool(
    name="linear_create_issue",
    description=(
        "Create a Linear issue. ONLY call this when the user explicitly uses a "
        "CREATE/FILE/OPEN/LOG verb for a ticket (create a ticket, file an issue, log "
        "this, open a Linear). Do NOT call this when the user asks to draft a ticket, "
        "outline a ticket, or describe what a ticket would look like — output the "
        "ticket text directly as your reply in that case."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Issue title"},
            "description": {"type": "string", "description": "Issue description (markdown supported)"},
            "team": {"type": "string", "description": "Team name (optional, defaults to first team)"},
            "priority": {"type": "integer", "description": "Priority: 0=none, 1=urgent, 2=high, 3=medium, 4=low"},
        },
        "required": ["title"],
    },
    handler=linear_create_issue,
    requires="linear_api_key",
    confirm=True,
)

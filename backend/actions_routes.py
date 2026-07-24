"""Suggested-actions execution surface (feedback item #3).

The `action_executor` Tier-2 agent prepares one-click actions from the meeting owner's
own action items; this router executes ONE of them after the user has reviewed and
approved it in the SuggestedActions card. Approve-first: the frontend always opens the
pre-filled, editable payload before this fires — there is no silent auto-execution.

Security: only a small allowlist of resource-creating tools can be invoked here (never
read/search/knowledge tools), and execution is user-scoped via the auth dependency.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import supabase, require_user_id
from chat_routes import _get_user_settings
from tools.registry import confirm_and_execute, get_tool

router = APIRouter()

# Tools a reviewed suggested-action may invoke. Confined to resource-creating actions
# the SuggestedActions card offers — so this endpoint can't be turned into a generic
# arbitrary-tool runner (no knowledge_lookup / web_search / *_read / *_search).
_ALLOWED_TOOLS = {
    "gmail_send",
    "calendar_create_event",
    "jira_create_issue",
    "linear_create_issue",
    "slack_post_message",
}


class ActionExecuteRequest(BaseModel):
    tool: str
    args: dict
    meeting_id: str | None = None
    task: str | None = None      # the originating action-item text (for the audit ref)
    workspace_id: str | None = None  # explicit workspace for actions with no single meeting
                                     # (cross-meeting Trend "open thread" actions)


def _meeting_workspace_id(meeting_id) -> str | None:
    """Best-effort: the workspace a meeting belongs to, for per-workspace routing."""
    if not meeting_id or not supabase:
        return None
    try:
        res = supabase.table("meetings").select("workspace_id").eq("id", meeting_id).limit(1).execute()
        if res.data:
            ws = res.data[0].get("workspace_id")
            return str(ws) if ws else None
    except Exception as exc:
        print(f"[actions] workspace lookup skipped: {exc}")
    return None


@router.post("/actions/execute")
async def execute_action(req: ActionExecuteRequest, user_id: str = Depends(require_user_id)):
    """Execute a single user-approved suggested action. Returns the tool result
    (e.g. ticket/email/event ref) or a 4xx with the failure reason."""
    if req.tool not in _ALLOWED_TOOLS or get_tool(req.tool) is None:
        raise HTTPException(status_code=400, detail=f"Action '{req.tool}' is not executable here")

    # Load the user's integration credentials and inject user_id so token-based tools
    # (gmail/calendar) resolve the right account — mirrors registry.execute_tool.
    settings = await _get_user_settings(user_id) or {}
    # Per-workspace routing (#2): if this action came from a workspace meeting, overlay
    # the workspace's integration creds (per-provider, personal fallback) so the ticket/
    # message lands in the TEAM's Jira/Slack, not the acting user's personal one. A
    # cross-meeting Trend "open thread" action has no single meeting, so it passes the
    # active workspace_id explicitly — resolve_tool_settings is membership-checked
    # (fail-closed), so an arbitrary id can't leak another team's creds.
    workspace_id = _meeting_workspace_id(req.meeting_id) or (req.workspace_id or "").strip() or None
    if workspace_id:
        from workspace_integrations import resolve_tool_settings
        settings = await resolve_tool_settings(settings, user_id, workspace_id)
    settings["user_id"] = user_id

    result = await confirm_and_execute(req.tool, req.args, user_settings=settings)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # Record the resolution so the action item shows as handled (same table the chat /
    # live-bot tool paths write). Best-effort — never fail the response on a log miss.
    ext = result.get("external_ref")
    if ext and supabase:
        try:
            supabase.table("action_refs").insert({
                "user_id": user_id,
                "action_item": (req.task or "")[:500],
                "tool": ext["tool"],
                "external_id": str(ext["external_id"]),
            }).execute()
        except Exception as exc:
            print(f"[actions] action_ref log skipped: {exc}")

    return result

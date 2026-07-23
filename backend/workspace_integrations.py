"""Per-workspace integrations resolver (#2).

`resolve_tool_settings()` overlays a workspace's configured integration creds on
top of the acting user's personal settings — per-provider, all-or-nothing, with a
personal fallback. This is the single routing point that makes a team meeting's
tickets/messages go to the TEAM's Jira/Slack instead of whoever's bot ran it.

Design (see docs/plans/2026-07-15-per-workspace-integrations.md):
- Per-provider precedence: a workspace's complete+enabled config wins for that
  provider; otherwise the acting user's personal creds are used.
- All-or-nothing per provider: never field-mix (e.g. a workspace jira_base_url with
  a personal jira_api_token) — the required fields must all be present, and optional
  fields absent from the workspace config are CLEARED.
- OAuth (google_*/ms_*) is never overlaid — it stays personal in v1.
- Backward-compatible: with no workspace_integrations rows (or the flag off), the
  output equals the personal settings, so behavior is identical to today.

Reads go through the service-role client (`auth.supabase`), which bypasses the
table's RLS — the table holds secrets and is server-side only.
"""

import asyncio
import os

from auth import supabase


def _flag_on() -> bool:
    """Gate the workspace-overlay branch. Default ON; set PRISM_WORKSPACE_INTEGRATIONS=0
    to fall back to purely-personal routing instantly."""
    return os.getenv("PRISM_WORKSPACE_INTEGRATIONS", "1").strip().lower() not in ("0", "false", "no", "off", "")


# provider -> required fields (all must be present for the workspace config to be
# usable) + the full field set to overlay (absent optionals clear the personal
# value → true all-or-nothing per provider). Field names mirror user_settings so
# the merged output is a drop-in for get_available_tools / confirm_and_execute.
PROVIDER_FIELDS = {
    "jira":   {"required": ("jira_base_url", "jira_email", "jira_api_token"),
               "all": ("jira_base_url", "jira_email", "jira_api_token", "jira_project_key")},
    "linear": {"required": ("linear_api_key",), "all": ("linear_api_key",)},
    "slack":  {"required": ("slack_bot_token",), "all": ("slack_bot_token", "slack_webhook")},
    "teams":  {"required": ("teams_webhook",), "all": ("teams_webhook",)},
    "notion": {"required": ("notion_token",), "all": ("notion_token", "notion_page_id")},
}


def _nonempty(v) -> bool:
    return bool(v and str(v).strip())


def _load_workspace_integrations(workspace_id: str) -> dict:
    """Sync: {provider: config} for this workspace's ENABLED rows. Service-role
    (bypasses RLS). Best-effort — returns {} on any failure."""
    if not supabase or not workspace_id:
        return {}
    try:
        res = (
            supabase.table("workspace_integrations")
            .select("provider, config, enabled")
            .eq("workspace_id", str(workspace_id))
            .execute()
        )
    except Exception as exc:
        print(f"[ws-integrations] load failed ws={workspace_id}: {exc!r}")
        return {}
    out: dict = {}
    for row in (res.data or []):
        if row.get("enabled") is False:
            continue
        cfg = row.get("config") or {}
        if isinstance(cfg, dict) and row.get("provider"):
            out[row["provider"]] = cfg
    return out


def _is_member(user_id: str, workspace_id: str) -> bool:
    """Sync: is the user a member of the workspace? Service-role. Fail-closed
    (returns False on any error) so a lookup failure never routes a non-member."""
    if not supabase or not user_id or not workspace_id:
        return False
    try:
        res = (
            supabase.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", str(workspace_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        print(f"[ws-integrations] membership check failed ws={workspace_id}: {exc!r}")
        return False


def apply_workspace_overlay(personal: dict, ws_rows: dict) -> dict:
    """Pure: overlay complete workspace provider configs on top of personal settings.
    Per-provider all-or-nothing; optionals absent from the workspace config are
    cleared; non-provider fields (OAuth, personas, etc.) are untouched. New dict."""
    merged = dict(personal or {})
    for provider, spec in PROVIDER_FIELDS.items():
        cfg = ws_rows.get(provider)
        if not isinstance(cfg, dict):
            continue
        if all(_nonempty(cfg.get(f)) for f in spec["required"]):
            for f in spec["all"]:
                merged[f] = cfg.get(f) or None
    return merged


async def resolve_tool_settings(personal: dict, user_id: str, workspace_id: str | None) -> dict:
    """The routing point: personal settings with the meeting's workspace integration
    creds overlaid (per-provider, personal fallback). Pass the ALREADY-loaded personal
    settings — each call site loads them its own way (chat's _get_user_settings keeps
    Google token refresh; the bot's _get_settings_for_bot; etc.). Returns `personal`
    unchanged when there's no workspace, the flag is off, or the caller isn't a member."""
    if not workspace_id or not _flag_on():
        return personal or {}
    # Defense-in-depth: never route a non-member through a workspace's creds.
    if not await asyncio.to_thread(_is_member, user_id, workspace_id):
        return personal or {}
    ws_rows = await asyncio.to_thread(_load_workspace_integrations, workspace_id)
    if not ws_rows:
        return personal or {}
    return apply_workspace_overlay(personal or {}, ws_rows)

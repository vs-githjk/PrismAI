import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase
from caches import invalidate_user_workspaces


router = APIRouter(tags=["workspaces"])


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


def _require_owner(client, workspace_id: str, user_id: str):
    res = (
        client.table("workspace_members")
        .select("role")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not res.data or res.data["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")


class CreateWorkspaceRequest(BaseModel):
    name: str
    user_email: str = ""


class RenameWorkspaceRequest(BaseModel):
    name: str | None = None
    default_persona: str | None = None


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------

@router.post("/workspaces")
async def create_workspace(body: CreateWorkspaceRequest, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workspace name is required")

    ws = client.table("workspaces").insert({
        "name": name,
        "created_by": user_id,
    }).execute()
    workspace = ws.data[0]

    client.table("workspace_members").insert({
        "workspace_id": workspace["id"],
        "user_id": user_id,
        "user_email": body.user_email or "",
        "role": "owner",
    }).execute()

    invalidate_user_workspaces(user_id)
    return workspace


@router.get("/workspaces")
async def list_workspaces(user_id: str = Depends(require_user_id)):
    client = _require_storage()
    memberships = (
        client.table("workspace_members")
        .select("workspace_id, role")
        .eq("user_id", user_id)
        .execute()
    )
    if not memberships.data:
        return []

    workspace_ids = [m["workspace_id"] for m in memberships.data]
    role_map = {m["workspace_id"]: m["role"] for m in memberships.data}

    workspaces = (
        client.table("workspaces")
        .select("id, name, invite_token, created_at, default_persona")
        .in_("id", workspace_ids)
        .order("created_at")
        .execute()
    )

    all_members = (
        client.table("workspace_members")
        .select("workspace_id, user_email")
        .in_("workspace_id", workspace_ids)
        .execute()
    )
    member_data: dict = {}
    for m in (all_members.data or []):
        wsid = m["workspace_id"]
        if wsid not in member_data:
            member_data[wsid] = {"count": 0, "emails": []}
        member_data[wsid]["count"] += 1
        if m.get("user_email"):
            member_data[wsid]["emails"].append(m["user_email"])

    result = []
    for ws in (workspaces.data or []):
        md = member_data.get(ws["id"], {"count": 0, "emails": []})
        result.append({
            **ws,
            "role": role_map.get(ws["id"], "member"),
            "member_count": md["count"],
            "member_emails": md["emails"],
        })
    return result


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    # Verify membership
    membership = (
        client.table("workspace_members")
        .select("role")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not membership.data:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws = (
        client.table("workspaces")
        .select("id, name, invite_token, created_at, default_persona")
        .eq("id", workspace_id)
        .maybe_single()
        .execute()
    )
    if not ws.data:
        raise HTTPException(status_code=404, detail="Workspace not found")

    members = (
        client.table("workspace_members")
        .select("user_id, user_email, role, joined_at")
        .eq("workspace_id", workspace_id)
        .order("joined_at")
        .execute()
    )

    return {
        **ws.data,
        "your_role": membership.data["role"],
        "members": members.data or [],
    }


@router.patch("/workspaces/{workspace_id}")
async def rename_workspace(workspace_id: str, body: RenameWorkspaceRequest, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    _require_owner(client, workspace_id, user_id)
    update: dict = {}
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Workspace name is required")
        update["name"] = name
    if body.default_persona is not None:
        # DB CHECK constraint enforces the allowed value set — frontend
        # restricts the picker too. Don't second-guess here.
        update["default_persona"] = body.default_persona
    if not update:
        return {"ok": True}
    client.table("workspaces").update(update).eq("id", workspace_id).execute()
    if "default_persona" in update:
        from personas import invalidate_persona
        invalidate_persona(workspace_id=workspace_id)
    return {"ok": True}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    _require_owner(client, workspace_id, user_id)
    # meetings.workspace_id → set null on delete (handled by DB constraint)
    client.table("workspaces").delete().eq("id", workspace_id).execute()
    # Every member of this workspace had it in their cached list; safest to clear all.
    # Workspace deletions are rare, so the next handful of users pay one DB query each.
    invalidate_user_workspaces(None)
    # Drop any persona cache entries pinned to this workspace so a removed
    # member doesn't keep seeing the workspace default for up to the TTL.
    from personas import invalidate_persona
    invalidate_persona(workspace_id=workspace_id)
    return {"ok": True}


@router.delete("/workspaces/{workspace_id}/members/{target_user_id}")
async def remove_member(workspace_id: str, target_user_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    # Owner can remove anyone; members can only remove themselves (leave)
    if target_user_id != user_id:
        _require_owner(client, workspace_id, user_id)
    # Prevent owner from removing themselves if they're the only owner
    if target_user_id == user_id:
        membership = (
            client.table("workspace_members")
            .select("role")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if membership.data and membership.data["role"] == "owner":
            other_owners = (
                client.table("workspace_members")
                .select("user_id", count="exact")
                .eq("workspace_id", workspace_id)
                .eq("role", "owner")
                .neq("user_id", user_id)
                .execute()
            )
            if (other_owners.count or 0) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot leave — you are the only owner. Delete the workspace or transfer ownership first."
                )
    client.table("workspace_members").delete().eq("workspace_id", workspace_id).eq("user_id", target_user_id).execute()
    invalidate_user_workspaces(target_user_id)
    # Removed member shouldn't keep resolving the workspace default for up to
    # the persona cache TTL. Both the user's own key and the workspace key get
    # dropped (their cached entry may have been keyed under either).
    from personas import invalidate_persona
    invalidate_persona(user_id=target_user_id, workspace_id=workspace_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Invite routes
# ---------------------------------------------------------------------------

@router.get("/invites/{token}")
async def get_invite(token: str):
    """Public — no auth required. Returns workspace name + member count for the accept screen."""
    client = _require_storage()
    ws = (
        client.table("workspaces")
        .select("id, name")
        .eq("invite_token", token)
        .maybe_single()
        .execute()
    )
    if not ws.data:
        raise HTTPException(status_code=404, detail="Invite link not found or has been revoked")

    member_count = (
        client.table("workspace_members")
        .select("user_id", count="exact")
        .eq("workspace_id", ws.data["id"])
        .execute()
    )
    return {
        "workspace_id": ws.data["id"],
        "workspace_name": ws.data["name"],
        "member_count": member_count.count or 0,
    }


class AcceptInviteRequest(BaseModel):
    user_email: str = ""


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, body: AcceptInviteRequest, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    ws = (
        client.table("workspaces")
        .select("id, name")
        .eq("invite_token", token)
        .maybe_single()
        .execute()
    )
    if not ws.data:
        raise HTTPException(status_code=404, detail="Invite link not found or has been revoked")

    workspace_id = ws.data["id"]

    # Upsert — safe to call multiple times (idempotent)
    client.table("workspace_members").upsert(
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "user_email": body.user_email or "",
            "role": "member",
        },
        on_conflict="workspace_id,user_id",
        ignore_duplicates=True,
    ).execute()

    invalidate_user_workspaces(user_id)
    return {"ok": True, "workspace_id": workspace_id, "workspace_name": ws.data["name"]}


@router.post("/workspaces/{workspace_id}/regenerate-invite")
async def regenerate_invite(workspace_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    _require_owner(client, workspace_id, user_id)
    new_token = str(uuid.uuid4())
    client.table("workspaces").update({"invite_token": new_token}).eq("id", workspace_id).execute()
    return {"invite_token": new_token}


@router.get("/workspaces/{workspace_id}/brief")
async def get_workspace_brief(workspace_id: str, user_id: str = Depends(require_user_id)):
    """Open (unchecked) action items from this workspace's meetings in the last 30 days,
    so a user joining an upcoming workspace meeting can see what's still outstanding.
    Each item links back to the source meeting via meeting_id."""
    client = _require_storage()

    # Verify membership
    membership = (
        client.table("workspace_members")
        .select("role")
        .eq("workspace_id", workspace_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not membership.data:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = (
        client.table("meetings")
        .select("id,date,title,result,user_id,recorded_by_user_id")
        .eq("workspace_id", workspace_id)
        .gte("date", since)
        .order("date", desc=True)
        .limit(200)
        .execute()
    )

    # Dedup fan-out copies by date[:16], preferring the current user's row so meeting_id
    # in the response opens correctly in their dashboard.
    dedup_map: dict = {}
    for row in (res.data or []):
        key = row.get("date", "")[:16]
        if key not in dedup_map or row.get("user_id") == user_id:
            dedup_map[key] = row
    meetings = sorted(dedup_map.values(), key=lambda r: r.get("date", ""), reverse=True)

    open_items: list[dict] = []
    for meeting in meetings:
        result = meeting.get("result") or {}
        for item in (result.get("action_items") or []):
            if item.get("completed"):
                continue
            task = (item.get("task") or "").strip()
            if not task:
                continue
            open_items.append({
                "task": task,
                "owner": (item.get("owner") or "").strip(),
                "due": (item.get("due") or "").strip(),
                "due_date": (item.get("due_date") or "").strip(),
                "meeting_id": meeting.get("id"),
                "meeting_title": meeting.get("title") or "Untitled meeting",
                "meeting_date": meeting.get("date") or "",
            })

    # Deadline-aware: dated items first (overdue/soonest), undated last; then cap.
    open_items.sort(key=lambda x: (not x["due_date"], x["due_date"]))
    return {"open_items": open_items[:10]}


# ── Per-workspace integrations (#2) ──────────────────────────────────────────
# Owner configures Jira/Linear/Slack/Teams/Notion once per workspace; the resolver
# (workspace_integrations.resolve_tool_settings) routes the workspace's meetings
# there. GET is member-gated and returns only a NON-SECRET status/label — raw
# tokens never leave the server (RLS + this). Writes are owner-only.
_INTEG_PROVIDERS = ("jira", "linear", "slack", "teams", "notion")


def _require_member(client, workspace_id: str, user_id: str) -> str:
    res = (
        client.table("workspace_members").select("role")
        .eq("workspace_id", workspace_id).eq("user_id", user_id).maybe_single().execute()
    )
    if not res.data:
        raise HTTPException(status_code=403, detail="Workspace membership required")
    return res.data.get("role") or "member"


def _integration_label(provider: str, cfg: dict) -> str:
    """A safe, non-secret one-liner summarizing a configured integration."""
    cfg = cfg or {}
    if provider == "jira":
        parts = [cfg.get("jira_email") or "", cfg.get("jira_project_key") or ""]
        return " · ".join(p for p in parts if p) or "configured"
    if provider == "linear":
        return "API key set" if cfg.get("linear_api_key") else "not set"
    if provider == "slack":
        if cfg.get("slack_bot_token"):
            return "bot token set"
        return "webhook set" if cfg.get("slack_webhook") else "not set"
    if provider == "teams":
        return "webhook set" if cfg.get("teams_webhook") else "not set"
    if provider == "notion":
        return "token set" if cfg.get("notion_token") else "not set"
    return "configured"


class WorkspaceIntegrationConfig(BaseModel):
    config: dict = {}
    enabled: bool = True


@router.get("/workspaces/{workspace_id}/integrations")
async def list_workspace_integrations(workspace_id: str, user_id: str = Depends(require_user_id)):
    """Member-gated. Per-provider status + a masked label — NEVER raw secrets.
    `can_edit` tells the UI whether this member may configure (owner-only)."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    role = _require_member(supabase, workspace_id, user_id)
    res = (
        supabase.table("workspace_integrations")
        .select("provider, config, enabled, updated_at").eq("workspace_id", workspace_id).execute()
    )
    rows = {r["provider"]: r for r in (res.data or [])}
    out = []
    for p in _INTEG_PROVIDERS:
        r = rows.get(p)
        cfg = (r or {}).get("config") or {}
        out.append({
            "provider": p,
            "connected": bool(r) and bool(cfg),
            "enabled": (r or {}).get("enabled", True),
            "label": _integration_label(p, cfg) if r else None,
            "updated_at": (r or {}).get("updated_at"),
        })
    return {"integrations": out, "can_edit": role == "owner"}


@router.put("/workspaces/{workspace_id}/integrations/{provider}")
async def set_workspace_integration(workspace_id: str, provider: str,
                                    body: WorkspaceIntegrationConfig,
                                    user_id: str = Depends(require_user_id)):
    """Owner-gated. Upsert a provider's config for the workspace (only known fields
    are persisted)."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    provider = (provider or "").lower()
    if provider not in _INTEG_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")
    _require_owner(supabase, workspace_id, user_id)
    from workspace_integrations import PROVIDER_FIELDS
    allowed = set(PROVIDER_FIELDS[provider]["all"])
    clean = {k: v for k, v in (body.config or {}).items() if k in allowed}
    supabase.table("workspace_integrations").upsert({
        "workspace_id": workspace_id,
        "provider": provider,
        "config": clean,
        "enabled": bool(body.enabled),
        "configured_by": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="workspace_id,provider").execute()
    return {"ok": True}


@router.delete("/workspaces/{workspace_id}/integrations/{provider}")
async def delete_workspace_integration(workspace_id: str, provider: str,
                                       user_id: str = Depends(require_user_id)):
    """Owner-gated. Disconnect a provider for the workspace."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    _require_owner(supabase, workspace_id, user_id)
    supabase.table("workspace_integrations").delete().eq(
        "workspace_id", workspace_id).eq("provider", (provider or "").lower()).execute()
    return {"ok": True}

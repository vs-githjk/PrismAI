import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase


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
    name: str


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
        .select("id, name, invite_token, created_at")
        .in_("id", workspace_ids)
        .order("created_at")
        .execute()
    )

    result = []
    for ws in (workspaces.data or []):
        member_count = (
            client.table("workspace_members")
            .select("user_id", count="exact")
            .eq("workspace_id", ws["id"])
            .execute()
        )
        result.append({
            **ws,
            "role": role_map.get(ws["id"], "member"),
            "member_count": member_count.count or 0,
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
        .select("id, name, invite_token, created_at")
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
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workspace name is required")
    client.table("workspaces").update({"name": name}).eq("id", workspace_id).execute()
    return {"ok": True}


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    _require_owner(client, workspace_id, user_id)
    # meetings.workspace_id → set null on delete (handled by DB constraint)
    client.table("workspaces").delete().eq("id", workspace_id).execute()
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

    return {"ok": True, "workspace_id": workspace_id, "workspace_name": ws.data["name"]}


@router.post("/workspaces/{workspace_id}/regenerate-invite")
async def regenerate_invite(workspace_id: str, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    _require_owner(client, workspace_id, user_id)
    new_token = str(uuid.uuid4())
    client.table("workspaces").update({"invite_token": new_token}).eq("id", workspace_id).execute()
    return {"invite_token": new_token}

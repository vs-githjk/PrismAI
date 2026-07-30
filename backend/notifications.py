"""Notification center (#9) — persistent bell + unread + history.

Two kinds of notification:
  • STORED (event-driven): meeting_ready / bot_issue / workspace_activity /
    meeting_soon. Written by `create_notification()` from event hooks; deduped by
    (user_id, dedup_key) so hooks are idempotent.
  • SYNTHESIZED (action_due): computed fresh at GET-time from the user's open
    action items so overdue status can never go stale. Never stored — read-state
    for these is client-managed (localStorage), keyed by their stable id.

All access is service-role (auth.supabase) and scoped by user_id in-query — the
table has RLS on with no policies, so the anon/authenticated keys are denied.
Every write is best-effort and never raises into the caller.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from auth import supabase

_TABLE = "notifications"
_MAX_STORED = 40


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── writes (event hooks call this) ────────────────────────────────────────────
def create_notification(user_id: str, type: str, title: str, body: str | None = None,
                        *, meeting_id: int | None = None, link: str | None = None,
                        workspace_id: str | None = None, dedup_key: str | None = None) -> None:
    """Best-effort insert of a stored notification. If dedup_key is given the write
    is idempotent — a repeat with the same (user_id, dedup_key) is ignored, so an
    event hook that fires twice (webhook + poll fallback) only notifies once.
    Never raises; a notification failing must not break the event that triggered it."""
    if not supabase or not user_id or not type:
        return
    row = {
        "user_id": str(user_id), "type": type, "title": title, "body": body,
        "meeting_id": meeting_id, "link": link,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "dedup_key": dedup_key, "read": False, "created_at": _now_iso(),
    }
    try:
        if dedup_key:
            supabase.table(_TABLE).upsert(
                row, on_conflict="user_id,dedup_key", ignore_duplicates=True
            ).execute()
        else:
            supabase.table(_TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — best-effort
        print(f"[notifications] create failed uid={str(user_id)[:8]} type={type}: {exc!r}")


# ── reads ─────────────────────────────────────────────────────────────────────
def list_stored(user_id: str, limit: int = _MAX_STORED) -> list[dict]:
    if not supabase or not user_id:
        return []
    try:
        res = (
            supabase.table(_TABLE)
            .select("id, type, title, body, meeting_id, link, workspace_id, read, created_at")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True).limit(limit).execute()
        )
        return res.data or []
    except Exception as exc:  # noqa: BLE001
        print(f"[notifications] list failed uid={str(user_id)[:8]}: {exc!r}")
        return []


def unread_count(user_id: str) -> int:
    if not supabase or not user_id:
        return 0
    try:
        res = (
            supabase.table(_TABLE).select("id", count="exact")
            .eq("user_id", str(user_id)).eq("read", False).execute()
        )
        return res.count or 0
    except Exception as exc:  # noqa: BLE001
        print(f"[notifications] unread_count failed uid={str(user_id)[:8]}: {exc!r}")
        return 0


def mark_read(user_id: str, notif_id: int) -> bool:
    if not supabase or not user_id:
        return False
    try:
        res = (
            supabase.table(_TABLE).update({"read": True})
            .eq("user_id", str(user_id)).eq("id", notif_id).execute()
        )
        return bool(res.data)
    except Exception as exc:  # noqa: BLE001
        print(f"[notifications] mark_read failed uid={str(user_id)[:8]}: {exc!r}")
        return False


def mark_all_read(user_id: str) -> None:
    if not supabase or not user_id:
        return
    try:
        supabase.table(_TABLE).update({"read": True}).eq("user_id", str(user_id)).eq("read", False).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[notifications] mark_all_read failed uid={str(user_id)[:8]}: {exc!r}")


# ── action_due synthesis (fresh at GET, never stored) ─────────────────────────
def _user_names(user_id: str) -> list[str]:
    """Display names this user's action items might be owned under. Derived from
    the email local part (owner strings are free-text names from the transcript,
    not linked accounts — so this is a soft match)."""
    from recall_routes import _name_from_email, resolve_owner_email
    email = ""
    try:
        # resolve_owner_email needs a bot_id; call the member-lookup path directly.
        wm = (
            supabase.table("workspace_members").select("user_email")
            .eq("user_id", str(user_id)).limit(1).execute()
        )
        if wm.data and (wm.data[0].get("user_email") or "").strip():
            email = wm.data[0]["user_email"].strip()
    except Exception:
        email = ""
    if not email:
        try:
            u = supabase.auth.admin.get_user_by_id(str(user_id))
            email = (getattr(getattr(u, "user", None), "email", "") or "").strip()
        except Exception:
            email = ""
    if not email:
        return []
    name = _name_from_email(email)
    parts = [p for p in name.replace(".", " ").split() if len(p) > 1]
    return list({name, *parts})


def _due_status(due_date_iso: str) -> tuple[str | None, int]:
    """('overdue'|'soon'|'later'|None, diffDays). soon = 0..3 days out."""
    if not due_date_iso:
        return None, 0
    try:
        d = datetime.strptime(due_date_iso[:10], "%Y-%m-%d").date()
    except Exception:
        return None, 0
    diff = (d - datetime.now(timezone.utc).date()).days
    if diff < 0:
        return "overdue", diff
    if diff <= 3:
        return "soon", diff
    return "later", diff


def synthesize_action_due(user_id: str) -> list[dict]:
    """Open action items owned by this user that are overdue or due soon, across
    their recent meetings (their own + fan-out workspace copies all carry their
    user_id). Returned as notification-shaped dicts with a STABLE id so the client
    can track read/dismiss state locally."""
    if not supabase or not user_id:
        return []
    names = _user_names(user_id)
    if not names:
        return []
    from proxy_routes import _user_owns_item  # fuzzy owner match, reused
    low_names = [n.lower() for n in names]
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        rows = (
            supabase.table("meetings").select("id, title, result, workspace_id")
            .eq("user_id", str(user_id)).gte("date", since)
            .order("date", desc=True).limit(80).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        print(f"[notifications] action_due fetch failed uid={str(user_id)[:8]}: {exc!r}")
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for m in rows:
        result = m.get("result") or {}
        for item in (result.get("action_items") or []):
            if not isinstance(item, dict):
                continue
            task = (item.get("task") or "").strip()
            if not task or item.get("completed") or item.get("checked"):
                continue
            if not _user_owns_item(item.get("owner", ""), low_names):
                continue
            status, diff = _due_status(item.get("due_date") or "")
            if status not in ("overdue", "soon"):
                continue
            mid = m.get("id")
            key = f"{mid}:{hashlib.md5(task.lower().encode()).hexdigest()[:8]}"
            if key in seen:
                continue
            seen.add(key)
            when = ("Overdue" if status == "overdue" else
                    "Due today" if diff == 0 else
                    "Due tomorrow" if diff == 1 else f"Due in {diff}d")
            out.append({
                "id": f"action_due:{key}",
                "type": "action_due",
                "title": when,
                "body": task,
                "meeting_id": mid,
                "link": None,
                "workspace_id": m.get("workspace_id"),
                "read": False,
                "created_at": _now_iso(),
                "synthesized": True,
                "sort_key": diff,  # overdue/soonest first
            })
    out.sort(key=lambda n: n["sort_key"])
    return out[:15]

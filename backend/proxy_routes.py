"""Stand-in async proxy (Feature A) — A1: the composer.

A workspace member who can't attend a meeting has Prism represent them. They open
a composer (a chat with the bot), which drafts an update from their open action
items + their standing proxy profile, refine it by conversation, then approve. The
approved text is frozen as their stand-in for that meeting.

A1 scope: tables + composer endpoints (draft -> converse -> approve/cancel) + the
standing profile get/upsert. Scheduled-bot delivery (A2/A3) and profile-enrichment
on approve (A4) land in later slices.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase
from caches import is_workspace_member
from clients import get_openai
from recall_routes import _normalize_meeting_url

router = APIRouter(tags=["proxy"])

# Bot names that mark a transcript action-item owner as NOT the user. (unused here
# but kept explicit: owner matching is by display name — see _user_owns_item.)
_DRAFT_MODEL = "gpt-4o-mini"


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


# ── Profile ──────────────────────────────────────────────────────────────────
def _load_profile(user_id: str) -> dict:
    try:
        res = supabase.table("proxy_profiles").select("*").eq("user_id", user_id).maybe_single().execute()
        return res.data or {}
    except Exception:
        return {}


def _profile_context(profile: dict) -> str:
    parts = []
    if (profile.get("role_focus") or "").strip():
        parts.append(f"Role / focus: {profile['role_focus'].strip()}")
    if (profile.get("standing_notes") or "").strip():
        parts.append(f"Standing notes: {profile['standing_notes'].strip()}")
    return "\n".join(parts)


# ── Action-item synthesis source (the "meaningful update" fuel) ───────────────
def _user_owns_item(owner: str, names: list[str]) -> bool:
    """Fuzzy name match: an action item is 'mine' if its owner string contains
    (or is contained by) one of my known display names. owner is free text from
    the transcript, not a linked account — hence the soft match."""
    o = (owner or "").strip().lower()
    if not o or o in ("unassigned", "tbd", "everyone", "team"):
        return False
    for n in names:
        n = (n or "").strip().lower()
        if n and (n in o or o in n):
            return True
    return False


def _gather_my_items(user_id: str, names: list[str]) -> dict:
    """Pull the caller's recent action items (open + completed) across their last
    30 days of meetings, name-matched. Returns {open: [...], done: [...]}."""
    out = {"open": [], "done": []}
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        res = (
            supabase.table("meetings")
            .select("title,date,result")
            .eq("user_id", user_id)
            .gte("date", since)
            .order("date", desc=True)
            .limit(60)
            .execute()
        )
    except Exception:
        return out
    for meeting in (res.data or []):
        result = meeting.get("result") or {}
        for item in (result.get("action_items") or []):
            task = (item.get("task") or "").strip()
            if not task or not _user_owns_item(item.get("owner", ""), names):
                continue
            entry = {"task": task, "due": (item.get("due") or "").strip(),
                     "meeting": meeting.get("title") or "a meeting"}
            (out["done"] if item.get("completed") else out["open"]).append(entry)
    return out


def _items_block(items: dict) -> str:
    parts = []
    if items["open"]:
        parts.append("Your open action items:\n" + "\n".join(
            f"- {i['task']}" + (f" (due {i['due']})" if i["due"] else "") for i in items["open"][:12]
        ))
    if items["done"]:
        parts.append("Recently completed by you:\n" + "\n".join(
            f"- {i['task']}" for i in items["done"][:8]
        ))
    return "\n\n".join(parts) if parts else "(no recent action items found under your name)"


def _draft_system(profile_ctx: str, items_block: str, meeting_label: str) -> str:
    base = (
        "You are drafting a short stand-in update on behalf of a user who can't attend "
        f"a meeting ({meeting_label or 'an upcoming meeting'}). Write in the user's own "
        "voice, first person, like a concise stand-up update: what they've finished, "
        "what's in progress, and any blockers. 2-4 sentences. Ground it ONLY in the "
        "action items and profile provided — never invent completed work. If something is "
        "ambiguous (e.g. an item could be done or not), ask the user a brief clarifying "
        "question instead of guessing."
    )
    ctx = ""
    if profile_ctx:
        ctx += f"\n\nWho they are:\n{profile_ctx}"
    ctx += f"\n\n{items_block}"
    return base + ctx


async def _llm_reply(system: str, history: list[dict], user_msg: str | None) -> str:
    client = get_openai()
    if client is None:
        return "I can't draft this right now — the assistant is unavailable."
    messages = [{"role": "system", "content": system}] + history
    if user_msg is not None:
        messages.append({"role": "user", "content": user_msg})
    try:
        resp = await client.chat.completions.create(
            model=_DRAFT_MODEL, temperature=0.4, max_tokens=400, messages=messages,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[proxy] draft llm failed: {exc}")
        return "Sorry, I had trouble drafting that. Try again?"


def _author_names(user_id: str, author_name: str, author_email: str) -> list[str]:
    names = []
    if author_name:
        names.append(author_name)
        names.append(author_name.split()[0])  # first name
    if author_email:
        names.append(author_email.split("@")[0])
    return [n for n in names if n]


# ── Requests ─────────────────────────────────────────────────────────────────
class CreateRepRequest(BaseModel):
    meeting_url: str
    workspace_id: str | None = None
    meeting_label: str = ""
    calendar_event_id: str | None = None
    scheduled_for: str | None = None  # ISO; meeting start
    author_name: str = ""
    author_email: str = ""


class MessageRequest(BaseModel):
    message: str
    # The conversation transcript so far, [{role, content}], owned by the client.
    history: list[dict] = []


class ApproveRequest(BaseModel):
    approved_body: str


class ProfileRequest(BaseModel):
    role_focus: str = ""
    standing_notes: str = ""


def _gate_workspace(user_id: str, workspace_id: str | None):
    if workspace_id and not is_workspace_member(supabase, user_id, workspace_id):
        raise HTTPException(status_code=403, detail="Not a member of this workspace")


def _owned_rep(rep_id: str, user_id: str) -> dict:
    res = supabase.table("proxy_representations").select("*").eq("id", rep_id).maybe_single().execute()
    row = res.data if res else None
    if not row or row.get("author_user_id") != user_id:
        raise HTTPException(status_code=404, detail="Stand-in not found")
    return row


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.post("/proxy/representations")
async def create_representation(body: CreateRepRequest, user_id: str = Depends(require_user_id)):
    """Start a stand-in for a meeting. Drafts a first-pass update from the caller's
    action items + standing profile, persists a draft row, returns it + the draft."""
    _require_storage()
    _gate_workspace(user_id, body.workspace_id)
    if not body.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL required")

    normalized = _normalize_meeting_url(body.meeting_url)
    names = _author_names(user_id, body.author_name, body.author_email)
    profile = _load_profile(user_id)
    items = _gather_my_items(user_id, names)
    system = _draft_system(_profile_context(profile), _items_block(items), body.meeting_label)
    draft = await _llm_reply(system, [], "Draft my stand-in update for this meeting.")

    row = {
        "workspace_id": body.workspace_id,
        "meeting_url": normalized,
        "calendar_event_id": body.calendar_event_id,
        "meeting_label": body.meeting_label,
        "scheduled_for": body.scheduled_for,
        "author_user_id": user_id,
        "author_name": body.author_name,
        "author_email": body.author_email,
        "draft_body": draft,
        "status": "draft",
    }
    res = supabase.table("proxy_representations").insert(row).execute()
    saved = (res.data or [row])[0]
    return {"representation": saved, "draft": draft, "system": system}


@router.post("/proxy/representations/{rep_id}/message")
async def converse(rep_id: str, body: MessageRequest, user_id: str = Depends(require_user_id)):
    """One conversational turn refining the stand-in. Returns the bot reply and the
    updated working draft (the reply IS the new draft text)."""
    _require_storage()
    row = _owned_rep(rep_id, user_id)
    if row.get("status") not in ("draft",):
        raise HTTPException(status_code=400, detail="This stand-in is no longer editable")

    names = _author_names(user_id, row.get("author_name", ""), row.get("author_email", ""))
    profile = _load_profile(user_id)
    items = _gather_my_items(user_id, names)
    system = _draft_system(_profile_context(profile), _items_block(items), row.get("meeting_label", ""))
    system += (
        "\n\nThe user is refining the draft. Reply conversationally AND end your message "
        "with the full updated draft on its own, prefixed exactly with 'DRAFT: '."
    )
    reply = await _llm_reply(system, body.history or [], body.message)

    # Extract the updated draft if the model marked one; else keep the reply as draft.
    new_draft = reply
    if "DRAFT:" in reply:
        new_draft = reply.split("DRAFT:", 1)[1].strip()
    supabase.table("proxy_representations").update({"draft_body": new_draft}).eq("id", rep_id).execute()
    return {"reply": reply, "draft": new_draft}


@router.post("/proxy/representations/{rep_id}/approve")
async def approve(rep_id: str, body: ApproveRequest, user_id: str = Depends(require_user_id)):
    """Freeze the approved text. A1 stops here (status -> pending); A2 attaches a
    scheduled bot for delivery, A4 enriches the standing profile."""
    _require_storage()
    _owned_rep(rep_id, user_id)
    text = (body.approved_body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to approve")
    supabase.table("proxy_representations").update({
        "approved_body": text,
        "draft_body": text,
        "status": "pending",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", rep_id).execute()
    return {"ok": True, "status": "pending"}


@router.post("/proxy/representations/{rep_id}/cancel")
async def cancel(rep_id: str, user_id: str = Depends(require_user_id)):
    _require_storage()
    _owned_rep(rep_id, user_id)
    supabase.table("proxy_representations").update({"status": "canceled"}).eq("id", rep_id).execute()
    return {"ok": True, "status": "canceled"}


@router.get("/proxy/representations")
async def list_representations(user_id: str = Depends(require_user_id)):
    _require_storage()
    res = (
        supabase.table("proxy_representations")
        .select("*")
        .eq("author_user_id", user_id)
        .neq("status", "canceled")
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return {"representations": res.data or []}


@router.get("/proxy/profile")
async def get_profile(user_id: str = Depends(require_user_id)):
    _require_storage()
    return {"profile": _load_profile(user_id)}


@router.put("/proxy/profile")
async def upsert_profile(body: ProfileRequest, user_id: str = Depends(require_user_id)):
    _require_storage()
    row = {
        "user_id": user_id,
        "role_focus": body.role_focus,
        "standing_notes": body.standing_notes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("proxy_profiles").upsert(row, on_conflict="user_id").execute()
    return {"ok": True, "profile": row}

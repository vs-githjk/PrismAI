"""Stand-in async proxy (Feature A) — A1: the composer.

A workspace member who can't attend a meeting has Prism represent them. They open
a composer (a chat with the bot), which drafts an update from their open action
items + their standing proxy profile, refine it by conversation, then approve. The
approved text is frozen as their stand-in for that meeting.

A1 scope: tables + composer endpoints (draft -> converse -> approve/cancel) + the
standing profile get/upsert. Scheduled-bot delivery (A2/A3) and profile-enrichment
on approve (A4) land in later slices.
"""
import asyncio
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase
from caches import is_workspace_member
from clients import get_openai
from recall_routes import _normalize_meeting_url

router = APIRouter(tags=["proxy"])


def _standin_schedule_on() -> bool:
    """Kill-switch for actually sending a scheduled bot on approve. Default ON;
    set PRISM_STANDIN_SCHEDULE=0 to approve/save stand-ins without spawning real
    future Recall bots (e.g. while testing the rest of the loop)."""
    return os.getenv("PRISM_STANDIN_SCHEDULE", "1") != "0"


def _join_at_ok(scheduled_for: str | None) -> bool:
    """Recall requires join_at to be >10 min in the future to guarantee the join."""
    if not scheduled_for:
        return False
    try:
        start = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return start > datetime.now(timezone.utc) + timedelta(minutes=10)
    except Exception:
        return False

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


async def _enrich_profile(user_id: str, messages: list, approved_body: str) -> None:
    """Enrichment-on-approve: distil DURABLE facts about the user (role, ownership,
    ongoing responsibilities — not transient status) from the stand-in conversation
    and merge them into their standing_notes, so the next draft starts smarter.
    Best-effort; never raises into the approve path."""
    try:
        profile = _load_profile(user_id)
        current = (profile.get("standing_notes") or "").strip()
        convo = "\n".join(
            f"{m.get('role')}: {m.get('content')}" for m in (messages or [])[-8:]
            if isinstance(m, dict)
        )
        system = (
            "You maintain a concise standing profile of a user so an assistant can "
            "represent them in meetings. Given their CURRENT standing notes, a recent "
            "stand-in update, and the conversation, output an UPDATED standing-notes "
            "paragraph that keeps only DURABLE facts about their role, ownership, and "
            "ongoing responsibilities — NOT transient status like 'finished X today'. "
            "Merge new durable facts into the existing notes, stay under 500 characters, "
            "and if nothing durable is new, return the existing notes unchanged. Output "
            "ONLY the notes text, no preamble."
        )
        user = (
            f"Current standing notes:\n{current or '(none)'}\n\n"
            f"Recent stand-in update:\n{approved_body}\n\nConversation:\n{convo}"
        )
        updated = (await _llm_reply(system, [], user)).strip()[:700]
        if updated and updated != current:
            supabase.table("proxy_profiles").upsert({
                "user_id": user_id,
                "role_focus": profile.get("role_focus", ""),
                "standing_notes": updated,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
    except Exception as exc:
        print(f"[proxy] profile enrichment failed: {exc}")


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


def _gather_my_items(user_id: str, names: list[str], workspace_id: str | None = None) -> dict:
    """Pull the caller's recent action items (open + completed) from the last 30 days,
    name-matched, SCOPED to the meeting's context: a workspace stand-in pulls only that
    workspace's meetings (never your personal to-dos); a personal stand-in pulls only
    your own no-workspace meetings. Returns {open: [...], done: [...]}."""
    out = {"open": [], "done": []}
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        q = supabase.table("meetings").select("title,date,result,user_id").gte("date", since)
        if workspace_id:
            q = q.eq("workspace_id", workspace_id)        # this workspace only
        else:
            q = q.eq("user_id", user_id).is_("workspace_id", "null")  # personal only
        res = q.order("date", desc=True).limit(80).execute()
    except Exception:
        return out

    # Dedup workspace fan-out copies (same meeting fanned to each member) by minute,
    # preferring the caller's own row.
    seen: dict = {}
    for row in (res.data or []):
        key = (row.get("date") or "")[:16]
        if key not in seen or row.get("user_id") == user_id:
            seen[key] = row

    for meeting in seen.values():
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


def _draft_system(profile_ctx: str, items_block: str, meeting_label: str, current_draft: str = "") -> str:
    base = (
        "You help a user prepare a stand-in update that Prism will deliver on their behalf "
        f"in a meeting they can't attend ({meeting_label or 'an upcoming meeting'}).\n\n"
        "Always reply in EXACTLY two parts:\n"
        "1) A brief conversational message to the USER — e.g. 'Here's a draft' or, if you "
        "need more info, a clarifying question.\n"
        "2) On a new line, 'DRAFT:' followed by the exact update to be read aloud in the "
        "meeting — first person, concise stand-up style (finished / in progress / blockers), "
        "2-4 sentences, grounded ONLY in the action items + profile (never invent completed "
        "work). If there isn't enough to report yet, put NOTHING after 'DRAFT:'.\n"
        "The DRAFT is spoken to the TEAM, so it must be an update — NEVER a question to the user."
    )
    ctx = ""
    if profile_ctx:
        ctx += f"\n\nWho they are:\n{profile_ctx}"
    ctx += f"\n\n{items_block}"
    if current_draft.strip():
        ctx += f"\n\nCurrent draft (refine this; keep it unless the user changes direction):\n{current_draft}"
    return base + ctx


def _split_reply_draft(raw: str) -> tuple[str, str]:
    """Split an LLM reply into (conversational message, deliverable draft). The model
    is told to put the deliverable after a 'DRAFT:' marker; the conversational part is
    what's shown in chat, the draft is what gets delivered in the meeting."""
    raw = (raw or "").strip()
    if "DRAFT:" in raw:
        before, after = raw.split("DRAFT:", 1)
        reply = before.strip() or "Here's a draft — anything to change?"
        return reply, after.strip()
    # No marker — treat the whole thing as conversation, with no deliverable yet.
    return raw, ""


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
    """Open the stand-in for a meeting. If one already exists for this meeting
    (not canceled), RESUME it — return its saved draft + conversation — instead of
    regenerating. Otherwise draft a first-pass update from the caller's action
    items + standing profile and persist a new draft row."""
    _require_storage()
    _gate_workspace(user_id, body.workspace_id)
    if not body.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL required")

    normalized = _normalize_meeting_url(body.meeting_url)

    # Resume an existing stand-in for this meeting rather than starting over.
    existing = (
        supabase.table("proxy_representations")
        .select("*")
        .eq("author_user_id", user_id)
        .eq("meeting_url", normalized)
        .neq("status", "canceled")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if existing.data:
        rep = existing.data[0]
        return {
            "representation": rep,
            "draft": rep.get("approved_body") or rep.get("draft_body") or "",
            "messages": rep.get("messages") or [],
            "resumed": True,
        }

    names = _author_names(user_id, body.author_name, body.author_email)
    profile = _load_profile(user_id)
    items = _gather_my_items(user_id, names, body.workspace_id)
    system = _draft_system(_profile_context(profile), _items_block(items), body.meeting_label)
    raw = await _llm_reply(system, [], "Prepare my stand-in update for this meeting.")
    reply, draft = _split_reply_draft(raw)
    messages = [{"role": "assistant", "content": reply}]

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
        "messages": messages,
        "status": "draft",
    }
    res = supabase.table("proxy_representations").insert(row).execute()
    saved = (res.data or [row])[0]
    return {"representation": saved, "reply": reply, "draft": draft, "messages": messages, "resumed": False}


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
    items = _gather_my_items(user_id, names, row.get("workspace_id"))
    old_draft = row.get("draft_body") or ""
    system = _draft_system(
        _profile_context(profile), _items_block(items), row.get("meeting_label", ""), current_draft=old_draft
    )
    # Use the persisted conversation as history (source of truth), not client-sent.
    history = row.get("messages") or body.history or []
    raw = await _llm_reply(system, history, body.message)
    reply, new_draft = _split_reply_draft(raw)
    if not new_draft:
        new_draft = old_draft  # a turn that produced no deliverable keeps the last one

    # Persist the turn (conversational message only) so reopening resumes the chat.
    messages = history + [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": reply},
    ]
    supabase.table("proxy_representations").update(
        {"draft_body": new_draft, "messages": messages}
    ).eq("id", rep_id).execute()
    return {"reply": reply, "draft": new_draft, "messages": messages}


@router.post("/proxy/representations/{rep_id}/approve")
async def approve(rep_id: str, body: ApproveRequest, user_id: str = Depends(require_user_id)):
    """Freeze the approved text and (A2) schedule a Recall bot to join the meeting
    at its start time and deliver this stand-in. Dedups onto an existing bot for the
    meeting when one is already scheduled/live. Gated by PRISM_STANDIN_SCHEDULE."""
    _require_storage()
    row = _owned_rep(rep_id, user_id)
    text = (body.approved_body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to approve")

    update = {
        "approved_body": text,
        "draft_body": text,
        "status": "pending",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }

    # Schedule (or attach to) a bot for delivery, unless one is already attached.
    scheduled = False
    if _standin_schedule_on() and not row.get("scheduled_bot_id"):
        join_at = row.get("scheduled_for")
        if _join_at_ok(join_at):
            try:
                from recall_routes import schedule_standin_bot
                res = await schedule_standin_bot(
                    row["meeting_url"], user_id, row.get("workspace_id"),
                    row.get("author_name"), join_at,
                )
                if res:
                    update["scheduled_bot_id"] = res["bot_id"]
                    update["join_at"] = join_at
                    scheduled = True
            except Exception as exc:
                print(f"[proxy] schedule on approve failed: {exc}")

    supabase.table("proxy_representations").update(update).eq("id", rep_id).execute()

    # Enrichment-on-approve: learn durable facts for next time (background, best-effort).
    asyncio.create_task(_enrich_profile(user_id, row.get("messages") or [], text))

    return {"ok": True, "status": "pending", "scheduled": scheduled}


@router.post("/proxy/representations/{rep_id}/cancel")
async def cancel(rep_id: str, user_id: str = Depends(require_user_id)):
    _require_storage()
    row = _owned_rep(rep_id, user_id)
    supabase.table("proxy_representations").update({"status": "canceled"}).eq("id", rep_id).execute()
    bot_id = row.get("scheduled_bot_id")
    if bot_id:
        try:
            from recall_routes import cancel_standin_bot
            await cancel_standin_bot(bot_id, user_id, rep_id)
        except Exception as exc:
            print(f"[proxy] cancel bot teardown failed: {exc}")
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

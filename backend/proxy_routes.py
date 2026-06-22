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
# The composer is a deliberate, low-volume path where reasoning quality matters
# (it's representing a person in a meeting), so it runs on a stronger model than the
# high-volume chat path. Override with PRISM_PROXY_MODEL.
_DRAFT_MODEL = os.getenv("PRISM_PROXY_MODEL", "gpt-4o")


def _require_storage():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    return supabase


# ── Profile ──────────────────────────────────────────────────────────────────
def _ws_key(workspace_id: str | None) -> str:
    """Stand-in profiles are per-(user, workspace). Personal is stored as '' (empty
    string) — NOT null — so the (user_id, workspace_id) primary key + upsert conflict
    target work cleanly without partial-index gymnastics."""
    return workspace_id or ""


def _load_profile(user_id: str, workspace_id: str | None = None) -> dict:
    try:
        res = (
            supabase.table("proxy_profiles").select("*")
            .eq("user_id", user_id).eq("workspace_id", _ws_key(workspace_id))
            .maybe_single().execute()
        )
        return res.data or {}
    except Exception:
        return {}


async def _enrich_profile(user_id: str, workspace_id: str | None,
                          messages: list, approved_body: str) -> None:
    """Enrichment-on-approve: distil DURABLE facts about the user (role, ownership,
    ongoing responsibilities — not transient status) from the stand-in conversation
    and merge them into their standing_notes FOR THIS WORKSPACE, so the next draft in
    the same space starts smarter without bleeding into other teams. Best-effort;
    never raises into the approve path."""
    try:
        profile = _load_profile(user_id, workspace_id)
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
            "Merge new durable facts into the existing notes, stay under 500 characters. "
            "If there are NO durable facts to record, output an empty string and nothing "
            "else. Output ONLY the notes text — no preamble, no placeholders like '(none)'."
        )
        user = (
            f"Current standing notes:\n{current or '(empty)'}\n\n"
            f"Recent stand-in update:\n{approved_body}\n\nConversation:\n{convo}"
        )
        updated = (await _llm_reply(system, [], user)).strip()[:700]
        # Guard against the model echoing a placeholder / writing junk.
        _JUNK = {"", "(none)", "none", "n/a", "(empty)", "empty", "no durable facts",
                 "no notes", "(no notes)", "none."}
        if updated.lower() in _JUNK:
            return
        if updated and updated != current:
            supabase.table("proxy_profiles").upsert({
                "user_id": user_id,
                "workspace_id": _ws_key(workspace_id),
                "role_focus": profile.get("role_focus", ""),
                "standing_notes": updated,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id,workspace_id").execute()
    except Exception as exc:
        print(f"[proxy] profile enrichment failed: {exc}")


def _profile_context(profile: dict) -> str:
    parts = []
    if (profile.get("role_focus") or "").strip():
        parts.append(f"Role / focus: {profile['role_focus'].strip()}")
    if (profile.get("standing_notes") or "").strip():
        parts.append(f"Standing notes: {profile['standing_notes'].strip()}")
    return "\n".join(parts)


def _profile_context_multi(user_id: str, scopes: list) -> str:
    """Build the 'who they are' context from the per-workspace profiles for the given
    scopes (the meeting's own scope, plus any the user authorized borrowing from). The
    first scope's role_focus wins; standing notes from every scope are merged. With a
    single scope this is identical to _profile_context of that workspace's profile."""
    role = ""
    notes: list[str] = []
    for sc in scopes:
        p = _load_profile(user_id, sc)
        if not role and (p.get("role_focus") or "").strip():
            role = p["role_focus"].strip()
        n = (p.get("standing_notes") or "").strip()
        if n and n not in notes:
            notes.append(n)
    parts = []
    if role:
        parts.append(f"Role / focus: {role}")
    if notes:
        parts.append("Standing notes: " + " ".join(notes))
    return "\n".join(parts)


def _scope_is_thin(items: dict, decisions: list, profile_ctx: str) -> bool:
    """True when there's barely anything to ground a draft in for this scope: fewer than
    two work items AND no standing profile notes. That's when we ask to borrow rather
    than emit a hollow (or personal-bleeding) draft."""
    n = len(items.get("open", [])) + len(items.get("done", [])) + len(decisions or [])
    return n < 2 and not (profile_ctx or "").strip()


def _borrow_options(user_id: str, current_workspace_id: str | None) -> list[dict]:
    """The OTHER spaces the user could borrow stand-in context from: their workspaces
    (minus the current one) plus Personal (when the current meeting is a workspace one).
    Each is {id, name}; id is null for Personal. Drives the composer's 'pull from' chips."""
    opts: list[dict] = []
    try:
        if current_workspace_id:
            opts.append({"id": None, "name": "Personal"})
        rows = (
            supabase.table("workspace_members").select("workspace_id")
            .eq("user_id", user_id).execute().data or []
        )
        ids = [
            r["workspace_id"] for r in rows
            if r.get("workspace_id") and r["workspace_id"] != current_workspace_id
        ]
        if ids:
            wss = supabase.table("workspaces").select("id,name").in_("id", ids).execute().data or []
            seen = set()
            for w in wss:
                if w["id"] in seen:
                    continue
                seen.add(w["id"])
                opts.append({"id": w["id"], "name": (w.get("name") or "Workspace")})
    except Exception:
        pass
    return opts


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


def _scope_list(workspace_id: str | None, borrow_scopes: list | None) -> list:
    """Build the ordered, de-duplicated list of meeting scopes to pull from: the
    meeting's own scope first, then any spaces the user explicitly authorized borrowing
    from. A scope is a workspace_id string, or None for personal (no-workspace) meetings."""
    scopes: list = []
    for s in [workspace_id, *(borrow_scopes or [])]:
        sv = s or None  # treat '' / null uniformly as personal
        if sv not in scopes:
            scopes.append(sv)
    return scopes


def _fetch_meetings_for_scopes(user_id: str, scopes: list) -> list:
    """Fetch + dedup the caller's recent meetings across one or more scopes. Workspace
    scopes pull that workspace's meetings; the personal scope (None) pulls the caller's
    own no-workspace rows. Dedup is per-(scope, minute), preferring the caller's own
    fan-out copy."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows: list = []
    for sc in scopes:
        try:
            q = supabase.table("meetings").select(
                "id,title,date,result,user_id,workspace_id"
            ).gte("date", since)
            if sc:
                q = q.eq("workspace_id", sc)
            else:
                q = q.eq("user_id", user_id).is_("workspace_id", "null")
            rows.extend(q.order("date", desc=True).limit(80).execute().data or [])
        except Exception:
            continue
    seen: dict = {}
    for row in rows:
        key = ((row.get("workspace_id") or ""), (row.get("date") or "")[:16])
        if key not in seen or row.get("user_id") == user_id:
            seen[key] = row
    return list(seen.values())


def _gather_my_items(user_id: str, names: list[str], workspace_id: str | None = None,
                     borrow_scopes: list | None = None) -> dict:
    """Pull the caller's recent action items (open + completed) from the last 30 days,
    name-matched, SCOPED to the meeting's context: a workspace stand-in pulls only that
    workspace's meetings (never your personal to-dos); a personal stand-in pulls only
    your own no-workspace meetings. When the user has authorized borrowing, the scope
    widens to include those spaces too. Returns {open: [...], done: [...]}."""
    out = {"open": [], "done": []}
    meetings = _fetch_meetings_for_scopes(user_id, _scope_list(workspace_id, borrow_scopes))

    for meeting in meetings:
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


def _decision_text(d) -> str:
    """A decision may be a bare string or a dict under various keys."""
    if isinstance(d, str):
        return d.strip()
    if isinstance(d, dict):
        for k in ("decision", "text", "title", "summary"):
            v = (d.get(k) or "").strip()
            if v:
                return v
    return ""


def _decision_person(d) -> str:
    if isinstance(d, dict):
        for k in ("owner", "decided_by", "by", "person", "author", "made_by"):
            v = (d.get(k) or "").strip()
            if v:
                return v
    return ""


def _gather_my_digest(user_id: str, names: list[str], workspace_id: str | None = None,
                      borrow_scopes: list | None = None) -> dict:
    """The Stand-in dashboard feed: the caller's OPEN action items + the decisions that
    are theirs, scoped to the active workspace (or personal when none), last 30 days. Each
    item carries meeting_id for click-through. A decision is 'mine' if its person field
    matches me OR it links (via decision_links) to one of my action items — so decisions
    with no explicit owner still attach to me through my work. When borrowing is
    authorized, the scope widens to include the chosen spaces."""
    out = {"action_items": [], "decisions": []}
    if not supabase:
        return out
    meetings = _fetch_meetings_for_scopes(user_id, _scope_list(workspace_id, borrow_scopes))

    for meeting in meetings:
        result = meeting.get("result") or {}
        mid = meeting.get("id")
        title = meeting.get("title") or "a meeting"
        actions = result.get("action_items") or []
        decisions = result.get("decisions") or []
        links = result.get("decision_links") or []
        dec_by_action = {a: l.get("decision") for l in links for a in (l.get("actions") or [])}
        actions_by_dec = {l.get("decision"): (l.get("actions") or []) for l in links}

        my_action_idx = set()
        for i, item in enumerate(actions):
            task = (item.get("task") or "").strip()
            if not task or item.get("completed") or not _user_owns_item(item.get("owner", ""), names):
                continue
            my_action_idx.add(i)
            from_dec = None
            di = dec_by_action.get(i)
            if di is not None and 0 <= di < len(decisions):
                from_dec = _decision_text(decisions[di])
            out["action_items"].append({
                "task": task,
                "owner": (item.get("owner") or "").strip(),
                "due_date": item.get("due_date") or item.get("due") or "",
                "meeting_id": mid,
                "meeting": title,
                "from_decision": from_dec,
            })

        for di, d in enumerate(decisions):
            text = _decision_text(d)
            if not text:
                continue
            person = _decision_person(d)
            mine = _user_owns_item(person, names) if person else False
            if not mine and any(a in my_action_idx for a in actions_by_dec.get(di, [])):
                mine = True
            if not mine:
                continue
            out["decisions"].append({
                "decision": text,
                "rationale": (d.get("rationale") if isinstance(d, dict) else "") or "",
                "importance": (d.get("importance") if isinstance(d, dict) else 3) or 3,
                "person": person,
                "meeting_id": mid,
                "meeting": title,
                "has_action": bool(actions_by_dec.get(di)),
            })

    # Action items: overdue / soonest-first; undated last. due_date is ISO (YYYY-MM-DD),
    # so a lexical sort is chronological — past dates (overdue) bubble to the top.
    out["action_items"].sort(key=lambda a: (0, a["due_date"]) if a.get("due_date") else (1, ""))
    out["decisions"].sort(key=lambda x: x.get("importance", 3))
    return out


def _decisions_block(decisions: list[dict]) -> str:
    """Compact block of the caller's decisions for the stand-in draft context. Importance-
    sorted upstream; cap so the prompt stays tight."""
    if not decisions:
        return ""
    lines = []
    for d in decisions[:8]:
        text = (d.get("decision") or "").strip()
        if text:
            lines.append(f"- {text}")
    return "Key decisions you made or own:\n" + "\n".join(lines) if lines else ""


def _workspace_member_names(workspace_id: str | None, exclude_user_id: str) -> list[str]:
    """Other members of the workspace (friendly names from their emails) so the draft
    can address them naturally instead of a generic 'Hey team'. Same lookup we already
    do for action items — basically free. Empty for personal meetings."""
    if not workspace_id:
        return []
    try:
        res = (
            supabase.table("workspace_members").select("user_id, user_email")
            .eq("workspace_id", workspace_id).execute()
        )
    except Exception:
        return []
    names = []
    for m in (res.data or []):
        if m.get("user_id") == exclude_user_id:
            continue
        local = (m.get("user_email") or "").split("@")[0].strip()
        if local:
            names.append(local)
    return names


def _draft_system(profile_ctx: str, items_block: str, meeting_label: str,
                  current_draft: str = "", member_names: list[str] | None = None,
                  decisions_block: str = "") -> str:
    base = (
        "You help a user prepare a stand-in message that Prism will deliver on their behalf "
        f"in a meeting they can't attend ({meeting_label or 'an upcoming meeting'}). The "
        "stand-in conveys WHATEVER the user wants said to the team for them. That's often a "
        "brief status update, but it can equally be questions they want asked, messages for "
        "specific people, or any request — it is NOT limited to work tasks.\n\n"
        "Always reply in EXACTLY two parts:\n"
        "1) A brief conversational message to the USER — e.g. 'Here's a draft' or, only when "
        "something is genuinely unspecified, a clarifying question.\n"
        "2) On a new line, 'DRAFT:' followed by the exact message to be read aloud in the "
        "meeting — first person, in the user's voice, concise. Include BOTH: (a) their work "
        "status, GROUNDED only in the action items + profile (never invent completed work), "
        "AND (b) any questions / messages / requests the user explicitly asked you to relay, "
        "even if unrelated to their tasks.\n"
        "If you have nothing to draft yet — no action items AND the user hasn't told you what "
        "to convey — do NOT claim 'here's a draft'. Instead, in part (1) briefly ask what "
        "they'd like to share or ask the team, and leave part (2) EMPTY (nothing after 'DRAFT:'). "
        "Only say 'Here's a draft' when there is actual content after 'DRAFT:'.\n"
        "Build the draft PROACTIVELY from what the user has already told you — do not keep "
        "asking for 'work updates' once they've given you something to convey. Use the FULL "
        "conversation to resolve references (e.g. 'the two things I mentioned') and act on "
        "them rather than asking them to repeat. The DRAFT is spoken TO THE TEAM, so phrase "
        "it as statements/questions directed at the team — never as a question back to the user."
    )
    ctx = ""
    if profile_ctx:
        ctx += f"\n\nWho they are:\n{profile_ctx}"
    ctx += f"\n\n{items_block}"
    if decisions_block:
        ctx += f"\n\n{decisions_block}\n(Reference these decisions if relevant — they show what the user owns/drove.)"
    if member_names:
        ctx += f"\n\nOthers in this meeting: {', '.join(member_names)}. Address them naturally."
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
    message: str = ""
    # The conversation transcript so far, [{role, content}], owned by the client.
    history: list[dict] = []
    # Spaces the user just authorized borrowing context from (workspace ids; null =
    # Personal). Sent when they click a "pull from" chip. Merged into the rep's
    # persisted borrow_scopes so refinements keep the widened scope.
    borrow_scopes: list | None = None


class ApproveRequest(BaseModel):
    approved_body: str


class ProfileRequest(BaseModel):
    role_focus: str = ""
    standing_notes: str = ""
    workspace_id: str | None = None


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
    ws = body.workspace_id
    profile_ctx = _profile_context_multi(user_id, [ws])
    items = _gather_my_items(user_id, names, ws)
    decisions = _gather_my_digest(user_id, names, ws)["decisions"]
    members = _workspace_member_names(ws, user_id)

    base_row = {
        "workspace_id": ws,
        "meeting_url": normalized,
        "calendar_event_id": body.calendar_event_id,
        "meeting_label": body.meeting_label,
        "scheduled_for": body.scheduled_for,
        "author_user_id": user_id,
        "author_name": body.author_name,
        "author_email": body.author_email,
        "borrow_scopes": [],
    }

    # Thin scope → don't draft from thin air (or bleed another space). Ask whether to
    # borrow context from another space the user belongs to. Only when borrowing is
    # actually possible; otherwise fall through and let the model ask what to share.
    if _scope_is_thin(items, decisions, profile_ctx):
        opts = _borrow_options(user_id, ws)
        if opts:
            label = body.meeting_label or "this meeting"
            reply = (
                f"I don't have much on you in {label} yet. Want me to pull context from "
                "another space to flesh this out? Pick one below — or just tell me what "
                "to share and I'll draft from that."
            )
            messages = [{"role": "assistant", "content": reply}]
            row = {**base_row, "draft_body": "", "messages": messages, "status": "draft"}
            res = supabase.table("proxy_representations").insert(row).execute()
            saved = (res.data or [row])[0]
            return {
                "representation": saved, "reply": reply, "draft": "", "messages": messages,
                "resumed": False, "awaiting_cross_workspace": True, "borrow_options": opts,
            }

    system = _draft_system(
        profile_ctx, _items_block(items), body.meeting_label,
        member_names=members, decisions_block=_decisions_block(decisions),
    )
    raw = await _llm_reply(system, [], "Prepare my stand-in update for this meeting.")
    reply, draft = _split_reply_draft(raw)
    messages = [{"role": "assistant", "content": reply}]

    row = {**base_row, "draft_body": draft, "messages": messages, "status": "draft"}
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
    ws = row.get("workspace_id")

    # Merge any newly-authorized borrow spaces into the rep's persisted scope.
    borrow = list(row.get("borrow_scopes") or [])
    if body.borrow_scopes is not None:
        for s in body.borrow_scopes:
            sv = s or None
            if sv not in borrow:
                borrow.append(sv)

    items = _gather_my_items(user_id, names, ws, borrow_scopes=borrow)
    decisions = _gather_my_digest(user_id, names, ws, borrow_scopes=borrow)["decisions"]
    profile_ctx = _profile_context_multi(user_id, _scope_list(ws, borrow))
    members = _workspace_member_names(ws, user_id)
    old_draft = row.get("draft_body") or ""

    # When the turn IS a borrow pick (chip click, no typed message), drive a fresh draft
    # from the now-widened context rather than treating it as a content instruction.
    user_msg = (body.message or "").strip()
    if body.borrow_scopes and not user_msg:
        wanted = [s or None for s in body.borrow_scopes]
        picked = [o["name"] for o in _borrow_options(user_id, ws) if (o["id"] or None) in wanted]
        where = " and ".join(picked) if picked else "my other spaces"
        user_msg = f"Pull from {where} and draft my stand-in update for this meeting."

    system = _draft_system(
        profile_ctx, _items_block(items), row.get("meeting_label", ""),
        current_draft=old_draft, member_names=members, decisions_block=_decisions_block(decisions),
    )
    # Use the persisted conversation as history (source of truth), not client-sent.
    history = row.get("messages") or body.history or []
    raw = await _llm_reply(system, history, user_msg)
    reply, new_draft = _split_reply_draft(raw)
    if not new_draft:
        new_draft = old_draft  # a turn that produced no deliverable keeps the last one

    # Persist the turn (conversational message only) so reopening resumes the chat.
    messages = history + [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]
    supabase.table("proxy_representations").update(
        {"draft_body": new_draft, "messages": messages, "borrow_scopes": borrow}
    ).eq("id", rep_id).execute()
    return {"reply": reply, "draft": new_draft, "messages": messages, "borrow_scopes": borrow}


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
    asyncio.create_task(_enrich_profile(user_id, row.get("workspace_id"), row.get("messages") or [], text))

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
async def list_representations(
    workspace_id: str | None = None,
    user_id: str = Depends(require_user_id),
):
    """The caller's stand-ins. Scoped to the active workspace (personal when none) so
    each workspace shows its own history, matching the rest of the Stand-in page."""
    _require_storage()
    q = (
        supabase.table("proxy_representations")
        .select("*")
        .eq("author_user_id", user_id)
        .neq("status", "canceled")
    )
    if workspace_id:
        q = q.eq("workspace_id", workspace_id)
    else:
        q = q.is_("workspace_id", "null")
    res = q.order("created_at", desc=True).limit(50).execute()
    return {"representations": res.data or []}


@router.get("/proxy/digest")
async def proxy_digest(
    workspace_id: str | None = None,
    author_name: str = "",
    author_email: str = "",
    user_id: str = Depends(require_user_id),
):
    """The Stand-in dashboard feed: the caller's open action items + their decisions for
    the active workspace (personal when none). Each carries meeting_id for click-through."""
    _require_storage()
    _gate_workspace(user_id, workspace_id)
    names = _author_names(user_id, author_name, author_email)
    return _gather_my_digest(user_id, names, workspace_id)


class PreviewRequest(BaseModel):
    workspace_id: str | None = None
    author_name: str = ""
    author_email: str = ""


@router.post("/proxy/preview")
async def preview_standin(body: PreviewRequest, user_id: str = Depends(require_user_id)):
    """Generate how Prism would represent the caller RIGHT NOW (no real meeting) from their
    open action items + standing profile — so they can see their stand-in voice anytime."""
    _require_storage()
    _gate_workspace(user_id, body.workspace_id)
    names = _author_names(user_id, body.author_name, body.author_email)
    profile_ctx = _profile_context_multi(user_id, [body.workspace_id])
    items = _gather_my_items(user_id, names, body.workspace_id)
    decisions = _gather_my_digest(user_id, names, body.workspace_id)["decisions"]
    members = _workspace_member_names(body.workspace_id, user_id)
    system = _draft_system(
        profile_ctx, _items_block(items), "an upcoming meeting",
        member_names=members, decisions_block=_decisions_block(decisions),
    )
    raw = await _llm_reply(
        system, [],
        "Show me how you would represent me if I missed a meeting right now. "
        "Reply with ONLY the stand-in update I'd want delivered — no preamble.",
    )
    reply, draft = _split_reply_draft(raw)
    return {"preview": (draft or reply or "").strip()}


@router.get("/proxy/profile")
async def get_profile(workspace_id: str | None = None, user_id: str = Depends(require_user_id)):
    _require_storage()
    _gate_workspace(user_id, workspace_id)
    return {"profile": _load_profile(user_id, workspace_id)}


@router.put("/proxy/profile")
async def upsert_profile(body: ProfileRequest, user_id: str = Depends(require_user_id)):
    _require_storage()
    _gate_workspace(user_id, body.workspace_id)
    row = {
        "user_id": user_id,
        "workspace_id": _ws_key(body.workspace_id),
        "role_focus": body.role_focus,
        "standing_notes": body.standing_notes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("proxy_profiles").upsert(row, on_conflict="user_id,workspace_id").execute()
    return {"ok": True, "profile": row}

"""Minimal MCP (Model Context Protocol) server over Streamable HTTP.

Exposes a PrismAI user's meeting data as read-only tools that Claude and ChatGPT
can PULL on demand. One stateless `POST /mcp` endpoint speaks JSON-RPC 2.0:
`initialize`, `tools/list`, `tools/call`, `ping`.

Why hand-rolled instead of the fastmcp SDK: fastmcp 3.x requires starlette >=1.0,
which is incompatible with our FastAPI (starlette <0.48). The read-only-tools
surface is small enough that a direct JSON-RPC handler is simpler AND gives us
clean control over the PAT auth header + rate limiting, with no dependency clash.

Auth: every `tools/call` goes through `pat.resolve_mcp_user(request)` → user_id.
Missing/invalid credential → HTTP 401 with a WWW-Authenticate hint (Milestone B
will point that at OAuth protected-resource metadata). `initialize`/`tools/list`
are unauthenticated (the tool list is identical for everyone; discovery first,
auth on first data pull) — this mirrors how MCP clients probe a server.
"""

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from auth import supabase
from caches import get_user_workspace_ids, is_workspace_member
from cross_meeting_service import has_meaningful_result
from pat import resolve_mcp_user
from ratelimit import enforce as rate_limit

# We accept whatever protocol version the client requests (forward/backward
# compatible for a tools-only server); this is the fallback we advertise.
_DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_SERVER_INFO = {"name": "PrismAI", "version": "1.0.0"}
_MAX_ITEMS = 50  # hard cap so tool results stay well under the ~150k-char limit

# App origin for click-through deep-links back into PrismAI (trust: the user can
# open the exact source meeting to verify). Matches oauth_routes' APP_BASE.
APP_BASE = os.getenv("APP_BASE_URL", "https://www.meetprismai.com").rstrip("/")


def _meeting_url(meeting_id) -> str:
    return f"{APP_BASE}/dashboard?meeting={meeting_id}"


router = APIRouter(tags=["mcp"])


# ─────────────────────────── data helpers ───────────────────────────

def _workspace_labels(user_id: str) -> dict[str, str]:
    """{workspace_id -> name} for the user's workspaces, so tool results can label
    where each meeting lives ("Personal" vs a named workspace) instead of a raw id."""
    if not supabase:
        return {}
    ids = get_user_workspace_ids(supabase, user_id)
    if not ids:
        return {}
    try:
        res = supabase.table("workspaces").select("id, name").in_("id", ids).execute()
    except Exception:
        return {}
    return {str(r.get("id")): (r.get("name") or "Workspace") for r in (res.data or [])}


def _label_for(ws_id, labels: dict[str, str]) -> str:
    if not ws_id:
        return "Personal"
    return labels.get(str(ws_id), "Workspace")


def _dedup_by_minute(rows: list[dict], caller_user_id: str) -> list[dict]:
    """Collapse workspace fan-out copies: two rows at the same minute are the same
    logical meeting. Prefer the caller's own copy (its id opens in their history)."""
    by_key: dict[str, dict] = {}
    for r in rows:
        key = (r.get("date") or "")[:16]
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = r
        elif r.get("user_id") == caller_user_id and cur.get("user_id") != caller_user_id:
            by_key[key] = r
    return list(by_key.values())


def _fetch_user_meetings(user_id: str, columns: str, workspace_id: str = "") -> list[dict]:
    """A user's meetings across personal + all their workspaces (or one workspace
    when `workspace_id` is given, membership-checked). Deduped, newest first.

    `workspace_id`: "" = all (personal + every workspace), "personal" = personal
    only, or a specific workspace id (must be a member)."""
    if not supabase:
        return []
    rows: list[dict] = []

    want_personal = workspace_id in ("", "personal")
    if want_personal:
        res = (
            supabase.table("meetings").select(columns)
            .eq("user_id", user_id).is_("workspace_id", "null")
            .order("date", desc=True).limit(_MAX_ITEMS).execute()
        )
        rows.extend(res.data or [])

    if workspace_id not in ("personal",):
        member_ws = get_user_workspace_ids(supabase, user_id)
        target = [workspace_id] if workspace_id else member_ws
        for ws in target:
            if ws not in member_ws:  # membership guard (IDOR)
                continue
            res = (
                supabase.table("meetings").select(columns)
                .eq("workspace_id", ws)
                .order("date", desc=True).limit(_MAX_ITEMS).execute()
            )
            rows.extend(res.data or [])

    rows = _dedup_by_minute(rows, user_id)
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows


# ─────────────────────────── tools ───────────────────────────

async def _tool_list_recent_meetings(user_id: str, args: dict) -> dict:
    limit = min(int(args.get("limit") or 20), _MAX_ITEMS)
    ws = (args.get("workspace_id") or "").strip()
    rows = _fetch_user_meetings(user_id, "id, title, date, score, workspace_id, user_id, result", ws)
    labels = _workspace_labels(user_id)
    out = []
    for r in rows:
        if not has_meaningful_result(r.get("result") or {}):
            continue
        out.append({
            "meeting_id": str(r.get("id")),
            "title": r.get("title") or "Untitled meeting",
            "date": r.get("date"),
            "score": r.get("score"),
            "workspace": _label_for(r.get("workspace_id"), labels),
            "url": _meeting_url(r.get("id")),
        })
        if len(out) >= limit:
            break
    return {"meetings": out, "count": len(out)}


async def _tool_list_open_action_items(user_id: str, args: dict) -> dict:
    limit = min(int(args.get("limit") or 30), _MAX_ITEMS)
    ws = (args.get("workspace_id") or "").strip()
    rows = _fetch_user_meetings(user_id, "id, title, date, workspace_id, user_id, result", ws)
    labels = _workspace_labels(user_id)
    items = []
    for r in rows:
        result = r.get("result") or {}
        if not has_meaningful_result(result):
            continue
        for it in (result.get("action_items") or []):
            if it.get("completed"):
                continue
            items.append({
                "task": it.get("task", ""),
                "owner": it.get("owner", ""),
                "due": it.get("due", ""),
                "due_date": it.get("due_date"),
                "meeting_id": str(r.get("id")),
                "meeting_title": r.get("title") or "Untitled meeting",
                "meeting_date": r.get("date"),
                "workspace": _label_for(r.get("workspace_id"), labels),
                "url": _meeting_url(r.get("id")),
            })
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
    return {"open_action_items": items, "count": len(items)}


async def _tool_get_meeting(user_id: str, args: dict) -> dict:
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        raise _ToolError("meeting_id is required")
    if not supabase:
        raise _ToolError("storage not configured")
    res = (
        supabase.table("meetings")
        .select("id, title, date, score, workspace_id, user_id, result")
        .eq("id", meeting_id).limit(1).execute()
    )
    row = (res.data or [None])[0]
    if not row:
        raise _ToolError("meeting not found")
    # Authz: owner OR workspace member (mirrors GET /meetings/{id}).
    if row.get("user_id") != user_id:
        ws = row.get("workspace_id")
        if not ws or not is_workspace_member(supabase, user_id, ws):
            raise _ToolError("meeting not found")  # don't reveal existence
    result = row.get("result") or {}
    return {
        "meeting_id": str(row.get("id")),
        "title": row.get("title"),
        "date": row.get("date"),
        "score": row.get("score"),
        "workspace": _label_for(row.get("workspace_id"), _workspace_labels(user_id)),
        "url": _meeting_url(row.get("id")),
        "summary": result.get("summary", ""),
        "tldr": result.get("tldr", ""),
        "decisions": result.get("decisions", []),
        "action_items": result.get("action_items", []),
        "sentiment": result.get("sentiment", {}),
    }


def _clip_on_word(text: str, cap: int) -> tuple[str, bool]:
    """Clip to cap chars on a word boundary (no mid-word cut). Returns (text, truncated)."""
    if len(text) <= cap:
        return text, False
    clipped = text[:cap].rsplit(" ", 1)[0].rstrip()
    return clipped + " …[truncated]", True


async def _fetch_pinned_docs(user_id: str, meeting_id: str, *, char_cap: int = 60000,
                             max_docs: int = 10, total_cap: int = 110000) -> list[dict]:
    """Load the knowledge docs PINNED to a meeting (e.g. a PRD the user saved from
    chat) with their text. Matches by MEETING_ID (incl. fan-out siblings), never by
    doc name — so an untitled/oddly-named PRD is still found. Caller must have
    already authorized meeting access. Scoped to the caller's own + workspace docs.
    Returns [] on any failure (best-effort).

    Two bounds: `char_cap` per doc (a full strategic doc / PRD fits whole at 60k),
    and `total_cap` across all returned docs, so a meeting with many big docs can't
    blow the MCP ~150k-char response budget. Each doc carries a `truncated` flag."""
    from knowledge_routes import _coerce_meeting_id, _sibling_meeting_ids
    mid = _coerce_meeting_id(meeting_id)
    if mid is None:
        return []
    try:
        sib_ids = await _sibling_meeting_ids(supabase, mid)
        ws_ids = get_user_workspace_ids(supabase, user_id)
        q = (
            supabase.table("knowledge_docs")
            .select("id, name, source_type, user_id, workspace_id")
            .is_("deleted_at", "null").in_("meeting_id", sib_ids)
        )
        # Scope to the caller's own docs OR their workspaces' docs.
        if ws_ids:
            q = q.or_(f"user_id.eq.{user_id},workspace_id.in.({','.join(ws_ids)})")
        else:
            q = q.eq("user_id", user_id)
        docs = q.execute().data or []
    except Exception:
        return []

    out = []
    remaining = total_cap
    for d in docs[:max_docs]:
        doc_id = d.get("id")
        truncated = False
        try:
            chunks = (
                supabase.table("knowledge_chunks").select("content, chunk_index")
                .eq("doc_id", doc_id).order("chunk_index").execute()
            )
            full = "".join(c.get("content", "") for c in (chunks.data or []))
            # Bound by the per-doc cap AND the remaining shared budget.
            cap = max(0, min(char_cap, remaining))
            if cap <= 0:
                text, truncated = "", bool(full)
            else:
                text, truncated = _clip_on_word(full, cap)
            remaining -= len(text)
        except Exception:
            text = ""
        out.append({
            "doc_id": str(doc_id),
            "name": d.get("name"),
            "source_type": d.get("source_type"),
            "content": text,
            "truncated": truncated,
        })
    return out


async def _tool_get_meeting_documents(user_id: str, args: dict) -> dict:
    """Read the knowledge docs PINNED to a meeting (e.g. a PRD the user saved from
    chat) with their text — so the assistant can actually read them."""
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        raise _ToolError("meeting_id is required")
    if not supabase:
        raise _ToolError("storage not configured")
    # Authz via meeting access (owner OR workspace member).
    mres = supabase.table("meetings").select("id, workspace_id, user_id").eq("id", meeting_id).limit(1).execute()
    mrow = (mres.data or [None])[0]
    if not mrow:
        raise _ToolError("meeting not found")
    if mrow.get("user_id") != user_id:
        ws = mrow.get("workspace_id")
        if not ws or not is_workspace_member(supabase, user_id, ws):
            raise _ToolError("meeting not found")

    out = await _fetch_pinned_docs(user_id, meeting_id)
    return {"documents": out, "count": len(out)}


async def _tool_search_meetings(user_id: str, args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise _ToolError("query is required")
    limit = min(int(args.get("limit") or 5), 10)
    from knowledge_service import search_knowledge  # local import: heavy deps
    try:
        hits = await search_knowledge(query, user_id, k=limit)
    except Exception as exc:
        raise _ToolError(f"search failed: {exc}")
    out = []
    for h in hits or []:
        out.append({
            "snippet": (h.get("content") or "")[:500],
            "source": h.get("doc_name") or h.get("meeting_title") or "",
            "meeting_title": h.get("meeting_title"),
            "score": h.get("score"),
            "source_type": h.get("source_type"),
        })
    return {"results": out, "count": len(out)}


_CODING_TASK_SYSTEM = (
    "You are a senior software engineer turning a meeting into a precise, "
    "self-contained coding task that a developer can hand DIRECTLY to an AI coding "
    "agent (e.g. Claude Code) to start implementing. Ground everything STRICTLY in "
    "the meeting and any PINNED DOCUMENTS provided (e.g. a PRD or spec the user "
    "attached to the meeting) — the pinned documents are the authoritative "
    "specification; prefer them over conversational transcript when they conflict, "
    "and pull concrete requirements, constraints, and acceptance criteria from them. "
    "Never invent requirements; if a section lacks detail in the meeting or docs, "
    "say so in one line rather than guessing. Output markdown with exactly these "
    "sections:\n"
    "## Title\n## Context (why this is needed)\n"
    "## Product principles & design constraints\n## Scope (what to build or change)\n"
    "## Acceptance criteria (a checklist)\n## Decisions & constraints (from the meeting)\n"
    "## Out of scope / open questions\n"
    "The 'Product principles & design constraints' section is REQUIRED and often the "
    "most important: capture the load-bearing product thesis and design philosophy — "
    "the non-obvious 'why it is built this way' that changes HOW an engineer builds, "
    "not just what they build. A competent implementation that satisfies the scope "
    "but ignores these principles would be the WRONG build; state them so that cannot "
    "happen.\n"
    "FIDELITY RULE — do not flatten specifics into principles: when the meeting or a "
    "pinned document names a concrete mechanism, preserve it VERBATIM as a buildable "
    "requirement, not a paraphrase. This includes named multi-step processes/loops "
    "(keep every step name), specific UI affordances or actions (keep their exact "
    "names), enumerated categories or intent classes (keep the full list), named "
    "data-model / logging structures, and any EXPLICIT WARNING against a particular "
    "approach (state the warning outright — never silently spec the thing it warns "
    "against). An engineer needs the specific mechanism; the philosophy behind it "
    "they can infer. If in doubt, keep the concrete detail.\n"
    "Be concrete and implementation-ready. Do NOT write the code itself."
)


def _pinned_docs_block(docs: list[dict]) -> str:
    """Format pinned docs for the coding-task prompt. Content is already bounded by
    _fetch_pinned_docs' char_cap, so don't re-truncate here."""
    parts = []
    for d in docs:
        text = (d.get("content") or "").strip()
        if not text:
            continue
        parts.append(f"--- PINNED DOCUMENT: {d.get('name') or 'Untitled'} ---\n{text}")
    return "\n\n".join(parts)


async def _tool_draft_coding_task(user_id: str, args: dict) -> dict:
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        raise _ToolError("meeting_id is required")
    if not supabase:
        raise _ToolError("storage not configured")
    res = (
        supabase.table("meetings")
        .select("id, title, workspace_id, user_id, transcript, result")
        .eq("id", meeting_id).limit(1).execute()
    )
    row = (res.data or [None])[0]
    if not row:
        raise _ToolError("meeting not found")
    if row.get("user_id") != user_id:  # authz: owner OR workspace member
        ws = row.get("workspace_id")
        if not ws or not is_workspace_member(supabase, user_id, ws):
            raise _ToolError("meeting not found")

    result = row.get("result") or {}
    focus = str(args.get("focus") or "").strip()
    include_documents = args.get("include_documents", True)
    # Ground the model in the analysis + the raw transcript (capped for cost).
    transcript = (row.get("transcript") or "")[:20000]
    context = {
        "summary": result.get("summary", ""),
        "decisions": result.get("decisions", []),
        "action_items": result.get("action_items", []),
    }
    # Pinned docs (e.g. a PRD) are the authoritative spec — fold them in, matched by
    # meeting_id not name. Best-effort: if it fails/empty, the task still drafts.
    # Generous per-doc cap so a full strategic doc / PRD reaches both the synthesis
    # pass and the returned source_documents; total_cap keeps the response bounded.
    docs = await _fetch_pinned_docs(user_id, meeting_id, char_cap=60000, max_docs=5, total_cap=100000) if include_documents else []
    docs_block = _pinned_docs_block(docs)
    docs_section = (
        f"\n\nPINNED DOCUMENTS (authoritative spec — ground the task in these):\n{docs_block}"
        if docs_block else ""
    )
    user_prompt = (
        f"Meeting title: {row.get('title') or 'Untitled'}\n"
        f"Focus for the task: {focus or 'the primary engineering work discussed'}\n\n"
        f"Meeting analysis (summary / decisions / action items):\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
        f"{docs_section}\n\n"
        f"Transcript (may be truncated):\n{transcript}"
    )
    from agents.utils import llm_call, AGENT_MODEL
    try:
        brief = await llm_call(_CODING_TASK_SYSTEM, user_prompt, model=AGENT_MODEL, max_tokens=4000)
    except Exception as exc:
        raise _ToolError(f"could not draft the task: {exc}")
    grounded = [d for d in docs if (d.get("content") or "").strip()]
    return {
        "meeting_id": str(row.get("id")),
        "title": row.get("title"),
        "focus": focus or None,
        "task_brief": brief,
        "grounded_documents": [d.get("name") for d in grounded],
        # The RAW source the brief was synthesized from, so the grounding is
        # inspectable (not just asserted) and the consuming model can catch any
        # place the brief compressed a specific mechanism into a soft principle —
        # without a second get_meeting_documents call.
        "source_documents": [
            {"name": d.get("name"), "content": d.get("content"), "truncated": d.get("truncated", False)}
            for d in grounded
        ],
        "note": (
            "task_brief is a synthesized summary; source_documents is the raw pinned-doc "
            "text it was grounded in. Treat source_documents as authoritative — if the "
            "brief omits or softens a specific named mechanism, affordance, list, or "
            "warning present in the source, prefer the source and correct the brief."
        ) if grounded else None,
        "url": _meeting_url(row.get("id")),
    }


class _ToolError(Exception):
    """Raised by a tool handler → surfaced to the client as an isError result."""


# name → (handler, description, inputSchema). All read-only.
_TOOLS: dict[str, dict] = {
    "list_open_action_items": {
        "handler": _tool_list_open_action_items,
        "description": (
            "List the user's OPEN (not-yet-completed) action items across their "
            "recent meetings — personal and workspace. Use this to answer 'what do "
            "I owe' / 'what are my open tasks'. Each item includes the owner, due "
            "date, the meeting it came from, and a `workspace` label ('Personal' or "
            "the workspace name) and a `url` linking to the meeting in PrismAI. "
            "ALWAYS attribute each item to its source meeting (link the meeting_title "
            "to its `url`) and note its workspace, so the user can click through and "
            "verify — do not present tasks unattributed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Optional. Limit to one workspace id, or 'personal' for personal meetings only. Omit for all."},
                "limit": {"type": "integer", "description": "Max items (default 30, max 50)."},
            },
        },
    },
    "search_meetings": {
        "handler": _tool_search_meetings,
        "description": (
            "Semantic search across the user's meetings and knowledge base. Use for "
            "'what did we decide about X', 'find the meeting where we discussed Y'. "
            "Returns the most relevant snippets with their source. ALWAYS cite the "
            "source (meeting_title / doc name) for each snippet you use — answers must "
            "be traceable to where the information came from, never unattributed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "limit": {"type": "integer", "description": "Max results (default 5, max 10)."},
            },
            "required": ["query"],
        },
    },
    "get_meeting_documents": {
        "handler": _tool_get_meeting_documents,
        "description": (
            "Read the documents PINNED to a specific meeting — files, notes, or a PRD "
            "the user attached to that meeting in PrismAI — WITH their full text. Use "
            "whenever the user references a doc tied to a meeting ('read the PRD from "
            "the X meeting', 'what's in the spec we saved to that meeting'). Returns "
            "each pinned doc's name, type, and content. Pair with get_meeting for the "
            "meeting's own summary/decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "The meeting whose pinned documents to read."},
            },
            "required": ["meeting_id"],
        },
    },
    "get_meeting": {
        "handler": _tool_get_meeting,
        "description": (
            "Get the full detail of ONE meeting by id — summary, decisions, action "
            "items, and sentiment. Use after search_meetings or list_recent_meetings "
            "to drill into a specific meeting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "The meeting id (from list_recent_meetings / search results)."},
            },
            "required": ["meeting_id"],
        },
    },
    "draft_coding_task": {
        "handler": _tool_draft_coding_task,
        "description": (
            "Turn a meeting into a self-contained, implementation-ready CODING TASK "
            "brief that can be handed directly to an AI coding agent (like Claude Code). "
            "Does a deep pass over the meeting's full transcript + decisions AND any "
            "documents PINNED to the meeting (e.g. a PRD/spec the user saved to it — "
            "used as the authoritative spec) to produce Title / Context / Scope / "
            "Acceptance criteria / Constraints / Out-of-scope. Use when the user wants "
            "to act on engineering work from a meeting ('turn the auth discussion into "
            "a coding task'). Pass `focus` to scope it to one feature or action item. "
            "It drafts the task only — it never writes code. The response includes "
            "`source_documents` (the raw pinned-doc text the brief was grounded in): "
            "review it and, where the brief has softened a specific named mechanism, "
            "affordance, list, or warning from the source, correct the brief before "
            "presenting it — the source is authoritative."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "meeting_id": {"type": "string", "description": "The meeting to derive the task from (from list/search)."},
                "focus": {"type": "string", "description": "Optional. Scope the task to a specific feature, bug, or action item discussed."},
                "include_documents": {"type": "boolean", "description": "Optional (default true). Fold the meeting's pinned documents (e.g. a PRD) into the task as the authoritative spec."},
            },
            "required": ["meeting_id"],
        },
    },
    "list_recent_meetings": {
        "handler": _tool_list_recent_meetings,
        "description": (
            "List the user's recent meetings (title, date, id) across personal and "
            "workspace. Each carries a `workspace` label ('Personal' or the workspace "
            "name) and a `url` — link each title to its `url` and note the workspace. "
            "Use to orient before get_meeting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Optional. Limit to one workspace id, or 'personal'. Omit for all."},
                "limit": {"type": "integer", "description": "Max meetings (default 20, max 50)."},
            },
        },
    },
}


def _tool_defs() -> list[dict]:
    return [
        {
            "name": name,
            "description": t["description"],
            "inputSchema": t["inputSchema"],
            "annotations": {"readOnlyHint": True},
        }
        for name, t in _TOOLS.items()
    ]


# ─────────────────────────── JSON-RPC plumbing ───────────────────────────

def _rpc_result(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


import os as _os
_MCP_RESOURCE_META = (
    _os.getenv("WEBHOOK_BASE_URL", "https://meeting-copilot-api.onrender.com").rstrip("/")
    + "/.well-known/oauth-protected-resource"
)


def _unauthorized() -> JSONResponse:
    # MCP does auth at the HTTP layer: 401 + WWW-Authenticate. The resource_metadata
    # pointer triggers Claude's OAuth discovery (RFC 9728 → our authorization server).
    return JSONResponse(
        status_code=401,
        content={"error": "invalid_token", "error_description": "Authentication required."},
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{_MCP_RESOURCE_META}"'},
    )


async def _handle_one(request: Request, msg: dict):
    """Handle a single JSON-RPC message. Returns a response dict, or None for
    notifications (no id). May return a JSONResponse for HTTP-level auth failures."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    method = msg.get("method")
    req_id = msg.get("id")
    is_notification = "id" not in msg
    params = msg.get("params") or {}

    if method == "initialize":
        client_version = params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION
        return _rpc_result(req_id, {
            "protocolVersion": client_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": _SERVER_INFO,
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # notification — no response

    if method == "ping":
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": _tool_defs()})

    if method == "tools/call":
        # Data access → require auth.
        user_id = resolve_mcp_user(request)
        if not user_id:
            return _unauthorized()
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = _TOOLS.get(name)
        if not tool:
            return _rpc_error(req_id, -32602, f"Unknown tool: {name}")
        try:
            data = await tool["handler"](user_id, args)
            text = json.dumps(data, ensure_ascii=False, default=str)
            return _rpc_result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except _ToolError as exc:
            return _rpc_result(req_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:
            print(f"[mcp] tool {name} failed: {exc}")
            return _rpc_result(req_id, {"content": [{"type": "text", "text": "Internal error running the tool."}], "isError": True})

    if is_notification:
        return None
    return _rpc_error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    # Public endpoint (auth is per-tool-call via the token) → rate-limit by IP.
    rate_limit(request, "mcp", 120, detail="Too many MCP requests — slow down.")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content=_rpc_error(None, -32700, "Parse error"))

    # JSON-RPC batch (list) or single message.
    if isinstance(body, list):
        responses = []
        for m in body:
            r = await _handle_one(request, m)
            if isinstance(r, JSONResponse):
                return r  # auth failure short-circuits the batch
            if r is not None:
                responses.append(r)
        # All-notifications batch → 202 with no body.
        if not responses:
            return JSONResponse(status_code=202, content=None)
        return JSONResponse(content=responses)

    r = await _handle_one(request, body)
    if isinstance(r, JSONResponse):
        return r
    if r is None:
        return JSONResponse(status_code=202, content=None)
    return JSONResponse(content=r)

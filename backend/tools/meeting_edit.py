"""Meeting text-correction tool.

Fixes a word or name that was mis-transcribed / misspelled throughout a SAVED
meeting — find every occurrence of a phrase and replace it across the stored
title, summary/analysis (`result` JSON) AND the raw transcript, then persist.
This is the gap the outbound tools (email, tickets, Slack) can't fill: those
create external things, none of them edit the meeting record. So "change MD
Academy to FDE Academy" used to fall through to the LLM and get turned into
Linear tickets — now it routes here.

Meeting- and owner-scoped: only available when the chat turn carries a
`_meeting_id` (authenticated per-meeting /chat), so the live bot and global chat
never see it, and it only ever edits the caller's own copy. The corrected term
is also saved to the per-user/workspace keyterm glossary so future meetings
transcribe it correctly (see recall_routes._gather_keyterms + custom_keyterms).
"""
import re

from auth import supabase
from .registry import register_tool


def _replace_in(obj, pattern: "re.Pattern", replacement: str):
    """Recursively replace `pattern`→`replacement` in every string inside a
    JSON-ish structure (str / list / dict). Returns (new_obj, count)."""
    if isinstance(obj, str):
        return pattern.subn(replacement, obj)
    if isinstance(obj, list):
        total = 0
        out = []
        for item in obj:
            ni, c = _replace_in(item, pattern, replacement)
            out.append(ni)
            total += c
        return out, total
    if isinstance(obj, dict):
        total = 0
        out = {}
        for k, v in obj.items():
            nv, c = _replace_in(v, pattern, replacement)
            out[k] = nv
            total += c
        return out, total
    return obj, 0


async def apply_correction(user_id: str, meeting_id, find: str, replace: str) -> dict:
    """Core correction: load the caller's own meeting, replace find→replace
    (case-insensitive) across title + result + transcript, persist, and remember
    the term in the keyterm glossary. Returns a result dict (never raises)."""
    find = (find or "").strip()
    replace = (replace or "").strip()
    if not (user_id and meeting_id):
        return {"error": "No saved meeting is in context to edit."}
    if not find or not replace:
        return {"error": "Provide both the text to find and what to replace it with."}
    if find.lower() == replace.lower():
        return {"error": "The find and replace text are identical — nothing to change."}
    if not supabase:
        return {"error": "Storage is unavailable right now."}

    try:
        row = (
            supabase.table("meetings")
            .select("result, transcript, title, workspace_id")
            .eq("id", meeting_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        ).data
    except Exception as exc:
        return {"error": f"Could not load the meeting: {exc}"}
    if not row:
        return {"error": "Meeting not found, or it isn't yours to edit."}

    pattern = re.compile(re.escape(find), re.IGNORECASE)
    new_result, c_result = _replace_in(row.get("result") or {}, pattern, replace)
    new_transcript, c_tx = _replace_in(row.get("transcript") or "", pattern, replace)
    new_title, c_title = _replace_in(row.get("title") or "", pattern, replace)
    total = c_result + c_tx + c_title

    if total == 0:
        return {
            "success": True,
            "replacements": 0,
            "result": row.get("result") or {},
            "transcript": row.get("transcript") or "",
            "summary": f"No mentions of '{find}' were found.",
            "message": f"I couldn't find '{find}' anywhere in this meeting, so nothing changed.",
        }

    try:
        supabase.table("meetings").update(
            {"result": new_result, "transcript": new_transcript, "title": new_title}
        ).eq("id", meeting_id).eq("user_id", user_id).execute()
    except Exception as exc:
        return {"error": f"Could not save the correction: {exc}"}

    # Remember the corrected term so future transcriptions spell it right (#3).
    # Best-effort — a glossary miss must never fail the correction the user asked for.
    try:
        supabase.table("custom_keyterms").upsert(
            {"user_id": user_id, "workspace_id": row.get("workspace_id") or "", "term": replace},
            on_conflict="user_id,workspace_id,term",
        ).execute()
    except Exception as exc:
        print(f"[correct] glossary upsert skipped: {exc}")

    return {
        "success": True,
        "replacements": total,
        "meeting_updated": True,
        "result": new_result,
        "transcript": new_transcript,
        "summary": f"Replaced '{find}' with '{replace}' ({total}×).",
        "message": (
            f"Done — corrected {total} mention{'s' if total != 1 else ''} of "
            f"'{find}' to '{replace}' across this meeting's summary, transcript and analysis."
        ),
    }


async def correct_meeting_text(arguments, user_settings=None):
    """Tool entrypoint. Reads meeting_id + user_id from the injected settings
    (see chat_routes: `_meeting_id` is set only on authenticated per-meeting /chat).
    Strips the heavy result/transcript payload from the LLM-visible return so the
    tool result fed back into the model stays small — the fresh data goes to the
    frontend via the /chat handler's separate re-read."""
    settings = user_settings or {}
    out = await apply_correction(
        settings.get("user_id"),
        settings.get("_meeting_id"),
        (arguments or {}).get("find", ""),
        (arguments or {}).get("replace", ""),
    )
    # Keep the model's tool-result context lightweight (no full transcript echo).
    return {k: v for k, v in out.items() if k not in ("result", "transcript")}


register_tool(
    name="correct_meeting_text",
    description=(
        "Correct a word, name, or phrase that was mis-transcribed or misspelled throughout "
        "THIS meeting: find every occurrence of a phrase and replace it across the summary, "
        "analysis, and raw transcript. Use this whenever the user asks to fix, change, rename, "
        "replace, or correct a term in the meeting (e.g. 'change MD Academy to FDE Academy', "
        "'it's spelled Raghav not Ragav', 'replace X with Y everywhere'). Edits the saved "
        "meeting in place — do NOT create tickets or send anything for these requests."
    ),
    parameters={
        "type": "object",
        "properties": {
            "find": {"type": "string", "description": "The exact text to replace (matched case-insensitively)."},
            "replace": {"type": "string", "description": "The correct text to replace it with."},
        },
        "required": ["find", "replace"],
    },
    handler=correct_meeting_text,
    # `requires` gates availability on a truthy settings key. `_meeting_id` is
    # injected only on authenticated per-meeting /chat, so this tool is invisible
    # to the live bot and cross-meeting chat (which have no single meeting to edit).
    requires="_meeting_id",
    confirm=False,
)

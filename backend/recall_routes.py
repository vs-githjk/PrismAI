import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from analysis_service import build_analysis_transcript, run_full_analysis
from auth import supabase, require_user_id
from cross_meeting_service import looks_like_blocker, build_blocker_snippet
from personas import persona_identity_resolved, persona_greeting_from_preset, DEFAULT_BOT_NAME, PERSONA_NAMES

# Line prefixes that mark a transcript line as the bot's own turn (recorded by
# realtime_routes._record_bot_line). Covers every persona display name + the
# default. Used to detect whether the bot participated when assembling the
# final transcript.
_BOT_NAME_PREFIXES = tuple(
    f"{n}:" for n in ({DEFAULT_BOT_NAME, "Prism", "PrismAI"} | set(PERSONA_NAMES.values()))
)

# Minimum human words for a transcript to count as a real meeting. Below this it's a
# no-show / instant-leave (nobody actually spoke) — analysing + saving it produces a
# junk "Meeting Transcript Unavailable" row, so we skip persistence entirely.
_MIN_HUMAN_WORDS = 12


def _human_word_count(transcript: str) -> int:
    """Count words spoken/typed by HUMANS — excludes the bot's own lines and bare
    slash-commands (e.g. '/leave'), so a meeting where only the bot talked or someone
    just typed /leave reads as empty."""
    total = 0
    for line in (transcript or "").splitlines():
        line = line.strip()
        if not line or line.startswith(_BOT_NAME_PREFIXES):
            continue
        # Strip a leading "Speaker: " label so the count is words, not the name.
        text = line.split(":", 1)[1].strip() if ":" in line else line
        if not text or text.lstrip().startswith("/"):  # bare slash-command line
            continue
        total += len(text.split())
    return total


router = APIRouter(tags=["recall"])

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8001")
RECALL_WEBHOOK_SECRET = os.getenv("RECALL_WEBHOOK_SECRET", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

# Branded bot join (#4): the in-meeting display name + a static logo tile shown as
# the bot's camera output so it reads as "PrismAI" with our mark rather than a bare
# "P" initial. The tile is a 1280x720 JPEG (Recall requires 16:9, <=1.3MB)
# generated from the app logo (backend/assets/bot_tile.jpg).
BOT_DISPLAY_NAME = os.getenv("PRISM_BOT_DISPLAY_NAME", "PrismAI")
# Live-streaming keyterm grounding is OFF by default — it broke Deepgram nova-3
# streaming transcription (no transcript.data events / empty transcript). Grounding
# still applies in the async batch re-transcription path. Flip to "1" to re-test.
_LIVE_KEYTERM_ENABLED = os.getenv("PRISM_LIVE_KEYTERM", "0") == "1"
_BOT_TILE_ENABLED = os.getenv("PRISM_BOT_LOGO", "1") != "0"
_BOT_TILE_PATH = os.path.join(os.path.dirname(__file__), "assets", "bot_tile.jpg")


@lru_cache(maxsize=1)
def _bot_video_output() -> dict | None:
    """Recall `automatic_video_output` payload showing our logo tile as the bot's
    camera when it's recording. Base64 is read+encoded once (cached). Best-effort:
    returns None (no tile, unchanged behaviour) if disabled or the asset is missing
    so a packaging slip can never block a bot from joining."""
    if not _BOT_TILE_ENABLED:
        return None
    try:
        with open(_BOT_TILE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return {"in_call_recording": {"kind": "jpeg", "b64_data": b64}}
    except Exception as exc:
        print(f"[recall] bot tile load skipped: {exc}")
        return None

# In-memory cache (always used for fast access; synced to Supabase when available)
bot_store: dict = {}

# live_token → bot_id index for public live-share lookups
_live_token_index: dict = {}

# Tracks bots whose proactive checker has been re-spawned after a server restart,
# so repeated /bot-status polls don't keep creating new tasks.
_proactive_respawned: set[str] = set()

# Bots whose transcript analysis is currently in flight. Without this guard, the
# /bot-status "zombie re-trigger" fires on every poll while status is still
# "processing" — spawning a duplicate full analysis each time and exploding token
# usage (this is what exhausted the Groq daily limit). One analysis per bot.
_processing_bots: set[str] = set()

# Stand-in delivery guards (in-memory; the DB pending->delivered flip is the real
# idempotency, these just avoid redundant work on repeated in_call_recording events).
_standin_delivered: set[str] = set()
_standin_intro_sent: set[str] = set()

# Bots with a live server-side lifecycle poller (scheduled stand-in bots — see
# _poll_standin_lifecycle). Prevents spawning two pollers for the same bot.
_standin_pollers: set[str] = set()

# Stand-in bots whose analysed meeting we've already promoted into the `meetings`
# table (see _persist_standin_meeting). The real idempotency is the existing-row
# check; this just avoids re-querying on repeat calls.
_standin_persisted: set[str] = set()


def _db_save(bot_id: str, fields: dict):
    """Persist bot state to Supabase (best-effort, non-blocking)."""
    if not supabase:
        return
    try:
        fields["bot_id"] = bot_id
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        supabase.table("bot_sessions").upsert(fields, on_conflict="bot_id").execute()
    except Exception as exc:
        print(f"[recall] db save failed for {bot_id}: {exc}")


def _db_load(bot_id: str) -> dict | None:
    """Load bot state from Supabase."""
    if not supabase:
        return None
    try:
        res = supabase.table("bot_sessions").select("*").eq("bot_id", bot_id).maybe_single().execute()
        if res and res.data:
            row = res.data
            # Restore memory state into _bot_state so live-share and command processing
            # have the compressed summary after a server restart.
            if row.get("memory_summary") or row.get("live_state"):
                try:
                    from realtime_routes import _get_bot_state
                    import meeting_memory
                    rt_state = _get_bot_state(bot_id)
                    meeting_memory.restore_memory_state(row, rt_state)
                except Exception as mem_exc:
                    print(f"[recall] memory restore failed for {bot_id}: {mem_exc}")
            if row.get("status") in ("joining", "recording") and bot_id not in _proactive_respawned:
                _proactive_respawned.add(bot_id)
                try:
                    from realtime_routes import _run_proactive_checker
                    asyncio.create_task(_run_proactive_checker(bot_id))
                except Exception as exc:
                    print(f"[recall] failed to re-spawn proactive checker: {exc}")
            # Restore the durable realtime transcript so _process_bot_transcript's
            # fallback can recover it after a restart when Recall has 0 recordings.
            rt_blob = row.get("realtime_transcript") or ""
            rt_lines = rt_blob.split("\n") if rt_blob else []
            loaded = {
                "status": row.get("status", "joining"),
                "result": row.get("result"),
                "error": row.get("error"),
                "transcript": row.get("transcript"),
                "commands": row.get("commands") or [],
                "user_id": row.get("user_id"),
                "realtime_transcript_lines": rt_lines,
                # Restore identity/context so a mid-meeting restart keeps the live/
                # notes link (live_token), the email-FROM-owner sender (owner_name),
                # and workspace fan-out/persona (workspace_id). These were persisted
                # by _db_save but previously dropped on load.
                "live_token": row.get("live_token"),
                "owner_name": row.get("owner_name"),
                "workspace_id": row.get("workspace_id"),
            }
            # Restore seekable segments so click-to-seek survives a mid-meeting restart.
            rt_segs = row.get("transcript_segments")
            if isinstance(rt_segs, list) and rt_segs:
                loaded["realtime_segments"] = rt_segs
            return loaded
    except Exception as exc:
        print(f"[recall] db load failed for {bot_id}: {exc}")
    return None


def _db_save_memory(bot_id: str, memory_summary: str, live_state: dict):
    """Persist memory columns to bot_sessions after each successful compression cycle."""
    _db_save(bot_id, {"memory_summary": memory_summary, "live_state": live_state})


def _db_append_command(bot_id: str, command: dict):
    """Append a command log entry atomically using Postgres jsonb_insert."""
    if not supabase:
        return
    try:
        # Use rpc to atomically append — avoids read-modify-write race when two
        # commands arrive simultaneously for the same bot.
        supabase.rpc(
            "append_bot_command",
            {"p_bot_id": bot_id, "p_command": command},
        ).execute()
    except Exception as exc:
        print(f"[recall] db append command failed: {exc}")

STATUS_MAP = {
    "joining_call": "joining",
    "in_call_not_recording": "joining",
    "in_call_recording": "recording",
    "call_ended": "processing",
    "done": "done",
    "fatal_error": "error",
}

# Human-readable explanation per Recall status sub_code, so when the bot drops we can
# tell the user WHY ("a participant removed Prism") instead of leaving it a mystery.
_LEAVE_REASON_TEXT = {
    "bot_removed": "A participant removed Prism from the meeting.",
    "bot_kicked_from_waiting_room": "Prism was removed from the waiting room before being admitted.",
    "timeout_exceeded_waiting_room": "Prism was never admitted from the waiting room (timed out).",
    "recording_permission_denied": "The host denied recording permission, so Prism left.",
    "recording_permission_allowed_timeout": "Recording was never approved, so Prism left.",
    "meeting_ended": "The meeting ended.",
    "call_ended_by_host": "The host ended the meeting.",
    "call_ended_by_platform_waiting_room_timeout": "Prism timed out in the waiting room.",
    "everyone_left": "Everyone left, so Prism left too.",
    "timeout_exceeded_everyone_left": "Everyone else had left, so Prism left.",
    "timeout_exceeded_only_bots": "Only bots remained, so Prism left.",
    "timeout_exceeded_silence": "The meeting was silent for a long time, so Prism left.",
    "bot_received_leave_call": "Prism was asked to leave the call (via /leave).",
    "bot_errored": "Prism hit an internal error and left.",
}

# Exits worth surfacing IN the meeting analysis (not just logs) — the bot didn't
# leave for a normal "meeting over" reason, so the notes should carry a trace of
# why it dropped (removed / denied recording / kicked from waiting room / asked to
# leave / errored). Normal endings (meeting_ended, everyone_left, call_ended_by_host)
# are intentionally NOT notable — no need to flag a clean finish.
_NOTABLE_LEAVE_SUBCODES = {
    "bot_removed",
    "bot_kicked_from_waiting_room",
    "timeout_exceeded_waiting_room",
    "recording_permission_denied",
    "recording_permission_allowed_timeout",
    "call_ended_by_platform_waiting_room_timeout",
    "bot_received_leave_call",
    "bot_errored",
}


def _extract_status_detail(payload: dict) -> tuple[str, str, str]:
    """Pull (code, sub_code, message) from a Recall status webhook. Recall has
    shifted the nesting over schema versions (data.status.* vs data.data.*), so
    check every known location and return '' for whatever is absent."""
    data = payload.get("data") or {}
    for node in (data.get("status"), data.get("data"), data):
        if isinstance(node, dict) and (node.get("code") or node.get("sub_code")):
            return (
                str(node.get("code") or ""),
                str(node.get("sub_code") or ""),
                str(node.get("message") or ""),
            )
    return "", "", ""


def _leave_reason_text(code: str, sub_code: str, message: str) -> str:
    """Friendly one-liner for why the bot left, preferring the known sub_code map,
    then Recall's own message, then a generic code dump (never empty)."""
    if sub_code and sub_code in _LEAVE_REASON_TEXT:
        return _LEAVE_REASON_TEXT[sub_code]
    if message:
        return message
    if sub_code:
        return f"Prism left ({code or 'call_ended'}: {sub_code})."
    return f"Prism left ({code or 'call ended'})."


def _record_leave_reason(bot_id: str, code: str, sub_code: str, message: str) -> None:
    """Log + persist why the bot left so it's never a silent disconnect. Surfaced
    via /bot-status (and the live payload) for the dashboard."""
    reason = _leave_reason_text(code, sub_code, message)
    notable = (sub_code in _NOTABLE_LEAVE_SUBCODES) or (code == "fatal_error")
    # Stickiness: a specific notable exit (asked to leave / removed / errored) is
    # more informative than a generic call_ended that Recall may fire moments later.
    # Once we've recorded a notable reason, don't let a later non-notable call
    # downgrade it (the webhook call_ended path records unconditionally).
    if not notable and (bot_store.get(bot_id, {}) or {}).get("leave_notable"):
        print(f"[recall] bot {bot_id} keeping earlier notable leave reason "
              f"(ignoring later code={code!r} sub_code={sub_code!r})")
        return
    print(f"[recall] bot {bot_id} left — code={code!r} sub_code={sub_code!r} "
          f"notable={notable} reason={reason!r}")
    if bot_id in bot_store:
        bot_store[bot_id]["leave_reason"] = reason
        bot_store[bot_id]["leave_sub_code"] = sub_code
        bot_store[bot_id]["leave_notable"] = notable
        bot_store[bot_id].setdefault("left_at", datetime.now(timezone.utc).isoformat())
    try:
        _db_save(bot_id, {"leave_reason": reason})
    except Exception as exc:
        print(f"[recall] leave_reason persist skipped: {exc}")


def _normalize_meeting_url(url: str) -> str:
    """Lowercase + strip query params/fragments so two users with the same meeting link match."""
    try:
        p = urlparse(url.strip().lower())
        return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))
    except Exception:
        return url.strip().lower()


async def _find_shared_workspace_bot(client, normalized_url: str, requesting_user_id: str) -> dict | None:
    """Return an active meeting_bots row for this URL where the bot owner shares a workspace
    with the requesting user. Returns None if no such bot exists, or if the workspace tables
    are missing (local dev without supabase/workspace_migration.sql applied).

    For non-scheduled candidates we confirm the bot is genuinely still in the call
    (Recall API) before treating it as a dedup target. Google Meet reuses meeting
    codes, so a stale 'recording'/'joining' row left by a crashed or finished bot on
    a reused URL would otherwise falsely shadow a brand-new meeting ("Prism is already
    in this meeting via …" + an empty transcript). Stale rows are marked done so they
    stop matching."""
    try:
        active = (
            client.table("meeting_bots")
            .select("bot_id, owner_user_id, status")
            .eq("meeting_url", normalized_url)
            # Include 'scheduled' so a teammate's not-yet-joined stand-in bot is caught
            # here too — otherwise an auto-join racing the stand-in's join double-books.
            .in_("status", ["scheduled", "joining", "recording", "processing"])
            .execute()
        )
        if not active.data:
            print(f"[recall] dedup: no active meeting_bots for url={normalized_url[:60]}")
            return None

        from caches import get_user_workspace_ids
        my_ws_ids = get_user_workspace_ids(client, requesting_user_id)
        if not my_ws_ids:
            print(f"[recall] dedup: {requesting_user_id} has no workspaces — can't match "
                  f"{len(active.data)} active bot(s) for this url")
            return None

        for bot in active.data:
            if bot["owner_user_id"] == requesting_user_id:
                continue
            shared = (
                client.table("workspace_members")
                .select("workspace_id, user_email")
                .eq("user_id", bot["owner_user_id"])
                .in_("workspace_id", my_ws_ids)
                .limit(1)
                .execute()
            )
            if not shared.data:
                continue
            # 'scheduled' = a future stand-in bot that hasn't joined yet (correctly
            # not "live") — trust it. For in-call statuses, verify the bot is actually
            # still in the meeting; a stale row on a reused Meet code must not shadow
            # a fresh join.
            if bot.get("status") != "scheduled" and not await _bot_is_live(bot["bot_id"]):
                print(f"[recall] dedup: candidate bot {bot['bot_id']} is not live — "
                      f"marking stale row done, not deduping")
                _mb_update_status(bot["bot_id"], "done")
                continue
            return {**bot, "owner_user_email": shared.data[0].get("user_email", "")}
        owners = [b.get("owner_user_id") for b in active.data]
        print(f"[recall] dedup: {len(active.data)} active bot(s) for this url but none "
              f"share a workspace with {requesting_user_id} (owners={owners})")
        return None
    except Exception as exc:
        print(f"[recall] dedup lookup skipped (workspace tables likely missing): {exc}")
        return None


async def _bot_is_live(bot_id: str) -> bool:
    """Ask Recall whether a bot is still in the call. Used to confirm a candidate
    dedup target is genuinely live before reusing it — guards against stale
    'joining'/'recording' rows left behind by a crashed or removed bot."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
        if resp.status_code != 200:
            return False
        changes = resp.json().get("status_changes") or []
        code = changes[-1].get("code", "") if changes else ""
        return code in ("joining_call", "in_call_not_recording", "in_call_recording")
    except Exception:
        return False


async def _find_own_active_bot(client, normalized_url: str, user_id: str) -> dict | None:
    """Return the requesting user's OWN bot that is still live in this meeting, so a
    second Join/Rejoin click attaches to it instead of spawning a duplicate bot in the
    same room (the bug that split a meeting's transcript across two bots). Verifies each
    candidate against Recall so a stale DB row never blocks a legitimate new join."""
    if not user_id:
        return None
    try:
        res = (
            client.table("meeting_bots")
            .select("bot_id, created_at")
            .eq("meeting_url", normalized_url)
            .eq("owner_user_id", user_id)
            .in_("status", ["joining", "recording"])
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
    except Exception as exc:
        print(f"[recall] self-dedup lookup skipped: {exc}")
        return None
    for row in (res.data or []):
        if await _bot_is_live(row["bot_id"]):
            return {"bot_id": row["bot_id"]}
        # Stale row — its bot is no longer in the call. Sync status so it stops
        # showing up as active for future dedup checks.
        _mb_update_status(row["bot_id"], "error")
    return None


def _mb_update_status(bot_id: str, status: str):
    """Update meeting_bots.status — best-effort, non-blocking."""
    if not supabase:
        return
    try:
        supabase.table("meeting_bots").update({"status": status}).eq("bot_id", bot_id).execute()
    except Exception as exc:
        print(f"[recall] meeting_bots status update failed for {bot_id}: {exc}")


def _live_token_for_bot(bot_id: str) -> str | None:
    """Best-effort lookup of a bot's live_token (in-memory, then DB). Used to hand
    a dedup'd teammate the shared bot's live token so they can open the live view
    + private catch-up from their own dashboard."""
    entry = bot_store.get(bot_id) or _db_load(bot_id) or {}
    return entry.get("live_token")


# Generic words / file noise we never want as keyterms — they'd waste Deepgram's
# ~500-token budget and bias spelling toward nothing useful.
_KEYTERM_STOPWORDS = {
    "document", "untitled", "meeting", "transcript", "notes", "note", "draft",
    "final", "copy", "doc", "pdf", "docx", "txt", "team", "call", "sync", "weekly",
    "daily", "standup", "agenda", "summary", "unassigned", "tbd", "everyone", "all",
    "none", "speaker", "guest", "participant", "user", "prism", "prismai",
}

# A transcript line that opens with a speaker label, e.g. "Jane Doe: hi there".
_SPEAKER_LINE_RE = re.compile(r"^([A-Z][\w .'’-]{1,38}):", re.MULTILINE)


def _name_from_email(email: str) -> str:
    """Derive a display name from an email local-part: jane.doe@x → 'Jane Doe'."""
    local = (email or "").split("@", 1)[0]
    parts = re.split(r"[._\-+0-9]+", local)
    words = [p.capitalize() for p in parts if len(p) >= 2]
    return " ".join(words[:3]).strip()


# Title-Case / camelCase term extractor for keyterm content-mining. Matches 1–3-word
# Title-Case runs ("Reciprocal Rank Fusion") and internal-caps tokens ("CodeQL", "PrismAI").
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2}\b")
_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+[A-Z][a-zA-Z]+\b")
# Common English words that get capitalised at sentence start — filtered so the
# keyterm budget isn't wasted on "The", "This", "We", etc.
_COMMON_LEADING_WORDS = frozenset({
    "the", "this", "that", "these", "those", "we", "i", "you", "he", "she", "it", "they",
    "a", "an", "and", "but", "or", "so", "if", "then", "there", "here", "our", "your",
    "their", "his", "her", "its", "what", "when", "where", "how", "why", "who", "which",
    "for", "to", "in", "on", "at", "as", "of", "by", "is", "are", "was", "were", "be",
    "will", "would", "should", "could", "can", "may", "might", "also", "now", "let",
    "lets", "let's", "no", "yes", "not", "all", "some", "each", "every", "any", "one",
})


def _proper_nouns_from_texts(texts: list[str], limit: int = 15) -> list[str]:
    """Rank candidate proper nouns mined from doc content. Multi-word Title-Case and
    internal-caps tokens are strong signals; single Title-Case words must recur (>=2)
    to beat sentence-initial noise. Returns highest-signal terms first, bounded."""
    from collections import Counter
    counts: Counter = Counter()
    strong: set[str] = set()

    def _keep(term: str) -> bool:
        # Drop common words (incl. sentence-initial "The/This/We") whose lowercase, or
        # leading word, is a known stopword — so the small budget isn't wasted on noise.
        first = term.split(" ", 1)[0].lower()
        if term.lower() in _KEYTERM_STOPWORDS or first in _KEYTERM_STOPWORDS:
            return False
        if first in _COMMON_LEADING_WORDS:
            return False
        return True

    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        for m in _PROPER_NOUN_RE.findall(text):
            if not _keep(m):
                continue
            counts[m] += 1
            if " " in m:            # multi-word Title Case = strong signal
                strong.add(m)
        for m in _CAMEL_RE.findall(text):
            if not _keep(m):
                continue
            counts[m] += 1
            strong.add(m)
    # Strong terms first (by frequency), then recurring single-word terms.
    ranked = sorted(strong, key=lambda t: -counts[t])
    singles = sorted((t for t, c in counts.items() if t not in strong and c >= 2),
                     key=lambda t: -counts[t])
    return (ranked + singles)[:limit]


def _gather_keyterms(user_id: str | None, workspace_id: str | None) -> list[str]:
    """Best-effort proper-noun list to ground Deepgram nova-3 (keyterm prompting):
    teammate names + knowledge-doc titles + knowledge-doc CONTENT proper nouns +
    recent-meeting speaker/owner names.
    Capitalisation is preserved (Deepgram weights proper nouns by spelling) and the
    list is bounded to ~40 terms. Returns [] on any failure so the bot-create config
    stays exactly as before — grounding is a pure add-on, never a blocker."""
    if not supabase or not (user_id or workspace_id):
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def _add(raw: str):
        t = re.sub(r"\.[a-z0-9]{2,4}$", "", (raw or "").strip())   # strip file ext
        t = re.sub(r"\s+", " ", t).strip(" -_·•")
        if len(t) < 2 or len(terms) >= 40:
            return
        low = t.lower()
        if low in _KEYTERM_STOPWORDS or low in seen:
            return
        # Deepgram nova-3 keyterm prompting expects SHORT proper nouns. Long titles
        # with dates/parens (e.g. "Prism App Development Sprint Planning (2026-06-26)")
        # break the streaming transcription connection — reject anything that isn't a
        # clean name/term: no digits, no punctuation, <=3 words, <=30 chars.
        if any(c.isdigit() for c in t):
            return
        if any(c in t for c in "()[]{}:/\\|@#&+*=<>\"'"):
            return
        if len(t) > 30 or len(t.split()) > 3:
            return
        # Keep proper-cased or multi-word terms; drop short all-lowercase common words.
        if " " not in t and t.islower() and len(t) < 6:
            return
        seen.add(low)
        terms.append(t)

    try:
        from caches import get_user_workspace_ids
        ws_ids = list(get_user_workspace_ids(supabase, user_id)) if user_id else []
    except Exception:
        ws_ids = []
    if workspace_id and workspace_id not in ws_ids:
        ws_ids.append(workspace_id)

    # 0. Explicit glossary (custom_keyterms) — hand-corrected mishearings and
    #    added proper nouns. Highest priority: added FIRST so a user's own
    #    corrections always survive the ~40-term cap. Fed by the chat correction
    #    tool (tools/meeting_edit.correct_meeting_text).
    try:
        glossary: list[str] = []
        if user_id:
            gp = (supabase.table("custom_keyterms").select("term")
                  .eq("user_id", user_id).eq("workspace_id", "").limit(40).execute())
            glossary += [r.get("term") or "" for r in (gp.data or [])]
        if ws_ids:
            gw = (supabase.table("custom_keyterms").select("term")
                  .in_("workspace_id", ws_ids).limit(40).execute())
            glossary += [r.get("term") or "" for r in (gw.data or [])]
        for t in glossary:
            _add(t)
    except Exception as exc:
        print(f"[keyterms] glossary skipped: {exc}")

    # 1. Teammate names from workspace member emails.
    try:
        if ws_ids:
            rows = (supabase.table("workspace_members").select("user_email")
                    .in_("workspace_id", ws_ids).limit(50).execute())
            for r in (rows.data or []):
                nm = _name_from_email(r.get("user_email") or "")
                if nm:
                    _add(nm)
    except Exception as exc:
        print(f"[keyterms] member names skipped: {exc}")

    # 2. Knowledge-doc titles (caller's own + workspace-shared docs).
    try:
        own = (supabase.table("knowledge_docs").select("name")
               .eq("user_id", user_id).is_("deleted_at", "null").limit(30).execute()) if user_id else None
        for r in (own.data if own else []):
            _add(r.get("name") or "")
        if ws_ids:
            shared = (supabase.table("knowledge_docs").select("name")
                      .in_("workspace_id", ws_ids).is_("deleted_at", "null").limit(30).execute())
            for r in (shared.data or []):
                _add(r.get("name") or "")
    except Exception as exc:
        print(f"[keyterms] doc titles skipped: {exc}")

    # 2.5 Proper nouns mined from knowledge-doc CONTENT (not just titles) — the real
    #     jargon / product / people names live in the body. Sample a bounded set of
    #     chunks, rank Title-Case / camelCase terms by frequency, add the top ones.
    try:
        contents: list[str] = []
        if user_id:
            own_c = (supabase.table("knowledge_chunks").select("content")
                     .eq("user_id", user_id).limit(60).execute())
            contents += [r.get("content") or "" for r in (own_c.data or [])]
        if ws_ids:
            shared_c = (supabase.table("knowledge_chunks").select("content")
                        .in_("workspace_id", ws_ids).limit(60).execute())
            contents += [r.get("content") or "" for r in (shared_c.data or [])]
        for term in _proper_nouns_from_texts(contents, limit=15):
            _add(term)
    except Exception as exc:
        print(f"[keyterms] doc content skipped: {exc}")

    # 3. Recent-meeting speaker + action-item-owner names (structured, from result
    #    JSON — avoids pulling full transcripts at join time).
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        q = supabase.table("meetings").select("result").gte("date", cutoff)\
            .order("date", desc=True).limit(15)
        if user_id:
            q = q.eq("user_id", user_id)
        rows = q.execute()
        for r in (rows.data or []):
            result = r.get("result") or {}
            if not isinstance(result, dict):
                continue
            for sp in ((result.get("sentiment") or {}).get("speakers") or []):
                if isinstance(sp, dict):
                    _add(sp.get("name") or "")
            for ai in (result.get("action_items") or []):
                if isinstance(ai, dict):
                    _add(ai.get("owner") or "")
    except Exception as exc:
        print(f"[keyterms] recent meeting names skipped: {exc}")

    if terms:
        print(f"[keyterms] grounding bot transcription with {len(terms)} terms: {terms[:12]}{'…' if len(terms) > 12 else ''}")
    return terms


def _recall_bot_create_json(meeting_url: str, realtime_url: str, webhook_url: str,
                            join_at: str | None = None, bot_name: str = BOT_DISPLAY_NAME,
                            keyterms: list[str] | None = None) -> dict:
    """The Recall bot-create payload, shared by immediate joins and scheduled
    stand-in bots. A future `join_at` (ISO 8601) makes Recall schedule the join
    instead of joining now; omit it (None) to join immediately. Callers drop a
    past/imminent join_at to None so live meetings are covered. `bot_name` is the
    in-meeting display name —
    stand-in bots pass the represented person's name so attendees recognise (and
    admit) it and know whose update it carries. `keyterms` is an optional list of
    proper nouns (teammate names, products, jargon) passed to Deepgram nova-3's
    keyterm prompting so it spells domain-specific terms correctly at transcribe
    time — see `_gather_keyterms`. Omitted when empty so behaviour is unchanged."""
    deepgram: dict = {
        "model": "nova-3",
        "language": "en",
        "smart_format": "true",
        "punctuate": "true",
        "diarize": "true",
        "endpointing": 300,
        "utterance_end_ms": 1000,
        "interim_results": "true",
    }
    if keyterms and _LIVE_KEYTERM_ENABLED:
        # Deepgram caps the keyterm budget at ~500 tokens; _gather_keyterms already
        # bounds the list, but clamp here too so a future caller can't blow it.
        # DEFAULT OFF (PRISM_LIVE_KEYTERM): passing keyterm to the LIVE deepgram_streaming
        # config broke spoken transcription entirely (no transcript.data events, empty
        # transcript) when the term list contained anything malformed. Keyterm grounding
        # stays ON only in the async batch re-transcription (_request_async_transcript),
        # where it's well-supported. Re-enable here only after live validation.
        deepgram["keyterm"] = keyterms[:50]
    body = {
        "meeting_url": meeting_url,
        "bot_name": bot_name,
        "webhook_url": webhook_url,
        "recording_config": {
            "video_mixed_layout": "speaker_view",
            "video_mixed_mp4": {},
            "audio_mixed_mp3": {},
            "transcript": {
                "provider": {
                    "deepgram_streaming": deepgram
                }
            },
            "realtime_endpoints": [
                {
                    "type": "webhook",
                    "url": realtime_url,
                    "events": [
                        "transcript.data",
                        "participant_events.chat_message",
                        "participant_events.join",
                        "participant_events.leave",
                    ],
                }
            ],
        },
    }
    tile = _bot_video_output()
    if tile:
        body["automatic_video_output"] = tile
    if join_at:
        body["join_at"] = join_at
    return body


def _find_existing_bot_for_standin(client, normalized_url: str, user_id: str,
                                   statuses=("scheduled", "joining", "recording", "processing")) -> dict | None:
    """Stand-in dedup: is there already a bot for this meeting that we should attach to
    instead of spawning another? Matches the user's own bot OR a teammate's bot in a
    shared workspace. Includes 'scheduled' status (unlike the live dedup helpers) since a
    stand-in bot may not have joined yet. Pass statuses=("scheduled",) to check ONLY
    not-yet-joined bots (used by /join-meeting so a live-dedup's stale-row check isn't
    re-run here)."""
    try:
        rows = (
            client.table("meeting_bots")
            .select("bot_id, owner_user_id")
            .eq("meeting_url", normalized_url)
            .in_("status", list(statuses))
            .execute()
        )
    except Exception as exc:
        print(f"[standin] dedup lookup skipped: {exc}")
        return None
    if not rows.data:
        return None
    from caches import get_user_workspace_ids
    my_ws = get_user_workspace_ids(client, user_id) or []
    for bot in rows.data:
        if bot["owner_user_id"] == user_id:
            return bot
        if my_ws:
            shared = (
                client.table("workspace_members")
                .select("workspace_id")
                .eq("user_id", bot["owner_user_id"])
                .in_("workspace_id", my_ws)
                .limit(1)
                .execute()
            )
            if shared.data:
                return bot
    return None


async def schedule_standin_bot(meeting_url: str, user_id: str, workspace_id: str | None,
                               owner_name: str | None, join_at: str) -> dict | None:
    """Create (or reuse) a Recall bot scheduled to join `meeting_url` at `join_at`
    to deliver a stand-in. Returns {bot_id, reused}. Skips intro/proactive — those
    fire when the bot actually joins (A3). Returns None if Recall isn't configured
    or the create failed."""
    if not RECALL_API_KEY:
        return None
    normalized = _normalize_meeting_url(meeting_url)

    # A meeting that's already started (or about to) can't be "scheduled" for a
    # future join — Recall needs lead time. If join_at is in the past or imminent,
    # join now instead so "Can't make it" still works on a live/imminent meeting.
    effective_join_at = join_at
    try:
        if join_at:
            start = datetime.fromisoformat(join_at.replace("Z", "+00:00"))
            if start <= datetime.now(timezone.utc) + timedelta(minutes=2):
                effective_join_at = None
    except Exception:
        effective_join_at = join_at

    # Dedup: attach to an existing scheduled/live bot for this meeting if there is one.
    if supabase:
        existing = _find_existing_bot_for_standin(supabase, normalized, user_id)
        if existing:
            print(f"[standin] reusing existing bot {existing['bot_id']} for stand-in")
            return {"bot_id": existing["bot_id"], "reused": True}

    realtime_token = secrets.token_urlsafe(32)
    realtime_url = f"{WEBHOOK_BASE_URL}/realtime-events/{realtime_token}"
    webhook_url = f"{WEBHOOK_BASE_URL}/recall-webhook"
    # Name the bot after the person it stands in for, so attendees recognise it in
    # the waiting room (and know whose update it's carrying). Falls back to PrismAI.
    display_name = f"{owner_name.strip()} (PrismAI stand-in)" if (owner_name or "").strip() else BOT_DISPLAY_NAME
    body = _recall_bot_create_json(meeting_url, realtime_url, webhook_url,
                                   join_at=effective_join_at, bot_name=display_name,
                                   keyterms=_gather_keyterms(user_id, workspace_id))
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/",
                headers={"Authorization": f"Token {RECALL_API_KEY}", "Content-Type": "application/json"},
                json=body,
                timeout=15,
            )
    except Exception as exc:
        print(f"[standin] recall schedule request failed: {exc}")
        return None
    if resp.status_code not in (200, 201):
        print(f"[standin] recall schedule failed ({resp.status_code}): {resp.text[:200]}")
        return None

    bot_id = resp.json()["id"]
    live_token = secrets.token_hex(16)
    bot_store[bot_id] = {
        "status": "scheduled", "result": None, "error": None, "commands": [],
        "user_id": user_id, "live_token": live_token, "owner_name": owner_name,
        "workspace_id": workspace_id, "realtime_token": realtime_token,
        "initial_mode": None, "standin": True,
    }
    _live_token_index[live_token] = bot_id
    _db_save(bot_id, {"status": "scheduled", "user_id": user_id, "live_token": live_token,
                      "owner_name": owner_name, "workspace_id": workspace_id})

    from realtime_routes import init_bot_realtime, register_realtime_token
    register_realtime_token(realtime_token, bot_id)
    if supabase:
        try:
            supabase.table("meeting_bots").insert({
                "bot_id": bot_id, "meeting_url": normalized,
                "owner_user_id": user_id, "status": "scheduled",
            }).execute()
        except Exception as exc:
            print(f"[standin] meeting_bots insert failed: {exc}")
        if workspace_id:
            try:
                supabase.table("meeting_bots").update(
                    {"workspace_id": workspace_id}
                ).eq("bot_id", bot_id).execute()
            except Exception:
                pass
    init_bot_realtime(bot_id)
    # Drive this headless bot's lifecycle ourselves — nothing else polls it (no
    # dashboard, no Recall account webhook). See _poll_standin_lifecycle.
    asyncio.create_task(_poll_standin_lifecycle(bot_id, effective_join_at))
    print(f"[standin] bot {bot_id} {'joining now' if not effective_join_at else f'scheduled for {effective_join_at}'}")
    return {"bot_id": bot_id, "reused": False}


async def cancel_standin_bot(bot_id: str, user_id: str, rep_id: str) -> None:
    """Best-effort teardown of a scheduled stand-in bot when its representation is
    canceled. Only deletes the Recall bot if WE own it, it hasn't joined yet, and no
    other live stand-in still needs it — never kills a teammate's or an already-live bot."""
    if not RECALL_API_KEY:
        return
    if supabase:
        try:
            others = (
                supabase.table("proxy_representations").select("id")
                .eq("scheduled_bot_id", bot_id).neq("status", "canceled").neq("id", rep_id)
                .limit(1).execute()
            )
            if others.data:
                return  # another stand-in still relies on this bot
            mb = (
                supabase.table("meeting_bots").select("owner_user_id, status")
                .eq("bot_id", bot_id).maybe_single().execute()
            )
            if mb and mb.data and (
                mb.data.get("owner_user_id") != user_id
                or mb.data.get("status") not in ("scheduled", "joining")
            ):
                return  # not ours, or already live — leave it alone
        except Exception as exc:
            print(f"[standin] cancel guard check failed: {exc}")
    try:
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
    except Exception as exc:
        print(f"[standin] cancel bot delete failed: {exc}")
    _mb_update_status(bot_id, "canceled")


async def _poll_standin_lifecycle(bot_id: str, join_at: str | None = None) -> None:
    """Server-side lifecycle driver for a headless scheduled stand-in bot.

    A scheduled stand-in bot has no dashboard polling /bot-status for it, and there is
    no Recall account webhook hitting /recall-webhook — so nothing would otherwise fire
    its join/end handlers. This task polls Recall's bot status directly and runs the
    SAME idempotent handlers the /bot-status poll runs: intro + stand-in delivery on
    in_call_recording, analysis on call_ended.

    In-memory task: it does NOT survive a process restart (same limitation as
    bot_store / the live token index). That's acceptable — it makes a single scheduled
    stand-in work end-to-end without any external webhook config."""
    if not RECALL_API_KEY or bot_id in _standin_pollers:
        return
    _standin_pollers.add(bot_id)
    try:
        # Wait until shortly before the scheduled join so we don't burn polls for a
        # meeting that's an hour out. Capped so a bad/far join_at can't sleep forever.
        if join_at:
            try:
                start = datetime.fromisoformat(join_at.replace("Z", "+00:00"))
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                lead = (start - datetime.now(timezone.utc)).total_seconds() - 60
                if lead > 0:
                    await asyncio.sleep(min(lead, 6 * 3600))
            except Exception:
                pass

        deadline = time.time() + 4 * 3600  # hard safety cap so the task always exits
        in_meeting = False
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                try:
                    resp = await client.get(
                        f"{RECALL_API_BASE}/bot/{bot_id}/",
                        headers={"Authorization": f"Token {RECALL_API_KEY}"},
                        timeout=10,
                    )
                    code = ""
                    if resp.status_code == 200:
                        changes = resp.json().get("status_changes") or []
                        code = changes[-1].get("code", "") if changes else ""
                except Exception as exc:
                    print(f"[standin] poll error bot={bot_id[:8]}: {exc}")
                    await asyncio.sleep(15)
                    continue

                if code == "in_call_recording" and bot_id not in _standin_delivered:
                    _standin_delivered.add(bot_id)
                    # Keep meeting_bots accurate so the live workspace-dedup can see this
                    # bot is in the room (a stale 'scheduled' row makes a teammate's join
                    # double-book instead of attaching).
                    _mb_update_status(bot_id, "recording")
                    if bot_store.get(bot_id, {}).get("standin") and bot_id not in _standin_intro_sent:
                        _standin_intro_sent.add(bot_id)
                        asyncio.create_task(_send_bot_intro(bot_id))
                    asyncio.create_task(deliver_standins_for_bot(bot_id))
                    in_meeting = True

                if code in ("call_ended", "done"):
                    entry = bot_store.setdefault(
                        bot_id, {"status": "joining", "result": None, "error": None, "commands": []}
                    )
                    if entry.get("status") not in ("done", "error") and bot_id not in _processing_bots:
                        entry["status"] = "processing"
                        _db_save(bot_id, {"status": "processing"})
                        asyncio.create_task(_process_bot_transcript(bot_id))
                    return

                if code in ("fatal", "error"):
                    print(f"[standin] poll stopping — bot={bot_id[:8]} status={code}")
                    return

                # Poll briskly while in/approaching the call, lazily while still waiting.
                await asyncio.sleep(
                    8 if in_meeting or code in ("in_call_recording", "in_call_not_recording", "joining_call")
                    else 20
                )
        print(f"[standin] poll hit safety cap bot={bot_id[:8]}")
    finally:
        _standin_pollers.discard(bot_id)


def resolve_owner_email(bot_id: str, user_id: str | None = None) -> str:
    """The real email of the bot's owner, so the live bot can email/relay TO them instead
    of inventing a placeholder. For a stand-in it's the representation's author_email; for
    any workspace bot, the owner's workspace_members email. Best-effort, returns '' if
    unknown (the bot then asks for the address rather than guessing)."""
    if not supabase:
        return ""
    try:
        rep = (
            supabase.table("proxy_representations").select("author_email")
            .eq("scheduled_bot_id", bot_id).neq("status", "canceled").limit(1).execute()
        )
        if rep.data and (rep.data[0].get("author_email") or "").strip():
            return rep.data[0]["author_email"].strip()
    except Exception as exc:
        print(f"[recall] resolve_owner_email rep lookup failed bot={bot_id[:8]}: {exc!r}")
    if user_id:
        try:
            wm = (
                supabase.table("workspace_members").select("user_email")
                .eq("user_id", user_id).limit(1).execute()
            )
            if wm.data and (wm.data[0].get("user_email") or "").strip():
                return wm.data[0]["user_email"].strip()
        except Exception as exc:
            print(f"[recall] resolve_owner_email member lookup failed uid={str(user_id)[:8]}: {exc!r}")
    return ""


def _resolve_owner_name(bot_id: str) -> str:
    """The name of the person this bot represents/serves. Prefers the in-memory value but
    falls back to the stand-in representation's author_name — so a server restart that
    wiped bot_store doesn't leave the analysis (and the follow-up email's sender) without
    a meeting owner, which makes the email agent guess a participant instead."""
    entry = bot_store.get(bot_id) or {}
    if (entry.get("owner_name") or "").strip():
        return entry["owner_name"].strip()
    if supabase:
        try:
            rep = (
                supabase.table("proxy_representations").select("author_name")
                .eq("scheduled_bot_id", bot_id).neq("status", "canceled").limit(1).execute()
            )
            if rep.data and (rep.data[0].get("author_name") or "").strip():
                return rep.data[0]["author_name"].strip()
        except Exception:
            pass
    return ""


async def _resolve_bot_persona_name(bot_id: str) -> str:
    """The single display name the bot used in this meeting (e.g. 'Glint'). Used to
    normalise transcript lines so the bot isn't analysed as two speakers — its stand-in
    delivery records under the default name while its replies use the persona name."""
    entry = bot_store.get(bot_id) or {}
    user_id = entry.get("user_id")
    workspace_id = entry.get("workspace_id")
    if not user_id and supabase:
        try:
            rep = (
                supabase.table("proxy_representations").select("author_user_id, workspace_id")
                .eq("scheduled_bot_id", bot_id).neq("status", "canceled").limit(1).execute()
            )
            if rep.data:
                user_id = rep.data[0].get("author_user_id")
                workspace_id = workspace_id or rep.data[0].get("workspace_id")
        except Exception:
            pass
    if not user_id or not supabase:
        return DEFAULT_BOT_NAME
    try:
        resp = supabase.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
        row = (resp.data if resp is not None else None) or {}
        name, _text, _preset = await persona_identity_resolved(supabase, row, workspace_id)
        return name or DEFAULT_BOT_NAME
    except Exception:
        return DEFAULT_BOT_NAME


def _normalize_bot_speaker(lines: list[str], canonical: str) -> list[str]:
    """Rewrite every bot-attributed line prefix to one canonical name so the bot reads as
    a single speaker in analysis (sentiment per-speaker, etc.)."""
    out = []
    for ln in lines:
        for pfx in _BOT_NAME_PREFIXES:
            if ln.startswith(pfx):
                ln = f"{canonical}:{ln[len(pfx):]}"
                break
        out.append(ln)
    return out


async def recover_active_bots() -> None:
    """Startup recovery: re-spawn lifecycle pollers for any bots left in a live state.

    The lifecycle poller is in-memory and dies with the process — so a server restart
    (local dev, or a Render cold start) mid-meeting leaves a scheduled stand-in with
    nothing driving its join/delivery/analysis. Worse, even a finished bot would never
    get analysed or promoted to the dashboard. On boot we scan meeting_bots for any bot
    still in a non-terminal state and re-attach a poller; the poller's first Recall
    status read then drives it the rest of the way (deliver if recording, analyse +
    auto-promote if already ended). Idempotent via the _standin_pollers / _processing_bots
    guards, so it's safe alongside the Recall webhook in production."""
    if not supabase or not RECALL_API_KEY:
        return
    # Only recover RECENT bots. A non-terminal row older than this is stale — a bot that
    # crashed or was abandoned mid-meeting and never reached a terminal status — and
    # re-spawning its poller just retries a transcript that will never exist (0 recordings
    # / 400 spam for ~12 min before it errors out). The window comfortably covers the
    # poller's own 4h safety cap plus a scheduled bot's lead time.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    try:
        rows = (
            supabase.table("meeting_bots").select("bot_id")
            .in_("status", ["scheduled", "joining", "recording", "processing"])
            .gte("created_at", cutoff)
            .execute().data or []
        )
    except Exception as exc:
        print(f"[standin] startup recovery query skipped: {exc}")
        return
    spawned = 0
    for row in rows:
        bid = row.get("bot_id")
        if bid and bid not in _standin_pollers:
            asyncio.create_task(_poll_standin_lifecycle(bid))
            spawned += 1
    if spawned:
        print(f"[standin] startup recovery re-spawned {spawned} lifecycle poller(s)")

    # Backfill any bot whose analysis finished but never landed on a dashboard — e.g.
    # a regular bot whose browser tab crashed/closed before POST /meetings, or a meeting
    # the delayed fallback missed because the process restarted within its window.
    # _persist_bot_meeting dedups on recall_bot_id, so already-saved meetings are skipped.
    backfill_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        done_rows = (
            supabase.table("meeting_bots").select("bot_id")
            .eq("status", "done").gte("created_at", backfill_cutoff)
            .execute().data or []
        )
    except Exception as exc:
        print(f"[recall] startup backfill query skipped: {exc}")
        done_rows = []
    backfilled = 0
    for row in done_rows:
        bid = row.get("bot_id")
        if bid and bid not in _standin_persisted:
            await _persist_bot_meeting(bid)
            backfilled += 1
    if backfilled:
        print(f"[recall] startup backfill checked {backfilled} finished bot(s) for missing dashboard rows")


def standin_updates_for_bot(bot_id: str) -> list[dict]:
    """Durable read of the stand-in updates bound to a bot's meeting, straight from
    Supabase (status pending OR delivered). Used by the spoken-on-request path so it
    never depends on in-memory bot_store (which a restart or a second worker process
    wipes) — and so it can NEVER fall through to the LLM and invent people. Returns
    [{name, body}], approval order."""
    if not supabase:
        return []
    try:
        mb = (
            supabase.table("meeting_bots").select("meeting_url")
            .eq("bot_id", bot_id).maybe_single().execute()
        )
        meeting_url = (mb.data or {}).get("meeting_url") if mb else None
        if not meeting_url:
            return []
        reps = (
            supabase.table("proxy_representations")
            .select("author_name, approved_body, approved_at")
            .eq("meeting_url", meeting_url)
            .in_("status", ["pending", "delivered"])
            .order("approved_at")
            .execute()
        )
    except Exception as exc:
        print(f"[standin] updates_for_bot lookup failed: {exc}")
        return []
    out = []
    for rep in (reps.data or []):
        body = (rep.get("approved_body") or "").strip()
        if body:
            out.append({"name": (rep.get("author_name") or "A teammate").strip(), "body": body})
    return out


async def deliver_standins_for_bot(bot_id: str) -> None:
    """When a bot reaches the meeting, deliver any pending stand-in updates bound to
    its meeting URL: a consolidated chat post (which announces who couldn't attend) +
    recorded into the transcript + stashed on bot_store for the live brief and the
    spoken-on-request path. Each rep is claimed via a conditional pending->delivered
    update, so it delivers exactly once even across bots / restarts.

    Runs for ANY bot (not just scheduled stand-in bots): when stand-ins were dedup'd
    onto a teammate's regular bot, that bot delivers them too."""
    if not supabase:
        return
    try:
        mb = (
            supabase.table("meeting_bots").select("meeting_url")
            .eq("bot_id", bot_id).maybe_single().execute()
        )
    except Exception:
        return
    meeting_url = (mb.data or {}).get("meeting_url") if mb else None
    if not meeting_url:
        return
    try:
        reps = (
            supabase.table("proxy_representations").select("*")
            .eq("meeting_url", meeting_url).eq("status", "pending").execute()
        )
    except Exception as exc:
        print(f"[standin] deliver lookup failed: {exc}")
        return
    pending = reps.data or []
    if not pending:
        return

    now = datetime.now(timezone.utc).isoformat()
    delivered = []
    for rep in pending:
        try:
            upd = (
                supabase.table("proxy_representations")
                .update({"status": "delivered", "delivered_at": now, "delivered_bot_id": bot_id})
                .eq("id", rep["id"]).eq("status", "pending").execute()
            )
            if upd.data:  # we claimed it
                delivered.append(rep)
        except Exception as exc:
            print(f"[standin] deliver claim failed: {exc}")

    lines, updates = [], []
    for rep in delivered:
        name = (rep.get("author_name") or "A teammate").strip()
        body = (rep.get("approved_body") or "").strip()
        if not body:
            continue
        lines.append(f"• {name} — “{body}”")
        updates.append({"name": name, "body": body})
    if not lines:
        return

    msg = "\U0001F4CB Stand-in updates — from people who couldn't attend:\n" + "\n".join(lines)
    bot_store.setdefault(bot_id, {})["standin_updates"] = updates

    from realtime_routes import _send_chat_response, _record_bot_line, _get_bot_state
    import perception_state
    await _send_chat_response(bot_id, msg)
    try:
        state = _get_bot_state(bot_id)
        async with perception_state.get_memory_lock(state):
            _record_bot_line(bot_id, state, msg, DEFAULT_BOT_NAME)
    except Exception as exc:
        print(f"[standin] transcript record failed: {exc}")
    print(f"[standin] delivered {len(updates)} stand-in update(s) for bot {bot_id}")


class JoinMeetingRequest(BaseModel):
    meeting_url: str
    owner_name: str | None = None
    workspace_id: str | None = None
    mode: str | None = None  # pre-join response mode: 'utterance' | 'autonomous'


def _extract_recall_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail

    text = (resp.text or "").strip()
    return text or f"Recall.ai request failed with status {resp.status_code}"


def _build_pre_meeting_brief(user_id: str | None) -> dict | None:
    """Return open action items, recent decisions, and blockers from the owner's meeting history.
    Pure Python — no LLM. Returns None when there is nothing noteworthy to surface."""
    if not supabase or not user_id:
        return None
    try:
        res = (
            supabase.table("meetings")
            .select("date,title,result")
            .eq("user_id", user_id)
            .order("id", desc=True)
            .limit(10)
            .execute()
        )
        meetings = [r for r in (res.data or []) if r.get("result")]
        if not meetings:
            return None

        open_items: list[dict] = []
        recent_decisions: list[dict] = []
        blockers: list[dict] = []

        for meeting in meetings[:5]:
            result = meeting.get("result") or {}
            date = meeting.get("date") or "recent meeting"
            title = meeting.get("title") or "Untitled"

            for item in (result.get("action_items") or []):
                if not item.get("completed") and item.get("task", "").strip():
                    open_items.append({
                        "task": item["task"].strip(),
                        "owner": (item.get("owner") or "").strip(),
                        "due": (item.get("due") or "").strip(),
                        "meeting_date": date,
                        "meeting_title": title,
                    })

            # Only pull decisions from the two most recent meetings
            if len(recent_decisions) < 4:
                for decision in (result.get("decisions") or [])[:3]:
                    if decision.get("decision", "").strip():
                        recent_decisions.append({
                            "decision": decision["decision"].strip(),
                            "owner": (decision.get("owner") or "").strip(),
                            "meeting_date": date,
                        })

            for item in (result.get("action_items") or []):
                if looks_like_blocker(item.get("task", "")) and item.get("task", "").strip():
                    blockers.append({
                        "snippet": build_blocker_snippet(item["task"]),
                        "meeting_date": date,
                    })
            summary = result.get("summary", "")
            if summary and looks_like_blocker(summary):
                blockers.append({
                    "snippet": build_blocker_snippet(summary),
                    "meeting_date": date,
                })

        try:
            refs = (
                supabase.table("action_refs")
                .select("action_item,tool,external_id,created_at")
                .eq("user_id", user_id)
                .eq("resolved", False)
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            )
            for ref in (refs.data or []):
                open_items.append({
                    "task": f"{ref['action_item']} [{ref['tool']}: {ref['external_id']}]",
                    "owner": "",
                    "due": "",
                    "meeting_date": (ref.get("created_at") or "")[:10],
                    "meeting_title": "",
                })
        except Exception:
            pass

        open_items = open_items[:5]
        recent_decisions = recent_decisions[:4]
        blockers = blockers[:3]

        if not open_items and not recent_decisions and not blockers:
            return None

        return {
            "open_items": open_items,
            "recent_decisions": recent_decisions,
            "blockers": blockers,
        }
    except Exception as exc:
        print(f"[recall] pre-meeting brief failed for user {user_id}: {exc}")
        return None


async def _send_bot_intro(bot_id: str):
    await asyncio.sleep(20)
    bot_state = bot_store.get(bot_id) or {}
    live_token = bot_state.get("live_token")
    owner_name = bot_state.get("owner_name") or "the meeting owner"
    user_id = bot_state.get("user_id")
    workspace_id = bot_state.get("workspace_id")
    frontend_url = os.getenv("FRONTEND_URL", "https://meetprismai.com")
    live_link = f"{frontend_url}/#live/{live_token}" if live_token else None

    # Persona-flavored greeting line. Pulls the owner's resolved persona preset
    # (personal override → workspace default → 'default') and picks the matching
    # hardcoded greeting from PERSONA_GREETINGS. The live-link + consent lines
    # below are appended verbatim regardless of preset — compliance-relevant
    # copy stays fixed; only the opening line carries the persona's voice.
    preset = "default"
    if user_id and supabase:
        try:
            resp = supabase.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
            row = (resp.data if resp is not None else None) or {}
            _name, _text, preset = await persona_identity_resolved(supabase, row, workspace_id)
        except Exception as exc:
            print(f"[recall] _send_bot_intro persona resolve failed bot={bot_id[:8]}: {exc!r}")

    message = persona_greeting_from_preset(preset)
    if live_link:
        message += f"\n\nAnyone can follow along live — and the full meeting notes will be here afterward: {live_link}"
    message += f"\n\n⚠️ If you don't consent to being recorded, let {owner_name} know or type /leave and I'll exit the call."
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/send_chat_message/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"message": message},
                timeout=10,
            )
        # Mark the intro as broadcast so late-joiner re-posts can fire. Everyone
        # present at intro saw this message; only participants who join AFTER get
        # a re-post (see post_late_join_link).
        if bot_id in bot_store:
            bot_store[bot_id]["intro_sent"] = True
    except Exception:
        pass


async def post_late_join_link(bot_id: str, participant_name: str = "") -> None:
    """Re-post the live/notes link when someone joins AFTER the intro broadcast,
    so late arrivals get the same link everyone else already saw. No-op until the
    intro has been sent (the initial roster is covered by the intro message), and
    no-op without a live_token. Introduces no new sharing — the intro already
    broadcasts this exact link to the whole chat."""
    state = bot_store.get(bot_id) or {}
    if not state.get("intro_sent"):
        return
    live_token = state.get("live_token")
    if not live_token:
        return
    frontend_url = os.getenv("FRONTEND_URL", "https://meetprismai.com")
    link = f"{frontend_url}/#live/{live_token}"
    who = f" {participant_name.strip()}" if participant_name and participant_name.strip() else ""
    message = (
        f"👋 Welcome{who}! Follow along live — and the full meeting notes will be "
        f"here after the meeting: {link}"
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/send_chat_message/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"message": message},
                timeout=10,
            )
    except Exception as exc:
        print(f"[recall] late-join link post failed bot={bot_id[:8]}: {exc!r}")


async def _fetch_transcript(bot_id: str, attempts: int = 12, prefer_async: bool = False):
    """Fetch transcript — tries media_shortcuts download URL first (async providers),
    then falls back to /bot/{id}/transcript/ (streaming providers like recallai_streaming).

    `attempts` is the patience budget. The full 12 (~10 min of backoff) is for audio-only
    meetings where Recall's transcript trickles in after the call ends. When we already
    hold a usable live transcript (the bot spoke / chat was captured), the caller passes a
    small number — Recall is then only needed for the recording segments, not the analysis,
    so there's no reason to block for minutes.

    `prefer_async` (Lever B): when we've requested a higher-accuracy async transcript,
    don't settle for the streaming `/transcript/` fallback while the async one is still
    landing — keep polling the media_shortcuts download until the last attempt, then allow
    the streaming fallback as a safety net so we never return empty."""
    for attempt in range(attempts):
        print(f"[recall] fetch transcript attempt {attempt + 1}/{attempts} for bot {bot_id}")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if resp.status_code != 200:
            print(f"[recall] bot fetch failed, status={resp.status_code}")
            await asyncio.sleep(3 * (attempt + 1))
            continue

        bot_data = resp.json()
        recordings = bot_data.get("recordings") or []
        print(f"[recall] bot has {len(recordings)} recording(s)")
        for i, rec in enumerate(recordings):
            shortcuts = rec.get("media_shortcuts") or {}
            print(f"[recall] recording[{i}] media_shortcuts keys={list(shortcuts.keys())} status={rec.get('status')}")

        # Path 1: download URL in media_shortcuts (try multiple known key names)
        download_url = None
        for rec in recordings:
            shortcuts = rec.get("media_shortcuts") or {}
            transcript_shortcut = shortcuts.get("transcript") or shortcuts.get("transcript.data")
            if isinstance(transcript_shortcut, dict):
                download_url = transcript_shortcut.get("download_url") or transcript_shortcut.get("data", {}).get("download_url")
            elif isinstance(transcript_shortcut, str):
                download_url = transcript_shortcut
            if not download_url:
                download_url = shortcuts.get("transcript.data.download_url")
            if download_url:
                print(f"[recall] found transcript download URL")
                break

        if download_url:
            print(f"[recall] downloading transcript from {download_url[:80]}...")
            async with httpx.AsyncClient() as client:
                transcript_resp = await client.get(download_url, timeout=30)
            if transcript_resp.status_code == 200:
                return transcript_resp
            print(f"[recall] transcript download failed, status={transcript_resp.status_code}")
            await asyncio.sleep(3 * (attempt + 1))
            continue

        # Path 2: streaming providers (recallai_streaming, gladia_v2_streaming, etc.)
        # Transcript is stored directly on the bot via /bot/{id}/transcript/
        # When we're holding out for a more-accurate async transcript, don't accept the
        # streaming transcript yet — wait for the async download to appear (Lever B).
        # On the final attempt we fall through so a meeting is never left transcript-less.
        if prefer_async and attempt < attempts - 1:
            wait = min(10 * (attempt + 1), 60)
            print(f"[recall] async transcript not ready yet, waiting {wait}s (prefer_async)...")
            await asyncio.sleep(wait)
            continue
        print(f"[recall] no download URL, trying /bot/{bot_id}/transcript/ (streaming provider)")
        async with httpx.AsyncClient() as client:
            t_resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/transcript/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if t_resp.status_code == 200:
            data = t_resp.json()
            # Endpoint returns list of segments or empty list
            if data:
                print(f"[recall] got transcript from /transcript/ endpoint, {len(data)} segments")
                return t_resp
            print(f"[recall] /transcript/ endpoint returned empty list")
        else:
            print(f"[recall] /transcript/ endpoint returned {t_resp.status_code}")

        wait = min(10 * (attempt + 1), 60)
        print(f"[recall] no transcript yet, waiting {wait}s...")
        await asyncio.sleep(wait)

    return None


# Lever B: re-transcribe the recording with Deepgram's async nova-3 model for the
# durable transcript (more accurate than the live streaming pass). Killable via env.
_ASYNC_TRANSCRIPT_ENABLED = os.getenv("PRISM_ASYNC_TRANSCRIPT", "1") != "0"


async def _request_async_transcript(bot_id: str) -> bool:
    """Ask Recall to (re)transcribe this bot's recording with Deepgram async nova-3 +
    our keyterms. Batch transcription is materially more accurate than the live
    streaming transcript, and the durable transcript is what gets analysed / displayed
    / indexed for RAG — so for bot-silent meetings we prefer it. Best-effort: returns
    True if a job was created (or already exists) so the caller waits for it, False on
    any failure so the caller keeps the streaming path. Costs one extra transcription,
    so callers only fire it when the bot didn't speak."""
    if not RECALL_API_KEY:
        return False
    entry = bot_store.get(bot_id) or {}
    keyterms = _gather_keyterms(entry.get("user_id"), entry.get("workspace_id"))
    provider: dict = {"model": "nova-3", "smart_format": "true", "punctuate": "true", "diarize": "true"}
    if keyterms:
        provider["keyterm"] = keyterms[:50]
    body = {"provider": {"deepgram_async": provider}}

    for attempt in range(4):
        try:
            async with httpx.AsyncClient() as client:
                bot_resp = await client.get(
                    f"{RECALL_API_BASE}/bot/{bot_id}/",
                    headers={"Authorization": f"Token {RECALL_API_KEY}"},
                    timeout=30,
                )
            recordings = bot_resp.json().get("recordings") or [] if bot_resp.status_code == 200 else []
            rec_id = recordings[0].get("id") if recordings else None
            if not rec_id:
                # Recording may still be finalising right after call end — wait + retry.
                await asyncio.sleep(5 * (attempt + 1))
                continue
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{RECALL_API_BASE}/recording/{rec_id}/create_transcript/",
                    headers={"Authorization": f"Token {RECALL_API_KEY}", "Content-Type": "application/json"},
                    json=body,
                    timeout=20,
                )
            if resp.status_code in (200, 201):
                print(f"[recall] async transcript requested (deepgram_async nova-3, {len(keyterms)} keyterms) for bot {bot_id}")
                return True
            # A transcript may already exist for this recording — fine, fetch will get it.
            txt = (resp.text or "")[:200]
            if resp.status_code in (400, 409) and ("already" in txt.lower() or "exist" in txt.lower()):
                print(f"[recall] async transcript already exists for bot {bot_id}")
                return True
            print(f"[recall] async transcript create failed status={resp.status_code} {txt}")
            await asyncio.sleep(5 * (attempt + 1))
        except Exception as exc:
            print(f"[recall] async transcript request error: {exc}")
            await asyncio.sleep(5 * (attempt + 1))
    return False


def _transcript_from_recall_data(raw) -> str:
    """Parse transcript from Recall's transcript data format."""
    # Handle list of segments with words (legacy + new format)
    if isinstance(raw, list):
        transcript_lines = []
        for segment in raw:
            speaker = segment.get("speaker") or segment.get("participant", {}).get("name") or "Speaker"
            # New format: words as list of dicts with "text"
            words = segment.get("words") or []
            if words:
                text = " ".join(w.get("text", "") for w in words)
            else:
                # Fallback: segment might have direct "text" field
                text = segment.get("text", "")
            if text.strip():
                transcript_lines.append(f"{speaker}: {text.strip()}")
        return "\n".join(transcript_lines)

    # Handle dict format (e.g., { "transcript": "..." })
    if isinstance(raw, dict):
        if "transcript" in raw:
            return raw["transcript"]
        # Try to find any text content
        for key in ("text", "content", "data"):
            if key in raw and isinstance(raw[key], str):
                return raw[key]

    # Handle plain string
    if isinstance(raw, str):
        return raw

    return ""


def _segments_from_recall_data(raw) -> list[dict] | None:
    """Normalize Recall's transcript response into Segment[] for video playback sync.

    Returns None when input is empty, missing word-level timestamps, or not a list
    (e.g., legacy { "transcript": "blob" } responses, plain string fallbacks).
    None is the sentinel for "no per-line timing available" — the realtime-buffer
    fallback transcript path also returns None so the player degrades to a plain
    transcript view.
    """
    if not isinstance(raw, list) or not raw:
        return None
    segments: list[dict] = []
    for segment in raw:
        words = segment.get("words") or []
        if not words:
            continue
        speaker = (
            segment.get("speaker")
            or (segment.get("participant") or {}).get("name")
            or "Speaker"
        )
        text = " ".join(w.get("text", "") for w in words).strip()
        if not text:
            continue
        segments.append({
            "speaker": speaker,
            "start": words[0].get("start_time", 0.0),
            "end": words[-1].get("end_time", 0.0),
            "text": text,
        })
    return segments or None


# deepgram_async diarization labels speakers as bare cluster IDs (e.g. "500-1",
# "100-0", "speaker 2") with NO participant-name mapping — Recall's live streaming
# transcript is what carries the real names. A transcript whose prefixes are these
# IDs makes the two per-speaker agents (sentiment, speaker_coach) analyse nameless
# speakers. Detect that so we can recover names before analysis.
_ANON_SPEAKER_RE = re.compile(r"^(?:speaker[\s_-]*)?\d+(?:[\s_-]+\d+)?$", re.I)


def _line_speaker_label(line: str) -> str | None:
    """The speaker prefix of a 'Speaker: text' line, or None if the line isn't one."""
    if ":" not in line:
        return None
    head = line.split(":", 1)[0].strip()
    if not head or len(head) > 48 or any(c in head for c in ".?!"):
        return None
    return head


def _speakers_anonymous(transcript: str, threshold: float = 0.6) -> bool:
    """True when most of the transcript's speaker prefixes are numeric diarization IDs
    (no real names) — the signature of a deepgram_async transcript that lost participant
    attribution."""
    total = anon = 0
    for line in transcript.split("\n"):
        label = _line_speaker_label(line)
        if label is None:
            continue
        total += 1
        if _ANON_SPEAKER_RE.match(label):
            anon += 1
    return total > 0 and (anon / total) >= threshold


def _relabel_segments_by_overlap(anon_segments: list[dict], named_segments: list[dict]) -> list[dict]:
    """Map each anonymously-labelled segment to the named live segment it overlaps most in
    time (recording-relative seconds), recovering real participant names on the more-
    accurate async transcript. Both segment lists share the {speaker,start,end,text} shape
    and recording-relative timing. Segments overlapping nothing keep their original label."""
    out: list[dict] = []
    for seg in anon_segments:
        s0 = float(seg.get("start") or 0.0)
        s1 = float(seg.get("end") or s0)
        best_name, best_ov = None, 0.0
        for ns in named_segments:
            n0 = float(ns.get("start") or 0.0)
            n1 = float(ns.get("end") or n0)
            ov = min(s1, n1) - max(s0, n0)
            if ov > best_ov:
                best_ov, best_name = ov, ns.get("speaker")
        new = dict(seg)
        if best_name and not _ANON_SPEAKER_RE.match(str(best_name)):
            new["speaker"] = best_name
        out.append(new)
    return out


def _resolve_owner_workspace(bot_id: str) -> tuple[str | None, str | None]:
    """Best-effort (owner_user_id, workspace_id) for a bot, durable across a restart.
    Precedence: a stand-in rep → the live bot_store entry → the meeting_bots row.
    workspace_id is only durable for stand-ins (rep) or once meeting_bots carries it;
    a regular bot recovered after a restart that wiped bot_store falls back to personal."""
    owner_user_id: str | None = None
    workspace_id: str | None = None
    if supabase:
        try:
            rep = (
                supabase.table("proxy_representations")
                .select("author_user_id, workspace_id")
                .eq("scheduled_bot_id", bot_id).neq("status", "canceled")
                .limit(1).execute()
            )
            if rep.data:
                owner_user_id = rep.data[0].get("author_user_id")
                workspace_id = rep.data[0].get("workspace_id")
        except Exception:
            pass
    mem = bot_store.get(bot_id) or {}
    owner_user_id = owner_user_id or mem.get("user_id")
    workspace_id = workspace_id or mem.get("workspace_id")
    if (not owner_user_id or not workspace_id) and supabase:
        try:
            mb = (
                supabase.table("meeting_bots").select("owner_user_id, workspace_id")
                .eq("bot_id", bot_id).maybe_single().execute()
            )
            row = (mb.data if mb else None) or {}
            owner_user_id = owner_user_id or row.get("owner_user_id")
            workspace_id = workspace_id or row.get("workspace_id")
        except Exception:
            pass
    return owner_user_id, workspace_id


async def _persist_bot_meeting(bot_id: str) -> None:
    """Promote ANY bot's analysis into the `meetings` table, server-side.

    Normally the owner's browser does this (POST /meetings on status=done). But a
    headless stand-in has no browser, and a regular bot whose dashboard tab crashed or
    was closed before analysis finished would otherwise live only in bot_sessions —
    invisible to the user. This saves it ourselves via save_meeting (so workspace
    fan-out + transcript indexing happen too). Idempotent: in-memory guard + an
    existing-row check on meetings.recall_bot_id, so it never double-writes alongside a
    browser save (the browser POST sets recall_bot_id, which this checks first)."""
    if not supabase or bot_id in _standin_persisted:
        return
    try:
        existing = (
            supabase.table("meetings").select("id")
            .eq("recall_bot_id", bot_id).limit(1).execute()
        )
        if existing.data:
            _standin_persisted.add(bot_id)
            return  # already on a dashboard (browser saved it first)
        # If the user explicitly deleted this meeting, don't resurrect it. Startup
        # recovery / a stray poller would otherwise re-persist a bot the user removed.
        try:
            mb = (
                supabase.table("meeting_bots").select("status")
                .eq("bot_id", bot_id).maybe_single().execute()
            )
            if mb and (mb.data or {}).get("status") == "deleted":
                _standin_persisted.add(bot_id)
                return
        except Exception:
            pass
        owner_user_id, workspace_id = _resolve_owner_workspace(bot_id)
        if not owner_user_id:
            return
        bs = (
            supabase.table("bot_sessions").select("result, transcript")
            .eq("bot_id", bot_id).maybe_single().execute()
        )
        data = bs.data if bs else None
        if not data or not data.get("result"):
            return
        result = data["result"]
        transcript = data.get("transcript") or ""
        summary = (result.get("summary") or "") if isinstance(result, dict) else ""
        health = (result.get("health_score") or {}) if isinstance(result, dict) else {}
        from storage_routes import save_meeting, MeetingEntry
        entry = MeetingEntry(
            id=(int(time.time() * 1000) * 1000) + secrets.randbelow(1000),
            date=datetime.now(timezone.utc).isoformat(),
            title=(result.get("title") if isinstance(result, dict) else None) or summary[:65] or "Meeting",
            score=health.get("score"),
            transcript=transcript,
            result=result,
            share_token=secrets.token_hex(8),
            workspace_id=workspace_id,
            recall_bot_id=bot_id,
        )
        _standin_persisted.add(bot_id)
        await save_meeting(entry, owner_user_id)
        print(f"[recall] auto-promoted bot {bot_id} into meetings for {owner_user_id} (workspace={workspace_id})")
        # Close the stand-in loop: brief each absent author this bot represented
        # (best-effort, non-blocking) — what happened for them + answers to what
        # they asked + tasks now theirs. No-op if this bot delivered no stand-ins.
        try:
            from proxy_routes import generate_standin_followups
            asyncio.create_task(generate_standin_followups(bot_id, entry.id, result, transcript))
        except Exception as exc:
            print(f"[recall] standin followup dispatch failed for {bot_id}: {exc}")
    except Exception as exc:
        print(f"[recall] auto-promote failed for {bot_id}: {exc}")


# Back-compat alias: stand-in bots are headless and persist immediately.
_persist_standin_meeting = _persist_bot_meeting


async def _persist_bot_meeting_delayed(bot_id: str, delay_s: float = 120.0) -> None:
    """Fallback persist for a regular (browser-driven) bot: wait for the owner's tab to
    save normally, then promote server-side only if it didn't (crashed/closed tab). The
    existing-row check in _persist_bot_meeting makes this a no-op when the browser won."""
    try:
        await asyncio.sleep(delay_s)
    except asyncio.CancelledError:
        return
    await _persist_bot_meeting(bot_id)


async def _process_bot_transcript(bot_id: str):
    # Idempotency: never run two analyses for the same bot concurrently. The
    # /bot-status poll re-triggers this while status=="processing" (to recover
    # from a server restart that killed the task) — but it can't tell a still-
    # running task from a dead one, so without this guard every poll spawned
    # another full analysis. One in-flight analysis per bot.
    if bot_id in _processing_bots:
        print(f"[recall] analysis already in flight for bot {bot_id}, skipping duplicate")
        return
    _processing_bots.add(bot_id)
    # Guarantee bot_store[bot_id] exists for the full duration of processing.
    # remove_bot() can pop the entry at any time; setdefault re-establishes it so
    # the status writes below never raise KeyError inside the except block.
    bot_store.setdefault(bot_id, {"status": "processing", "result": None, "error": None, "commands": []})
    try:
        print(f"[recall] starting transcript processing for bot {bot_id}")
        # If we already hold a usable live transcript, we'll analyse from it regardless of
        # Recall (the bot's chat replies + typed chat aren't in Recall's audio transcript),
        # so only give Recall a brief window to provide recording segments — don't block
        # the ~10-min audio-retry budget. Saves up to ~10 min before a meeting lands on the
        # dashboard whenever the bot was active.
        _live_lines = [ln for ln in (bot_store.get(bot_id, {}).get("realtime_transcript_lines") or []) if ln.strip()]
        _bot_spoke_live = any(ln.startswith(_BOT_NAME_PREFIXES) for ln in _live_lines)

        # Lever B: when the bot was SILENT, the durable transcript is Recall's audio
        # transcript — so re-transcribe it with Deepgram's more-accurate async nova-3
        # (+ keyterms) and hold out for that instead of the live streaming pass. We skip
        # this when the bot spoke: there we must use the bot-inclusive live transcript
        # (Recall's audio wouldn't contain the bot's chat replies), so a second
        # transcription would be wasted spend.
        prefer_async = False
        if _ASYNC_TRANSCRIPT_ENABLED and not _bot_spoke_live:
            prefer_async = await _request_async_transcript(bot_id)

        if prefer_async:
            attempts = 6          # ~3.5 min for the async transcript to land, then fall back
        else:
            attempts = 2 if len(_live_lines) >= 2 else 12
        resp = await _fetch_transcript(bot_id, attempts=attempts, prefer_async=prefer_async)

        transcript = ""
        segments: list[dict] | None = None
        if resp is not None:
            raw = resp.json()
            print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:500]}")
            transcript = _transcript_from_recall_data(raw)
            segments = _segments_from_recall_data(raw)

        # The realtime buffer interleaves the humans' utterances with the bot's
        # own turns (recorded via _record_bot_line) in chronological order. When
        # the bot actually spoke, prefer it as the transcript: Recall's audio
        # transcript wouldn't contain the bot's chat replies, so it'd read as a
        # monologue ("talking to myself" in a 1-on-1). Segments still come from
        # Recall for the recording player. Otherwise it's a plain fallback when
        # Recall returned nothing.
        rt_lines = bot_store.get(bot_id, {}).get("realtime_transcript_lines") or []
        bot_spoke = any(ln.startswith(_BOT_NAME_PREFIXES) for ln in rt_lines)
        if bot_spoke and rt_lines:
            # Collapse the bot's two names (persona for replies, default for the stand-in
            # delivery) into one so it isn't analysed as two separate speakers.
            rt_lines = _normalize_bot_speaker(rt_lines, await _resolve_bot_persona_name(bot_id))
            transcript = "\n".join(rt_lines)
            print(f"[recall] bot participated — using bot-inclusive live transcript: {len(rt_lines)} lines, {len(transcript)} chars")
        elif not transcript.strip() and rt_lines:
            transcript = "\n".join(rt_lines)
            print(f"[recall] using realtime transcript buffer: {len(rt_lines)} lines, {len(transcript)} chars")

        # Seekable segments: Recall's word-timestamped transcript is preferred, but when
        # it's absent (bot spoke → live transcript used, or Recall returned no words) fall
        # back to the segments we built live from Deepgram's recording-relative word times.
        # Keeps click-to-seek working for those meetings instead of degrading to plain text.
        if not segments:
            rt_segments = bot_store.get(bot_id, {}).get("realtime_segments") or []
            if rt_segments:
                segments = rt_segments
                print(f"[recall] using {len(rt_segments)} realtime-buffer segments for playback sync")

        # Speaker-name recovery: a deepgram_async (Lever B) transcript diarizes speakers as
        # bare numeric IDs (e.g. "500-1") with no participant mapping — which reads fine in
        # summary/action-items (owners come from spoken content) but breaks sentiment +
        # speaker_coach (the per-speaker agents key off the prefix). Recall's live streaming
        # transcript DOES carry real names. When the chosen transcript is anonymous:
        #   1. If we have named live segments, relabel by time-overlap → keep async wording
        #      + seekable timing + real names.
        #   2. Else fall back to the named live transcript entirely (names >> marginal async
        #      spelling gain). This also restores click-to-seek for those meetings.
        if transcript.strip() and _speakers_anonymous(transcript):
            named_segs = bot_store.get(bot_id, {}).get("realtime_segments") or []
            if segments and named_segs and _speakers_anonymous(
                "\n".join(f"{s.get('speaker')}: {s.get('text','')}" for s in segments)
            ):
                segments = _relabel_segments_by_overlap(segments, named_segs)
                transcript = "\n".join(f"{s.get('speaker')}: {s.get('text','')}" for s in segments)
                print(f"[recall] recovered speaker names via time-overlap relabel ({len(segments)} segments)")
            elif rt_lines and not _speakers_anonymous("\n".join(rt_lines)):
                transcript = "\n".join(rt_lines)
                if named_segs:
                    segments = named_segs
                print(f"[recall] anonymous async speakers — fell back to named live transcript ({len(rt_lines)} lines)")
            else:
                print("[recall] transcript has anonymous speakers but no named source to recover from")

        if not transcript.strip():
            error_msg = "No transcript content found — the meeting may have been too short or had no speech"
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = error_msg
            _db_save(bot_id, {"status": "error", "error": error_msg})
            print(f"[recall] ERROR: empty transcript")
            return

        # No-show guard: the bot joined but nobody actually spoke (a scheduled meeting
        # neither party attended, or someone joined and instantly typed /leave). The
        # transcript is technically non-empty (a leave command, the bot's own intro) but
        # has no real human dialogue — analysing + SAVING it just litters the dashboard
        # with a junk "Meeting Transcript Unavailable" row. Mark it done-with-no-content
        # and return BEFORE analysis/persist so no meeting is created.
        human_words = _human_word_count(transcript)
        if human_words < _MIN_HUMAN_WORDS:
            error_msg = (
                "Meeting didn't take place — no participants spoke "
                f"({human_words} human words). Skipped analysis and did not save a meeting."
            )
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = error_msg
            _db_save(bot_id, {"status": "error", "error": error_msg})
            _mb_update_status(bot_id, "no_show")
            print(f"[recall] no-show: {human_words} human words < {_MIN_HUMAN_WORDS}, skipping persist for bot {bot_id}")
            from realtime_routes import cleanup_bot_state
            cleanup_bot_state(bot_id)
            return

        print(f"[recall] transcript OK, {len(transcript)} chars. Running analysis...")
        # Durable owner lookup (survives a restart that wiped bot_store) so the follow-up
        # email is written FROM the represented owner, not a guessed participant.
        owner_name = _resolve_owner_name(bot_id)
        analysis_transcript = build_analysis_transcript(transcript, owner_name=owner_name)
        result = await run_full_analysis(analysis_transcript, owner_name=owner_name)
        # Traceability: if the bot didn't leave for a normal reason (removed / denied
        # recording / asked to leave / errored), stamp WHY + WHEN onto the meeting so
        # it's visible in the analysis, not just server logs. Recall's Google-Meet
        # removal webhook doesn't expose WHO removed the bot, so we surface the reason
        # + time; `message` carries any extra detail Recall did give.
        _bs = bot_store.get(bot_id) or {}
        if _bs.get("leave_notable") and isinstance(result, dict):
            result["exit_note"] = {
                "reason": _bs.get("leave_reason"),
                "sub_code": _bs.get("leave_sub_code") or "",
                "at": _bs.get("left_at"),
            }
            print(f"[recall] stamped exit_note onto meeting {bot_id[:8]}: {result['exit_note']}")
        bot_store[bot_id]["transcript"] = transcript
        bot_store[bot_id]["result"] = result
        bot_store[bot_id]["status"] = "done"
        bot_store[bot_id]["transcript_segments"] = segments
        _db_save(bot_id, {
            "status": "done",
            "transcript": transcript,
            "result": result,
            "transcript_segments": segments,
        })
        _mb_update_status(bot_id, "done")
        print(f"[recall] analysis complete for bot {bot_id}")
        # Persist to the meetings table server-side so a meeting is never lost to a
        # crashed/closed dashboard tab. A headless stand-in has no browser → save now;
        # a regular bot's browser normally saves it → only fall back after a delay if it
        # didn't. Both dedup on recall_bot_id, so no double-write when the browser wins.
        if (bot_store.get(bot_id) or {}).get("standin"):
            await _persist_bot_meeting(bot_id)
        else:
            asyncio.create_task(_persist_bot_meeting_delayed(bot_id))
        from realtime_routes import cleanup_bot_state
        cleanup_bot_state(bot_id)
    except Exception as exc:
        # re-establish entry in case remove_bot() popped it during an await
        bot_store.setdefault(bot_id, {"status": "error", "result": None, "error": None, "commands": []})
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = str(exc)
        _db_save(bot_id, {"status": "error", "error": str(exc)})
        _mb_update_status(bot_id, "error")
        print(f"[recall] ERROR processing bot {bot_id}: {exc}")
        from realtime_routes import cleanup_bot_state
        cleanup_bot_state(bot_id)
    finally:
        _processing_bots.discard(bot_id)


async def _optional_user_id(request: Request) -> str | None:
    """Try to extract user_id from auth header, return None if not authenticated."""
    try:
        return await require_user_id(request)
    except HTTPException:
        return None


@router.post("/join-meeting")
async def join_meeting(req: JoinMeetingRequest, request: Request):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    if not req.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL cannot be empty")

    # Optionally link bot to authenticated user (enables live tool access)
    user_id = await _optional_user_id(request)

    if user_id and supabase:
        normalized_url = _normalize_meeting_url(req.meeting_url)

        # Self-dedup: if THIS user already has a live bot in this meeting (a second
        # Join/Rejoin click), attach to it instead of spawning a duplicate bot — two
        # bots in one room split the transcript so analysis polls a bot that never
        # captured anything. Verified against Recall so stale rows don't block joins.
        own = await _find_own_active_bot(supabase, normalized_url, user_id)
        if own:
            print(f"[recall] self-dedup: reusing live bot {own['bot_id']} for {user_id}")
            return {
                "skip": True,
                "self": True,
                "existing_bot_id": own["bot_id"],
                "owner_user_id": user_id,
                "owner_user_email": "",
                "live_token": _live_token_for_bot(own["bot_id"]),
            }

        # Workspace dedup: if a teammate's bot is already in this meeting, skip joining
        existing = await _find_shared_workspace_bot(supabase, normalized_url, user_id)
        if existing:
            print(f"[recall] dedup: skipping join for {user_id}, existing bot {existing['bot_id']} from {existing['owner_user_id']}")
            return {
                "skip": True,
                "existing_bot_id": existing["bot_id"],
                "owner_user_id": existing["owner_user_id"],
                "owner_user_email": existing.get("owner_user_email", ""),
                "live_token": _live_token_for_bot(existing["bot_id"]),
            }

        # Scheduled stand-in dedup: a bot may already be SCHEDULED for this meeting
        # (you set a stand-in because you couldn't attend) but not yet joined, so the
        # live-dedup checks above miss it. Attach to it instead of spawning a second
        # bot — this is what prevents auto-join from double-booking a stand-in meeting.
        scheduled = _find_existing_bot_for_standin(
            supabase, normalized_url, user_id, statuses=("scheduled",)
        )
        if scheduled:
            print(f"[recall] scheduled-dedup: attaching join to scheduled bot {scheduled['bot_id']}")
            return {
                "skip": True,
                "existing_bot_id": scheduled["bot_id"],
                "owner_user_id": scheduled["owner_user_id"],
                "owner_user_email": "",
                "live_token": _live_token_for_bot(scheduled["bot_id"]),
            }

    webhook_url = f"{WEBHOOK_BASE_URL}/recall-webhook"

    # Generate a one-time webhook auth token for the realtime stream.
    # 32 URL-safe bytes = 256 bits of entropy — unguessable. The token
    # binds this specific bot's events to a verified URL path; without it,
    # an attacker who knows or guesses the bot_id can POST forged events
    # to the public webhook endpoint.
    realtime_token = secrets.token_urlsafe(32)
    realtime_url = f"{WEBHOOK_BASE_URL}/realtime-events/{realtime_token}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RECALL_API_BASE}/bot/",
            headers={
                "Authorization": f"Token {RECALL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=_recall_bot_create_json(
                req.meeting_url, realtime_url, webhook_url,
                keyterms=_gather_keyterms(user_id, req.workspace_id),
            ),
            timeout=15,
        )

    if resp.status_code not in (200, 201):
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai error: {detail}")

    data = resp.json()
    bot_id = data["id"]
    live_token = secrets.token_hex(16)
    bot_store[bot_id] = {
        "status": "joining",
        "result": None,
        "error": None,
        "commands": [],
        "user_id": user_id,
        "live_token": live_token,
        "owner_name": req.owner_name,
        "workspace_id": req.workspace_id,
        "realtime_token": realtime_token,
        "initial_mode": req.mode if req.mode in ("utterance", "autonomous") else None,
    }
    _live_token_index[live_token] = bot_id
    _db_save(bot_id, {"status": "joining", "user_id": user_id, "live_token": live_token,
                      "owner_name": req.owner_name, "workspace_id": req.workspace_id})

    from realtime_routes import init_bot_realtime, _run_proactive_checker, register_realtime_token
    # Bind the webhook token AFTER Recall confirmed the bot id. The mapping
    # in realtime_routes lets the tokenized webhook handler resolve token →
    # bot_id and reject any forged or stale tokens.
    register_realtime_token(realtime_token, bot_id)

    # Register in meeting_bots for workspace dedup
    if user_id and supabase:
        try:
            supabase.table("meeting_bots").insert({
                "bot_id": bot_id,
                "meeting_url": _normalize_meeting_url(req.meeting_url),
                "owner_user_id": user_id,
                "status": "joining",
            }).execute()
        except Exception as exc:
            print(f"[recall] meeting_bots insert failed: {exc}")
        # Stamp workspace durably so a server-side persist (after a restart that wiped
        # bot_store) can still save the meeting to the right workspace. Best-effort —
        # the column is absent on schemas before meeting_bots_workspace_migration.
        if req.workspace_id:
            try:
                supabase.table("meeting_bots").update(
                    {"workspace_id": req.workspace_id}
                ).eq("bot_id", bot_id).execute()
            except Exception:
                pass

    init_bot_realtime(bot_id)

    asyncio.create_task(_send_bot_intro(bot_id))
    asyncio.create_task(_run_proactive_checker(bot_id))
    return {"bot_id": bot_id, "status": "joining", "live_token": live_token}


@router.delete("/remove-bot/{bot_id}")
async def remove_bot(bot_id: str):
    """Stop and remove a Recall.ai bot from the call."""
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    try:
        async with httpx.AsyncClient() as client:
            # Use leave_call for active bots (DELETE only works for scheduled/unjoined bots)
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/leave_call/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
            print(f"[recall] leave_call for bot {bot_id}: status={resp.status_code}")
            # If leave_call fails (bot not in call), try DELETE as fallback
            if resp.status_code not in (200, 201, 204):
                await client.delete(
                    f"{RECALL_API_BASE}/bot/{bot_id}/",
                    headers={"Authorization": f"Token {RECALL_API_KEY}"},
                    timeout=10,
                )
    except httpx.HTTPError:
        pass  # Best-effort — don't block the client reset
    bot_store.pop(bot_id, None)
    from realtime_routes import cleanup_bot_state
    cleanup_bot_state(bot_id)
    return {"ok": True}


async def leave_call(bot_id: str) -> bool:
    """Ask the Recall bot to leave the call gracefully (used by the `/leave` chat
    command). Unlike `remove_bot`, this does NOT tear down bot_store / realtime
    state — the recording still finalizes, so Recall fires call_ended → the normal
    analysis + save flow runs and the meeting is notes-complete. Best-effort."""
    if not RECALL_API_KEY:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/leave_call/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
            print(f"[recall] /leave -> leave_call bot={bot_id[:8]}: {resp.status_code}")
            return resp.status_code in (200, 201, 204)
    except httpx.HTTPError as exc:
        print(f"[recall] /leave leave_call failed bot={bot_id[:8]}: {exc}")
        return False


@router.get("/bot-status/{bot_id}")
async def bot_status(bot_id: str):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")

    # Try loading from DB if not in memory (handles server restart)
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RECALL_API_BASE}/bot/{bot_id}/",
            headers={"Authorization": f"Token {RECALL_API_KEY}"},
            timeout=10,
        )

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Bot not found")
    if resp.status_code != 200:
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai status check failed: {detail}")

    recall_data = resp.json()
    recall_status = recall_data.get("status_changes", [{}])[-1].get("code", "") if recall_data.get("status_changes") else ""
    our_status = STATUS_MAP.get(recall_status, bot_store.get(bot_id, {}).get("status", "joining"))

    if recall_status == "in_call_recording" and bot_id not in _standin_delivered:
        # Fallback for the webhook in_call_recording trigger (idempotent via guard +
        # DB claim) so stand-ins still deliver if the webhook is missed.
        _standin_delivered.add(bot_id)
        if bot_store.get(bot_id, {}).get("standin") and bot_id not in _standin_intro_sent:
            _standin_intro_sent.add(bot_id)
            asyncio.create_task(_send_bot_intro(bot_id))
        asyncio.create_task(deliver_standins_for_bot(bot_id))

    if recall_status in ("call_ended", "done"):
        # The call has ended → make sure analysis runs, exactly once. Skip if it's
        # already finished (done/error) or currently in flight. _process_bot_transcript
        # is itself idempotent (its _processing_bots guard); the in-flight check here
        # just avoids spawning throwaway tasks on every poll. On a server restart the
        # in-memory guard is empty while the DB still says "processing", so a genuinely
        # dead task is correctly re-triggered.
        entry = bot_store.setdefault(
            bot_id, {"status": "joining", "result": None, "error": None, "commands": []}
        )
        # Capture the leave reason once (webhook may have been missed). The last
        # status_change carries Recall's code/sub_code/message.
        if not entry.get("leave_reason"):
            last = (recall_data.get("status_changes") or [{}])[-1]
            _record_leave_reason(bot_id, last.get("code") or recall_status,
                                 last.get("sub_code") or "", last.get("message") or "")
        if entry.get("status") not in ("done", "error") and bot_id not in _processing_bots:
            entry["status"] = "processing"
            _db_save(bot_id, {"status": "processing"})
            asyncio.create_task(_process_bot_transcript(bot_id))

    entry = bot_store.get(bot_id, {"status": our_status, "result": None, "error": None, "commands": []})
    # Don't let Recall's "done" override our internal "processing"
    entry["status"] = our_status if entry.get("status") not in ("done", "error", "processing") else entry["status"]
    return entry


@router.get("/live/{live_token}")
async def live_meeting(live_token: str):
    """Public endpoint for live-share viewers. Returns safe bot state by live_token."""
    bot_id = _live_token_index.get(live_token)

    # Fall back to DB if server restarted and index was lost
    if not bot_id and supabase:
        try:
            res = supabase.table("bot_sessions").select("bot_id").eq("live_token", live_token).maybe_single().execute()
            if res.data:
                bot_id = res.data["bot_id"]
                _live_token_index[live_token] = bot_id
        except Exception:
            pass

    if not bot_id:
        raise HTTPException(status_code=404, detail="Live session not found")

    # Load from DB into memory if needed
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    entry = bot_store.get(bot_id, {})
    from realtime_routes import _bot_state
    rt = _bot_state.get(bot_id, {})

    # Build pre-meeting brief lazily — compute once, cache in bot_store
    status = entry.get("status", "joining")
    if bot_id in bot_store and "brief" not in bot_store[bot_id] and status not in ("done", "error"):
        bot_store[bot_id]["brief"] = await asyncio.to_thread(
            _build_pre_meeting_brief, entry.get("user_id")
        )

    import meeting_memory as _mm
    memory_snapshot = _mm.get_memory_snapshot(rt) if rt else {}

    # Operational counters (Phase A pre-perception observability). Safe to
    # expose on this possession-based endpoint: dedup_hits / partial_drops /
    # cancel_count / replace_depth_hits / cousin_hit_no_match are operational
    # signal, not security signal. Security counters live on a separate
    # require_user_id-gated endpoint below.
    import perception_state as _pp
    op_counters = _pp.operational_counters(rt) if rt else {}

    return {
        "status": status,
        "commands": entry.get("commands", []),
        "transcript_lines": rt.get("transcript_buffer", [])[-100:],
        "result": entry.get("result"),
        "error": entry.get("error"),
        "brief": entry.get("brief"),
        # Memory and idea engine fields — consumed by the live-share frontend panel
        "memory_summary": memory_snapshot.get("memory_summary", ""),
        "live_decisions": memory_snapshot.get("live_decisions", []),
        "live_action_items": memory_snapshot.get("live_action_items", []),
        "top_entities": memory_snapshot.get("top_entities", []),
        "idea_history": memory_snapshot.get("idea_history", []),
        # Stand-in updates delivered into this meeting (Feature A) — for the brief panel.
        "standin_updates": entry.get("standin_updates", []),
        # Include transcript when done so signed-in viewers can save a copy
        "transcript": entry.get("transcript") if status == "done" else None,
        "counters": op_counters,
    }


class LiveAskRequest(BaseModel):
    question: str = ""
    mode: str = "qa"  # "catchup" | "qa"


@router.post("/live/{live_token}/ask")
async def live_ask(live_token: str, body: LiveAskRequest, request: Request):
    """Private live catch-up / Q&A over a meeting's live state. Token-gated like
    GET /live/{token} (no login required); streams the answer back to the caller
    only — never into the meeting. A valid Bearer token whose user is a member of
    the bot's workspace unlocks the knowledge-base fallback (else meeting-only)."""
    bot_id = _live_token_index.get(live_token)
    if not bot_id and supabase:
        try:
            res = supabase.table("bot_sessions").select("bot_id").eq("live_token", live_token).maybe_single().execute()
            if res.data:
                bot_id = res.data["bot_id"]
                _live_token_index[live_token] = bot_id
        except Exception:
            pass
    if not bot_id:
        raise HTTPException(status_code=404, detail="Live session not found")

    from realtime_routes import stream_catchup_answer, _catchup_rate_ok
    if not _catchup_rate_ok(live_token):
        raise HTTPException(status_code=429, detail="One moment — too many questions in a row.")

    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry

    # RAG fallback unlock — only for a logged-in member of the bot's workspace
    # (or the owner of a personal, no-workspace bot). Anonymous => meeting-only.
    member_user_id = None
    caller_id = await _optional_user_id(request)
    if caller_id:
        entry = bot_store.get(bot_id) or {}
        ws_id = entry.get("workspace_id")
        if ws_id and supabase:
            try:
                m = (
                    supabase.table("workspace_members")
                    .select("user_id")
                    .eq("workspace_id", ws_id)
                    .eq("user_id", caller_id)
                    .maybe_single()
                    .execute()
                )
                if m and m.data:
                    member_user_id = caller_id
            except Exception:
                pass
        elif not ws_id and entry.get("user_id") == caller_id:
            member_user_id = caller_id

    mode = body.mode if body.mode in ("catchup", "qa") else "qa"
    return StreamingResponse(
        stream_catchup_answer(bot_id, mode, body.question or "", member_user_id),
        media_type="text/event-stream",
    )


@router.get("/bot-counters/{bot_id}")
async def bot_counters(bot_id: str, user_id: str = Depends(require_user_id)):
    """Owner-only counters for a bot. Returns 404 on ownership mismatch so we
    don't confirm bot existence to a non-owner.

    Operational counters live on /live/{token}. This endpoint exposes the
    security-signal counters (injection_redactions, owner_gate_blocks) that
    would leak attack-attempt feedback to non-owners.
    """
    if bot_id not in bot_store:
        db_entry = _db_load(bot_id)
        if db_entry:
            bot_store[bot_id] = db_entry
    rec = bot_store.get(bot_id)
    if not rec or rec.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Bot not found")
    from realtime_routes import _bot_state
    import perception_state as _pp
    rt = _bot_state.get(bot_id, {})
    return {
        "bot_id": bot_id,
        "counters": _pp.security_counters(rt),
        "recent_drops": _pp.get_drops(bot_id),
        # Latency timeline for the most recent cancellation. Three monotonic
        # timestamps + a reason. Diff (last_upload_aborted_mono - detected_mono)
        # is the "interrupt-utterance-detected → last-audio-uploaded" number
        # that's the whole point of Phase B.
        "last_cancel_timeline": rt.get("last_cancel_timeline"),
    }


@router.post("/recall-webhook")
async def recall_webhook(request: Request):
    body = await request.body()
    if RECALL_WEBHOOK_SECRET:
        sig = request.headers.get("x-recall-signature", "")
        expected = hmac.new(RECALL_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {"ok": True}

    bot_id = (
        payload.get("data", {}).get("bot", {}).get("id")
        or payload.get("bot_id")
        or payload.get("id")
    )
    event = (
        payload.get("event")
        or payload.get("data", {}).get("status", {}).get("code")
        or ""
    )

    if not bot_id:
        return {"ok": True}

    if bot_id not in bot_store:
        bot_store[bot_id] = {"status": "unknown", "result": None, "error": None, "commands": []}

    if event in ("bot.joining_call", "joining_call"):
        bot_store[bot_id]["status"] = "joining"
        _db_save(bot_id, {"status": "joining"})
        _mb_update_status(bot_id, "joining")
    elif event in ("bot.in_call_recording", "in_call_recording"):
        bot_store[bot_id]["status"] = "recording"
        _db_save(bot_id, {"status": "recording"})
        _mb_update_status(bot_id, "recording")
        # A scheduled stand-in bot got no intro at creation — introduce it now that
        # it's actually in the room (announces it's attending on someone's behalf).
        if bot_store.get(bot_id, {}).get("standin") and bot_id not in _standin_intro_sent:
            _standin_intro_sent.add(bot_id)
            asyncio.create_task(_send_bot_intro(bot_id))
        # Any bot reaching the room delivers pending stand-ins bound to its meeting.
        if bot_id not in _standin_delivered:
            _standin_delivered.add(bot_id)
            asyncio.create_task(deliver_standins_for_bot(bot_id))
    elif event in ("bot.call_ended", "call_ended", "bot.done", "done"):
        # Capture WHY the bot left (removed / permission denied / meeting ended / …)
        # before kicking off analysis, so a disconnect is never an unexplained drop.
        code, sub_code, message = _extract_status_detail(payload)
        _record_leave_reason(bot_id, code or event, sub_code, message)
        if bot_store[bot_id].get("status") not in ("processing", "done"):
            bot_store[bot_id]["status"] = "processing"
            _db_save(bot_id, {"status": "processing"})
            _mb_update_status(bot_id, "processing")
            asyncio.create_task(_process_bot_transcript(bot_id))
    elif event in ("bot.fatal_error", "fatal_error"):
        code, sub_code, message = _extract_status_detail(payload)
        _record_leave_reason(bot_id, code or "fatal_error", sub_code, message)
        # Enrich the user-facing error only when Recall actually told us why;
        # otherwise keep the generic message.
        err = _leave_reason_text(code or "fatal_error", sub_code, message) if (sub_code or message) else "Bot encountered a fatal error"
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = err
        _db_save(bot_id, {"status": "error", "error": err})
        _mb_update_status(bot_id, "error")

    return {"ok": True}

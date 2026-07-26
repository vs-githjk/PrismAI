"""B2 — semantic cross-meeting synthesis.

ONE cached Haiku pass over recent meeting DIGESTS (summaries / decisions / open
action items / sentiment — never transcripts) → a narrative + semantic topics +
open threads ("raised across N meetings, never closed") + decision evolution.
Replaces the lexical theme / decision-loop counting with real understanding.

- Bounded input (~40 meetings, trimmed digests) keeps the prompt ~6-8k tokens.
- Anti-hallucination: every item must cite meeting_ids present in the input;
  items whose citations don't resolve are dropped (mirrors the RAG trust layer).
- Durable cache keyed by (scope_id, meeting_set_hash): recompute only when the
  meeting set changes. Lazy-on-load — computed on the request that misses; the
  cheap deterministic metrics (/insights) never wait on this.
- Flag PRISM_CROSS_MEETING_SEMANTIC (default ON); < MIN_MEETINGS → locked state.
"""
import hashlib
import json
import os
import re
from datetime import UTC, datetime

from agents.utils import llm_call, strip_fences
from cross_meeting_service import has_meaningful_result

try:
    from auth import supabase
except ImportError:
    supabase = None


SEMANTIC_ENABLED = os.getenv("PRISM_CROSS_MEETING_SEMANTIC", "1") not in ("0", "false", "False")
MIN_MEETINGS = 3
MAX_MEETINGS = 40
CACHE_TABLE = "cross_meeting_cache"
# Bump when the synthesis logic/prompt changes so stale cached payloads auto-invalidate
# (folded into meeting_set_hash → a new hash → cache miss → recompute).
CACHE_VERSION = "2"


def _empty() -> dict:
    return {"narrative": "", "topics": [], "open_threads": [], "decision_evolution": []}


def _clip(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return f"{cleaned[:limit].rstrip()}…" if len(cleaned) > limit else cleaned


def build_digest(entry: dict, ref: int) -> dict:
    """A compact, bounded per-meeting digest — no transcript. This is ALL the model
    sees, so trimming here is what keeps the synthesis prompt cheap.

    `ref` is a small 1-based index the model cites instead of the real meeting id:
    meeting ids here are 16-digit numbers an LLM cannot echo reliably, so citing the
    raw id dropped every citation on validation. We map ref → real id server-side."""
    result = entry.get("result") or {}

    decisions = []
    for decision in (result.get("decisions") or [])[:6]:
        text = _clip(decision.get("decision", ""), 140)
        if not text:
            continue
        owner = (decision.get("owner") or "").strip()
        decisions.append(f"{text} (owner: {owner})" if owner else text)

    open_items = []
    for item in (result.get("action_items") or []):
        if item.get("completed"):
            continue
        text = _clip(item.get("task", ""), 120)
        if not text:
            continue
        owner = (item.get("owner") or "").strip()
        open_items.append(f"{text} (owner: {owner})" if owner else text)
        if len(open_items) >= 6:
            break

    sentiment = result.get("sentiment") or {}
    return {
        "ref": ref,
        "date": (entry.get("date") or "")[:10],
        "title": _clip(entry.get("title") or result.get("title") or "Untitled", 80),
        "summary": _clip(result.get("summary", ""), 400),
        "decisions": decisions,
        "open_action_items": open_items,
        "sentiment": _clip(sentiment.get("overall", "") or "", 30),
    }


def meeting_set_hash(meetings: list[dict]) -> str:
    ids = sorted(str(m.get("id")) for m in meetings if m.get("id") is not None)
    return hashlib.sha256((CACHE_VERSION + "|" + "|".join(ids)).encode()).hexdigest()[:32]


_SYSTEM = """You are a cross-meeting intelligence analyst for a meeting-notes product.
You are given JSON digests of a user's recent meetings — each with a `ref` (a small
integer id for that meeting), date, title, summary, decisions, open_action_items, and
sentiment. Synthesize what is actually happening ACROSS these meetings. Do NOT summarize
any single meeting.

Return ONLY a single valid JSON object — no prose, no markdown — with EXACTLY this schema:
{
  "narrative": "2-3 sentences: the throughline across these meetings, in plain language",
  "topics": [
    {"topic": "short noun phrase", "status": "active|stalled|resolved",
     "gist": "one sentence", "refs": [<ref numbers>]}
  ],
  "open_threads": [
    {"thread": "something raised but never resolved", "why_open": "one sentence",
     "suggested_next_step": "one concrete action", "refs": [<ref numbers, oldest to newest>]}
  ],
  "decision_evolution": [
    {"topic": "the decision subject",
     "timeline": [{"ref": <ref number>, "what_changed": "one sentence"}]}
  ]
}

HARD RULES:
- Cite meetings by their `ref` number ONLY (e.g. [2, 5, 9]). Every ref you output MUST be
  one of the provided ref numbers. Never invent refs.
- Use ONLY facts present in the digests. Never invent meetings, decisions, owners, or events.
- open_threads = subjects discussed in 2+ meetings with NO resolving decision. This is the
  most valuable output — prioritize genuine unresolved threads over filler.
- topics = real recurring SUBJECTS across 2+ meetings, semantically grouped (not keywords).
- decision_evolution = only where a decision on one subject changed or progressed across
  meetings; each timeline needs 2+ steps.
- Always write a narrative. If a list section lacks enough signal, return an empty array.
  Quality over quantity: at most 6 topics, 6 open_threads, 4 decision_evolution items.
  Keep every string tight."""


def _parse_and_validate(raw: str, ref_to_id: dict) -> dict:
    """ref_to_id maps the small citation ref → the real meeting id. The model cites
    refs; we resolve them back to real ids (dropping any ref not in the map)."""
    def norm_ids(raw_refs) -> list:
        out, seen = [], set()
        for value in (raw_refs or []):
            try:
                ref = int(value)
            except (TypeError, ValueError):
                continue
            real = ref_to_id.get(ref)
            if real is not None and real not in seen:
                seen.add(real)
                out.append(real)
        return out

    text = strip_fences(raw or "")
    data = None
    try:
        data = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except Exception:
                data = None
    if not isinstance(data, dict):
        return _empty()

    topics = []
    for topic in (data.get("topics") or [])[:6]:
        if not isinstance(topic, dict):
            continue
        ids = norm_ids(topic.get("refs") or topic.get("meeting_ids"))
        name = (topic.get("topic") or "").strip()
        if not ids or not name:
            continue
        status = (topic.get("status") or "active").lower()
        if status not in ("active", "stalled", "resolved"):
            status = "active"
        topics.append({
            "topic": name[:80],
            "status": status,
            "gist": (topic.get("gist") or "").strip()[:200],
            "meeting_ids": ids,
        })

    open_threads = []
    for thread in (data.get("open_threads") or [])[:6]:
        if not isinstance(thread, dict):
            continue
        ids = norm_ids(thread.get("refs") or thread.get("meeting_ids"))
        label = (thread.get("thread") or "").strip()
        if not ids or not label:
            continue
        open_threads.append({
            "thread": label[:140],
            "why_open": (thread.get("why_open") or "").strip()[:200],
            "suggested_next_step": (thread.get("suggested_next_step") or "").strip()[:200],
            "meeting_ids": ids,
        })

    evolution = []
    for item in (data.get("decision_evolution") or [])[:4]:
        if not isinstance(item, dict):
            continue
        timeline = []
        for step in (item.get("timeline") or []):
            if not isinstance(step, dict):
                continue
            resolved = norm_ids([step.get("ref", step.get("meeting_id"))])
            if not resolved:
                continue
            timeline.append({"meeting_id": resolved[0], "what_changed": (step.get("what_changed") or "").strip()[:200]})
        subject = (item.get("topic") or "").strip()
        if subject and len(timeline) >= 2:
            evolution.append({"topic": subject[:80], "timeline": timeline})

    return {
        "narrative": (data.get("narrative") or "").strip()[:600],
        "topics": topics,
        "open_threads": open_threads,
        "decision_evolution": evolution,
    }


async def _run_synthesis(meetings: list[dict]) -> dict:
    digests = [build_digest(entry, i + 1) for i, entry in enumerate(meetings)]
    ref_to_id = {i + 1: entry.get("id") for i, entry in enumerate(meetings)}
    user = "Meeting digests (JSON):\n" + json.dumps(digests, ensure_ascii=False)
    raw = await llm_call(_SYSTEM, user, temperature=0.2, max_tokens=2000)
    return _parse_and_validate(raw, ref_to_id)


def _cache_get(scope_id: str, mhash: str) -> dict | None:
    if not supabase:
        return None
    try:
        res = (
            supabase.table(CACHE_TABLE)
            .select("payload")
            .eq("scope_id", scope_id)
            .eq("meeting_set_hash", mhash)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return rows[0].get("payload")
    except Exception as exc:
        print(f"[cross-meeting] cache read failed: {exc!r}")
    return None


def _cache_put(scope_id: str, mhash: str, payload: dict) -> None:
    if not supabase:
        return
    try:
        # Keep exactly one row per scope: upsert the current hash (race-safe on the PK),
        # then drop any other hashes for this scope so stale sets don't accumulate.
        supabase.table(CACHE_TABLE).upsert(
            {"scope_id": scope_id, "meeting_set_hash": mhash, "payload": payload},
            on_conflict="scope_id,meeting_set_hash",
        ).execute()
        supabase.table(CACHE_TABLE).delete().eq("scope_id", scope_id).neq("meeting_set_hash", mhash).execute()
    except Exception as exc:
        print(f"[cross-meeting] cache write failed: {exc!r}")


async def get_semantic_insights(meetings: list[dict], scope_id: str) -> dict:
    """Public entrypoint — pass the SAME meeting list /insights uses. Returns a dict
    with `narrative` / `topics` / `open_threads` / `decision_evolution` plus a status
    flag (`locked` / `error` / `enabled: false`). Cache hit → instant; miss → compute
    once and persist. Never raises (best-effort → empty on failure)."""
    if not SEMANTIC_ENABLED:
        return {"enabled": False, **_empty()}

    meaningful = [m for m in meetings if has_meaningful_result(m.get("result"))][:MAX_MEETINGS]
    if len(meaningful) < MIN_MEETINGS:
        return {"locked": True, "min_meetings": MIN_MEETINGS, **_empty()}

    mhash = meeting_set_hash(meaningful)
    cached = _cache_get(scope_id, mhash)
    if cached is not None:
        return cached

    try:
        result = await _run_synthesis(meaningful)
    except Exception as exc:
        print(f"[cross-meeting] synthesis failed: {exc!r}")
        return {"error": True, **_empty()}

    print(f"[cross-meeting] synthesized scope={scope_id} meetings={len(meaningful)} "
          f"narrative={'yes' if result['narrative'] else 'no'} topics={len(result['topics'])} "
          f"threads={len(result['open_threads'])} evolution={len(result['decision_evolution'])}")
    payload = {"generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), **result}
    _cache_put(scope_id, mhash, payload)
    return payload

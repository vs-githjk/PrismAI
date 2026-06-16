"""Ambient contribution lane — Automatic mode for the live bot.

Content-based triggers (unanswered question / KB hit / blocker) → one grounded
70B call that drafts and prices a contribution → tiered delivery (chat for
mid-value, direct voice for high-value) behind a speak-time timing gate.
Wiring lives in realtime_routes; this module is pure logic + the one model call.

Flags:
  PRISM_AUTONOMOUS=1         enables the lane (Utterance mode = current prod)
  PRISM_AUTONOMOUS_SHADOW=1  run + log every decision, never post or speak
  PRISM_AMBIENT_VOICE=0      chat-only rollout stage (voice tier demotes to chat)

Spec: docs/superpowers/specs/2026-06-11-ambient-contribution-lane-design.md
"""

from __future__ import annotations

import asyncio
import json
import os
import re

from clients import get_groq
import meeting_memory
import perception_state
from agents.utils import strip_fences


# ── Flags ─────────────────────────────────────────────────────────────────────
def autonomous_enabled() -> bool:
    return os.getenv("PRISM_AUTONOMOUS") == "1"

def shadow_mode() -> bool:
    return os.getenv("PRISM_AUTONOMOUS_SHADOW") == "1"


# ── Warmup gate ───────────────────────────────────────────────────────────────
WARMUP_MIN_ENTITIES = 5  # distinct named entities ⇒ meeting has substance


def past_warmup(state: dict) -> bool:
    """True once the meeting has substantive content — so the bot doesn't
    contribute during intros / small talk. Substance = a decision/action
    captured, or enough distinct named entities. Requires the meeting to have
    actually started."""
    if not state.get("meeting_start_ts"):
        return False
    if (state.get("live_decisions") or state.get("live_action_items")):
        return True
    return len(state.get("live_entities") or {}) >= WARMUP_MIN_ENTITIES


# ── Mute / unmute voice directives ────────────────────────────────────────────
_MUTE_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+"
    r"(?:stay\s+quiet|be\s+quiet|stay\s+silent|mute|stop\s+talking|stop\s+interrupting|"
    r"quiet\s+down|hush)\b",
    re.IGNORECASE,
)
_UNMUTE_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+"
    r"(?:chime\s+in|you\s+can\s+talk|you\s+can\s+chime|talk\s+again|unmute|"
    r"start\s+talking|speak\s+up)\b",
    re.IGNORECASE,
)


def detect_mute_command(text: str) -> str | None:
    """'mute' | 'unmute' | None for an explicit mute/unmute directive to Prism."""
    t = text or ""
    if _UNMUTE_RE.search(t):
        return "unmute"
    if _MUTE_RE.search(t):
        return "mute"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Ambient contribution lane (spec 2026-06-11)
# ══════════════════════════════════════════════════════════════════════════════

AMBIENT_PREFACES = [
    "One thing worth adding — ",
    "Quick note — ",
    "If it helps — ",
]

def ambient_voice_on() -> bool:
    return os.getenv("PRISM_AMBIENT_VOICE", "1") == "1"

def ambient_model() -> str:
    return os.getenv("PRISM_AMBIENT_MODEL", "llama-3.3-70b-versatile")

def voice_min() -> float:
    return float(os.getenv("PRISM_AMBIENT_VOICE_MIN", "8"))

def chat_min() -> float:
    return float(os.getenv("PRISM_AMBIENT_CHAT_MIN", "5"))

def answer_wait_s() -> float:
    return float(os.getenv("PRISM_ANSWER_WAIT_S", "6"))

def quiet_gap_s() -> float:
    return float(os.getenv("PRISM_QUIET_GAP_S", "1.5"))

def gap_wait_s() -> float:
    return float(os.getenv("PRISM_GAP_WAIT_S", "8"))

def voice_cooldown_s() -> float:
    return float(os.getenv("PRISM_AMBIENT_VOICE_COOLDOWN_S", "60"))

def chat_cooldown_s() -> float:
    return float(os.getenv("PRISM_AMBIENT_CHAT_COOLDOWN_S", "25"))

def ambient_timeout_s() -> float:
    """Hard cap on the generator call. Bounds both the OpenAI client (so the
    socket is released) and an asyncio.wait_for guard (so the caller's
    _ambient_busy flag is freed even if the SDK ignores its own timeout) — a
    hung request must never wedge the lane for the rest of the meeting."""
    return float(os.getenv("PRISM_AMBIENT_TIMEOUT_S", "8"))


# ── Trigger Q: question detection + addressee window ─────────────────────────
_QUESTION_START_RE = re.compile(
    r"^(what|who|when|where|how|why|did|does|do|is|are|was|were|which|can|"
    r"could|should|would|anyone|any)\b",
    re.IGNORECASE,
)

def is_question(text: str) -> bool:
    """Transcript-level question heuristic. Deepgram smart_format punctuates,
    so '?' is the primary signal; the question-word fallback needs >=4 words to
    avoid firing on fragments like 'what now'."""
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    return bool(_QUESTION_START_RE.match(t)) and len(t.split()) >= 4


def question_window_s(text: str, participant_names: list, kb_top_score) -> float:
    """Answer-wait window with addressee scaling (spec R3). Naming a human
    participant lengthens it (explicitly not ours); a strong KB hit or a
    past-decision/action shape shortens it (no human is the addressee of
    record). The named-human rule wins when both apply."""
    base = answer_wait_s()
    low = (text or "").lower()
    for name in participant_names or []:
        first = (name or "").strip().split(" ")[0].lower()
        if first and len(first) >= 3 and first in low:
            return base * 1.5
    if (kb_top_score or 0.0) >= 0.80:
        return base * 0.7
    if meeting_memory.DECISION_PATTERN.search(text or "") or meeting_memory.ACTION_ITEM_PATTERN.search(text or ""):
        return base * 0.7
    return base


# ── The contribution generator (one grounded call; the value IS the decider) ──
def parse_contribution_output(raw) -> dict | None:
    """Strict parse of the generator reply. None on ANY drift (fail-safe
    silent). kind='none' normalizes to a zero-value silent shape."""
    if not raw or not isinstance(raw, str):
        return None
    s = strip_fences(raw).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start:end + 1])
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    kind = obj.get("kind")
    if kind not in ("answer", "fact", "risk", "none"):
        return None
    try:
        value = float(obj.get("value"))
    except Exception:
        return None
    if kind == "none":
        return {"value": 0.0, "kind": "none", "contribution": "", "subject": ""}
    contribution = obj.get("contribution")
    if not isinstance(contribution, str) or not contribution.strip():
        return None
    return {
        "value": max(0.0, min(10.0, value)),
        "kind": kind,
        "contribution": contribution.strip()[:600],
        "subject": str(obj.get("subject", "")).strip()[:80],
    }


def _contribution_system(bot_name: str) -> str:
    return (
        f"You are {bot_name}, an AI meeting assistant listening silently to a live "
        "meeting. You are given a TRIGGER (an unanswered question, a knowledge-base "
        "match, or a risk/decision moment) plus meeting memory and evidence. Draft the "
        "single best brief contribution you could make right now, then price its value "
        "honestly.\n"
        "Rules:\n"
        "- contribution: at most 2 sentences, spoken-style, direct. No preamble.\n"
        "- Use ONLY facts present in the evidence or meeting memory. If the evidence is "
        "thin or you would have to guess, set value <= 4.\n"
        "- When a fact comes from a document, name it (e.g. \"Per the Q3 forecast doc, ...\").\n"
        "- If the room already covered it, or it appears under ALREADY CONTRIBUTED, value <= 4.\n"
        "- value rubric: 8-10 = directly answers the open question with grounded info, or "
        "corrects a material error; 5-7 = relevant and helpful but not urgent; 0-4 = "
        "tangential, obvious, or ungrounded.\n"
        'Respond with JSON ONLY, no prose: {"value": <0-10>, "kind": "answer|fact|risk|none", '
        '"contribution": "<text>", "subject": "<2-5 words>"}'
    )


async def _call_ambient_model(system: str, user: str) -> str:
    """The lane's only LLM I/O. Direct Groq (no Haiku fallback — ambient is
    optional behavior; on 429/5xx the lane stays silent). Isolated for mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=ambient_model(),
        temperature=0.2,
        max_tokens=220,
        timeout=ambient_timeout_s(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def generate_contribution(state: dict, trigger_kind: str, evidence: str,
                                bot_name: str = "Prism") -> dict | None:
    """One grounded call: memory context + trigger evidence in, priced
    contribution out. None = stay silent (drift, error, or rate limit)."""
    context = meeting_memory.build_memory_context(state)
    already = list(state.get("contributed_subjects") or [])
    already += [s for s in (state.get("previous_idea_summaries") or [])]
    contributed = "; ".join(already) if already else "(none)"
    user = (
        f"{context}\n\n[TRIGGER: {trigger_kind}]\n{evidence}\n\n"
        f"[ALREADY CONTRIBUTED]: {contributed}\n\n"
        "[TASK] Draft and price your best contribution. JSON only."
    )
    perception_state.bump(state, "ambient_generations")
    try:
        raw = await asyncio.wait_for(
            _call_ambient_model(_contribution_system(bot_name), user),
            timeout=ambient_timeout_s(),
        )
    except Exception as e:
        # asyncio.TimeoutError (a hung call) lands here too — stay silent so a
        # wedged request can't hold _ambient_busy for the rest of the meeting.
        print(f"[ambient] generator error: {e}")
        return None
    out = parse_contribution_output(raw)
    if out is None:
        perception_state.bump(state, "ambient_parse_fail")
    return out


# ── Delivery policy: tiers, cooldowns, subject ledger ─────────────────────────
def delivery_tier(value: float, max_tier: str = "voice") -> str:
    """'voice' | 'chat' | 'drop'. max_tier='chat' caps B-triggers; the voice
    flag off demotes voice-worthy values to chat (chat-only rollout stage)."""
    if value >= voice_min() and max_tier == "voice" and ambient_voice_on():
        return "voice"
    if value >= chat_min():
        return "chat"
    return "drop"


def voice_cooldown_clear(state: dict, now: float) -> bool:
    return (now - state.get("ambient_voice_last_ts", 0.0)) >= voice_cooldown_s()


def chat_cooldown_clear(state: dict, now: float) -> bool:
    return (now - state.get("ambient_chat_last_ts", 0.0)) >= chat_cooldown_s()


_MAX_CONTRIBUTED_SUBJECTS = 25

def subject_already_contributed(state: dict, subject: str) -> bool:
    key = (subject or "").strip().lower()
    return bool(key) and key in (state.get("contributed_subjects") or [])


def record_contributed_subject(state: dict, subject: str) -> None:
    key = (subject or "").strip().lower()
    if not key:
        return
    subs = state.setdefault("contributed_subjects", [])
    if key not in subs:
        subs.append(key)
        if len(subs) > _MAX_CONTRIBUTED_SUBJECTS:
            del subs[: len(subs) - _MAX_CONTRIBUTED_SUBJECTS]


# ── Speak-time timing gate (spec R2) ──────────────────────────────────────────
_TRAILING_CONNECTIVES = frozenset({"and", "but", "because", "um", "uh", "like"})

def last_utterance_terminal(state: dict) -> bool:
    """Semantic end-of-turn approximation on text: the last buffered utterance
    ends with terminal punctuation and not on a trailing connective. 'I went to
    the store and' is not a gap, even after 2s of silence."""
    buf = state.get("transcript_buffer") or []
    if not buf:
        return True
    line = buf[-1]
    text = line.split(":", 1)[1].strip() if ":" in line else line.strip()
    if not text:
        return True
    if text[-1] not in ".?!":
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return not (words and words[-1] in _TRAILING_CONNECTIVES)


def gate_clear(state: dict, now: float) -> bool:
    """All three speak-time conditions: audio-quiet >= quiet_gap_s, no pending
    partial utterance in the accumulator, last utterance semantically terminal."""
    if (now - state.get("last_audio_ts", 0.0)) < quiet_gap_s():
        return False
    acc = state.get("accumulator")
    if acc is not None and getattr(acc, "pending", None):
        return False
    return last_utterance_terminal(state)

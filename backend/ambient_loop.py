"""Ambient response loop — no-wake-word autonomous mode for the live bot.

A staged cost funnel: free recall gate → 8B decider → (existing) 70B generator →
TTS, gated by a utterance⇄autonomous mode state machine. Pure logic + the decider
model call; the generator/idea-engine are injected as callables by realtime_routes
so this module never imports realtime_routes (no circular import).

Flags:
  PRISM_AUTONOMOUS=1         enables autonomous mode (utterance mode = current prod)
  PRISM_AUTONOMOUS_SHADOW=1  run the funnel + log decisions, but NEVER speak

Spec: docs/superpowers/specs/2026-06-07-ambient-response-loop-design.md
"""

from __future__ import annotations

import json
import os
import re
import time

from clients import get_groq
import meeting_memory
import perception_state
import cross_meeting_service
from agents.utils import strip_fences

# ── Tunable constants ─────────────────────────────────────────────────────────
ACTIVE_WINDOW_S = 20.0          # window for "active cross-talk" detection
ACTIVE_UTTERANCE_COUNT = 3      # utterances within the window ⇒ active cross-talk
MODERATE_NO_FLOOR = 0.4         # decider "no" at/above this conf ⇒ Idea Engine handoff


# ── Flags / env-tunable params ────────────────────────────────────────────────
def autonomous_enabled() -> bool:
    return os.getenv("PRISM_AUTONOMOUS") == "1"

def shadow_mode() -> bool:
    return os.getenv("PRISM_AUTONOMOUS_SHADOW") == "1"

def decider_model() -> str:
    return os.getenv("PRISM_DECIDER_MODEL", "llama-3.1-8b-instant")

def pause_debounce_s() -> float:
    return float(os.getenv("PRISM_PAUSE_DEBOUNCE_S", "8"))

def lull_threshold_s() -> float:
    return float(os.getenv("PRISM_LULL_THRESHOLD_S", "35"))

def autonomy_cap_s() -> float:
    return float(os.getenv("PRISM_AUTONOMY_CAP_S", "300"))

def offer_decider_model() -> str:
    return os.getenv("PRISM_OFFER_DECIDER_MODEL", "llama-3.3-70b-versatile")

def offer_cooldown_s() -> float:
    return float(os.getenv("PRISM_OFFER_COOLDOWN_S", "90"))

def offer_consent_window_s() -> float:
    return float(os.getenv("PRISM_OFFER_CONSENT_WINDOW_S", "25"))

def offer_threshold() -> float:
    return float(os.getenv("PRISM_OFFER_THRESHOLD", "0.6"))


# ── Consent interjection: warmup + mute (v2) ──────────────────────────────────
WARMUP_MIN_ENTITIES = 5  # distinct named entities ⇒ meeting has substance


def past_warmup(state: dict) -> bool:
    """True once the meeting has substantive content — so the bot doesn't offer
    during intros / small talk. Substance = a decision/action captured, or enough
    distinct named entities. Requires the meeting to have actually started."""
    if not state.get("meeting_start_ts"):
        return False
    if (state.get("live_decisions") or state.get("live_action_items")):
        return True
    return len(state.get("live_entities") or {}) >= WARMUP_MIN_ENTITIES


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


# ── Consent interjection: offer line + subject dedup ──────────────────────────
_MAX_OFFERED_SUBJECTS = 25


def make_offer(subject: str) -> str:
    """The brief, templated consent-seeking offer. No tools, no answer content."""
    subject = (subject or "").strip()
    if not subject:
        return "Actually, I think I have something relevant here. Would you like to know more?"
    return f"Actually, I have some information about {subject}. Would you like to know more?"


def subject_already_offered(state: dict, subject: str) -> bool:
    return (subject or "").strip().lower() in (state.get("offered_subjects") or [])


def record_offered_subject(state: dict, subject: str) -> None:
    key = (subject or "").strip().lower()
    if not key:
        return
    subs = state.setdefault("offered_subjects", [])
    if key not in subs:
        subs.append(key)
        if len(subs) > _MAX_OFFERED_SUBJECTS:
            del subs[: len(subs) - _MAX_OFFERED_SUBJECTS]


# ── Mode state machine ────────────────────────────────────────────────────────
# Handoff: "prism" + a delegation verb. Reuses the wake-word cousins loosely.
_HANDOFF_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+"
    r"(?:run with (?:this|it)|take it from here|take over|take this|you (?:take|drive|handle|run)|"
    r"handle (?:this|it)|drive|go ahead and run)\b",
    re.IGNORECASE,
)
# Explicit stop addressed to prism (separate from perception_state.is_stop_command,
# which also catches "shut up"/"quiet"; we accept either).
_STOP_RE = re.compile(
    r"\b(?:prism|prismai|prism ai)\b[,:\s]+(?:stop|that'?s enough|we'?re good|stand down|back off)\b",
    re.IGNORECASE,
)


def _enter(state: dict, mode: str, reason: str, now: float, renew: bool) -> str:
    """Set mode + reason; bump the shift counter only on an actual mode change."""
    changed = state.get("mode") != mode
    state["mode"] = mode
    state["mode_entry_reason"] = reason
    if changed or renew:
        state["mode_since_ts"] = now
    if changed:
        perception_state.bump(state, "ambient_mode_shifts")
    return mode


# ── Stage 2: decider ──────────────────────────────────────────────────────────
def parse_decider_output(raw: str | None) -> dict:
    """Parse the decider's reply into {respond, confidence, reason}. ANY drift
    (empty, non-JSON, missing/!bool respond) fails safe to respond=False."""
    fallback = {"respond": False, "confidence": 0.0, "reason": "parse_failed"}
    if not raw or not isinstance(raw, str):
        return fallback
    s = strip_fences(raw).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return fallback
    try:
        obj = json.loads(s[start:end + 1])
    except Exception:
        return fallback
    if not isinstance(obj, dict) or not isinstance(obj.get("respond"), bool):
        return fallback
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "respond": obj["respond"],
        "confidence": conf,
        "reason": str(obj.get("reason", ""))[:200],
    }


_DECIDER_SYSTEM = (
    "You are the response gate for an AI meeting assistant that is listening "
    "silently. Decide ONLY whether the assistant should speak right now. Say yes "
    "only when there is a clear, helpful, NON-interrupting contribution: an "
    "unanswered question it can answer, a relevant fact to surface, or a real "
    "risk to flag. Default to staying silent for chit-chat, rhetorical questions, "
    "or anything already being handled by the people talking.\n"
    "Respond with JSON ONLY, no prose: "
    '{"respond": <true|false>, "confidence": <0.0-1.0>, "reason": "<short>"}'
)


def _signal_summary(state: dict) -> str:
    """Cheap structured signals fed to the decider alongside the memory context."""
    decisions = state.get("live_decisions") or []
    actions = state.get("live_action_items") or []
    entities = state.get("live_entities") or {}
    top = ", ".join(w for w, _ in entities.most_common(8)) if hasattr(entities, "most_common") else ""
    return (
        f"decisions_so_far={len(decisions)} action_items={len(actions)}\n"
        f"key_topics: {top}"
    )


async def _call_decider_model(system: str, user: str) -> str:
    """The only I/O in the decider. Calls Groq directly (llm_call is hardcoded to
    70B) so we can run the cheap 8B model. Isolated for easy test mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=decider_model(),
        temperature=0.1,
        max_tokens=120,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def decide(state: dict) -> dict:
    """Stage 2: should the assistant speak now? Returns {respond, confidence, reason}.
    Fed the rolling memory context + cheap signals — not a generated candidate."""
    context = meeting_memory.build_memory_context(state)
    user = (
        f"{context}\n\n[SIGNALS]\n{_signal_summary(state)}\n\n"
        "[TASK] Should the assistant speak now? JSON only."
    )
    try:
        raw = await _call_decider_model(_DECIDER_SYSTEM, user)
    except Exception as e:  # fail-safe silent on any model/transport error
        print(f"[ambient] decider error: {e}")
        return {"respond": False, "confidence": 0.0, "reason": "decider_error"}
    return parse_decider_output(raw)


# ── Consent interjection: offer-decider (70B, reads the room) ─────────────────
_OFFER_SYSTEM = (
    "You are a thoughtful AI colleague listening to a live meeting. Decide whether "
    "to BRIEFLY offer to share genuinely useful, on-topic information right now — "
    "like a polite person who has something valuable to add and asks first.\n"
    "Offer ONLY when ALL hold: (a) the moment is substantive (a real question, "
    "decision, or work topic — NOT greetings, rapport, jokes, or small talk); "
    "(b) you likely have valuable, non-obvious information to add; (c) it has not "
    "already been answered or handled by the people talking. When people are just "
    "chatting or socializing, do NOT offer.\n"
    "If you offer, name the SUBJECT in a few words. Output JSON ONLY: "
    '{"offer": <true|false>, "subject": "<short>", "confidence": <0.0-1.0>, "reason": "<short>"}'
)


def parse_offer_output(raw: str | None) -> dict:
    """Parse the offer-decider reply. Fail-safe to offer=False on any drift."""
    fallback = {"offer": False, "subject": "", "confidence": 0.0, "reason": "parse_failed"}
    if not raw or not isinstance(raw, str):
        return fallback
    s = strip_fences(raw).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return fallback
    try:
        obj = json.loads(s[start:end + 1])
    except Exception:
        return fallback
    if not isinstance(obj, dict) or not isinstance(obj.get("offer"), bool):
        return fallback
    try:
        conf = float(obj.get("confidence", 0.0))
    except Exception:
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        "offer": obj["offer"],
        "subject": str(obj.get("subject", ""))[:80].strip(),
        "confidence": conf,
        "reason": str(obj.get("reason", ""))[:200],
    }


async def _call_offer_model(system: str, user: str) -> str:
    """70B offer-decision call (direct Groq). Isolated for test mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=offer_decider_model(),
        temperature=0.2,
        max_tokens=120,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def offer_decider(state: dict) -> dict:
    """70B 'read the room': should the bot offer to share info, and about what?
    Returns {offer, subject, confidence, reason}; fail-safe offer=False."""
    context = meeting_memory.build_memory_context(state)
    user = (
        f"{context}\n\n[SIGNALS]\n{_signal_summary(state)}\n\n"
        "[TASK] Should you briefly offer to share useful info now? JSON only."
    )
    try:
        raw = await _call_offer_model(_OFFER_SYSTEM, user)
    except Exception as e:
        print(f"[ambient] offer-decider error: {e}")
        return {"offer": False, "subject": "", "confidence": 0.0, "reason": "decider_error"}
    return parse_offer_output(raw)


# ── Consent interjection: consent classifier (8B) ─────────────────────────────
_CONSENT_TOKEN_RE = re.compile(r"\b(yes|no|unclear)\b", re.IGNORECASE)

_CONSENT_SYSTEM = (
    "An AI meeting assistant offered to share some information and asked if the "
    "humans want to hear it. Given the human's reply, decide whether they agreed "
    "to hear it. Watch for tricky cases: 'No way, tell me!' is YES; 'yeah, no, "
    "we're good' is NO; a bare 'okay' is usually just acknowledgement, not "
    "agreement (UNCLEAR). Answer with one word: YES, NO, or UNCLEAR."
)


def parse_consent(raw: str | None) -> str:
    """Map the classifier's reply to 'yes' | 'no' | 'unclear'. Fail-safe to
    'unclear' (never deliver on ambiguity)."""
    if not raw or not isinstance(raw, str):
        return "unclear"
    m = _CONSENT_TOKEN_RE.search(raw)
    if not m:
        return "unclear"
    return m.group(1).lower()


async def _call_consent_model(system: str, user: str) -> str:
    """8B consent classification call (direct Groq). Isolated for test mocking."""
    groq = get_groq()
    resp = await groq.chat.completions.create(
        model=decider_model(),  # reuse the cheap 8B decider model
        temperature=0.0,
        max_tokens=8,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def classify_consent(subject: str, utterance: str) -> str:
    """Did the human agree to hear the offered info? 'yes' | 'no' | 'unclear'."""
    user = (
        f"The assistant offered to share information about: {subject or 'something relevant'}.\n"
        f"The human then said: \"{utterance}\"\n"
        "Did they agree to hear it? Answer YES, NO, or UNCLEAR."
    )
    try:
        raw = await _call_consent_model(_CONSENT_SYSTEM, user)
    except Exception as e:
        print(f"[ambient] consent classifier error: {e}")
        return "unclear"
    return parse_consent(raw)


# ── Stage 1: free recall gate ─────────────────────────────────────────────────
_REQUEST_RE = re.compile(
    r"\b(can|could|would|should|let'?s|we need|i need|do we|please|"
    r"how do|how should|what'?s the|any idea|anyone know)\b",
    re.IGNORECASE,
)


def recall_gate(state: dict, utterance_text: str, now: float) -> bool:
    """High-recall, ~free pre-filter. Fires the decider when an utterance plausibly
    contains an opening, OR on a debounced pause tick (so the decider gets a
    periodic shot at implicit openings). Tuned to over-fire; the decider is the
    precision stage.
    """
    text = utterance_text or ""
    low = text.lower()
    if "?" in text:
        return True
    if set(re.findall(r"\b\w+\b", low)) & meeting_memory._QUESTION_WORDS:
        return True
    if _REQUEST_RE.search(low):
        return True
    if cross_meeting_service.looks_like_blocker(text):
        return True
    if meeting_memory.DECISION_PATTERN.search(text) or meeting_memory.ACTION_ITEM_PATTERN.search(text):
        return True
    # Debounced pause tick — periodic shot at implicit openings.
    if (now - state.get("_ambient_last_gate_ts", 0.0)) >= pause_debounce_s():
        return True
    return False


# ── Consent interjection: state machine (v2) ──────────────────────────────────
async def interject(
    bot_id: str,
    state: dict,
    utterance_text: str,
    speaker: str,
    *,
    speak_offer,      # async (bot_id, text) -> bool  (True if the offer was spoken, False if talked over)
    run_delivery,     # async (bot_id, subject, speaker) -> str | None  (full answer about subject)
    now: float | None = None,
) -> dict:
    """v2 consent-based interjection. One call per completed utterance in
    autonomous mode. IDLE → (offer) → OFFER_PENDING → (consent) → deliver/drop.
    Returns an action dict for observability/tests. Never raises into the caller."""
    now = time.time() if now is None else now

    # 0. Mute / unmute — always honored (no mutex; synchronous).
    cmd = detect_mute_command(utterance_text)
    if cmd == "mute":
        state["muted"] = True
        state["interjection_state"] = "idle"
        state["pending_offer"] = None
        perception_state.bump(state, "mutes")
        print(f"[ambient] muted bot={bot_id[:8]}")
        return {"action": "muted"}
    if cmd == "unmute":
        state["muted"] = False
        print(f"[ambient] unmuted bot={bot_id[:8]}")
        return {"action": "unmuted"}
    if state.get("muted"):
        return {"action": "muted_skip"}

    if state.get("_ambient_evaluating"):
        return {"action": "busy"}
    state["_ambient_evaluating"] = True
    try:
        # 1. OFFER_PENDING → consent handling (suppresses new offers).
        if state.get("interjection_state") == "offer_pending":
            return await _handle_pending_offer(bot_id, state, utterance_text, speaker, now, run_delivery)

        # 2. IDLE → maybe offer.
        if not past_warmup(state):
            return {"action": "warmup"}
        if (now - state.get("offer_last_ts", 0.0)) < offer_cooldown_s():
            return {"action": "cooldown"}
        if not recall_gate(state, utterance_text, now):
            return {"action": "gate_miss"}
        state["_ambient_last_gate_ts"] = now

        # Cheap 8B substance prefilter, then the 70B read-the-room offer-decider.
        pre = await decide(state)
        if not pre["respond"]:
            return {"action": "prefilter_stop", "confidence": pre["confidence"]}
        od = await offer_decider(state)
        if not od["offer"] or od["confidence"] < offer_threshold():
            return {"action": "no_offer", "confidence": od["confidence"]}
        subject = od["subject"]
        if subject_already_offered(state, subject):
            return {"action": "dup_subject", "subject": subject}

        if shadow_mode():
            perception_state.bump(state, "offers_made")
            print(f"[ambient] SHADOW would offer bot={bot_id[:8]} subject={subject!r} conf={od['confidence']:.2f}")
            return {"action": "shadow_offer", "subject": subject}

        spoke = await speak_offer(bot_id, make_offer(subject))
        if not spoke:
            perception_state.bump(state, "offers_talked_over")
            return {"action": "offer_talked_over", "subject": subject}

        perception_state.bump(state, "offers_made")
        record_offered_subject(state, subject)
        state["interjection_state"] = "offer_pending"
        state["pending_offer"] = {"subject": subject, "ts": now, "turns": 0}
        state["offer_last_ts"] = now
        print(f"[ambient] offered bot={bot_id[:8]} subject={subject!r} conf={od['confidence']:.2f}")
        return {"action": "offered", "subject": subject}
    finally:
        state["_ambient_evaluating"] = False


async def _handle_pending_offer(bot_id, state, utterance_text, speaker, now, run_delivery) -> dict:
    """An offer is out; classify the human's reply and deliver / drop / wait."""
    po = state.get("pending_offer") or {}
    subject = po.get("subject", "")
    po["turns"] = po.get("turns", 0) + 1

    consent = await classify_consent(subject, utterance_text)
    if consent == "yes":
        state["interjection_state"] = "idle"
        state["pending_offer"] = None
        perception_state.bump(state, "offers_accepted")
        spoken = await run_delivery(bot_id, subject, speaker)
        state["offer_last_ts"] = now
        print(f"[ambient] delivered bot={bot_id[:8]} subject={subject!r} spoke={bool(spoken)}")
        return {"action": "delivered" if spoken else "delivery_declined", "subject": subject}
    if consent == "no":
        state["interjection_state"] = "idle"
        state["pending_offer"] = None
        perception_state.bump(state, "offers_declined")
        return {"action": "declined", "subject": subject}

    # unclear → wait, unless the consent window has passed (time or turns).
    expired = (now - po.get("ts", now)) > offer_consent_window_s() or po["turns"] >= 2
    if expired:
        state["interjection_state"] = "idle"
        state["pending_offer"] = None
        perception_state.bump(state, "offers_expired")
        return {"action": "expired", "subject": subject}
    return {"action": "awaiting_consent", "subject": subject, "turns": po["turns"]}


def check_lull(state: dict, now: float) -> str | None:
    """Called from the accumulator tick loop (NOT on an utterance). If the
    meeting has been active but silent for > lull_threshold_s and we're in
    utterance mode, shift to autonomous (reason=lull). Returns the new mode
    on a shift, else None. The next utterance is then evaluated through the
    funnel; lull-entered autonomous reverts on active cross-talk (update_mode).
    """
    if state.get("manual_mode") in ("utterance", "autonomous"):
        return None
    if state.get("mode") != "utterance":
        return None
    if not state.get("meeting_start_ts"):
        return None
    last = state.get("last_activity_ts", 0.0)
    if last <= 0:
        return None
    if (now - last) <= lull_threshold_s():
        return None
    return _enter(state, "autonomous", "lull", now, renew=True)


def update_mode(state: dict, utterance_text: str, speaker_name: str, now: float) -> str:
    """Detect handoff / stop / cap / lull-revert on a completed utterance.
    Mutates + returns state['mode'] ('utterance' | 'autonomous'). Also records
    activity for lull/active-crosstalk tracking. Honors a manual override.
    """
    # Activity tracking (drives lull + active-cross-talk detection).
    state["last_activity_ts"] = now
    rec = state.setdefault("recent_utterance_ts", [])
    rec.append(now)
    cutoff = now - ACTIVE_WINDOW_S
    state["recent_utterance_ts"] = [t for t in rec if t >= cutoff]

    # Manual override wins unconditionally.
    manual = state.get("manual_mode")
    if manual in ("utterance", "autonomous"):
        return _enter(state, manual, "manual", now, renew=False)

    text = (utterance_text or "")
    mode = state.get("mode", "utterance")

    # Explicit stop → utterance.
    if _STOP_RE.search(text) or perception_state.is_stop_command(text):
        return _enter(state, "utterance", "", now, renew=False)

    # Explicit handoff → autonomous (renews the autonomy cap window).
    if _HANDOFF_RE.search(text):
        return _enter(state, "autonomous", "handoff", now, renew=True)

    # Autonomy cap → revert.
    if mode == "autonomous" and (now - state.get("mode_since_ts", now)) > autonomy_cap_s():
        return _enter(state, "utterance", "", now, renew=False)

    # Lull-entered autonomous reverts when active cross-talk resumes.
    if (
        mode == "autonomous"
        and state.get("mode_entry_reason") == "lull"
        and len(state["recent_utterance_ts"]) >= ACTIVE_UTTERANCE_COUNT
    ):
        return _enter(state, "utterance", "", now, renew=False)

    return mode

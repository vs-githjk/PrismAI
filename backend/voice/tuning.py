"""Phase 5 — every "feel" knob for the voice agent, in one place (§5's knob table).

These decide whether the bot reads as a participant or as a system that technically
responds. All of them are env-overridable so the owner can turn them between meetings
without a code change (§6 is a knob-turning loop, not a feature build).

Seeds come from Curio's `agent/tuning.py` wherever we have an equivalent — those values
are already proven on real conversations, so starting anywhere else would be guessing.
Where the shapes differ, the difference is stated rather than papered over:

  · Curio has no Silero VAD (its backchannel tolerance is a word-count strategy on Flux
    interims). Ours is duration-gated VAD speech (fork ④ — Silero owns barge-in). We port
    Curio's *value* for "how much speech is a real interruption" as `LATE_INTERRUPT_MIN_WORDS`
    (its BACKCHANNEL_MIN_WORDS=3), never its mechanism.
  · Curio's `USER_TURN_SETTLE_SECS` (0.3) belongs to pipecat's user-turn aggregator. Our
    pipeline has no aggregator (the brain is outside the framework, Q1), so there is no
    equivalent — a settle delay here would be pure added latency with nothing to settle.
  · Curio's ICE/STUN + opener knobs are WebRTC-client concerns; we speak through Recall's
    Output Media instead.

Restart the backend after changing anything here.
"""

from __future__ import annotations

import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0") not in ("0", "false", "False", "")


def _opt_f(name: str) -> float | None:
    """Optional float knob — unset (or blank) means "feature off"."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# ── Barge-in (§1) ────────────────────────────────────────────────────────────
# Operational kill-switch. Off → Flux's own StartOfTurn interruption is used instead
# (the Phase-2 behaviour: any turn start kills the reply, no backchannel tolerance).
BARGE_IN_ENABLED = _b("PRISM_VOICE_BARGE_IN", True)

# How long Silero must hear sustained speech, from the START of the burst, before we
# treat it as a real interruption rather than a backchannel ("yeah", "mm-hm", "right").
# Lower = twitchier (an "uh-huh" kills the reply); higher = the bot talks over you longer.
BARGE_MIN_SPEECH_MS = _i("PRISM_BARGE_MIN_SPEECH_MS", 500)

# A burst that stayed UNDER the threshold but whose transcript turns out to be this many
# words or more is a LATE interrupt (the human said something substantive, briefly).
# Seeded from Curio's BACKCHANNEL_MIN_WORDS=3 — the value it proved, not its mechanism.
LATE_INTERRUPT_MIN_WORDS = _i("PRISM_LATE_INTERRUPT_MIN_WORDS", 3)

# Silero VADParams. Defaults are pipecat's own; start_secs is how long speech must be
# confirmed before VAD reports a start (it is *inside* BARGE_MIN_SPEECH_MS, not on top).
VAD_CONFIDENCE = _f("PRISM_VAD_CONFIDENCE", 0.7)
VAD_START_SECS = _f("PRISM_VAD_START_SECS", 0.2)
VAD_STOP_SECS = _f("PRISM_VAD_STOP_SECS", 0.2)
VAD_MIN_VOLUME = _f("PRISM_VAD_MIN_VOLUME", 0.6)

# ── Politeness gap (§2) ──────────────────────────────────────────────────────
# How long the room must be acoustically quiet before the bot starts an utterance, and
# the never-hang cap if the room never goes quiet. Same values as the transcript-timestamp
# version they replace — now measured on VAD truth instead of lagged transcripts.
GAP_SILENCE_S = _f("PRISM_GAP_SILENCE_S", 1.2)
GAP_MAX_WAIT_S = _f("PRISM_GAP_MAX_WAIT_S", 4.0)
GAP_ENABLED = _b("PRISM_GAP_WAIT", True)
# Poll interval while waiting. VAD state is local and free to read, so the acoustic path
# polls tight; the transcript-timestamp fallback stays lazy.
GAP_POLL_VAD_S = _f("PRISM_GAP_POLL_VAD_S", 0.05)
GAP_POLL_FALLBACK_S = _f("PRISM_GAP_POLL_FALLBACK_S", 0.2)
# Log a rolling median/p90 of observed waits every N waits (the §2 report-back).
GAP_REPORT_EVERY = _i("PRISM_GAP_REPORT_EVERY", 10)

# ── End-of-turn / latency (§3) ───────────────────────────────────────────────
FLUX_MODEL = os.getenv("PRISM_FLUX_MODEL", "flux-general-en")
# Confidence Flux needs before declaring the turn over. Lower = snappier + more risk of
# cutting in mid-thought; higher = patient but laggy after short answers. (Curio: 0.7)
FLUX_EOT_THRESHOLD = _f("PRISM_FLUX_EOT_THRESHOLD", 0.7)
# Hard ceiling: this much silence ends the turn regardless of semantic confidence.
FLUX_EOT_TIMEOUT_MS = _i("PRISM_FLUX_EOT_TIMEOUT_MS", 5000)
# Eager end-of-turn. UNSET = off (Flux's default, and Curio's). Setting it (try 0.5, must
# be below FLUX_EOT_THRESHOLD) turns on the SPECULATIVE voice-channel call: the talk brain
# starts on the eager transcript and the reply is held until EndOfTurn confirms it —
# expected 200–400ms off first audio, at the cost of some discarded LLM calls.
FLUX_EAGER_EOT_THRESHOLD = _opt_f("PRISM_FLUX_EAGER_EOT_THRESHOLD")
# A speculation nobody adopts is abandoned after this long (a turn the gate declined).
SPECULATION_TTL_S = _f("PRISM_SPECULATION_TTL_S", 15.0)

# ── Voice & delivery (§4) ────────────────────────────────────────────────────
TTS_MODEL = os.getenv("PRISM_TTS_MODEL", "sonic-3")
# No default: the voice is a key-stop item, picked by the owner in the §6 loop.
TTS_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
TTS_SPEED = _f("PRISM_TTS_SPEED", 1.0)      # valid 0.6–1.5; below ~0.92 starts to drag
TTS_VOLUME = _f("PRISM_TTS_VOLUME", 1.0)    # valid 0.5–2.0
# Single emotion hint applied to EVERY sentence — a soft value makes the bot coo at small
# talk. Leave unset and let Sonic-3 infer delivery from the words (Curio's finding).
TTS_EMOTION = os.getenv("PRISM_TTS_EMOTION", "").strip() or None

# Spoken-copy caps (the speak-short / chat-full rule, KRC item 21). The seed is the
# pre-streaming value; §4 wants these re-picked once the streaming mouth is on real audio,
# which needs a real meeting first — so they ship as knobs at the old value, not as a guess.
SPOKEN_MAX_SENTENCES = _i("PRISM_SPOKEN_MAX_SENTENCES", 3)
SPOKEN_MAX_CHARS = _i("PRISM_SPOKEN_MAX_CHARS", 340)

# ── Queue / ack (fork ③, item 10) ────────────────────────────────────────────
# Post "on it…" to chat only when the agent channel is still working after this long.
ACK_DELAY_S = _f("PRISM_CHAT_ACK_DELAY_S", 1.5)
DEDUP_WINDOW_S = _f("PRISM_DEDUP_WINDOW_S", 3.0)
DEDUP_DROP_RATIO = _f("PRISM_DEDUP_DROP_RATIO", 0.85)   # ≥ → same command re-heard, drop
DEDUP_AMBIG_RATIO = _f("PRISM_DEDUP_AMBIG_RATIO", 0.60)  # [ambig, drop) → tier-2 model


def summary() -> str:
    """One grep-able line of the live knob values — printed when a pipeline starts, so a
    meeting's log says exactly what the bot was tuned to when the owner reports feel."""
    return (
        f"barge={'on' if BARGE_IN_ENABLED else 'off'}/{BARGE_MIN_SPEECH_MS}ms "
        f"late_words={LATE_INTERRUPT_MIN_WORDS} gap={GAP_SILENCE_S}/{GAP_MAX_WAIT_S}s "
        f"eot={FLUX_EOT_THRESHOLD}@{FLUX_EOT_TIMEOUT_MS}ms eager={FLUX_EAGER_EOT_THRESHOLD} "
        f"tts={TTS_MODEL}/speed={TTS_SPEED}/vol={TTS_VOLUME}/emotion={TTS_EMOTION} "
        f"spoken={SPOKEN_MAX_SENTENCES}sent/{SPOKEN_MAX_CHARS}ch ack={ACK_DELAY_S}s "
        f"dedup={DEDUP_DROP_RATIO}/{DEDUP_WINDOW_S}s"
    )


# ── self-check ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Parsers must never raise on junk — a bad env value degrades to the seed, because a
    # typo'd knob in Render's dashboard must not take the bot's voice out.
    os.environ["PRISM_BARGE_MIN_SPEECH_MS"] = "notanumber"
    assert _i("PRISM_BARGE_MIN_SPEECH_MS", 500) == 500
    os.environ["PRISM_BARGE_MIN_SPEECH_MS"] = "700"
    assert _i("PRISM_BARGE_MIN_SPEECH_MS", 500) == 700
    os.environ["PRISM_GAP_SILENCE_S"] = "0.8"
    assert _f("PRISM_GAP_SILENCE_S", 1.2) == 0.8
    os.environ["PRISM_FLUX_EAGER_EOT_THRESHOLD"] = ""
    assert _opt_f("PRISM_FLUX_EAGER_EOT_THRESHOLD") is None      # unset → feature off
    os.environ["PRISM_FLUX_EAGER_EOT_THRESHOLD"] = "0.5"
    assert _opt_f("PRISM_FLUX_EAGER_EOT_THRESHOLD") == 0.5
    os.environ["PRISM_VOICE_BARGE_IN"] = "0"
    assert _b("PRISM_VOICE_BARGE_IN", True) is False
    assert "barge=" in summary()
    print("tuning self-check OK")

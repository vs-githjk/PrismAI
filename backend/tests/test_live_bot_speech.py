"""Live-bot 'speak like a human' changes (2026-07): the solo-mode intent gate
(is_addressed_or_actionable) and the SILENT no-op sentinel (_is_silent_reply).

Pure logic — no network, no LLM. The intent gate decides whether a wake-word-less
utterance in solo free-flow is worth routing to the model; SILENT is the
model-side backstop the reply path suppresses."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import realtime_routes as rr


# ── Solo-mode intent gate ─────────────────────────────────────────────────────
def test_intent_gate_positives():
    for text in (
        "can you pull up the PR",          # request phrase + question opener
        "what did we decide",              # question opener + 'what did'
        "Prism summarize",                 # names the bot
        "schedule a sync tomorrow",        # leading imperative verb
    ):
        assert rr.is_addressed_or_actionable(text) is True, text


def test_intent_gate_negatives():
    for text in (
        "I'm thinking so good",
        "I hope this email finds you well",   # 'email' as a noun, not an imperative
        "because you need the same tone",
        "yeah, drilling the same",
    ):
        assert rr.is_addressed_or_actionable(text) is False, text


def test_intent_gate_question_mark_passes():
    assert rr.is_addressed_or_actionable("the budget looks fine right?") is True


def test_intent_gate_persona_alias_passes():
    # Every persona display name counts as addressing the bot.
    assert rr.is_addressed_or_actionable("Flash, what's next") is True
    assert rr.is_addressed_or_actionable("hey Spectrum can you help") is True


def test_intent_gate_summarize_prefix_passes():
    assert rr.is_addressed_or_actionable("summarize the last ten minutes") is True
    assert rr.is_addressed_or_actionable("summarise where we landed") is True


def test_intent_gate_empty_is_false():
    assert rr.is_addressed_or_actionable("") is False
    assert rr.is_addressed_or_actionable("   ") is False
    assert rr.is_addressed_or_actionable(None) is False


# ── SILENT no-op sentinel ─────────────────────────────────────────────────────
def test_silent_reply_matches_bare_sentinel():
    for raw in ("SILENT", "silent.", " SILENT ", '"SILENT"', "`SILENT`", "SILENT!"):
        assert rr._is_silent_reply(raw) is True, raw


def test_silent_reply_ignores_word_in_sentence():
    for raw in (
        "the room went silent",
        "SILENT mode is now on",
        "I'll stay quiet unless asked",
        "We agreed to keep it silent for now.",
    ):
        assert rr._is_silent_reply(raw) is False, raw


def test_silent_reply_empty_is_false():
    assert rr._is_silent_reply("") is False
    assert rr._is_silent_reply(None) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

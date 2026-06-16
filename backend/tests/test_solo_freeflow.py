"""Solo free-flow: when exactly one human is present the live bot responds
without a wake word. Tests the participant counting + eligibility helpers."""
import os
import types

import realtime_routes as rr


def _u(text, *, speaker_id="s1", speaker_name="Alice", word_count=None):
    """Minimal FlushedUtterance stand-in for the helper tests."""
    return types.SimpleNamespace(
        text=text,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        word_count=word_count if word_count is not None else len(text.split()),
    )


def _state(**over):
    s = {
        "participants": {},
        "participants_seen": False,
        "human_speaker_ids": set(),
        "max_humans_seen": 0,
    }
    s.update(over)
    return s


# ── bot self-exclusion ────────────────────────────────────────────────────────
def test_bot_names_excluded_from_human_count():
    assert rr._looks_like_bot_participant("Prism", {}) is True
    assert rr._looks_like_bot_participant("Flash", {}) is True
    assert rr._looks_like_bot_participant("PrismAI", {}) is True
    assert rr._looks_like_bot_participant("Alice", {}) is False


def test_is_current_user_flag_excludes_bot():
    assert rr._looks_like_bot_participant("Whatever", {"is_current_user": True}) is True
    assert rr._looks_like_bot_participant("Whatever", {"is_bot": True}) is True


# ── participant-driven solo detection ─────────────────────────────────────────
def test_solo_active_with_one_human_plus_bot(monkeypatch):
    monkeypatch.setenv("PRISM_SOLO_FREEFLOW", "1")
    s = _state(
        participants_seen=True,
        participants={
            "p1": {"name": "Alice", "is_bot": False},
            "bot": {"name": "Prism", "is_bot": True},
        },
    )
    assert rr._human_participant_count(s) == 1
    assert rr._solo_mode_active(s) is True


def test_not_solo_with_two_humans(monkeypatch):
    monkeypatch.setenv("PRISM_SOLO_FREEFLOW", "1")
    s = _state(
        participants_seen=True,
        participants={
            "p1": {"name": "Alice", "is_bot": False},
            "p2": {"name": "Bob", "is_bot": False},
            "bot": {"name": "Prism", "is_bot": True},
        },
    )
    assert rr._human_participant_count(s) == 2
    assert rr._solo_mode_active(s) is False


def test_flag_off_disables_solo(monkeypatch):
    monkeypatch.setenv("PRISM_SOLO_FREEFLOW", "0")
    s = _state(
        participants_seen=True,
        participants={"p1": {"name": "Alice", "is_bot": False}},
    )
    assert rr._solo_mode_active(s) is False


# ── speaker fallback (no participant events) ──────────────────────────────────
def test_speaker_fallback_one_human(monkeypatch):
    monkeypatch.setenv("PRISM_SOLO_FREEFLOW", "1")
    s = _state(human_speaker_ids={"s1"}, max_humans_seen=1)
    assert rr._solo_mode_active(s) is True


def test_speaker_fallback_blocks_group_after_two_seen(monkeypatch):
    monkeypatch.setenv("PRISM_SOLO_FREEFLOW", "1")
    # Only one speaker active right now, but we've seen two → never free-flow.
    s = _state(human_speaker_ids={"s1"}, max_humans_seen=2)
    assert rr._solo_mode_active(s) is False


# ── eligibility filter ────────────────────────────────────────────────────────
def test_eligibility_rejects_filler():
    assert rr._solo_freeflow_eligible(_u("um okay")) is False
    assert rr._solo_freeflow_eligible(_u("yeah")) is False


def test_eligibility_accepts_real_utterance():
    assert rr._solo_freeflow_eligible(_u("what did we decide about the budget")) is True

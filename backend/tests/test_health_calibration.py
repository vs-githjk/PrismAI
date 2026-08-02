"""Calibration fixes (Aug 2026): the sentiment gate counts HUMANS (the bot's own
lines are not a participant), and health_score can decline to grade — score null,
never a fake 50 — for recordings that never tried to be meetings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.orchestrator import count_human_speakers, run_orchestrator  # noqa: E402
from agents.health_score import _normalize, _DEFAULT  # noqa: E402


SOLO_WITH_BOT = "Abhinav Dasari: Prism, what's the weather?\nPrism: It's sunny today."
SOLO_WITH_PERSONA = "Abhinav Dasari: Flash, summarize.\nFlash: Here's the summary."
TWO_HUMANS = "Alice: We need to decide.\nBob: Agreed, let's ship it."


def test_bot_lines_do_not_count_as_speakers():
    assert count_human_speakers(SOLO_WITH_BOT) == 1
    assert count_human_speakers(SOLO_WITH_PERSONA) == 1
    assert count_human_speakers(TWO_HUMANS) == 2


def test_interpersonal_agents_gated_off_for_human_plus_bot():
    # The July 17 regression: 'Abhinav + Prism' passed the old >=2-speaker gate and
    # sentiment graded the product as a coworker ("Prism dominates 81% of talk").
    # speaker_coach follows the same rule — no second human, no talk balance.
    for solo in (SOLO_WITH_BOT, SOLO_WITH_PERSONA):
        routed = run_orchestrator(solo)
        assert "sentiment" not in routed
        assert "speaker_coach" not in routed
    routed = run_orchestrator(TWO_HUMANS)
    assert "sentiment" in routed
    assert "speaker_coach" in routed


def test_failure_default_has_no_score():
    hs = _DEFAULT["health_score"]
    assert hs["score"] is None
    assert hs["breakdown"]["clarity"] is None
    assert hs["badges"] == []


def test_normalize_accepts_null_score():
    out = _normalize({"health_score": {"score": None, "verdict": "Not a meeting.",
                                       "breakdown": {"clarity": None, "action_orientation": None, "engagement": None}}})
    hs = out["health_score"]
    assert hs["score"] is None
    assert hs["breakdown"]["engagement"] is None
    assert hs["badges"] == []


def test_normalize_clamps_and_coerces():
    out = _normalize({"health_score": {"score": "72.6", "badges": ["Concise", ""],
                                       "breakdown": {"clarity": 150, "action_orientation": -3, "engagement": "abc"}}})
    hs = out["health_score"]
    assert hs["score"] == 73
    assert hs["breakdown"]["clarity"] == 100
    assert hs["breakdown"]["action_orientation"] == 0
    assert hs["breakdown"]["engagement"] is None
    assert hs["badges"] == ["Concise"]

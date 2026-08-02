"""Server-side Trend metrics — the mirror of frontend/tests/insights.test.mjs.

normalizeInsights prefers the SERVER's avg_score / score_delta over the client
fallback, so a fix on only one side leaves the bug live in production. Both sides
had the same two defects: "delta vs prior" subtracted the OLDEST meeting in the
window (a rising score reported a decline), and "30-day average" had no window.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cross_meeting_service import derive_cross_meeting_insights


def days_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def meeting(score, date, mid=None):
    return {
        "id": mid or f"m-{score}-{date}",
        "date": date,
        "result": {"summary": "x", "health_score": {"score": score}},
    }


def test_score_delta_uses_the_previous_meeting_not_the_oldest():
    # The exact shape that reported -4: newest 84, previous 73, oldest 88.
    history = [meeting(84, days_ago(1)), meeting(73, days_ago(2)), meeting(88, days_ago(3))]
    out = derive_cross_meeting_insights(history)
    assert out["latest_score"] == 84
    assert out["score_delta"] == 11, "84-73, not 84-88"


def test_score_delta_is_order_independent():
    oldest_first = [meeting(88, days_ago(3)), meeting(73, days_ago(2)), meeting(84, days_ago(1))]
    assert derive_cross_meeting_insights(oldest_first)["score_delta"] == 11


def test_score_delta_is_none_for_a_single_meeting():
    out = derive_cross_meeting_insights([meeting(84, days_ago(1))])
    assert out["score_delta"] is None, "0 would claim 'no change' where there is no comparison"


def test_score_delta_negative_when_score_really_fell():
    history = [meeting(60, days_ago(1)), meeting(90, days_ago(2))]
    assert derive_cross_meeting_insights(history)["score_delta"] == -30


def test_avg_score_is_windowed_to_30_days():
    history = [meeting(90, days_ago(1)), meeting(80, days_ago(10)), meeting(20, days_ago(45))]
    out = derive_cross_meeting_insights(history)
    assert out["avg_score"] == 85, "mean of 90 and 80; the 45-day-old meeting is out of window"
    assert out["avg_score_count"] == 2


def test_avg_score_none_when_window_is_empty():
    out = derive_cross_meeting_insights([meeting(70, days_ago(90))])
    assert out["avg_score"] is None
    assert out["avg_score_count"] == 0


def test_undated_rows_are_kept_rather_than_dropped():
    out = derive_cross_meeting_insights([meeting(70, None), meeting(90, days_ago(1))])
    assert out["avg_score_count"] == 2
    assert out["avg_score"] == 80


def test_unscored_meetings_do_not_count_as_zero():
    unscored = {"id": "u", "date": days_ago(1), "result": {"summary": "no health score"}}
    history = [unscored, meeting(80, days_ago(2)), meeting(70, days_ago(3))]
    out = derive_cross_meeting_insights(history)
    assert out["latest_score"] == 80, "latest SCORED meeting, not the unscored newest row"
    assert out["avg_score"] == 75

"""Late-joiner notes-link re-post gating (_should_repost_late_join).

The bot's intro is broadcast eagerly at /join-meeting, so everyone already in the
room when the bot arrives is covered by it. Recall replays a join event for that
whole initial roster the instant the bot enters — those must NOT be re-posted to;
only participants who arrive well after the bot qualify."""
import realtime_routes as rr


def _state():
    return {"intro_sent": True}


def test_initial_roster_not_reposted():
    """Everyone present when the bot joins (join events within the grace window
    of the first roster event) is suppressed — they saw the intro."""
    s = _state()
    t0 = 1000.0
    # 10 people already in the room; their join events all land ~immediately.
    for i in range(10):
        assert rr._should_repost_late_join(s, f"p{i}", False, now=t0 + i * 0.1) is False


def test_genuine_late_joiner_reposted():
    s = _state()
    t0 = 1000.0
    rr._should_repost_late_join(s, "host", False, now=t0)  # sets roster_epoch
    # Someone arrives well after the grace window.
    assert rr._should_repost_late_join(s, "late", False, now=t0 + rr._ROSTER_GRACE_SEC + 60) is True


def test_bot_never_reposted():
    s = _state()
    assert rr._should_repost_late_join(s, "botpid", True, now=2000.0) is False


def test_deduped_per_pid():
    s = _state()
    t0 = 1000.0
    rr._should_repost_late_join(s, "host", False, now=t0)
    late = t0 + rr._ROSTER_GRACE_SEC + 60
    assert rr._should_repost_late_join(s, "late", False, now=late) is True
    # Same pid firing again (Recall re-sends) must not double-notify.
    assert rr._should_repost_late_join(s, "late", False, now=late + 5) is False

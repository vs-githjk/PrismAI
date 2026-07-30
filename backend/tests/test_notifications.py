"""Notification center (#9) unit tests — pure logic + synthesis, no live DB."""

from datetime import datetime, timedelta, timezone

import notifications as n


def _iso_days(delta: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=delta)).isoformat()


def test_due_status_thresholds():
    assert n._due_status(_iso_days(-2))[0] == "overdue"
    assert n._due_status(_iso_days(0))[0] == "soon"
    assert n._due_status(_iso_days(3))[0] == "soon"
    assert n._due_status(_iso_days(4))[0] == "later"
    assert n._due_status("")[0] is None
    assert n._due_status("not-a-date")[0] is None


class _FakeMeetings:
    """Fake supabase for synthesize_action_due: one meeting with mixed items."""
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        self._t = name
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})


def test_synthesize_action_due_filters(monkeypatch):
    rows = [{
        "id": 5, "title": "Sync", "workspace_id": None,
        "result": {"action_items": [
            {"task": "Ship overdue thing", "owner": "Vidyut Sriram", "due_date": _iso_days(-1)},
            {"task": "Due soon thing", "owner": "vidyut", "due_date": _iso_days(2)},
            {"task": "Far future", "owner": "Vidyut", "due_date": _iso_days(30)},
            {"task": "Someone else's", "owner": "Alice", "due_date": _iso_days(-1)},
            {"task": "Done one", "owner": "Vidyut", "due_date": _iso_days(-1), "completed": True},
        ]},
    }]
    monkeypatch.setattr(n, "supabase", _FakeMeetings(rows))
    monkeypatch.setattr(n, "_user_names", lambda uid: ["vidyut", "vidyut sriram"])

    out = n.synthesize_action_due("u1")
    tasks = [o["body"] for o in out]
    assert "Ship overdue thing" in tasks     # overdue, mine -> in
    assert "Due soon thing" in tasks         # due in 2d, mine -> in
    assert "Far future" not in tasks         # 30d out -> excluded
    assert "Someone else's" not in tasks     # not mine -> excluded
    assert "Done one" not in tasks           # completed -> excluded
    # Overdue sorts before due-soon.
    assert out[0]["body"] == "Ship overdue thing"
    # Every synthesized item is flagged + carries a stable id + meeting link.
    assert all(o["synthesized"] and o["id"].startswith("action_due:") and o["meeting_id"] == 5 for o in out)


def test_synthesize_no_names_returns_empty(monkeypatch):
    monkeypatch.setattr(n, "_user_names", lambda uid: [])
    assert n.synthesize_action_due("u1") == []


def test_create_notification_noops_without_supabase(monkeypatch):
    monkeypatch.setattr(n, "supabase", None)
    # Must not raise even with storage down.
    n.create_notification("u1", "meeting_ready", "Ready", dedup_key="ready:1")

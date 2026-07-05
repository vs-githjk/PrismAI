"""Tests for the calendar tool's attendee-placeholder guard."""

from tools.calendar import _split_attendees


def test_split_attendees_rejects_placeholder_domains():
    valid, rejected = _split_attendees(["real@gmail.com", "adithya@example.com"])
    assert valid == ["real@gmail.com"]
    assert rejected == ["adithya@example.com"]


def test_split_attendees_rejects_malformed():
    valid, rejected = _split_attendees(["adithya", "  ", "ok@company.io"])
    assert valid == ["ok@company.io"]
    assert rejected == ["adithya"]


def test_split_attendees_all_valid():
    valid, rejected = _split_attendees(["a@b.com", "c@d.org"])
    assert valid == ["a@b.com", "c@d.org"]
    assert rejected == []


def test_split_attendees_empty():
    assert _split_attendees([]) == ([], [])

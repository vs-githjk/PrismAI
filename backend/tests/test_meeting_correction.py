"""Meeting text-correction tool (tools/meeting_edit) — the chat surface that fixes
a mis-transcribed term across a saved meeting's title / summary / analysis /
transcript, and feeds the corrected spelling into the keyterm glossary."""
import re
import asyncio

import tools.meeting_edit as me
from tools.registry import get_available_tools, _TOOLS


# ── pure recursive replace ────────────────────────────────────────────────────
def test_replace_in_nested_structure():
    pat = re.compile(re.escape("MD Academy"), re.IGNORECASE)
    obj = {
        "summary": "MD Academy is expanding. Visit md academy soon.",
        "action_items": [{"task": "Rename MD Academy product", "owner": "Vidyut"}],
        "score": 87,
        "topics": ["MD Academy roadmap", "hiring"],
    }
    new, n = me._replace_in(obj, pat, "FDE Academy")
    assert n == 4  # summary(2) + action task(1) + topic(1)
    assert "MD Academy" not in new["summary"]
    assert new["summary"].count("FDE Academy") == 2
    assert new["action_items"][0]["task"] == "Rename FDE Academy product"
    assert new["action_items"][0]["owner"] == "Vidyut"  # untouched
    assert new["score"] == 87  # non-strings untouched
    assert new["topics"][0] == "FDE Academy roadmap"


# ── a fake supabase that records the update ──────────────────────────────────
class _FakeQuery:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._filters = {}
        self._payload = None
        self._op = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._store.setdefault("upserts", []).append(payload)
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def in_(self, k, v):
        self._filters[k] = v
        return self

    def limit(self, *_a):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._op == "update":
            self._store["updated"] = self._payload
            return type("R", (), {"data": [{"id": 1}]})()
        if self._op == "upsert":
            return type("R", (), {"data": []})()
        # select
        return type("R", (), {"data": self._store.get("row")})()


class _FakeSupabase:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _FakeQuery(self._store, name)


def _run(coro):
    return asyncio.run(coro)


def test_correction_replaces_and_persists(monkeypatch):
    store = {"row": {
        "result": {"summary": "MD Academy pitch went well."},
        "transcript": "Vidyut: MD Academy is the plan.",
        "title": "MD Academy sync",
        "workspace_id": "ws-1",
    }}
    monkeypatch.setattr(me, "supabase", _FakeSupabase(store))
    out = _run(me.apply_correction("u1", 1, "MD Academy", "FDE Academy"))
    assert out["success"] and out["replacements"] == 3
    assert out["meeting_updated"] is True
    # persisted payload has every field corrected
    up = store["updated"]
    assert "MD Academy" not in up["result"]["summary"]
    assert "MD Academy" not in up["transcript"]
    assert up["title"] == "FDE Academy sync"
    # corrected term stored to the glossary under the meeting's workspace
    assert store["upserts"][-1] == {"user_id": "u1", "workspace_id": "ws-1", "term": "FDE Academy"}


def test_correction_case_insensitive():
    pat = re.compile(re.escape("raghav"), re.IGNORECASE)
    new, n = me._replace_in("Meet Raghav and RAGHAV.", pat, "Raghav Gupta")
    assert n == 2 and new == "Meet Raghav Gupta and Raghav Gupta."


def test_correction_no_match_is_safe(monkeypatch):
    store = {"row": {"result": {"summary": "Nothing to see."}, "transcript": "", "title": "Sync", "workspace_id": ""}}
    monkeypatch.setattr(me, "supabase", _FakeSupabase(store))
    out = _run(me.apply_correction("u1", 1, "MD Academy", "FDE Academy"))
    assert out["success"] and out["replacements"] == 0
    assert "updated" not in store  # nothing persisted when nothing changed


def test_correction_guards():
    assert "error" in _run(me.apply_correction("", 1, "a", "b"))        # no user
    assert "error" in _run(me.apply_correction("u1", None, "a", "b"))   # no meeting
    assert "error" in _run(me.apply_correction("u1", 1, "", "b"))       # empty find
    assert "error" in _run(me.apply_correction("u1", 1, "same", "SAME"))  # identical


def test_tool_registered_and_gated_on_meeting_id():
    assert "correct_meeting_text" in _TOOLS
    # Not offered without a meeting in context (live bot / global chat)...
    names = {t["function"]["name"] for t in get_available_tools({})}
    assert "correct_meeting_text" not in names
    # ...offered on an authenticated per-meeting chat.
    names2 = {t["function"]["name"] for t in get_available_tools({"_meeting_id": 42})}
    assert "correct_meeting_text" in names2


def test_tool_return_strips_heavy_payload(monkeypatch):
    store = {"row": {
        "result": {"summary": "MD Academy."}, "transcript": "MD Academy.",
        "title": "MD Academy", "workspace_id": "",
    }}
    monkeypatch.setattr(me, "supabase", _FakeSupabase(store))
    out = _run(me.correct_meeting_text({"find": "MD Academy", "replace": "FDE Academy"},
                                       user_settings={"user_id": "u1", "_meeting_id": 1}))
    # LLM-visible result stays small — no full result/transcript echoed back
    assert "result" not in out and "transcript" not in out
    assert out["meeting_updated"] is True and out["replacements"] == 3

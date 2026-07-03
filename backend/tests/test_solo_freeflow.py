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
    # Branded display name + stand-in display name are still our bot, not a human.
    assert rr._looks_like_bot_participant("PrismAI Notetaker", {}) is True
    assert rr._looks_like_bot_participant("Jane Doe (PrismAI stand-in)", {}) is True
    assert rr._looks_like_bot_participant("Alice", {}) is False


def test_leave_command_regex():
    assert rr._LEAVE_CMD_RE.match("/leave")
    assert rr._LEAVE_CMD_RE.match("/leave Prism")
    assert rr._LEAVE_CMD_RE.match("  /LEAVE  ")
    assert not rr._LEAVE_CMD_RE.match("please leave")
    assert not rr._LEAVE_CMD_RE.match("leave a note")


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


# ── bot-utterance recording (so the saved transcript shows the dialogue) ──────
def test_record_bot_line_writes_durable_and_buffer():
    import recall_routes as rc

    bot_id = "test-bot-record"
    rr.bot_store[bot_id] = {"realtime_transcript_lines": []}
    state = {"transcript_buffer": []}
    try:
        rr._record_bot_line(bot_id, state, "Here's the summary.", "Flash")
        # Live-memory buffer + durable transcript both get the persona-named line.
        assert state["transcript_buffer"] == ["Flash: Here's the summary."]
        assert rr.bot_store[bot_id]["realtime_transcript_lines"] == ["Flash: Here's the summary."]
        # The recall-side detector recognizes it as a bot turn.
        assert rr.bot_store[bot_id]["realtime_transcript_lines"][0].startswith(rc._BOT_NAME_PREFIXES)
    finally:
        rr.bot_store.pop(bot_id, None)


def test_record_bot_line_ignores_empty():
    bot_id = "test-bot-empty"
    rr.bot_store[bot_id] = {"realtime_transcript_lines": []}
    state = {"transcript_buffer": []}
    try:
        rr._record_bot_line(bot_id, state, "   ", "Prism")
        assert state["transcript_buffer"] == []
        assert rr.bot_store[bot_id]["realtime_transcript_lines"] == []
    finally:
        rr.bot_store.pop(bot_id, None)


def test_human_only_lines_not_flagged_as_bot():
    import recall_routes as rc

    lines = ["Alice: hello there", "Bob: what's the plan"]
    assert not any(ln.startswith(rc._BOT_NAME_PREFIXES) for ln in lines)


# ── stand-in spoken-on-request (Feature A3) ───────────────────────────────────
def test_standin_query_regex_matches():
    for q in [
        "any updates from people who couldn't make it",
        "who is out today",
        "who's away",
        "any async updates",
        "stand-in updates please",
        "updates from the team who couldn't attend",
    ]:
        assert rr._STANDIN_QUERY_RE.search(q), q


def test_standin_query_regex_ignores_unrelated():
    assert not rr._STANDIN_QUERY_RE.search("what time is the launch")
    assert not rr._STANDIN_QUERY_RE.search("summarize the meeting")


def test_standin_spoken_summary_single_and_multi():
    s1 = rr._standin_spoken_summary([{"name": "Alice", "body": "Finished the API."}])
    assert "Alice" in s1 and "Finished the API." in s1
    s2 = rr._standin_spoken_summary([
        {"name": "Alice", "body": "Did X."}, {"name": "Bob", "body": "Did Y."},
    ])
    assert "Alice says: Did X." in s2 and "Bob says: Did Y." in s2
    assert rr._standin_spoken_summary([]) == ""

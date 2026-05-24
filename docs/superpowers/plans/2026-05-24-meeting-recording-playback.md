# Meeting Recording Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let workspace members watch and scrub through any Recall.ai bot-joined meeting after it ends, with a clickable transcript synced to the video.

**Architecture:** Opt the Recall.ai bot into `video_mixed_mp4` + `audio_mixed_mp3` recording outputs. Persist a canonical `Segment[]` (per-line timestamps) on the meeting row at save time, copied server-side from `bot_sessions` (the trust boundary). Add a new on-demand `GET /meetings/{id}/recording` endpoint that pulls a fresh signed download URL from Recall on every call (signed URLs expire ~24h, can't denormalize). Frontend `<RecordingPlayer />` consumes both and renders a synced clickable transcript or audio fallback or graceful-unavailable state.

**Tech Stack:** Python 3 / FastAPI (backend), React 18 / Vite (frontend), Supabase Postgres (storage), Recall.ai (recording provider), httpx (Recall API client), pytest + unittest (backend tests). No frontend test framework — frontend gets a manual smoke checklist.

**Spec:** [docs/specs/2026-05-24-meeting-recording-playback-design.md](../../specs/2026-05-24-meeting-recording-playback-design.md)

---

## File Structure

### Created

- `supabase/recording_migration.sql` — three nullable columns on `meetings` + one on `bot_sessions` + one partial index.
- `frontend/src/components/dashboard/RecordingPlayer.jsx` — new component, owns the fetch lifecycle, polling, transcript sync, and per-reason error UI.
- `backend/tests/test_recording.py` — unit tests for `_segments_from_recall_data`, `parse_expires_hint`, and the GET endpoint's reason mapping + auth + trust boundary.

### Modified

- `backend/recall_routes.py` — add `video_mixed_mp4` + `audio_mixed_mp3` to bot creation; add `_segments_from_recall_data` helper next to `_transcript_from_recall_data`; save structured segments to `bot_sessions` in `_process_bot_transcript`.
- `backend/storage_routes.py` — extend `MeetingEntry` with `recall_bot_id`; server-side enrichment in `save_meeting`; extend `_fan_out_to_workspace` to include the three new columns; add the new `GET /meetings/{id}/recording` route + the `parse_expires_hint` helper.
- `backend/tests/test_storage_routes.py` (if it exists) or add a focused fan-out test inside `test_recording.py` — assert teammate rows carry the three new fields.
- `frontend/src/components/dashboard/MeetingView.jsx` — mount `<RecordingPlayer />` above the existing transcript disclosure.

### Touched but no logic change

- `backend/main.py` — no change (recall_router and storage_router are already registered; the new route is on `storage_router`).

---

## Task 1: Database migration

**Files:**
- Create: `supabase/recording_migration.sql`

- [ ] **Step 1: Write the migration file**

Create `supabase/recording_migration.sql` with this content:

```sql
-- Meeting Recording Playback — adds Recall.ai recording metadata to meetings
-- and a server-trust staging column on bot_sessions for transcript segments.
-- Run in the Supabase SQL editor AFTER all previous workspace + knowledge migrations.
-- Idempotent: safe to re-run.

alter table meetings
  add column if not exists recall_bot_id text,
  add column if not exists recording_provider text,         -- 'recall' | future: 'supabase'
  add column if not exists transcript_segments jsonb;       -- Segment[] | null

alter table bot_sessions
  add column if not exists transcript_segments jsonb;       -- staging area, server-pulled at save time

create index if not exists meetings_recall_bot_id_idx
  on meetings(recall_bot_id) where recall_bot_id is not null;
```

- [ ] **Step 2: Run the migration in Supabase**

Open the Supabase SQL editor for the project, paste the file's contents, click Run. Verify success in the response panel (no error rows).

- [ ] **Step 3: Verify the columns exist**

In the same SQL editor, run:

```sql
select column_name, data_type from information_schema.columns
where table_name = 'meetings' and column_name in ('recall_bot_id', 'recording_provider', 'transcript_segments');
select column_name, data_type from information_schema.columns
where table_name = 'bot_sessions' and column_name = 'transcript_segments';
```

Expected: three rows from the first query, one row from the second.

- [ ] **Step 4: Commit**

```bash
git add supabase/recording_migration.sql
git commit -m "Add recording_migration.sql for Recall playback columns"
```

---

## Task 2: `_segments_from_recall_data` helper (TDD)

**Files:**
- Modify: `backend/recall_routes.py` (add helper next to `_transcript_from_recall_data` at line 394)
- Create: `backend/tests/test_recording.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_recording.py`:

```python
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Stub supabase/groq so recall_routes imports cleanly in tests
fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

fake_groq_module = types.ModuleType("groq")
class _FakeAsyncGroq:
    def __init__(self, *a, **k): pass
fake_groq_module.AsyncGroq = _FakeAsyncGroq
sys.modules.setdefault("groq", fake_groq_module)

from recall_routes import _segments_from_recall_data


class TestSegmentsFromRecallData(unittest.TestCase):
    def test_streaming_provider_shape_with_words(self):
        raw = [
            {
                "speaker": "Alice",
                "words": [
                    {"text": "Hello", "start_time": 0.5, "end_time": 1.0},
                    {"text": "world", "start_time": 1.1, "end_time": 1.6},
                ],
            },
            {
                "speaker": "Bob",
                "words": [
                    {"text": "Hi", "start_time": 2.0, "end_time": 2.3},
                ],
            },
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [
            {"speaker": "Alice", "start": 0.5, "end": 1.6, "text": "Hello world"},
            {"speaker": "Bob", "start": 2.0, "end": 2.3, "text": "Hi"},
        ])

    def test_skips_segments_with_no_words(self):
        raw = [
            {"speaker": "Alice", "words": []},
            {"speaker": "Bob", "words": [{"text": "ok", "start_time": 1.0, "end_time": 1.2}]},
        ]
        segments = _segments_from_recall_data(raw)
        self.assertEqual(segments, [{"speaker": "Bob", "start": 1.0, "end": 1.2, "text": "ok"}])

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(_segments_from_recall_data([]))

    def test_returns_none_for_non_list_input(self):
        self.assertIsNone(_segments_from_recall_data({"transcript": "blob"}))
        self.assertIsNone(_segments_from_recall_data("plain string"))
        self.assertIsNone(_segments_from_recall_data(None))

    def test_uses_participant_name_when_speaker_missing(self):
        raw = [{
            "participant": {"name": "Carol"},
            "words": [{"text": "yo", "start_time": 0.1, "end_time": 0.3}],
        }]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Carol", "start": 0.1, "end": 0.3, "text": "yo"},
        ])

    def test_falls_back_to_unknown_speaker_label(self):
        raw = [{"words": [{"text": "hi", "start_time": 0.0, "end_time": 0.2}]}]
        self.assertEqual(_segments_from_recall_data(raw), [
            {"speaker": "Speaker", "start": 0.0, "end": 0.2, "text": "hi"},
        ])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: `ImportError: cannot import name '_segments_from_recall_data' from 'recall_routes'`.

- [ ] **Step 3: Add the helper in recall_routes.py**

Insert this function in `backend/recall_routes.py` immediately after `_transcript_from_recall_data` (which ends around line 425):

```python
def _segments_from_recall_data(raw) -> list[dict] | None:
    """Normalize Recall's transcript response into Segment[] for video playback sync.

    Returns None when input is empty, missing word-level timestamps, or not a list
    (e.g., legacy { "transcript": "blob" } responses, plain string fallbacks).
    None is the sentinel for "no per-line timing available" — the realtime-buffer
    fallback transcript path also returns None so the player degrades to a plain
    transcript view.
    """
    if not isinstance(raw, list) or not raw:
        return None
    segments: list[dict] = []
    for segment in raw:
        words = segment.get("words") or []
        if not words:
            continue
        speaker = (
            segment.get("speaker")
            or (segment.get("participant") or {}).get("name")
            or "Speaker"
        )
        text = " ".join(w.get("text", "") for w in words).strip()
        if not text:
            continue
        segments.append({
            "speaker": speaker,
            "start": words[0].get("start_time", 0.0),
            "end": words[-1].get("end_time", 0.0),
            "text": text,
        })
    return segments or None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/recall_routes.py backend/tests/test_recording.py
git commit -m "Add _segments_from_recall_data helper for transcript-video sync"
```

---

## Task 3: Save segments in `_process_bot_transcript`

**Files:**
- Modify: `backend/recall_routes.py` (lines ~428–479, the `_process_bot_transcript` function)

- [ ] **Step 1: Add a test for the bot_sessions save path**

Append this test class to `backend/tests/test_recording.py`:

```python
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock


class TestProcessBotTranscriptSavesSegments(unittest.TestCase):
    def test_saves_segments_to_bot_sessions_on_success(self):
        import recall_routes
        recall_routes.bot_store["bot-xyz"] = {
            "status": "processing", "result": None, "error": None,
            "commands": [], "user_id": "user-1",
        }

        # Mock _fetch_transcript to return a response with structured segments
        fake_response = MagicMock()
        fake_response.json.return_value = [
            {"speaker": "Alice", "words": [
                {"text": "hi", "start_time": 0.0, "end_time": 0.3},
            ]},
        ]

        # Capture _db_save calls
        saved_fields: list[dict] = []
        def fake_db_save(bot_id, fields):
            saved_fields.append(fields)

        async def fake_run_full_analysis(_t):
            return {"summary": "ok"}

        with patch.object(recall_routes, "_fetch_transcript", AsyncMock(return_value=fake_response)), \
             patch.object(recall_routes, "_db_save", side_effect=fake_db_save), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "run_full_analysis", side_effect=fake_run_full_analysis), \
             patch.object(recall_routes, "build_analysis_transcript", side_effect=lambda t, owner_name=None: t), \
             patch("realtime_routes.cleanup_bot_state"):
            asyncio.run(recall_routes._process_bot_transcript("bot-xyz"))

        # Find the final "done" save and confirm segments were included
        done_save = next((f for f in saved_fields if f.get("status") == "done"), None)
        self.assertIsNotNone(done_save, "expected a status=done _db_save call")
        self.assertIn("transcript_segments", done_save)
        self.assertEqual(done_save["transcript_segments"], [
            {"speaker": "Alice", "start": 0.0, "end": 0.3, "text": "hi"},
        ])

    def test_segments_null_when_realtime_buffer_fallback_used(self):
        import recall_routes
        recall_routes.bot_store["bot-fb"] = {
            "status": "processing", "result": None, "error": None,
            "commands": [], "user_id": "user-1",
            "realtime_transcript_lines": ["Alice: from buffer"],
        }

        # _fetch_transcript returns None → triggers realtime-buffer fallback
        saved_fields: list[dict] = []
        async def fake_run_full_analysis(_t):
            return {"summary": "ok"}

        with patch.object(recall_routes, "_fetch_transcript", AsyncMock(return_value=None)), \
             patch.object(recall_routes, "_db_save", side_effect=lambda b, f: saved_fields.append(f)), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "run_full_analysis", side_effect=fake_run_full_analysis), \
             patch.object(recall_routes, "build_analysis_transcript", side_effect=lambda t, owner_name=None: t), \
             patch("realtime_routes.cleanup_bot_state"):
            asyncio.run(recall_routes._process_bot_transcript("bot-fb"))

        done_save = next((f for f in saved_fields if f.get("status") == "done"), None)
        self.assertIsNotNone(done_save)
        self.assertIsNone(done_save.get("transcript_segments"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_recording.py::TestProcessBotTranscriptSavesSegments -v
```

Expected: `AssertionError: 'transcript_segments' not found` on the first test (we haven't wired it yet).

- [ ] **Step 3: Modify `_process_bot_transcript` to compute and persist segments**

In `backend/recall_routes.py`, locate `_process_bot_transcript` (starts around line 428). Replace the body section from after `if resp is not None:` through the final `_db_save(...)` call with this revised version:

Find this block (around lines 437–467):

```python
        transcript = ""
        if resp is not None:
            raw = resp.json()
            print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:500]}")
            transcript = _transcript_from_recall_data(raw)

        # Fallback: use realtime-streamed transcript lines accumulated during the meeting
        if not transcript.strip():
            rt_lines = bot_store.get(bot_id, {}).get("realtime_transcript_lines") or []
            if rt_lines:
                transcript = "\n".join(rt_lines)
                print(f"[recall] using realtime transcript buffer: {len(rt_lines)} lines, {len(transcript)} chars")
```

And replace with:

```python
        transcript = ""
        segments: list[dict] | None = None
        if resp is not None:
            raw = resp.json()
            print(f"[recall] transcript raw type={type(raw).__name__} len={len(raw) if isinstance(raw, (list, dict)) else 'n/a'} preview={str(raw)[:500]}")
            transcript = _transcript_from_recall_data(raw)
            segments = _segments_from_recall_data(raw)

        # Fallback: use realtime-streamed transcript lines accumulated during the meeting.
        # Segments stay None here — the live buffer has no global timestamps, so the player
        # gracefully degrades to a plain transcript view for these meetings.
        if not transcript.strip():
            rt_lines = bot_store.get(bot_id, {}).get("realtime_transcript_lines") or []
            if rt_lines:
                transcript = "\n".join(rt_lines)
                print(f"[recall] using realtime transcript buffer: {len(rt_lines)} lines, {len(transcript)} chars")
```

Then locate the final success-path `_db_save` call (around line 465):

```python
        _db_save(bot_id, {"status": "done", "transcript": transcript, "result": result})
```

Replace with:

```python
        bot_store[bot_id]["transcript_segments"] = segments
        _db_save(bot_id, {
            "status": "done",
            "transcript": transcript,
            "result": result,
            "transcript_segments": segments,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: all tests pass (8 total now).

- [ ] **Step 5: Commit**

```bash
git add backend/recall_routes.py backend/tests/test_recording.py
git commit -m "Persist transcript_segments to bot_sessions in _process_bot_transcript"
```

---

## Task 4: Add video + audio recording config to `join_meeting`

**Files:**
- Modify: `backend/recall_routes.py` (the `recording_config` dict inside `join_meeting`, around lines 534–571)

> **Pre-merge verification:** Recall has rotated this schema once before. Before merging this PR, the implementing engineer must:
> 1. Confirm `video_mixed_mp4` and `audio_mixed_mp3` are still the current top-level keys inside `recording_config` (check https://docs.recall.ai/reference/bot_create).
> 2. Confirm the Recall account is on Pro tier or above (video output is plan-gated; Starter returns 400).
> 3. Manually launch a real bot in a test meeting with the new config and confirm it joins successfully.

- [ ] **Step 1: Modify the `recording_config` payload**

In `backend/recall_routes.py`, find the `recording_config` dict inside the `client.post(f"{RECALL_API_BASE}/bot/", ...)` call (starts around line 534):

```python
                "recording_config": {
                    "transcript": {
                        "provider": {
                            ...
                        }
                    },
                    "realtime_endpoints": [
                        ...
                    ],
                },
```

Replace with:

```python
                "recording_config": {
                    # Video output — required for post-meeting playback.
                    # speaker_view composites the active speaker as the main pane;
                    # gallery_view is the multi-tile alternative.
                    "video_mixed_layout": "speaker_view",
                    "video_mixed_mp4": {},
                    # Always-on audio fallback — used by the player when no video
                    # is captured (phone bridges, screenshare-disabled meetings).
                    "audio_mixed_mp3": {},
                    "transcript": {
                        "provider": {
                            ...  # KEEP existing deepgram_streaming config exactly as-is
                        }
                    },
                    "realtime_endpoints": [
                        ...  # KEEP existing realtime_endpoints exactly as-is
                    ],
                },
```

Important: do NOT remove or alter the existing `transcript` and `realtime_endpoints` blocks. Only ADD the three new sibling keys: `video_mixed_layout`, `video_mixed_mp4`, `audio_mixed_mp3`.

- [ ] **Step 2: Run existing tests to confirm no regression**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests pass. None of the existing tests assert on `recording_config` shape, so adding keys is non-breaking.

- [ ] **Step 3: Commit**

```bash
git add backend/recall_routes.py
git commit -m "Opt Recall bot into video_mixed_mp4 + audio_mixed_mp3 outputs"
```

---

## Task 5: Extend `MeetingEntry` + server-side enrichment in `save_meeting`

**Files:**
- Modify: `backend/storage_routes.py` (`MeetingEntry` model at line 29, `save_meeting` at line 212)

- [ ] **Step 1: Write the failing test for trust boundary**

Append to `backend/tests/test_recording.py`:

```python
class TestSaveMeetingEnrichment(unittest.TestCase):
    def _make_client(self, bot_session_row: dict | None):
        """Build a fake supabase client that returns a specific bot_sessions row."""
        captured_upserts: list[dict] = []

        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def neq(self, *a, **k): return self
            def maybe_single(self): return self
            def upsert(self, payload, **k):
                captured_upserts.append({"table": self.name, "payload": payload})
                class _Exec:
                    def execute(_): return MagicMock(data=[])
                return _Exec()
            def execute(self):
                if self.name == "bot_sessions":
                    return MagicMock(data=bot_session_row)
                if self.name == "workspace_members":
                    return MagicMock(data=[])
                return MagicMock(data=[])

        client = MagicMock()
        client.table = lambda name: FakeTable(name)
        client.upserts = captured_upserts
        return client

    def test_enriches_meeting_row_when_caller_owns_bot(self):
        import storage_routes
        client = self._make_client({
            "bot_id": "bot-A", "user_id": "user-1",
            "transcript_segments": [{"speaker": "A", "start": 0, "end": 1, "text": "hi"}],
        })
        entry = storage_routes.MeetingEntry(
            id=42, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={}, recall_bot_id="bot-A",
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertEqual(meetings_upsert["payload"].get("recall_bot_id"), "bot-A")
        self.assertEqual(meetings_upsert["payload"].get("recording_provider"), "recall")
        self.assertEqual(meetings_upsert["payload"].get("transcript_segments"),
                         [{"speaker": "A", "start": 0, "end": 1, "text": "hi"}])

    def test_writes_nulls_when_caller_does_not_own_bot(self):
        import storage_routes
        # Bot exists but belongs to user-2; caller is user-1
        client = self._make_client({
            "bot_id": "bot-B", "user_id": "user-2",
            "transcript_segments": [{"speaker": "X", "start": 0, "end": 1, "text": "secret"}],
        })
        entry = storage_routes.MeetingEntry(
            id=43, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={}, recall_bot_id="bot-B",
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            # Save must SUCCEED (no 403)
            result = asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
            self.assertEqual(result, {"ok": True})
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertIsNone(meetings_upsert["payload"].get("recall_bot_id"))
        self.assertIsNone(meetings_upsert["payload"].get("recording_provider"))
        self.assertIsNone(meetings_upsert["payload"].get("transcript_segments"))

    def test_writes_nulls_when_no_recall_bot_id_provided(self):
        import storage_routes
        client = self._make_client(None)
        entry = storage_routes.MeetingEntry(
            id=44, date="2026-05-24T10:00:00Z", title="t", transcript="",
            result={},
        )
        with patch.object(storage_routes, "_require_storage", return_value=client):
            asyncio.run(storage_routes.save_meeting(entry, user_id="user-1"))
        meetings_upsert = next(u for u in client.upserts if u["table"] == "meetings")
        self.assertIsNone(meetings_upsert["payload"].get("recall_bot_id"))
        self.assertIsNone(meetings_upsert["payload"].get("recording_provider"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_recording.py::TestSaveMeetingEnrichment -v
```

Expected: `pydantic.ValidationError` on `recall_bot_id` (not yet a valid field) or `KeyError` on the assertion.

- [ ] **Step 3: Add `recall_bot_id` to `MeetingEntry`**

In `backend/storage_routes.py`, find `MeetingEntry` (line 29):

```python
class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int | None = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""
    workspace_id: str | None = None
    recorded_by_user_id: str | None = None
```

Replace with:

```python
class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int | None = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""
    workspace_id: str | None = None
    recorded_by_user_id: str | None = None
    recall_bot_id: str | None = None
```

- [ ] **Step 4: Add enrichment logic and updated upsert in `save_meeting`**

Find `save_meeting` (line 212) and its upsert (line 215):

```python
@router.post("/meetings")
async def save_meeting(entry: MeetingEntry, user_id: str = Depends(require_user_id)):
    client = _require_storage()
    client.table("meetings").upsert({
        "id": entry.id,
        "user_id": user_id,
        "date": entry.date,
        "title": entry.title,
        "score": entry.score,
        "transcript": entry.transcript,
        "result": entry.result,
        "share_token": entry.share_token or None,
        "workspace_id": entry.workspace_id or None,
        "recorded_by_user_id": entry.recorded_by_user_id or None,
    }).execute()
```

Replace with:

```python
@router.post("/meetings")
async def save_meeting(entry: MeetingEntry, user_id: str = Depends(require_user_id)):
    client = _require_storage()

    # Server-side enrichment from bot_sessions — the trust boundary.
    # The frontend sends recall_bot_id as a reference; we look up the structured
    # transcript segments server-side and only attach them if the caller owns the
    # bot. If they don't own it (stale local state, bad client), the save still
    # succeeds with nulls instead of 403 — silent degradation preserves UX.
    recall_bot_id = entry.recall_bot_id or None
    recording_provider: str | None = None
    transcript_segments = None
    if recall_bot_id:
        try:
            bs = (
                client.table("bot_sessions")
                .select("user_id, transcript_segments")
                .eq("bot_id", recall_bot_id)
                .maybe_single()
                .execute()
            )
            row = bs.data if bs else None
            if row and row.get("user_id") == user_id:
                recording_provider = "recall"
                transcript_segments = row.get("transcript_segments")
            else:
                # Caller doesn't own this bot — drop the reference rather than 403
                recall_bot_id = None
        except Exception as exc:
            print(f"[storage] bot_sessions lookup failed for {recall_bot_id}: {exc}")
            recall_bot_id = None

    # Mutate the entry so _fan_out_to_workspace (called below) sees the same
    # resolved values — it uses these to populate teammate rows in Task 6.
    entry.recall_bot_id = recall_bot_id
    entry.__dict__["_resolved_segments"] = transcript_segments
    entry.__dict__["_resolved_provider"] = recording_provider

    client.table("meetings").upsert({
        "id": entry.id,
        "user_id": user_id,
        "date": entry.date,
        "title": entry.title,
        "score": entry.score,
        "transcript": entry.transcript,
        "result": entry.result,
        "share_token": entry.share_token or None,
        "workspace_id": entry.workspace_id or None,
        "recorded_by_user_id": entry.recorded_by_user_id or None,
        "recall_bot_id": recall_bot_id,
        "recording_provider": recording_provider,
        "transcript_segments": transcript_segments,
    }).execute()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: all `TestSaveMeetingEnrichment` tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/storage_routes.py backend/tests/test_recording.py
git commit -m "Enrich meeting rows with recall_bot_id + segments at save time (server-side)"
```

---

## Task 6: Propagate new columns through workspace fan-out

**Files:**
- Modify: `backend/storage_routes.py` (`_fan_out_to_workspace` upsert at line 195)

- [ ] **Step 1: Add the fan-out propagation test**

Append to `backend/tests/test_recording.py`:

```python
class TestFanOutPropagatesRecordingFields(unittest.TestCase):
    def test_fan_out_includes_recall_columns(self):
        import storage_routes
        captured_upserts: list[dict] = []

        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def neq(self, *a, **k): return self
            def upsert(self, payload, **k):
                captured_upserts.append({"table": self.name, "payload": payload})
                class _Exec:
                    def execute(_): return MagicMock(data=[])
                return _Exec()
            def execute(self):
                if self.name == "workspace_members":
                    return MagicMock(data=[{"user_id": "teammate-1"}, {"user_id": "teammate-2"}])
                return MagicMock(data=[])

        client = MagicMock()
        client.table = lambda name: FakeTable(name)

        entry = storage_routes.MeetingEntry(
            id=100, date="2026-05-24T10:00:00Z", title="shared",
            transcript="t", result={"summary": "s"},
            workspace_id="ws-1", recall_bot_id="bot-shared",
        )

        asyncio.run(storage_routes._fan_out_to_workspace(
            client, entry, recorder_user_id="owner-1", workspace_id="ws-1",
        ))

        fan_payloads = [u["payload"] for u in captured_upserts if u["table"] == "meetings"]
        self.assertEqual(len(fan_payloads), 2, "expected one upsert per teammate")
        for p in fan_payloads:
            self.assertIn("recall_bot_id", p)
            self.assertIn("recording_provider", p)
            self.assertIn("transcript_segments", p)
            self.assertEqual(p.get("recall_bot_id"), "bot-shared")
            self.assertEqual(p.get("recording_provider"), "recall")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && python -m pytest tests/test_recording.py::TestFanOutPropagatesRecordingFields -v
```

Expected: `KeyError` on `recall_bot_id` — the fan-out upsert does not yet include the new fields.

- [ ] **Step 3: Update `_fan_out_to_workspace` to propagate the new fields**

In `backend/storage_routes.py`, find `_fan_out_to_workspace` (line 182). The current upsert payload (lines 195–206):

```python
            client.table("meetings").upsert({
                "id": fan_id,
                "user_id": member_id,
                "date": entry.date,
                "title": entry.title,
                "score": entry.score,
                "transcript": entry.transcript,
                "result": entry.result,
                "share_token": None,
                "workspace_id": workspace_id,
                "recorded_by_user_id": recorder_user_id,
            }).execute()
```

Replace with:

```python
            client.table("meetings").upsert({
                "id": fan_id,
                "user_id": member_id,
                "date": entry.date,
                "title": entry.title,
                "score": entry.score,
                "transcript": entry.transcript,
                "result": entry.result,
                "share_token": None,
                "workspace_id": workspace_id,
                "recorded_by_user_id": recorder_user_id,
                # Recording fields propagate so every teammate sees the same player.
                # The owner-only segments are safe to fan out: workspace_members are
                # the access boundary, and the player auth already gates by membership.
                # _resolved_segments / _resolved_provider are set by save_meeting in Task 5.
                # When the test calls _fan_out_to_workspace directly (no save_meeting
                # pre-call), these fall back to entry.recall_bot_id / "recall" — same
                # final shape, no behaviour change.
                "recall_bot_id": entry.recall_bot_id,
                "recording_provider": entry.__dict__.get("_resolved_provider")
                                       or ("recall" if entry.recall_bot_id else None),
                "transcript_segments": entry.__dict__.get("_resolved_segments"),
            }).execute()
```

No changes to `save_meeting` in this task — Task 5 step 4 already sets `_resolved_segments` and `_resolved_provider` on the entry.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: all tests pass including `TestFanOutPropagatesRecordingFields`.

- [ ] **Step 5: Commit**

```bash
git add backend/storage_routes.py backend/tests/test_recording.py
git commit -m "Propagate recording fields through workspace fan-out"
```

---

## Task 7: `parse_expires_hint` URL helper (TDD)

**Files:**
- Modify: `backend/storage_routes.py` (add helper above the route definitions, around line 175)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_recording.py`:

```python
class TestParseExpiresHint(unittest.TestCase):
    def test_returns_int_when_x_amz_expires_present(self):
        import storage_routes
        url = "https://example.s3.amazonaws.com/foo.mp4?X-Amz-Expires=3600&X-Amz-Signature=abc"
        self.assertEqual(storage_routes.parse_expires_hint(url), 3600)

    def test_returns_none_when_param_missing(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint("https://x.com/foo.mp4"))

    def test_returns_none_for_non_integer_value(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint(
            "https://x.com/foo.mp4?X-Amz-Expires=forever"
        ))

    def test_returns_none_for_empty_input(self):
        import storage_routes
        self.assertIsNone(storage_routes.parse_expires_hint(""))
        self.assertIsNone(storage_routes.parse_expires_hint(None))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_recording.py::TestParseExpiresHint -v
```

Expected: `AttributeError: module 'storage_routes' has no attribute 'parse_expires_hint'`.

- [ ] **Step 3: Add the helper in storage_routes.py**

In `backend/storage_routes.py`, add the import to the existing import block at the top of the file:

```python
from urllib.parse import urlparse, parse_qs
```

Then add this function definition above `router = APIRouter(tags=["storage"])` (around line 15):

```python
def parse_expires_hint(url: str | None) -> int | None:
    """Extract the X-Amz-Expires hint from an S3 presigned URL.

    Returns None when the param is missing, non-integer, or input is empty.
    The hint is approximate — clients should treat it as a cache TTL guide,
    not a precise countdown.
    """
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)
        value = qs.get("X-Amz-Expires", [None])[0]
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py::TestParseExpiresHint -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/storage_routes.py backend/tests/test_recording.py
git commit -m "Add parse_expires_hint helper for S3 presigned URL TTL extraction"
```

---

## Task 8: `GET /meetings/{id}/recording` endpoint

**Files:**
- Modify: `backend/storage_routes.py` (add new route + helper at the end of the file)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_recording.py`:

```python
class TestGetRecordingEndpoint(unittest.TestCase):
    def _make_client(self, meeting_row, workspace_member_rows=None):
        captured: list = []
        class FakeTable:
            def __init__(self, name): self.name = name
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def in_(self, *a, **k): return self
            def maybe_single(self): return self
            def execute(self):
                if self.name == "meetings":
                    return MagicMock(data=meeting_row)
                if self.name == "workspace_members":
                    return MagicMock(data=workspace_member_rows or [])
                return MagicMock(data=[])
        client = MagicMock()
        client.table = lambda name: FakeTable(name)
        return client

    def _fake_recall_response(self, recordings_payload, status_code=200):
        async def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = status_code
            resp.json = lambda: {"recordings": recordings_payload}
            return resp
        return fake_get

    def test_returns_video_url_when_video_mixed_present(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{
            "media_shortcuts": {
                "video_mixed": {"data": {"download_url": "https://s3/foo.mp4?X-Amz-Expires=86400"}},
                "audio_mixed": {"data": {"download_url": "https://s3/foo.mp3?X-Amz-Expires=86400"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "video")
        self.assertEqual(result["url"], "https://s3/foo.mp4?X-Amz-Expires=86400")
        self.assertEqual(result["expires_hint_seconds"], 86400)

    def test_falls_back_to_audio_when_only_audio_present(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{
            "media_shortcuts": {
                "audio_mixed": {"data": {"download_url": "https://s3/foo.mp3"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "audio")
        self.assertEqual(result["url"], "https://s3/foo.mp3")

    def test_returns_not_ready_when_recording_exists_but_no_urls(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        recordings = [{"media_shortcuts": {}}]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_ready"})

    def test_returns_no_recording_when_recordings_array_empty(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([])
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "no_recording"})

    def test_returns_expired_on_recall_404(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([], status_code=404)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "expired"})

    def test_returns_not_found_on_recall_403(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response([], status_code=403)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_found"})

    def test_returns_not_a_bot_meeting_when_recall_bot_id_null(self):
        import storage_routes
        client = self._make_client({
            "id": 1, "user_id": "user-1", "workspace_id": None,
            "recall_bot_id": None, "recording_provider": None,
        })
        with patch.object(storage_routes, "_require_storage", return_value=client):
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result, {"url": None, "reason": "not_a_bot_meeting"})

    def test_returns_404_when_caller_not_owner_or_workspace_member(self):
        from fastapi import HTTPException
        import storage_routes
        # Meeting owned by user-99, no workspace
        client = self._make_client({
            "id": 1, "user_id": "user-99", "workspace_id": None,
            "recall_bot_id": "bot-1", "recording_provider": "recall",
        })
        with patch.object(storage_routes, "_require_storage", return_value=client):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_workspace_member_can_access(self):
        import storage_routes
        # Meeting owned by user-99 in workspace ws-1; caller user-1 is a member
        client = self._make_client(
            {
                "id": 1, "user_id": "user-99", "workspace_id": "ws-1",
                "recall_bot_id": "bot-1", "recording_provider": "recall",
            },
            workspace_member_rows=[{"user_id": "user-1"}],
        )
        recordings = [{
            "media_shortcuts": {
                "video_mixed": {"data": {"download_url": "https://s3/v.mp4"}},
            }
        }]
        with patch.object(storage_routes, "_require_storage", return_value=client), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get = self._fake_recall_response(recordings)
            result = asyncio.run(storage_routes.get_meeting_recording(1, user_id="user-1"))
        self.assertEqual(result["kind"], "video")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_recording.py::TestGetRecordingEndpoint -v
```

Expected: `AttributeError: module 'storage_routes' has no attribute 'get_meeting_recording'`.

- [ ] **Step 3: Add the endpoint**

First, add these imports to the existing import block at the top of `backend/storage_routes.py`:

```python
import os
import httpx
```

Add these module-level constants near the other globals (around line 14, before `router = APIRouter(...)`):

```python
RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = os.getenv("RECALL_API_BASE", "https://us-west-2.recall.ai/api/v1")
```

Then append the helper and the new route at the BOTTOM of `backend/storage_routes.py`:

```python


def _caller_can_access_meeting(client, meeting_row: dict, user_id: str) -> bool:
    """Same auth model as GET /meetings/{id}: owner OR workspace member."""
    if meeting_row.get("user_id") == user_id:
        return True
    workspace_id = meeting_row.get("workspace_id")
    if not workspace_id:
        return False
    try:
        res = (
            client.table("workspace_members")
            .select("user_id")
            .eq("workspace_id", workspace_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return bool(res and res.data)
    except Exception:
        return False


@router.get("/meetings/{meeting_id}/recording")
async def get_meeting_recording(meeting_id: int, user_id: str = Depends(require_user_id)):
    """Return a fresh signed download URL for the meeting's Recall.ai recording.

    Auth: caller must own the meeting OR be a member of its workspace. Non-members
    get a 404 (we never confirm existence to non-members).

    Response shapes (see spec for full contract):
      { "url": "...", "expires_hint_seconds": N, "kind": "video" | "audio" }
      { "url": None, "reason": "not_ready" | "no_recording" | "expired" |
                               "not_found" | "not_a_bot_meeting" }
    """
    client = _require_storage()

    # Load meeting row
    try:
        res = (
            client.table("meetings")
            .select("id, user_id, workspace_id, recall_bot_id, recording_provider")
            .eq("id", meeting_id)
            .maybe_single()
            .execute()
        )
        meeting = res.data if res else None
    except Exception:
        meeting = None

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not _caller_can_access_meeting(client, meeting, user_id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    bot_id = meeting.get("recall_bot_id")
    if not bot_id:
        return {"url": None, "reason": "not_a_bot_meeting"}

    if not RECALL_API_KEY:
        raise HTTPException(status_code=503, detail="Recall.ai not configured")

    # Fetch fresh signed URL from Recall (URLs expire ~24h, can't cache)
    try:
        async with httpx.AsyncClient() as recall:
            resp = await recall.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=10,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Recall.ai unreachable: {exc}")

    if resp.status_code == 404:
        return {"url": None, "reason": "expired"}
    if resp.status_code == 403:
        return {"url": None, "reason": "not_found"}
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Recall.ai error: {resp.status_code}")

    data = resp.json()
    recordings = data.get("recordings") or []
    if not recordings:
        return {"url": None, "reason": "no_recording"}

    shortcuts = (recordings[0] or {}).get("media_shortcuts") or {}
    video_url = (
        ((shortcuts.get("video_mixed") or {}).get("data") or {}).get("download_url")
    )
    audio_url = (
        ((shortcuts.get("audio_mixed") or {}).get("data") or {}).get("download_url")
    )

    if video_url:
        payload = {"url": video_url, "kind": "video"}
        hint = parse_expires_hint(video_url)
        if hint is not None:
            payload["expires_hint_seconds"] = hint
        return payload
    if audio_url:
        payload = {"url": audio_url, "kind": "audio"}
        hint = parse_expires_hint(audio_url)
        if hint is not None:
            payload["expires_hint_seconds"] = hint
        return payload

    return {"url": None, "reason": "not_ready"}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_recording.py -v
```

Expected: all `TestGetRecordingEndpoint` tests pass (9 cases).

- [ ] **Step 5: Verify the route is registered**

The new route lives on `storage_router`, which is already included in `main.py` line 52. No `main.py` change needed. Verify by listing routes:

```bash
cd backend && python -c "from main import app; print([r.path for r in app.routes if 'recording' in r.path])"
```

Expected output: `['/meetings/{meeting_id}/recording']`.

- [ ] **Step 6: Commit**

```bash
git add backend/storage_routes.py backend/tests/test_recording.py
git commit -m "Add GET /meetings/{id}/recording with all documented reason codes"
```

---

## Task 9: Frontend — `RecordingPlayer.jsx` skeleton with fetch + states

**Files:**
- Create: `frontend/src/components/dashboard/RecordingPlayer.jsx`

No frontend test framework; verify via manual smoke after Task 12.

- [ ] **Step 1: Create the component file**

Create `frontend/src/components/dashboard/RecordingPlayer.jsx`:

```jsx
import { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../../lib/api'

const POLL_INTERVAL_MS = 15000
const POLL_MAX_ATTEMPTS = 20  // 15s * 20 = 5min

const REASON_COPY = {
  expired: "Recall.ai's retention window has passed.",
  not_found: 'The bot recording was deleted.',
  no_recording: 'No audio was captured during this meeting.',
  not_a_bot_meeting: null,  // handled by returning null
}

export default function RecordingPlayer({
  meetingId,
  recordingProvider,
  transcriptSegments,
  transcriptText,
}) {
  const [state, setState] = useState('loading')  // 'loading' | 'ready' | 'processing' | 'gone'
  const [media, setMedia] = useState(null)        // { url, kind } when ready
  const [reason, setReason] = useState(null)      // when state==='gone'
  const attemptsRef = useRef(0)
  const timeoutRef = useRef(null)
  const abortRef = useRef(null)

  // Non-bot meetings render nothing
  if (recordingProvider !== 'recall') return null

  useEffect(() => {
    let cancelled = false

    const fetchOnce = async () => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const res = await apiFetch(`/meetings/${meetingId}/recording`, { signal: controller.signal })
        if (cancelled) return
        const data = await res.json().catch(() => ({}))
        if (data.url) {
          setMedia({ url: data.url, kind: data.kind })
          setState('ready')
          return
        }
        if (data.reason === 'not_ready') {
          attemptsRef.current += 1
          if (attemptsRef.current >= POLL_MAX_ATTEMPTS) {
            setState('processing')
            setReason('cap_reached')
            return
          }
          setState('processing')
          timeoutRef.current = setTimeout(fetchOnce, POLL_INTERVAL_MS)
          return
        }
        if (data.reason === 'not_a_bot_meeting') {
          // Defensive — provider check above should have prevented this
          return
        }
        setReason(data.reason || 'not_found')
        setState('gone')
      } catch (err) {
        if (err?.name === 'AbortError' || cancelled) return
        setReason('not_found')
        setState('gone')
      }
    }

    fetchOnce()

    return () => {
      cancelled = true
      abortRef.current?.abort()
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [meetingId])

  if (state === 'loading') {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/60">
        Loading recording…
      </div>
    )
  }

  if (state === 'processing') {
    const copy = reason === 'cap_reached'
      ? 'Recording is taking longer than expected. Refresh the page to try again.'
      : 'Recording is still being prepared by Recall.ai. This usually takes 1–3 minutes after the meeting ends.'
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
        {copy}
      </div>
    )
  }

  if (state === 'gone') {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/70">
        <div className="font-medium text-white/90">Recording is no longer available</div>
        <div className="mt-1 text-white/50">{REASON_COPY[reason] || 'The recording could not be loaded.'}</div>
      </div>
    )
  }

  // state === 'ready'
  return (
    <SyncedPlayer
      url={media.url}
      kind={media.kind}
      segments={transcriptSegments}
      transcriptText={transcriptText}
    />
  )
}

// Stub; Task 10/11 expand this.
function SyncedPlayer({ url, kind, segments, transcriptText }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/40 p-4">
      {kind === 'audio' ? (
        <audio src={url} controls className="w-full" />
      ) : (
        <video src={url} controls className="w-full rounded-lg" />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify the file parses by running the dev server briefly**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no errors. (Don't run the dev server in this step — Task 13 covers mounting and end-to-end smoke.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/RecordingPlayer.jsx
git commit -m "Add RecordingPlayer skeleton with fetch lifecycle + per-reason error UI"
```

---

## Task 10: Synced clickable transcript with binary search + throttled timeupdate

**Files:**
- Modify: `frontend/src/components/dashboard/RecordingPlayer.jsx` (replace the `SyncedPlayer` stub)

- [ ] **Step 1: Replace the `SyncedPlayer` stub with the full implementation**

In `frontend/src/components/dashboard/RecordingPlayer.jsx`, remove the existing `SyncedPlayer` stub function and add at the bottom of the file:

```jsx
function SyncedPlayer({ url, kind, segments, transcriptText }) {
  const mediaRef = useRef(null)
  const [activeIdx, setActiveIdx] = useState(-1)
  const lastUpdateRef = useRef(0)
  const userScrolledAtRef = useRef(0)
  const activeRowRef = useRef(null)
  const listRef = useRef(null)

  const hasSegments = Array.isArray(segments) && segments.length > 0

  // Throttled onTimeUpdate handler — ~4Hz
  const handleTimeUpdate = () => {
    const now = performance.now()
    if (now - lastUpdateRef.current < 250) return
    lastUpdateRef.current = now
    const t = mediaRef.current?.currentTime ?? 0
    const idx = findSegmentIndex(segments, t)
    if (idx !== activeIdx) setActiveIdx(idx)
  }

  // Auto-scroll active row into view, but only if user hasn't scrolled in last 3s
  useEffect(() => {
    if (activeIdx < 0 || !activeRowRef.current) return
    const sinceUserScroll = performance.now() - userScrolledAtRef.current
    if (sinceUserScroll < 3000) return
    activeRowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeIdx])

  // User-scroll detector
  const noteUserScroll = () => {
    userScrolledAtRef.current = performance.now()
  }

  const seekTo = (seconds) => {
    if (!mediaRef.current) return
    mediaRef.current.currentTime = seconds
    mediaRef.current.play().catch(() => {})
  }

  return (
    <div className="grid gap-4 md:grid-cols-[3fr_2fr] rounded-2xl border border-white/10 bg-black/40 p-4">
      <div>
        {kind === 'audio' ? (
          <audio
            ref={mediaRef}
            src={url}
            controls
            className="w-full"
            onTimeUpdate={handleTimeUpdate}
          />
        ) : (
          <video
            ref={mediaRef}
            src={url}
            controls
            className="w-full rounded-lg"
            onTimeUpdate={handleTimeUpdate}
          />
        )}
      </div>
      <div
        ref={listRef}
        onWheel={noteUserScroll}
        onTouchMove={noteUserScroll}
        className="max-h-[420px] overflow-y-auto rounded-lg border border-white/5 bg-white/5 p-3"
      >
        {hasSegments ? (
          segments.map((seg, i) => (
            <button
              key={i}
              ref={i === activeIdx ? activeRowRef : null}
              onClick={() => seekTo(seg.start)}
              className={
                'block w-full text-left text-xs leading-5 px-2 py-1 rounded transition-colors ' +
                (i === activeIdx
                  ? 'text-sky-400 bg-white/5'
                  : 'text-white/70 hover:text-white hover:bg-white/5')
              }
            >
              <span className="font-medium text-white/90">{seg.speaker}: </span>
              {seg.text}
            </button>
          ))
        ) : (
          <pre className="whitespace-pre-wrap text-xs leading-5 text-white/70">
            {transcriptText || ''}
          </pre>
        )}
      </div>
    </div>
  )
}

function findSegmentIndex(segments, currentTime) {
  if (!Array.isArray(segments) || segments.length === 0) return -1
  // Binary search for the segment where start <= t < end. Falls back to the
  // last segment that started before currentTime when no exact match (end-of-segment gaps).
  let lo = 0, hi = segments.length - 1, best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const seg = segments[mid]
    if (currentTime < seg.start) {
      hi = mid - 1
    } else if (currentTime >= seg.end) {
      best = mid
      lo = mid + 1
    } else {
      return mid
    }
  }
  return best
}
```

- [ ] **Step 2: Verify the file parses**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/RecordingPlayer.jsx
git commit -m "Wire synced clickable transcript with binary search highlight"
```

---

## Task 11: Mount `RecordingPlayer` in `MeetingView`

**Files:**
- Modify: `frontend/src/components/dashboard/MeetingView.jsx`

- [ ] **Step 1: Import the component**

In `frontend/src/components/dashboard/MeetingView.jsx`, add at the top with the other imports:

```jsx
import RecordingPlayer from './RecordingPlayer'
```

- [ ] **Step 2: Render `<RecordingPlayer />` above the transcript disclosure**

Locate the transcript section (around line 154):

```jsx
      {transcript && (
```

Insert immediately BEFORE that block:

```jsx
      {meeting?.id && meeting?.recording_provider === 'recall' && (
        <RecordingPlayer
          meetingId={meeting.id}
          recordingProvider={meeting.recording_provider}
          transcriptSegments={meeting.transcript_segments}
          transcriptText={transcript}
        />
      )}
```

The wrapping condition (`meeting?.id && meeting?.recording_provider === 'recall'`) ensures the player is hidden for:
- Fresh in-session analyses (no `meeting` object yet)
- Non-bot meetings (paste / record / upload — `recording_provider` is null)

- [ ] **Step 3: Pass through `recall_bot_id`, `recording_provider`, and `transcript_segments` on the frontend save call**

The save call lives in `App.jsx`. Find the `POST /meetings` call (search for `'/meetings'` with a `method: 'POST'`). Add `recall_bot_id` to the payload — it should be sourced from the same place the bot result is being saved from. Locate the bot-completion handler in `App.jsx` (look for `bot_id` or `recall_bot_id` already in scope).

If a `recall_bot_id` variable is already in scope at the save site (which it should be, as the bot flow generates and tracks it), add this key to the payload:

```jsx
        recall_bot_id: recall_bot_id || null,
```

If the variable is named differently in App.jsx (likely `botId` or `currentBotId`), use that. Verify by grepping:

```bash
cd frontend/src && grep -n 'bot_id\|botId' App.jsx | head -20
```

- [ ] **Step 4: Verify the build still succeeds**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/MeetingView.jsx frontend/src/App.jsx
git commit -m "Mount RecordingPlayer in MeetingView + thread recall_bot_id through save"
```

---

## Task 12: Verify backend `GET /meetings/{id}` returns the new fields

**Files:**
- Modify: `backend/storage_routes.py` (the `get_meeting` endpoint, locate via `@router.get("/meetings/{id}")`)

The frontend reads `meeting.recording_provider` and `meeting.transcript_segments` from the meeting object. Confirm the existing `GET /meetings/{id}` endpoint passes them through.

- [ ] **Step 1: Read the existing `get_meeting` (single meeting) endpoint**

```bash
cd backend && grep -n '@router.get("/meetings/{' storage_routes.py
```

Open the file at that line and inspect the SELECT or column list.

- [ ] **Step 2: Ensure new columns are in the SELECT (or that it's `select("*")`)**

If the existing endpoint uses `.select("*")`, no change needed — the new columns flow through automatically. If it uses an explicit column list, add: `recall_bot_id, recording_provider, transcript_segments`.

Similarly check `GET /meetings` (list) at line 77 — verify it either uses `select("*")` or doesn't strip the new fields. The dashboard list view doesn't render the player, but `transcript_segments` could be heavy on the list endpoint. If the list endpoint explicitly selects columns, do NOT add `transcript_segments` there (only the single-meeting GET needs it).

- [ ] **Step 3: Run tests to make sure nothing regressed**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 4: Commit (only if any change was needed)**

```bash
git add backend/storage_routes.py
git commit -m "Pass through recording fields on GET /meetings/{id}"
```

If no change was needed (already `select("*")`), skip the commit and proceed to Task 13.

---

## Task 13: Manual end-to-end smoke test

No code changes — this is a verification gate before merging.

**Pre-requisites verified once before starting:**
- [ ] Migration `supabase/recording_migration.sql` has been run in the Supabase SQL editor (Task 1, step 2).
- [ ] Recall account is on Pro tier or above.
- [ ] Recall API key is set in backend `.env`.
- [ ] `video_mixed_mp4` and `audio_mixed_mp3` are confirmed current Recall schema keys (https://docs.recall.ai/reference/bot_create).

**Test 1 — Happy path with screenshare:**
- [ ] Start backend (`cd backend && uvicorn main:app --reload --port 8000`) and frontend (`cd frontend && npm run dev`).
- [ ] Open localhost:5173, sign in, navigate to a Google Meet or Zoom test meeting.
- [ ] Use "Have prism join" to send the bot. Confirm the bot joins.
- [ ] Talk for 3+ minutes with at least 2 speakers. Share a screen briefly.
- [ ] End the meeting.
- [ ] Wait for analysis to complete. Open the meeting from the dashboard history.
- [ ] **Verify:** Within 1–3 minutes, `<RecordingPlayer />` transitions from "Recording is still being prepared…" to showing a `<video>` element.
- [ ] **Verify:** The transcript on the right is clickable and the player has audio + video (not just audio).
- [ ] Click a transcript line → video seeks to that timestamp. Click another. Confirm it works in both directions.
- [ ] Let the video play for 30s and confirm the active transcript line highlights and auto-scrolls.
- [ ] Manually scroll the transcript while the video plays — auto-scroll should pause for ~3s, then resume.

**Test 2 — Audio-only fallback:**
- [ ] Join a meeting where only audio is captured (e.g., everyone has video off; or use Recall's audio-only test bot if available).
- [ ] Confirm the player renders an `<audio>` element instead of `<video>`.
- [ ] Click a transcript line; audio seeks correctly.

**Test 3 — Non-bot meetings unchanged:**
- [ ] Open a meeting created via paste / record / upload (any old meeting in history with `recording_provider = null`).
- [ ] **Verify:** The transcript disclosure renders exactly as before. No `<RecordingPlayer />` mounts (no extra card, no "loading", no "unavailable" message).

**Test 4 — Expired recording state:**
- [ ] Either pick a real meeting >30 days old, OR temporarily edit `backend/storage_routes.py::get_meeting_recording` to short-circuit `return {"url": None, "reason": "expired"}`.
- [ ] Open the meeting. Confirm the "Recording is no longer available" card renders with the correct subtext.
- [ ] Revert any temporary code change before committing.

**Test 5 — Workspace member access:**
- [ ] Create a workspace with two members (use a second browser/profile).
- [ ] Have user A bot-record a meeting in the workspace.
- [ ] Sign in as user B (workspace member, not the recorder) and open the same meeting.
- [ ] **Verify:** Player works for user B — they see video + clickable transcript.

**Test 6 — Live-share viewers DO NOT see the recording:**
- [ ] As user A, copy the live-share link (`/#live/{token}`) and open it in an incognito window (unauthenticated).
- [ ] After the meeting ends, confirm `<RecordingPlayer />` does NOT appear. The live-share view should not even call `/meetings/{id}/recording`.

- [ ] **Step Final: Commit a note in the spec marking smoke verified**

```bash
git commit --allow-empty -m "Recording playback E2E smoke verified across 6 test cases"
```

---

## Self-Review

**Spec coverage:**
- Architecture (spec Section 2): Task 4 (bot config) + Task 3 (segments save) + Task 5 (server-side enrichment) + Task 6 (fan-out) + Task 8 (GET endpoint).
- Data Model (spec Section 3): Task 1 (migration) + Task 2 (canonical Segment helper) + Task 5 (`MeetingEntry.recall_bot_id`).
- Recall config caveats (spec Section 4): Task 4 pre-merge verification gate.
- API contract (spec Section 5): Task 7 (`parse_expires_hint`) + Task 8 (all seven response shapes covered in tests).
- Frontend player (spec Section 6): Tasks 9 (skeleton + lifecycle), 10 (synced transcript), 11 (mount). Auto-scroll guard, throttling, polling cap all included in code blocks.
- Testing (spec Section 7): Backend unit tests in each TDD task; manual E2E smoke in Task 13. No frontend automated tests — documented as "no frontend test framework" tradeoff in plan header.
- Deployment checklist (spec Section 8): Task 13 pre-requisites mirror the spec checklist.

**Placeholder scan:** No TBD/TODO/"implement later" found. Every step has either runnable code or a shell command.

**Type consistency:**
- `Segment` shape `{speaker, start, end, text}` used identically in Task 2 (helper output), Task 5 (enrichment), Task 8 (endpoint passthrough), Task 10 (player consumption).
- `recall_bot_id`, `recording_provider`, `transcript_segments` column names used identically across Tasks 1, 5, 6, 8, 11.
- Reason strings (`not_ready`, `no_recording`, `expired`, `not_found`, `not_a_bot_meeting`) consistent across Tasks 8 and 9.

**One nuance worth flagging during execution:** Task 11 step 3 (frontend payload threading) depends on whether `App.jsx` has the bot id in scope at the save site under the name `bot_id`, `botId`, or `currentBotId`. The plan includes a grep command to discover the actual name. If the bot id isn't in scope at all (saved earlier in lifecycle, lost), Task 11 would need an extra step to lift the value into the save closure — that's the most likely place a small mid-implementation adjustment is needed.

---

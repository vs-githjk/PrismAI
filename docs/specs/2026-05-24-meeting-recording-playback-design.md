# Meeting Recording Playback — Watch Bot-Recorded Meetings After They End

**Date:** 2026-05-24
**Status:** Design — ready for implementation plan
**Author:** Session with Abhinav + Claude

---

## Context

Recall.ai already joins meetings on PrismAI's behalf and produces a transcript ([recall_routes.py:490](../../backend/recall_routes.py#L490)). What it doesn't do today is hand back a playable recording — the bot creation POST opts into `transcript` only, not video or audio mix. So when a meeting ends, the user gets summary + decisions + action items, but no way to scrub back through what was actually said.

This spec adds a video-recording playback experience for bot-joined meetings. Users open a past meeting in `MeetingView` and see a synced video player above the transcript: clicking a transcript line jumps the video to that timestamp; the currently-spoken line auto-highlights as the video plays.

---

## Goal

Let workspace members watch and scrub through any bot-joined meeting after it ends, with the transcript clickable and time-synced to the video. Keep the existing transcript-only experience intact for non-bot meetings (paste / record / upload).

---

## Non-Goals

- **Browser-recorded / uploaded meeting playback.** The Record tab uses Web Speech (no audio blob) and Upload discards the file after `/transcribe` ([analysis_routes.py:71](../../backend/analysis_routes.py#L71)). Adding playback for those input modes requires a Supabase Storage bucket and a new upload endpoint — a clean Phase 2 PR once the Recall plumbing is in place.
- **Permanent archival.** Recall hosts the MP4. We don't mirror to Supabase Storage. When Recall's retention window expires (typically ~30 days), the recording is gone — the UI surfaces this gracefully but we don't try to preserve it.
- **Live playback during the meeting.** This is post-meeting only. Live-share viewers already see streaming transcript via `/live/{token}`; that endpoint is intentionally left unchanged.
- **GDPR / participant deletion path.** Worth a follow-up ticket — needs an admin endpoint to call Recall's bot delete and null out recording fields. Out of scope here.
- **URL-refresh during playback.** If the pre-signed URL expires mid-watch (user pauses for hours), the user reloads the page. No client-side refresh logic in v1.
- **Recording URL caching across workspace members.** Multiple teammates opening the same meeting each hit Recall's API. Acceptable for v1 traffic levels.

---

## Architecture

```
JOIN
  POST /join-meeting → recording_config gains:
    video_mixed_layout: "speaker_view"
    video_mixed_mp4: {}
    audio_mixed_mp3: {}             (audio-only fallback)
    transcript: deepgram_streaming  (unchanged)
  Bot registered in meeting_bots (existing dedup key).

MEETING ENDS → /recall-webhook → _process_bot_transcript
  Existing: fetch transcript, run analysis, save to bot_sessions.
  NEW: normalize Recall's transcript response into canonical
       Segment[] and save as bot_sessions.transcript_segments.
  We do NOT fetch the video URL here. MP4 rendering lags transcript
  rendering by minutes, and signed URLs expire (~24h) — denormalising
  the URL is a liability. Always fetch on demand at GET time.
  Fallback realtime-buffer transcripts: segments stay null.

FRONTEND SAVES MEETING
  POST /meetings payload includes recall_bot_id (when it's a bot meeting).
  Backend looks up bot_sessions[recall_bot_id]. If the caller owns that
    bot (bot_sessions.user_id == caller), it copies transcript_segments
    onto the meeting row and sets recording_provider="recall".
  If the caller does NOT own the bot, save still succeeds but the three
    recording fields are written as null. Silent degradation, not 403 —
    avoids breaking the UX when local state holds a stale bot_id.
  Existing _fan_out_to_workspace copies the new columns to teammate rows
    so every workspace member sees the same player.

USER OPENS MEETING
  GET /meetings/{id} returns the row including recording_provider,
    recall_bot_id, transcript_segments (existing workspace-auth applies).
  GET /meetings/{id}/recording (NEW, workspace-auth):
    Calls Recall GET /bot/{recall_bot_id}/, inspects
      recordings[0].media_shortcuts.
    Returns one of: ready (video), ready (audio fallback), not_ready,
      no_recording, expired, not_found, not_a_bot_meeting.

PLAYER
  <RecordingPlayer> mounted above the existing transcript section in
    MeetingView. Returns null when recording_provider is null, so non-bot
    meetings are visually unchanged.
  Renders <video> or <audio> based on response 'kind'. Synced clickable
    transcript when transcript_segments is non-null. Plain transcript
    fallback when segments are null (realtime-buffer path).
```

Three backend files touched (`recall_routes.py`, `storage_routes.py`, `main.py` for the new route registration), one frontend file modified (`MeetingView.jsx`), one new frontend component (`RecordingPlayer.jsx`), one Supabase migration.

---

## Data Model

### Migration `supabase/recording_migration.sql` (manual, run in SQL editor)

```sql
alter table meetings
  add column if not exists recall_bot_id text,
  add column if not exists recording_provider text,         -- 'recall' | future: 'supabase'
  add column if not exists transcript_segments jsonb;       -- Segment[] | null

alter table bot_sessions
  add column if not exists transcript_segments jsonb;       -- staging area, server-pulled at save time

create index if not exists meetings_recall_bot_id_idx
  on meetings(recall_bot_id) where recall_bot_id is not null;
```

All new columns are nullable. Existing rows are untouched and the player hides itself for them.

### Canonical Segment shape

Single normalized form used by both ingest paths and the player:

```ts
type Segment = {
  speaker: string;   // "John Doe" or "Speaker 1"
  start: number;     // seconds, monotonically increasing
  end: number;       // seconds
  text: string;      // joined word text
}
```

Add `_segments_from_recall_data(raw)` next to the existing `_transcript_from_recall_data()` ([recall_routes.py:394](../../backend/recall_routes.py#L394)). Both Recall paths (`media_shortcuts.transcript.data.download_url` and `/bot/{id}/transcript/`) produce `[{speaker, words: [{text, start_time, end_time}]}]` shape. Normalize once: `start = words[0].start_time`, `end = words[-1].end_time`, `text = " ".join(w.text)`. Skip segments with empty `words`. When the realtime-buffer fallback fires, the function returns `None` and `transcript_segments` stays null.

### Trust boundary at save time

`MeetingEntry` pydantic model gains `recall_bot_id: str | None`. In `save_meeting` ([storage_routes.py:212](../../backend/storage_routes.py#L212)), after the existing upsert payload is built:

1. If `recall_bot_id` is provided, query `bot_sessions` for the matching row.
2. If found AND `bot_sessions.user_id == caller`, copy `transcript_segments` into the meeting row payload and set `recording_provider = "recall"`.
3. Otherwise, set both fields to null and proceed. No 403.

This means the client cannot forge segments and cannot leak segments from someone else's bot. Server-side resolution is the trust boundary.

### Fan-out — both call sites updated

Currently `_fan_out_to_workspace` ([storage_routes.py:182](../../backend/storage_routes.py#L182)) copies an explicit field list (id, user_id, date, title, score, transcript, result, share_token, workspace_id, recorded_by_user_id). The new columns must be added to BOTH:

- The fan-out upsert ([storage_routes.py:195](../../backend/storage_routes.py#L195))
- The `save_meeting` upsert ([storage_routes.py:215](../../backend/storage_routes.py#L215))

Missing either one silently fails for teammate rows.

---

## Recall Configuration

In `join_meeting` ([recall_routes.py:530](../../backend/recall_routes.py#L530)), the `recording_config` block adds two siblings to `transcript` and `realtime_endpoints`:

```python
"recording_config": {
    "video_mixed_layout": "speaker_view",
    "video_mixed_mp4": {},
    "audio_mixed_mp3": {},
    "transcript": { ... unchanged ... },
    "realtime_endpoints": [ ... unchanged ... ],
},
```

**Two caveats the implementing engineer must verify before merging:**

1. **Recall API schema.** Recall has rotated this schema once before (the `realtime_endpoints` key moved tiers). The exact key names and nesting for video output must be validated against the live Recall docs at implementation time. If `video_mixed_mp4` is not the current key, update both the bot-creation POST and the `_segments_from_recall_data` lookup keys accordingly.
2. **Plan tier.** Video output requires Recall's Pro tier or above. On Starter / free, the bot creation POST returns 400 with a plan-tier error. Run a one-off dev-env sanity check (join a real meeting with the new config, confirm the bot is created and the recording renders) before merging to main.

---

## API Contract — `GET /meetings/{id}/recording`

**Auth:** workspace-gated, mirroring the existing `GET /meetings/{id}` pattern — the caller must either own the meeting row OR be a member of the meeting's workspace. Non-members get a 404 (we never confirm existence to non-members).

**Behavior:** load the meeting row. If `recall_bot_id` is null → `not_a_bot_meeting`. Otherwise call Recall `GET /bot/{recall_bot_id}/` and inspect `recordings[0].media_shortcuts`. Preference order:

1. `video_mixed.data.download_url` → `{ kind: "video", url, expires_hint_seconds }`
2. `audio_mixed.data.download_url` → `{ kind: "audio", url, expires_hint_seconds }`
3. Otherwise → `{ url: null, reason: "no_recording" }`

If Recall returns 404 → `expired`. 403 → `not_found`. Network error or 5xx → 502 to client (not a documented reason; it's a real backend error).

**Response shapes (full contract):**

```json
{ "url": "https://...", "expires_hint_seconds": 86400, "kind": "video" }
{ "url": "https://...", "expires_hint_seconds": 86400, "kind": "audio" }
{ "url": null, "reason": "not_ready" }
{ "url": null, "reason": "no_recording" }
{ "url": null, "reason": "expired" }
{ "url": null, "reason": "not_found" }
{ "url": null, "reason": "not_a_bot_meeting" }
```

Reason strings are part of the contract — frontend keys distinct messaging per reason.

**`expires_hint_seconds`:** parsed from the URL's `X-Amz-Expires` query parameter when present (Recall uses S3 presigned URLs). When absent, omitted from the response. Documented as approximate — for client-side cache hints only, not a precise countdown.

**`not_ready` vs `no_recording`:** Recall renders the MP4 asynchronously; the transcript is usually ready before the video URL materializes. Distinguish purely on the recordings array:

- `recordings` is empty → `no_recording` (bot was kicked before any media captured, or fatal_error).
- `recordings[0]` exists but neither `video_mixed.data.download_url` nor `audio_mixed.data.download_url` is present → `not_ready` (rendering is in flight).
- At least one download URL present → `ready` with the preferred kind.

Do not gate on the bot's status field — by the time the frontend reaches this endpoint, our internal `_process_bot_transcript` has usually already marked the bot `done`, even though Recall's MP4 render may lag by 1–3 minutes.

---

## Frontend — `<RecordingPlayer />`

New component in `frontend/src/components/dashboard/RecordingPlayer.jsx`. Props:

```jsx
<RecordingPlayer
  meetingId={meeting.id}
  recordingProvider={meeting.recording_provider}    // null → returns null
  transcriptSegments={meeting.transcript_segments}  // null → unclickable transcript
  transcriptText={meeting.transcript}               // fallback display
/>
```

Mounted in `MeetingView.jsx` above the existing transcript disclosure ([MeetingView.jsx:154](../../frontend/src/components/dashboard/MeetingView.jsx#L154)). When `recordingProvider === null`, returns `null` — the existing transcript section is unchanged for non-bot meetings.

### Lifecycle

1. **Mount:** `apiFetch('/meetings/{id}/recording')` with an `AbortController`. Single `recordingState` enum derived from the response.
2. **States:**
   - `loading` — spinner only (initial fetch in flight)
   - `ready` — render `<video>` or `<audio>` per `kind`, with synced transcript (if segments non-null)
   - `processing` (from `reason: not_ready`) — "Recording is still being prepared…" with auto-retry every 15s, capped at 20 attempts (5min total). Cancelled on unmount via `AbortController.abort()` + `clearTimeout` in the `useEffect` cleanup. After cap: "Refresh the page to try again" CTA.
   - `gone` (from `expired` / `not_found` / `no_recording`) — "Recording is no longer available" with a one-line subtext per reason: "Recall.ai's retention window has passed" / "The bot recording was deleted" / "No audio was captured during this meeting"
3. **Steady state:** when `ready`, no further polling. URL is used as-is for the media element `src`.

### Synced clickable transcript

Renders only when `kind=ready` AND `transcriptSegments` is non-null. A scroll container of `<button>` rows, one per segment, styled to match the existing transcript card.

- **Click handler:** `mediaRef.current.currentTime = segment.start; mediaRef.current.play()`
- **Active highlight:** `onTimeUpdate` on the media element runs a binary search for the segment where `start <= currentTime < end`. Throttled to ~4Hz (250ms) via a ref-tracked last-update timestamp. Active segment styled with `text-sky-400` + `bg-white/5`.
- **Auto-scroll:** `activeRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })`, but ONLY when the user hasn't manually scrolled within the last 3s. Tracked via a `wheel` / `touchmove` listener that sets a `userScrolledAt` ref. Without this guard, users can't browse the transcript while the video plays.

### Segments-null path

When `kind=ready` but `transcriptSegments` is null (realtime-buffer fallback transcript), the existing plaintext transcript disclosure renders below the player unchanged. Player works, transcript just isn't clickable. No "missing feature" message — the degrade is silent.

### Layout

Above the existing `MeetingView` transcript section, in a card matching `SentimentCard`'s container styling. Mobile (`md:` breakpoint and below): player full-width, transcript stacks below. Desktop: 60/40 split, transcript on the right with independent scroll.

---

## Testing

### Backend unit — `backend/tests/test_recording.py` (new)

- `_segments_from_recall_data()` — three fixtures: download-URL JSON shape, `/transcript/` streaming shape, empty list. Each produces the same canonical `Segment[]` (or `None` for empty).
- `GET /meetings/{id}/recording` — six cases mocked via `httpx.MockTransport` on Recall's `/bot/{id}/`: video URL present, audio URL only, empty recordings array, 404, 403, network error. Each maps to the documented `{url, reason}` response (or 502 for network errors).
- Auth: non-workspace caller → 404 (matches existing `/meetings/{id}` pattern; never confirm existence to non-members).
- Trust boundary: `POST /meetings` with `recall_bot_id` owned by another user → save succeeds, recording fields written as null.
- `expires_hint_seconds` parsing: URL with `X-Amz-Expires=3600` → field present and equals 3600; URL without it → field omitted.

### Backend integration — extend `backend/tests/test_storage_routes.py`

- Workspace fan-out copies `recall_bot_id`, `recording_provider`, `transcript_segments` to teammate rows. Currently asserts the other fields fan out; extend with the three new ones.

### Frontend unit — `frontend/src/components/dashboard/__tests__/RecordingPlayer.test.jsx` (new)

- Returns `null` when `recordingProvider` is null.
- Renders `processing` state, then `<video>`, when API returns `not_ready` followed by `ready` on retry.
- Clicking a segment seeks the media element (stubbed `HTMLMediaElement`).
- Active-segment highlight tracks `onTimeUpdate` (fire synthetic events).
- Polling stops on unmount (`AbortController.signal.aborted === true`).
- Each `reason` string renders distinct copy.

### Manual / pre-merge E2E

- Real Recall bot joins a 5-min Google Meet with screenshare. Video URL returns within ~3 min of meeting end; clicking transcript lines seeks correctly; transcript auto-highlights as video plays.
- Audio-only path: phone-bridge Zoom (no video). Player falls back to `<audio>` mode.
- Retention-expired path: temporarily monkey-patch the GET endpoint to force a 404 from Recall. Player shows "no longer available" state.

### Out of test scope (call out)

- Real Recall API calls in CI (cost + flakiness).
- Video-codec compatibility across browsers (rely on Recall's MP4 H.264 baseline output).

---

## Deployment Checklist

1. Run `supabase/recording_migration.sql` in the Supabase SQL editor.
2. Verify Recall account is on Pro tier or above (video output is plan-gated).
3. Verify Recall's `video_mixed_mp4` / `audio_mixed_mp3` keys are still the current schema before merging.
4. Frontend Vercel deploy + backend Render deploy pick up automatically on push to `main` per existing CI.
5. Smoke test with a real bot in a short meeting end-to-end.

---

## Open Questions Resolved During Brainstorming

- **Scope:** "All meetings (bot + record + upload)" was the stated scope. Approach A (Recall-first, with Record/Upload as Phase 2) chosen because the hard parts — Recall config, fresh-URL endpoint, synced player, workspace auth — all live in Phase 1. Record/Upload becomes mostly "same player pointed at a different URL".
- **Media type:** Video + audio mixed (single composited MP4 from Recall).
- **Storage:** Recall hosts. We don't mirror.
- **Transcript sync:** Yes — clickable, auto-highlight, auto-scroll with user-scroll guard.
- **Access:** Owner + workspace members. Live-share viewers explicitly excluded.

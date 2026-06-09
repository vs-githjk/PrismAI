# Notifications System — Plan

**Date:** 2026-06-03
**Status:** Drafted, **deferred until after AWS migration**
**Roadmap phase:** Bonus Phase (slots between AWS migration and Phase 6 Voice ID)
**Scope:** New phase, not a feature add — 2–3 days of focused work done right
**Author:** Vidyut

---

## Problem

Today, PrismAI has no way to tell users that something happened outside the meeting they're currently looking at. Real failure modes that go silent:

- Bot fails to join a meeting → user finds out only when they check the dashboard
- Teammate joins their workspace → no signal
- Workspace invite received → no signal
- Brief panel has new open action items → user has to manually open the panel
- Action item assigned to you in a meeting you didn't attend → invisible
- Calendar-matched workspace meeting starts in 5 min → no nudge
- (Future) Voice ID detects a new speaker that needs naming → silent

Several pieces of pending work assume this surface exists:

- **Deferred bot-takeover (Option B)** needs "your teammate's bot died, take over?" alerts
- **Phase 6 (Voice ID)** needs "new speaker detected — name them?" prompts
- **Phase 7 (Context-Aware Chat)** needs "I noticed a pattern across your meetings" surfaces

Building notifications once, properly, gives every future phase a clean integration point.

---

## Goals

1. **Reliable signal** for events that occur outside the active dashboard view.
2. **One source of truth** — a `notifications` table in Supabase with read/dismiss state.
3. **Real-time delivery** to open browser sessions (no polling).
4. **Sub-second** unread-badge update when a new notification fires.
5. **Foundation** for browser push + email digests later, without re-architecting.

## Non-goals

- **No browser push notifications** in v1 (needs service worker, permission UX, mobile considerations — separate phase).
- **No email digests** in v1.
- **No mobile native** notifications.
- **No per-channel preferences UI** in v1 (every notification type fires in-app for now; preferences come later).

---

## Architecture

```
Event source              →   Generator                 →  Storage              →  Delivery
─────────────────             ─────────────                 ─────────              ─────────
recall webhook (bot fail)     notify_bot_failed()           notifications table     supabase realtime
calendar matcher              notify_upcoming_match()           ↓                       ↓
workspace_routes (invite)     notify_invite_received()      INSERT row              FE listener
storage_routes (action_item)  notify_action_assigned()                              ↓
proactive nudges              notify_pattern()                                      bell icon
                                                                                    + toast
```

- Generators are thin Python helpers that `INSERT` rows. They live near the event source (e.g., `recall_routes` calls `notify_bot_failed(user_id, ...)`).
- The frontend opens a Supabase Realtime subscription scoped to `user_id` filtering on `notifications`.
- On a new row event, FE prepends to the in-memory list, bumps the unread count, and optionally fires a toast for high-priority types.

---

## Data model

```sql
create table public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,                    -- target recipient (text to match workspace_members convention)
  type text not null,                       -- enum-like; see TYPES below
  title text not null,                      -- "Bot failed to join Standup"
  body text,                                -- optional longer text
  payload jsonb default '{}'::jsonb,        -- type-specific data (meeting_id, workspace_id, action_item_idx…)
  href text,                                -- optional FE route to navigate on click
  priority text default 'normal',           -- 'normal' | 'high' (high → toast on arrival)
  read_at timestamptz,                      -- null = unread
  dismissed_at timestamptz,                 -- soft-dismissed; excluded from default list
  created_at timestamptz default now()
);

create index notifications_user_unread on notifications (user_id, created_at desc)
  where read_at is null and dismissed_at is null;

create index notifications_user_recent on notifications (user_id, created_at desc)
  where dismissed_at is null;

-- RLS: users see only their own notifications.
alter table public.notifications enable row level security;

create policy notifications_owner_read on public.notifications
  for select using (auth.uid()::text = user_id);

create policy notifications_owner_update on public.notifications
  for update using (auth.uid()::text = user_id)
  with check (auth.uid()::text = user_id);

-- Inserts come from the service role (backend generators) — no policy
-- needed since service role bypasses RLS.
```

**TYPES (v1 set):**

| Type | Fires when | Generator location |
|---|---|---|
| `bot_failed` | Recall webhook reports `call_ended` with error status | `recall_routes._mb_update_status` on terminal-error |
| `bot_joined` | Bot successfully recording (suppressed if user is on the live page) | `recall_routes` webhook handler |
| `workspace_invite` | A new invite hits the user (only when they're already a Prism account, not on invite acceptance) | `workspace_routes.add_member` |
| `workspace_member_joined` | A teammate accepts an invite for a workspace you own | `workspace_routes.accept_invite` |
| `meeting_starting_soon` | Calendar match + meeting starts in ≤5 min + you haven't joined the bot yet | New cron-style endpoint or per-user calendar poll |
| `action_assigned` | A meeting fan-out copy lands in your row with an action item owner-tagged as you | `storage_routes._fan_out_to_workspace` |
| `brief_updated` | New open action items appear in a workspace you're in (rate-limited 1/hour/workspace) | `storage_routes` after `_fan_out_to_workspace` |
| `pattern_detected` (future) | Phase 7 reserved | Phase 7 |
| `voice_id_new_speaker` (future) | Phase 6 reserved | Phase 6 |

---

## Generators (backend)

Single helper module `backend/notifications.py`:

```python
async def notify(user_id: str, *, type: str, title: str,
                 body: str | None = None, payload: dict | None = None,
                 href: str | None = None, priority: str = "normal") -> None:
    """Best-effort write — failures log but never break the calling flow."""
    try:
        await asyncio.to_thread(
            supabase.table("notifications").insert({
                "user_id": user_id, "type": type, "title": title,
                "body": body, "payload": payload or {}, "href": href,
                "priority": priority,
            }).execute
        )
    except Exception as exc:
        print(f"[notify] insert failed user={user_id} type={type}: {exc!r}")
```

Each event source imports `notify` and calls it at the right moment. Generators are dumb writes — no business logic.

**Suppression rules** (avoid notification spam):
- `bot_joined` — suppress if any session for that user has `prism_active_meeting_id == meeting_id` in the last 30s (the user is watching it; no need to ping)
- `brief_updated` — debounce per `(workspace_id)` to at most 1 per hour
- `meeting_starting_soon` — fire exactly once per `(meeting_id, user_id)` (insert-conflict on a unique partial index, or check existence before insert)

---

## Delivery surfaces (frontend)

### v1: in-app only, two surfaces

1. **Bell icon in dashboard header** — shows unread count badge; click opens a dropdown listing recent notifications (newest first, ~20 visible). Each row: icon, title, body, relative time, click → navigate `href`. "Mark all read" and "Clear all" actions.
2. **Toast** — only for `priority='high'` types (e.g. `bot_failed`). Auto-dismiss after 8s; click navigates `href`.

### Component plan

```
frontend/src/components/notifications/
  NotificationBell.jsx       — header icon + unread badge + dropdown trigger
  NotificationDropdown.jsx   — list of recent notifications, mark-read, clear
  NotificationToast.jsx      — high-priority arrival toast (auto-dismiss)
  useNotifications.js        — hook: subscribe + state + mark-read/dismiss actions
  notificationTypes.js       — icon + accent color per type (mirror of personas pattern)
```

`useNotifications` opens a Supabase Realtime subscription:

```js
const channel = supabase
  .channel('notifications')
  .on('postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'notifications',
        filter: `user_id=eq.${userId}` },
      handleInsert)
  .subscribe()
```

Mounts once in `App.jsx` so it survives view switches.

---

## Backend routes

`backend/notification_routes.py`:

- `GET /notifications` — recent (default 20, paginated). Filters out `dismissed_at IS NOT NULL`. Auth-gated.
- `POST /notifications/{id}/read` — set `read_at = now()`.
- `POST /notifications/read-all` — bulk mark-all-read for the caller.
- `POST /notifications/{id}/dismiss` — set `dismissed_at = now()`.
- `DELETE /notifications` — bulk dismiss all (used by "Clear all").

All gated by `Depends(require_user_id)`.

---

## Migration

`supabase/notifications_migration.sql` — new file, idempotent. Run order: after migration #19 (`recording_migration.sql`) → this becomes #20.

Run-time check: confirm Realtime is enabled on the `notifications` table in the Supabase dashboard (Replication → toggle "Realtime" for the table).

---

## Testing

- **Unit tests:** `notify()` writes the expected payload shape; suppression rules fire correctly.
- **Integration:** trigger each generator from its event source in a test env, verify a row lands.
- **Frontend:** mock the Realtime channel; assert badge count + dropdown render + read/dismiss state transitions.
- **Manual:** join a bot in two browsers as two users, kill one bot mid-meeting, assert the bot-failed toast arrives in the relevant user's browser within ~1s.

---

## Rollout

1. Migration applied to Supabase prod (idempotent — safe to re-run).
2. Backend ships generators dark (notifications written but no FE consumer yet).
3. Frontend ships bell + dropdown + toast.
4. Realtime enabled in Supabase dashboard last (the "flip the switch" moment).

If anything goes wrong: notifications writes are best-effort wrapped — failures log but don't break the calling flow. The frontend bell is purely additive UI. Rollback is `git revert` on the FE; the table can stay (no harm).

---

## Out of scope (deferred)

- **Browser push** — needs service worker + permission UX + endpoint persistence; a separate phase after this lands.
- **Email digests** — needs an SMTP sender (Resend, Postmark) + a daily-rollup batch job.
- **Per-user channel preferences** — UI for "mute action items, only ping me on bot failure". Add when users ask.
- **Mobile** — entirely separate roadmap.
- **Cross-device sync of read state** — works for free via Supabase Realtime, but explicit "last-seen-at" cursor for offline catch-up is nice-to-have.

---

## Why this isn't a small add-on

The intuitive "just add a notification" framing hides the real surface area:

1. A persistent store with the right indexes for unread-fast queries.
2. RLS so users can't see each other's notifications.
3. Realtime fan-out (not polling — polling 50 users every 30s = 6000 reqs/hour).
4. Suppression rules so the system doesn't become noise.
5. A consistent generator API so every event source writes the same shape.
6. A frontend bell + dropdown + toast that handles read/unread/dismissed state across views.

Doing this once after AWS migration — when the infra is settled — is right. Doing it mid-flight under a different infra would mean redoing parts of the realtime wiring after the move.

---

## Estimated effort

- Migration + generators + routes: **~1 day**
- Frontend bell + dropdown + toast + Realtime hook: **~1 day**
- Wiring each event source + suppression + manual QA: **~0.5–1 day**

**Total: 2–3 focused days.** Real risk vector is the suppression rules — get them wrong and the bell becomes noise; users learn to ignore it. Tune via the manual QA pass.

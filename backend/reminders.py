"""meeting_soon reminder scanner (#9) — the server-side timer that fires the
5-min-before reminder even when the user's tab is closed.

Runs as an in-process asyncio loop from main.py's lifespan (same pattern as
recover_active_bots) — no separate cron. Scans only users who OPTED IN (they
have a push subscription), lists their upcoming calendar events, and when one
starts within the next ~5 minutes fires a meeting_soon notification (stored,
deduped) + a Web Push. Fire-once via an in-memory set + the notification's
dedup_key (durable across the loop).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from auth import supabase
import notifications
import webpush

_SCAN_INTERVAL_S = 60
_WINDOW_MIN = 5          # remind when an event starts within the next 5 minutes
_reminded: set[str] = set()   # f"{user_id}:{event_id}" already fired
_ENABLED = os.getenv("PRISM_MEETING_REMINDERS", "1") == "1"


async def reminder_loop() -> None:
    if not _ENABLED:
        print("[reminders] disabled via PRISM_MEETING_REMINDERS")
        return
    print("[reminders] meeting_soon scanner started")
    while True:
        try:
            await _scan_once()
        except Exception as exc:  # noqa: BLE001
            print(f"[reminders] scan error: {exc!r}")
        await asyncio.sleep(_SCAN_INTERVAL_S)


async def _scan_once() -> None:
    if not supabase:
        return
    # Opted-in users only = those with a push subscription. Keeps the scan cheap
    # and means meeting_soon only fires for people who asked for reminders.
    try:
        subs = supabase.table("push_subscriptions").select("user_id").execute().data or []
    except Exception as exc:  # noqa: BLE001
        print(f"[reminders] sub list failed: {exc!r}")
        return
    user_ids = {s["user_id"] for s in subs if s.get("user_id")}
    if not user_ids:
        return

    from calendar_routes import list_upcoming_events_for_user
    now = datetime.now(timezone.utc)
    for uid in user_ids:
        events = await list_upcoming_events_for_user(uid, minutes_ahead=_WINDOW_MIN + 1)
        for ev in events:
            eid, start = ev.get("id"), ev.get("start")
            if not eid or not start:
                continue
            key = f"{uid}:{eid}"
            if key in _reminded:
                continue
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except Exception:
                continue
            mins = (start_dt - now).total_seconds() / 60.0
            if 0 <= mins <= _WINDOW_MIN:
                _reminded.add(key)
                title = ev.get("title") or "Upcoming meeting"
                body = f"Starts in {max(1, round(mins))} min"
                notifications.create_notification(
                    uid, "meeting_soon", title, body=body, dedup_key=f"soon:{eid}",
                )
                webpush.send_to_user(uid, title, body, url="/dashboard")

    # Bound the in-memory guard so it can't grow forever across days.
    if len(_reminded) > 5000:
        _reminded.clear()

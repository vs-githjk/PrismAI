"""Calendar tools: create events and list upcoming events."""

from datetime import datetime, timezone, timedelta

import httpx

from .registry import register_tool

GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"


async def _get_google_token(user_settings: dict) -> str:
    token = user_settings.get("google_access_token")
    if not token:
        raise Exception("Google not connected — connect Google Calendar first")
    return token


async def calendar_create_event(args: dict, user_settings: dict | None = None) -> dict:
    token = await _get_google_token(user_settings)

    event_body = {
        "summary": args.get("title", "Untitled Meeting"),
        "start": {"dateTime": args["start"], "timeZone": args.get("timezone", "America/New_York")},
        "end": {"dateTime": args["end"], "timeZone": args.get("timezone", "America/New_York")},
    }

    if args.get("description"):
        event_body["description"] = args["description"]

    if args.get("attendees"):
        event_body["attendees"] = [{"email": e} for e in args["attendees"]]
        event_body["conferenceData"] = {
            "createRequest": {"requestId": f"prism-{int(datetime.now().timestamp())}"}
        }

    params = {}
    if args.get("attendees"):
        params["conferenceDataVersion"] = 1
        params["sendUpdates"] = "all"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=event_body,
            params=params,
            timeout=15,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        return {
            "success": True,
            "event_id": data.get("id"),
            "link": data.get("htmlLink"),
            "summary": f"Created event '{args.get('title')}' — {args['start']}",
        }
    else:
        return {"error": f"Calendar API error {resp.status_code}: {resp.text[:200]}"}


async def calendar_list_events(args: dict, user_settings: dict | None = None) -> dict:
    token = await _get_google_token(user_settings)

    days_ahead = min(args.get("days_ahead", 7), 30)
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": now.isoformat(),
                "timeMax": time_max.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "15",
            },
            timeout=15,
        )

    if resp.status_code != 200:
        return {"error": f"Calendar API error {resp.status_code}: {resp.text[:200]}"}

    items = resp.json().get("items", [])
    events = []
    for item in items:
        start = item.get("start", {})
        events.append({
            "title": item.get("summary", "Untitled"),
            "start": start.get("dateTime") or start.get("date"),
            "attendees": len(item.get("attendees", [])),
        })

    return {"events": events, "summary": f"Found {len(events)} events in the next {days_ahead} days"}


# Register tools
register_tool(
    name="calendar_create_event",
    description="Create a Google Calendar event / schedule a follow-up meeting",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time in ISO 8601 format (e.g. 2025-01-15T14:00:00)"},
            "end": {"type": "string", "description": "End time in ISO 8601 format"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
            "description": {"type": "string", "description": "Event description"},
            "timezone": {"type": "string", "description": "Timezone (default: America/New_York)"},
        },
        "required": ["title", "start", "end"],
    },
    handler=calendar_create_event,
    requires="google_access_token",
    confirm=True,
)

register_tool(
    name="calendar_list_events",
    description="List upcoming Google Calendar events",
    parameters={
        "type": "object",
        "properties": {
            "days_ahead": {"type": "integer", "description": "Number of days to look ahead (max 30)", "default": 7},
        },
        "required": [],
    },
    handler=calendar_list_events,
    requires="google_access_token",
    confirm=False,
)

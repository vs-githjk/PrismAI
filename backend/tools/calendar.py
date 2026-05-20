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
        "start": {"dateTime": args["start"], "timeZone": args.get("timezone", "UTC")},
        "end": {"dateTime": args["end"], "timeZone": args.get("timezone", "UTC")},
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
    available_links = []
    for item in items:
        start = item.get("start", {})
        title = item.get("summary", "Untitled")
        start_str = start.get("dateTime") or start.get("date")

        meet_link = item.get("hangoutLink")
        if not meet_link:
            for ep in item.get("conferenceData", {}).get("entryPoints", []):
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri")
                    break
        event_link = item.get("htmlLink")

        events.append({
            "title": title,
            "start": start_str,
            "attendees": len(item.get("attendees", [])),
            "meet_link": meet_link,
            "event_link": event_link,
        })

        if meet_link or event_link:
            available_links.append({
                "title": title,
                "start": start_str,
                "meet_link": meet_link,
                "event_link": event_link,
            })

    return {
        "AVAILABLE_LINKS_FOR_FORWARDING": available_links,
        "events": events,
        "summary": f"Found {len(events)} events in the next {days_ahead} days. "
                   f"{len(available_links)} have shareable links — if the user asked you to "
                   f"forward, share, or include a meeting link in an email/message, copy the "
                   f"URL from AVAILABLE_LINKS_FOR_FORWARDING verbatim into the body of the next tool call.",
    }


async def calendar_update_event(args: dict, user_settings: dict | None = None) -> dict:
    token = await _get_google_token(user_settings)

    # Find the event by title match
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=30)

    async with httpx.AsyncClient() as client:
        list_resp = await client.get(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            params={"timeMin": now.isoformat(), "timeMax": time_max.isoformat(),
                    "singleEvents": "true", "orderBy": "startTime", "maxResults": "20"},
            timeout=15,
        )

    if list_resp.status_code != 200:
        return {"error": f"Could not fetch events: {list_resp.status_code}"}

    query = args.get("title", "").lower()
    items = list_resp.json().get("items", [])
    match = next((e for e in items if query in e.get("summary", "").lower()), None)
    if not match:
        return {"error": f"No upcoming event found matching '{args.get('title')}'"}

    event_id = match["id"]
    patch = {}
    if args.get("new_start"):
        tz = args.get("timezone", "UTC")
        patch["start"] = {"dateTime": args["new_start"], "timeZone": tz}
        patch["end"] = {"dateTime": args["new_end"], "timeZone": tz} if args.get("new_end") else match["end"]
    if args.get("new_title"):
        patch["summary"] = args["new_title"]

    if not patch:
        return {"error": "Nothing to update — provide new_start/new_end or new_title"}

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events/{event_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=patch,
            timeout=15,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        return {"success": True, "link": data.get("htmlLink"),
                "summary": f"Updated '{data.get('summary')}' — new time: {data.get('start', {}).get('dateTime', 'unchanged')}"}
    return {"error": f"Calendar API error {resp.status_code}: {resp.text[:200]}"}


# Register tools
register_tool(
    name="calendar_create_event",
    description="Create a Google Calendar event / schedule a follow-up meeting",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time in LOCAL time ISO 8601 format — do NOT convert to UTC (e.g. 2025-01-15T14:00:00 for 2pm)"},
            "end": {"type": "string", "description": "End time in LOCAL time ISO 8601 format — do NOT convert to UTC"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
            "description": {"type": "string", "description": "Event description"},
            "timezone": {"type": "string", "description": "IANA timezone identifier (e.g. 'Asia/Kolkata' for IST UTC+5:30, 'America/New_York' for ET, 'Europe/London' for GMT/BST). IMPORTANT: IST = Asia/Kolkata = UTC+5:30, NOT UTC+5."},
        },
        "required": ["title", "start", "end"],
    },
    handler=calendar_create_event,
    requires="google_access_token",
    confirm=False,
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

register_tool(
    name="calendar_update_event",
    description="Reschedule or rename an existing Google Calendar event by matching its title",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title (or partial title) of the event to find"},
            "new_title": {"type": "string", "description": "New event title (optional)"},
            "new_start": {"type": "string", "description": "New start time in LOCAL time ISO 8601 format — do NOT convert to UTC"},
            "new_end": {"type": "string", "description": "New end time in LOCAL time ISO 8601 format — do NOT convert to UTC"},
            "timezone": {"type": "string", "description": "IANA timezone identifier (e.g. 'Asia/Kolkata' for IST UTC+5:30, 'America/New_York' for ET). IST = Asia/Kolkata = UTC+5:30, NOT UTC+5."},
        },
        "required": ["title"],
    },
    handler=calendar_update_event,
    requires="google_access_token",
    confirm=False,
)

import os
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase

router = APIRouter(tags=["calendar"])

GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")


# ─── Meeting link detection ──────────────────────────────────────────────────

MEETING_LINK_PATTERNS = [
    "zoom.us/j/",
    "zoom.us/my/",
    "meet.google.com/",
    "teams.microsoft.com/l/meetup-join",
    "teams.live.com/meet/",
    "webex.com/meet/",
    "webex.com/join/",
    "whereby.com/",
    "around.co/r/",
    "meet.jit.si/",
]


def extract_meeting_link(event: dict) -> str | None:
    # 1. Google Meet built-in link
    hangout = event.get("hangoutLink")
    if hangout:
        return hangout

    # 2. Conference data (Zoom, Teams via calendar integration)
    conf = event.get("conferenceData", {})
    for ep in conf.get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            uri = ep.get("uri", "")
            if any(p in uri for p in MEETING_LINK_PATTERNS):
                return uri

    # 3. Scan event description for known meeting links
    description = event.get("description", "") or ""
    location = event.get("location", "") or ""
    combined = f"{description}\n{location}"
    for line in combined.splitlines():
        line = line.strip()
        for pattern in MEETING_LINK_PATTERNS:
            if pattern in line:
                # Extract URL (grab the token containing the pattern)
                for token in line.split():
                    if pattern in token:
                        url = token.rstrip(".,;)")
                        if url.startswith("http"):
                            return url

    return None


# ─── Token refresh ────────────────────────────────────────────────────────────

async def refresh_google_token(refresh_token: str) -> dict | None:
    """Exchange refresh token for a new access token. Returns token data or None."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                },
                timeout=10,
            )
        if resp.status_code == 200:
            return resp.json()
    except httpx.HTTPError:
        pass
    return None


async def get_valid_token(user_id: str) -> str:
    """Return a valid Google access token for the user, refreshing if needed."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    resp = supabase.table("user_settings").select(
        "google_access_token,google_refresh_token,google_token_expires_at"
    ).eq("user_id", user_id).single().execute()

    row = resp.data
    if not row or not row.get("google_access_token"):
        raise HTTPException(status_code=404, detail="Google Calendar not connected")

    access_token = row["google_access_token"]
    refresh_token = row.get("google_refresh_token")
    expires_at_str = row.get("google_token_expires_at")

    # Check if token is expired (with 60s buffer)
    if expires_at_str and refresh_token:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= expires_at - timedelta(seconds=60):
                new_token_data = await refresh_google_token(refresh_token)
                if new_token_data and new_token_data.get("access_token"):
                    access_token = new_token_data["access_token"]
                    new_expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=new_token_data.get("expires_in", 3600)
                    )
                    supabase.table("user_settings").update({
                        "google_access_token": access_token,
                        "google_token_expires_at": new_expires_at.isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("user_id", user_id).execute()
        except (ValueError, TypeError):
            pass

    return access_token


# ─── Routes ──────────────────────────────────────────────────────────────────

class CalendarConnectRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None  # seconds until expiry


@router.post("/calendar/connect")
async def calendar_connect(
    req: CalendarConnectRequest,
    user_id: str = Depends(require_user_id),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    expires_at = None
    if req.expires_in:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=req.expires_in)
        ).isoformat()

    row = {
        "user_id": user_id,
        "google_access_token": req.access_token,
        "google_refresh_token": req.refresh_token,
        "google_token_expires_at": expires_at,
        "calendar_connected": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    supabase.table("user_settings").upsert(row, on_conflict="user_id").execute()
    return {"ok": True}


@router.delete("/calendar/disconnect")
async def calendar_disconnect(user_id: str = Depends(require_user_id)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    supabase.table("user_settings").update({
        "google_access_token": None,
        "google_refresh_token": None,
        "google_token_expires_at": None,
        "calendar_connected": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()
    return {"ok": True}


@router.get("/calendar/status")
async def calendar_status(user_id: str = Depends(require_user_id)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    resp = supabase.table("user_settings").select(
        "calendar_connected,google_token_expires_at"
    ).eq("user_id", user_id).maybe_single().execute()

    row = resp.data
    connected = bool(row and row.get("calendar_connected") and row.get("google_token_expires_at") is not None or
                     row and row.get("calendar_connected") and row.get("google_token_expires_at") is None and row.get("calendar_connected"))

    # Actually: connected if calendar_connected is True AND access token exists
    if row:
        resp2 = supabase.table("user_settings").select("google_access_token").eq("user_id", user_id).maybe_single().execute()
        connected = bool(resp2.data and resp2.data.get("google_access_token"))
    else:
        connected = False

    return {"connected": connected}


@router.get("/calendar/events")
async def calendar_events(
    days_ahead: int = 7,
    user_id: str = Depends(require_user_id),
):
    access_token = await get_valid_token(user_id)

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "timeMin": now.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "15",
                    "fields": "items(id,summary,start,end,description,location,hangoutLink,conferenceData,attendees)",
                },
                timeout=15,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Google Calendar unavailable: {exc}")

    if resp.status_code == 401:
        # Token rejected — mark disconnected
        if supabase:
            supabase.table("user_settings").update({
                "calendar_connected": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
        raise HTTPException(status_code=401, detail="Google Calendar token expired — please reconnect")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Google Calendar API error")

    raw_items = resp.json().get("items", [])
    events = []
    for item in raw_items:
        start = item.get("start", {})
        end = item.get("end", {})
        meeting_link = extract_meeting_link(item)
        events.append({
            "id": item.get("id"),
            "title": item.get("summary", "Untitled event"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "all_day": "date" in start and "dateTime" not in start,
            "meeting_link": meeting_link,
            "has_meeting_link": meeting_link is not None,
            "attendee_count": len(item.get("attendees", [])),
        })

    return {"events": events}

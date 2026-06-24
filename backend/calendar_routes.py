import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase
from clients import get_http

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
    """Exchange refresh token for a new access token. Returns token data or None.

    Diagnostic logging on every failure path — without it, gmail_send and
    calendar_* tools silently degrade to using the expired access_token.
    The user sees "Invalid Credentials" from Google and we have no idea
    why our refresh failed. The logs here surface the real cause: missing
    env vars, revoked grant, client mismatch, etc.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print(
            "[google-refresh] FAIL missing env vars "
            f"client_id_set={bool(GOOGLE_CLIENT_ID)} "
            f"client_secret_set={bool(GOOGLE_CLIENT_SECRET)}"
        )
        return None
    try:
        async with get_http() as client:
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
            print("[google-refresh] OK")
            return resp.json()
        # Common Google errors: invalid_grant (revoked/expired), invalid_client
        # (wrong id/secret), unauthorized_client (consent screen issue).
        print(
            f"[google-refresh] FAIL status={resp.status_code} body={resp.text[:300]}"
        )
    except httpx.HTTPError as e:
        print(f"[google-refresh] FAIL http_error={type(e).__name__}: {e}")
    return None


async def get_valid_token(user_id: str, row: dict | None = None, return_remaining: bool = False):
    """Return a valid Google access token for the user, refreshing if needed.

    Optional ``row`` lets callers (e.g. realtime command path) pass an already-
    fetched user_settings row so we skip the Supabase round-trip when the
    token is still fresh. When ``return_remaining`` is True, returns
    ``(access_token, seconds_until_expiry_or_None)`` so the caller can cap
    its own cache TTL.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    if row is None:
        try:
            resp = supabase.table("user_settings").select(
                "google_access_token,google_refresh_token,google_token_expires_at"
            ).eq("user_id", user_id).maybe_single().execute()
        except Exception:
            raise HTTPException(status_code=503, detail="Database error fetching calendar credentials")
        row = (resp.data if resp is not None else None) or {}

    if not row or not row.get("google_access_token"):
        raise HTTPException(status_code=404, detail="Google Calendar not connected")

    access_token = row["google_access_token"]
    refresh_token = row.get("google_refresh_token")
    expires_at_str = row.get("google_token_expires_at")
    seconds_remaining: float | None = None

    # Check if token is expired (with 60s buffer)
    if expires_at_str and refresh_token:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if now >= expires_at - timedelta(seconds=60):
                new_token_data = await refresh_google_token(refresh_token)
                if new_token_data and new_token_data.get("access_token"):
                    access_token = new_token_data["access_token"]
                    new_expires_at = now + timedelta(seconds=new_token_data.get("expires_in", 3600))
                    supabase.table("user_settings").update({
                        "google_access_token": access_token,
                        "google_token_expires_at": new_expires_at.isoformat(),
                        "updated_at": now.isoformat(),
                    }).eq("user_id", user_id).execute()
                    seconds_remaining = (new_expires_at - now).total_seconds()
            else:
                seconds_remaining = (expires_at - now).total_seconds()
        except (ValueError, TypeError):
            pass

    if return_remaining:
        return access_token, seconds_remaining
    return access_token


# ─── Routes ──────────────────────────────────────────────────────────────────

class CalendarConnectRequest(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None  # seconds until expiry


class ExchangeCodeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


@router.post("/calendar/exchange-code")
async def calendar_exchange_code(
    req: ExchangeCodeRequest,
    user_id: str = Depends(require_user_id),
):
    """Exchange a Google OAuth authorization code (PKCE) for tokens and store them."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google OAuth credentials not configured on server")

    try:
        async with get_http() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": req.code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": req.redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": req.code_verifier,
                },
                timeout=15,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Google token exchange failed: {exc}")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Google rejected code exchange: {resp.text}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in Google response")

    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    expires_at = None
    if expires_in:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    row: dict = {
        "user_id": user_id,
        "google_access_token": access_token,
        "google_token_expires_at": expires_at,
        "calendar_connected": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Google only returns refresh_token on first authorization (or after revoke+reconnect).
    # Only overwrite the stored refresh_token when a new one is actually provided,
    # otherwise the user loses the ability to refresh tokens until they fully revoke access.
    if refresh_token:
        row["google_refresh_token"] = refresh_token
    supabase.table("user_settings").upsert(row, on_conflict="user_id").execute()
    return {"ok": True}


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

    try:
        resp = supabase.table("user_settings").select(
            "calendar_connected,google_access_token"
        ).eq("user_id", user_id).maybe_single().execute()
        row = resp.data or {}
        connected = bool(row.get("calendar_connected") and row.get("google_access_token"))
    except Exception:
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
        async with get_http() as client:
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
            "attendee_emails": [
                a["email"] for a in item.get("attendees", [])
                if a.get("email") and not a.get("self")
            ],
        })

    return {"events": events}


class CreateEventRequest(BaseModel):
    title: str
    start: str  # ISO 8601 datetime (e.g. "2026-04-14T15:00:00")
    end: str | None = None  # defaults to start + 30 min
    description: str | None = None
    attendees: list[str] = []  # emails; names without "@" are dropped
    timezone: str = "UTC"
    confirm: bool = False  # set true to create despite a detected duplicate/overlap


def _to_aware(iso: str, tzname: str) -> datetime:
    """Parse an ISO datetime to a tz-aware UTC-comparable value. A naive string is
    interpreted in the event's timezone; falls back to UTC for a bad tz name."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tzname or "UTC"))
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _find_calendar_conflicts(token: str, title: str, start: datetime, end: datetime) -> dict | None:
    """List events overlapping [start, end] and classify the first conflict.
    Returns {type: 'duplicate'|'overlap', events: [{title, start, end}]} or None.
    Best-effort — any lookup failure returns None so creation isn't blocked."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "10",
                },
                timeout=10,
            )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", []) or []
    except Exception:
        return None

    duplicates, overlaps = [], []
    for ev in items:
        ev_start_s = (ev.get("start") or {}).get("dateTime")
        ev_end_s = (ev.get("end") or {}).get("dateTime")
        if not ev_start_s:
            continue  # all-day event — skip
        summary = (ev.get("summary") or "").strip()
        info = {"title": summary or "(untitled)", "start": ev_start_s, "end": ev_end_s}
        try:
            ev_start = datetime.fromisoformat(ev_start_s.replace("Z", "+00:00"))
        except Exception:
            ev_start = None
        same_title = summary.lower() == (title or "").strip().lower()
        same_start = ev_start is not None and abs((ev_start - start).total_seconds()) < 60
        if same_title and same_start:
            duplicates.append(info)
        else:
            overlaps.append(info)
    if duplicates:
        return {"type": "duplicate", "events": duplicates}
    if overlaps:
        return {"type": "overlap", "events": overlaps}
    return None


@router.post("/calendar/create-event")
async def calendar_create_event_route(
    req: CreateEventRequest,
    user_id: str = Depends(require_user_id),
):
    """Create a Google Calendar event from a follow-up suggestion. Reuses the
    same insert logic the live bot uses (adds a Meet link when attendees exist).
    Before creating, checks for an existing duplicate/overlapping event and returns
    a conflict (without creating) unless req.confirm is set."""
    from tools.calendar import calendar_create_event

    access_token = await get_valid_token(user_id)  # raises 404 if not connected

    end = req.end
    if not end:
        try:
            start_dt = datetime.fromisoformat(req.start.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start datetime")
        end = (start_dt + timedelta(minutes=30)).isoformat()

    if not req.confirm:
        conflict = await _find_calendar_conflicts(
            access_token, req.title,
            _to_aware(req.start, req.timezone), _to_aware(end, req.timezone),
        )
        if conflict:
            return {"conflict": True, **conflict}

    args = {
        "title": req.title,
        "start": req.start,
        "end": end,
        "timezone": req.timezone,
        "description": req.description,
        "attendees": [e for e in req.attendees if e and "@" in e],
    }
    result = await calendar_create_event(args, {"google_access_token": access_token})
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result

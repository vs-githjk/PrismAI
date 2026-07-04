"""Microsoft / Outlook calendar via MS Graph.

Mirrors calendar_routes.py (Google). Uses the app's own OAuth PKCE flow against
the Microsoft identity platform — NOT the Supabase Azure SSO session, because
Supabase doesn't persist the provider_token (same reason Google Calendar has its
own flow). Reuses the Azure 'Prism' app registration; needs MICROSOFT_CLIENT_ID
+ MICROSOFT_CLIENT_SECRET on the server and the Graph delegated scope
Calendars.Read (+ offline_access for refresh tokens).
"""

import os
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id, supabase
from clients import get_http
from calendar_routes import MEETING_LINK_PATTERNS

router = APIRouter(tags=["ms-calendar"])

GRAPH_API = "https://graph.microsoft.com/v1.0"
# /common lets both work/school AND personal Microsoft accounts sign in (matches
# the Azure app's "any org directory + personal accounts" account type).
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "")
# offline_access → refresh token; the rest are the calendar read scope + OIDC.
MS_SCOPE = "openid email offline_access Calendars.Read"


# ─── Meeting link detection (Graph event shape) ──────────────────────────────

def extract_ms_meeting_link(event: dict) -> str | None:
    # 1. Teams/online meeting join URL (the reliable source)
    online = event.get("onlineMeeting") or {}
    if online.get("joinUrl"):
        return online["joinUrl"]
    if event.get("onlineMeetingUrl"):
        return event["onlineMeetingUrl"]

    # 2. Scan the body preview + location for a known meeting link
    body_preview = event.get("bodyPreview", "") or ""
    location = (event.get("location") or {}).get("displayName", "") or ""
    combined = f"{body_preview}\n{location}"
    for line in combined.splitlines():
        line = line.strip()
        for pattern in MEETING_LINK_PATTERNS:
            if pattern in line:
                for token in line.split():
                    if pattern in token:
                        url = token.rstrip(".,;)")
                        if url.startswith("http"):
                            return url
    return None


# ─── Token refresh ────────────────────────────────────────────────────────────

async def refresh_ms_token(refresh_token: str) -> dict | None:
    """Exchange a refresh token for a fresh access token. Returns token data or None."""
    if not MS_CLIENT_ID or not MS_CLIENT_SECRET:
        print("[ms-refresh] FAIL — MICROSOFT_CLIENT_ID/SECRET not configured")
        return None
    try:
        async with get_http() as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "client_id": MS_CLIENT_ID,
                    "client_secret": MS_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": MS_SCOPE,
                },
                timeout=15,
            )
        if resp.status_code == 200:
            return resp.json()
        print(f"[ms-refresh] FAIL status={resp.status_code} body={resp.text[:300]}")
    except httpx.HTTPError as e:
        print(f"[ms-refresh] FAIL http_error={type(e).__name__}: {e}")
    return None


async def get_valid_ms_token(user_id: str, row: dict | None = None) -> str:
    """Return a valid Microsoft Graph access token, refreshing if needed."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    if row is None:
        try:
            resp = supabase.table("user_settings").select(
                "ms_access_token,ms_refresh_token,ms_token_expires_at"
            ).eq("user_id", user_id).maybe_single().execute()
        except Exception:
            raise HTTPException(status_code=503, detail="Database error fetching Outlook credentials")
        row = (resp.data if resp is not None else None) or {}

    if not row or not row.get("ms_access_token"):
        raise HTTPException(status_code=404, detail="Outlook calendar not connected")

    access_token = row["ms_access_token"]
    refresh_token = row.get("ms_refresh_token")
    expires_at_str = row.get("ms_token_expires_at")

    if expires_at_str and refresh_token:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if now >= expires_at - timedelta(seconds=60):
                new_token = await refresh_ms_token(refresh_token)
                if new_token and new_token.get("access_token"):
                    access_token = new_token["access_token"]
                    new_expires_at = now + timedelta(seconds=new_token.get("expires_in", 3600))
                    update = {
                        "ms_access_token": access_token,
                        "ms_token_expires_at": new_expires_at.isoformat(),
                        "updated_at": now.isoformat(),
                    }
                    # MS may rotate the refresh token; persist the new one when present.
                    if new_token.get("refresh_token"):
                        update["ms_refresh_token"] = new_token["refresh_token"]
                    supabase.table("user_settings").update(update).eq("user_id", user_id).execute()
        except (ValueError, TypeError):
            pass

    return access_token


# ─── Routes ──────────────────────────────────────────────────────────────────

class MsExchangeCodeRequest(BaseModel):
    code: str
    code_verifier: str
    redirect_uri: str


@router.post("/ms-calendar/exchange-code")
async def ms_exchange_code(req: MsExchangeCodeRequest, user_id: str = Depends(require_user_id)):
    """Exchange a Microsoft OAuth authorization code (PKCE) for tokens and store them."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    if not MS_CLIENT_ID or not MS_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Microsoft OAuth credentials not configured on server")

    try:
        async with get_http() as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "client_id": MS_CLIENT_ID,
                    "client_secret": MS_CLIENT_SECRET,
                    "code": req.code,
                    "redirect_uri": req.redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": req.code_verifier,
                    "scope": MS_SCOPE,
                },
                timeout=15,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Microsoft token exchange failed: {exc}")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Microsoft rejected code exchange: {resp.text[:300]}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in Microsoft response")

    expires_in = token_data.get("expires_in")
    expires_at = None
    if expires_in:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    row: dict = {
        "user_id": user_id,
        "ms_access_token": access_token,
        "ms_token_expires_at": expires_at,
        "outlook_connected": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if token_data.get("refresh_token"):
        row["ms_refresh_token"] = token_data["refresh_token"]
    supabase.table("user_settings").upsert(row, on_conflict="user_id").execute()
    return {"ok": True}


@router.delete("/ms-calendar/disconnect")
async def ms_disconnect(user_id: str = Depends(require_user_id)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    supabase.table("user_settings").update({
        "ms_access_token": None,
        "ms_refresh_token": None,
        "ms_token_expires_at": None,
        "outlook_connected": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()
    return {"ok": True}


@router.get("/ms-calendar/status")
async def ms_status(user_id: str = Depends(require_user_id)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")
    try:
        # The token IS the connection — a stored access token means we can call Graph
        # (and refresh when it expires). Deriving `connected` from the presence of the
        # token, not the separate `outlook_connected` flag, keeps status in sync with
        # /ms-calendar/events (which only needs the token). Previously the flag could
        # drift to false (e.g. a transient 401 flipped it) while the token stayed,
        # showing "not connected" even though the calendar worked.
        resp = supabase.table("user_settings").select(
            "ms_access_token"
        ).eq("user_id", user_id).maybe_single().execute()
        row = (resp.data if resp is not None else None) or {}
        connected = bool(row.get("ms_access_token"))
    except Exception:
        connected = False
    return {"connected": connected}


@router.get("/ms-calendar/events")
async def ms_events(days_ahead: int = 7, user_id: str = Depends(require_user_id)):
    access_token = await get_valid_ms_token(user_id)

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days_ahead)

    try:
        async with get_http() as client:
            resp = await client.get(
                f"{GRAPH_API}/me/calendarView",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    # Return all start/end times in UTC so parsing is uniform.
                    "Prefer": 'outlook.timezone="UTC"',
                },
                params={
                    "startDateTime": now.isoformat(),
                    "endDateTime": time_max.isoformat(),
                    "$orderby": "start/dateTime",
                    "$top": "15",
                    "$select": "id,subject,start,end,isAllDay,onlineMeeting,onlineMeetingUrl,isOnlineMeeting,location,bodyPreview,attendees",
                },
                timeout=15,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Outlook calendar unavailable: {exc}")

    if resp.status_code == 401:
        # The token is truly dead (and refresh already failed upstream) — clear it so
        # status reflects reality (token-based) and the user is prompted to reconnect.
        # Clearing only the flag but keeping the token left status/events inconsistent.
        if supabase:
            supabase.table("user_settings").update({
                "ms_access_token": None,
                "ms_refresh_token": None,
                "ms_token_expires_at": None,
                "outlook_connected": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
        raise HTTPException(status_code=401, detail="Outlook token expired — please reconnect")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Outlook calendar API error")

    raw_items = resp.json().get("value", [])
    events = []
    for item in raw_items:
        start = item.get("start", {})
        end = item.get("end", {})
        meeting_link = extract_ms_meeting_link(item)
        # Graph returns naive UTC datetimes (with Prefer header) — append Z so the
        # frontend parses them as ISO UTC, matching the Google shape.
        start_dt = start.get("dateTime")
        end_dt = end.get("dateTime")
        if start_dt and not start_dt.endswith("Z") and "+" not in start_dt:
            start_dt = start_dt.rstrip("0").rstrip(".") + "Z" if "." in start_dt else start_dt + "Z"
        if end_dt and not end_dt.endswith("Z") and "+" not in end_dt:
            end_dt = end_dt.rstrip("0").rstrip(".") + "Z" if "." in end_dt else end_dt + "Z"
        attendees = item.get("attendees", []) or []
        emails = [
            a.get("emailAddress", {}).get("address")
            for a in attendees
            if a.get("emailAddress", {}).get("address")
        ]
        events.append({
            "id": item.get("id"),
            "title": item.get("subject", "Untitled event"),
            "start": start_dt,
            "end": end_dt,
            "all_day": bool(item.get("isAllDay")),
            "meeting_link": meeting_link,
            "has_meeting_link": meeting_link is not None,
            "attendee_count": len(attendees),
            "attendee_emails": emails,
            "source": "outlook",
        })

    return {"events": events}

"""OAuth 2.1 authorization-server endpoints for the MCP connector (Milestone B).

Flow:
  1. Claude fetches /.well-known/oauth-protected-resource (from the /mcp 401) →
     /.well-known/oauth-authorization-server for our endpoints.
  2. Claude registers via POST /oauth/register (DCR) → gets a client_id.
  3. Claude opens GET /oauth/authorize (PKCE). We validate, then redirect the
     browser to the frontend consent page.
  4. The user signs in (Supabase) + approves; the consent page calls
     POST /oauth/authorize/approve (auth-gated) → we mint a code and hand back the
     redirect to Claude's callback.
  5. Claude exchanges the code at POST /oauth/token (form-urlencoded, PKCE verify)
     → access + refresh tokens. Refresh rotates.
"""

import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from auth import require_user_id
from ratelimit import enforce as rate_limit
import oauth

router = APIRouter(tags=["oauth"])

# Backend (this API) — the OAuth issuer + resource server. Reuses the same env
# render.yaml already sets. The frontend hosts the consent UI.
BACKEND_BASE = os.getenv("WEBHOOK_BASE_URL", "https://meeting-copilot-api.onrender.com").rstrip("/")
APP_BASE = os.getenv("APP_BASE_URL", "https://www.meetprismai.com").rstrip("/")
_CONSENT_PATH = "/#oauth-consent"  # hash route in the SPA (host-agnostic)


def _oauth_error(error: str, description: str = "", status: int = 400) -> JSONResponse:
    body = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


# ─────────────────────── discovery metadata ───────────────────────

@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    # RFC 9728 — points Claude from the resource (/mcp) to our authorization server.
    return JSONResponse({
        "resource": f"{BACKEND_BASE}/mcp",
        "authorization_servers": [BACKEND_BASE],
        "scopes_supported": [oauth.DEFAULT_SCOPE],
        "bearer_methods_supported": ["header"],
    })


# Also serve it under the /mcp-suffixed path some clients probe.
@router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata_mcp():
    return await protected_resource_metadata()


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    # RFC 8414 — advertises our endpoints. PKCE S256 mandatory; public clients.
    return JSONResponse({
        "issuer": BACKEND_BASE,
        "authorization_endpoint": f"{BACKEND_BASE}/oauth/authorize",
        "token_endpoint": f"{BACKEND_BASE}/oauth/token",
        "registration_endpoint": f"{BACKEND_BASE}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [oauth.DEFAULT_SCOPE],
    })


# ─────────────────────── dynamic client registration ───────────────────────

@router.post("/oauth/register")
async def register(request: Request):
    rate_limit(request, "oauth_register", 20, detail="Too many registration requests.")
    try:
        body = await request.json()
    except Exception:
        return _oauth_error("invalid_client_metadata", "Body must be JSON.")
    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error("invalid_redirect_uri", "redirect_uris is required.")
    client_name = body.get("client_name") or "MCP client"
    try:
        reg = oauth.register_client(client_name, redirect_uris, public=True)
    except RuntimeError:
        return _oauth_error("server_error", "Registration unavailable.", status=503)
    # RFC 7591 response.
    return JSONResponse(status_code=201, content={
        "client_id": reg["client_id"],
        "client_id_issued_at": 0,
        "redirect_uris": reg["redirect_uris"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": client_name,
    }, headers={"Cache-Control": "no-store"})


# ─────────────────────── authorization endpoint ───────────────────────

@router.get("/oauth/authorize")
async def authorize(request: Request,
                    response_type: str = "", client_id: str = "", redirect_uri: str = "",
                    code_challenge: str = "", code_challenge_method: str = "",
                    scope: str = "", state: str = ""):
    """Validate the request, then hand off to the frontend consent page. On an
    invalid client/redirect we must NOT redirect (open-redirect guard) — show 400.
    Other errors redirect back to the client with an error code (per OAuth)."""
    client = oauth.get_client(client_id)
    if not client or not oauth.redirect_uri_allowed(client, redirect_uri):
        return _oauth_error("invalid_request", "Unknown client_id or redirect_uri.")

    def _err_redirect(err: str):
        q = {"error": err, **({"state": state} if state else {})}
        return RedirectResponse(f"{redirect_uri}?{urlencode(q)}", status_code=302)

    if response_type != "code":
        return _err_redirect("unsupported_response_type")
    if not code_challenge or code_challenge_method != "S256":
        return _err_redirect("invalid_request")

    # Hand off to the consent UI. The params aren't secret (code_challenge is the
    # public half of PKCE); the user authenticates + approves there.
    q = urlencode({
        "client_id": client_id,
        "client_name": client.get("client_name") or "An application",
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "scope": scope or oauth.DEFAULT_SCOPE,
        "state": state,
    })
    return RedirectResponse(f"{APP_BASE}{_CONSENT_PATH}?{q}", status_code=302)


class ApproveRequest(BaseModel):
    client_id: str
    redirect_uri: str
    code_challenge: str
    scope: str | None = None
    state: str | None = None


@router.post("/oauth/authorize/approve")
async def approve(req: ApproveRequest, user_id: str = Depends(require_user_id)):
    """Called by the consent page AFTER the user (authenticated via Supabase) clicks
    Allow. Re-validates the client+redirect, mints a PKCE-bound code for THIS user,
    and returns the redirect URL back to the OAuth client."""
    client = oauth.get_client(req.client_id)
    if not client or not oauth.redirect_uri_allowed(client, req.redirect_uri):
        return _oauth_error("invalid_request", "Unknown client_id or redirect_uri.")
    code = oauth.issue_auth_code(
        req.client_id, user_id, req.redirect_uri, req.code_challenge, req.scope or oauth.DEFAULT_SCOPE
    )
    q = {"code": code, **({"state": req.state} if req.state else {})}
    return {"redirect_to": f"{req.redirect_uri}?{urlencode(q)}"}


# ─────────────────────── token endpoint ───────────────────────

@router.post("/oauth/token")
async def token(request: Request,
                grant_type: str = Form(""),
                code: str = Form(""),
                redirect_uri: str = Form(""),
                client_id: str = Form(""),
                code_verifier: str = Form(""),
                refresh_token: str = Form("")):
    rate_limit(request, "oauth_token", 60, detail="Too many token requests.")

    if grant_type == "authorization_code":
        if not (code and client_id and redirect_uri and code_verifier):
            return _oauth_error("invalid_request", "Missing required parameters.")
        result = oauth.exchange_auth_code(code, code_verifier, redirect_uri, client_id)
        if not result:
            return _oauth_error("invalid_grant", "Invalid or expired authorization code.")
        tokens = oauth.issue_tokens_for_code(client_id, result["user_id"], result["scope"])
        return JSONResponse(tokens, headers={"Cache-Control": "no-store"})

    if grant_type == "refresh_token":
        if not (refresh_token and client_id):
            return _oauth_error("invalid_request", "Missing required parameters.")
        tokens = oauth.rotate_refresh_token(refresh_token, client_id)
        if not tokens:
            return _oauth_error("invalid_grant", "Invalid or expired refresh token.")
        return JSONResponse(tokens, headers={"Cache-Control": "no-store"})

    return _oauth_error("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

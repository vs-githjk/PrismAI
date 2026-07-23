"""Sandbox routes — Phase 1 of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md.
Pivot: docs/adr/0003-present-via-managed-browser-not-e2b-desktop.md (E2B →
Browserbase — the default provider is now a managed cloud browser).

Two auth-gated endpoints over the caller's per-user presentation surface
(`backend/sandbox/` — provider abstraction; Browserbase adapter by default, the
E2B desktop as a fallback selected by PRISM_SANDBOX_PROVIDER):

- POST /sandbox/setup  — get-or-create the caller's workspace ("Set up my AI
  workspace"), persist the ref to `user_settings` whenever a NEW one is
  provisioned, and return the login/view URLs. The interactive URL is the
  owner's setup-login surface only and must never appear in any meeting-facing
  payload (Phase 3 concern — this endpoint only answers the authenticated owner).
- GET  /sandbox/status — cheap provisioned/running probe. Never creates.

Column mapping (user_settings) — one durable id column, two adapters:
  Browserbase (default): sandbox_id ← the persistent Context id (holds the
    user's logins). sandbox_auth_key / sandbox_stream_url are unused ("") — a
    Session (with its live URLs) is minted per resume() and never persisted.
  E2B (fallback): sandbox_id ← SandboxRef.sandbox_id, sandbox_auth_key ←
    SandboxRef.auth_key, sandbox_stream_url ← SandboxRef.stream_base (the noVNC
    password is generated client-side at the one and only stream.start() and is
    UNRECOVERABLE later, so a fresh E2B ref must be persisted immediately).
The auth key (E2B) is never returned on its own — it only ever appears embedded
in the URLs the provider builds.

Both provider SDKs are synchronous (e2b-desktop has no async desktop Sandbox;
the Browserbase REST + Playwright sync APIs are sync by design), so every
provider call is wrapped in asyncio.to_thread to keep the event loop unblocked.
Same for the sync Supabase client.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_user_id, supabase
from sandbox import SandboxRef, get_provider

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

_SETTINGS_COLS = "sandbox_id,sandbox_auth_key,sandbox_stream_url"

# ponytail: in-process per-user lock is enough at this scale (single backend
# instance) — it stops two concurrent /sandbox/setup calls from both seeing
# "no sandbox" and provisioning two (one would leak, billed until idle-pause).
_setup_locks: dict[str, asyncio.Lock] = {}


def _require_db():
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")


# The env key each provider's SDK reads (+ where to get it). Checking it here
# turns a cryptic SDK exception into an actionable 503 operator message.
_PROVIDER_KEY = {
    "browserbase": ("BROWSERBASE_API_KEY", "https://www.browserbase.com/settings"),
    "e2b": ("E2B_API_KEY", "https://e2b.dev/dashboard"),
}


def _provider_name() -> str:
    # Mirror sandbox.provider.get_provider's default so the key check AND the
    # rebuilt ref shape match the provider that will actually be resolved.
    return (os.getenv("PRISM_SANDBOX_PROVIDER") or "browserbase").strip().lower()


def _provider_key_present() -> bool:
    """Is the selected provider's API key configured? Unknown provider → False,
    so /status reports what the DB knows instead of asking an absent SDK."""
    entry = _PROVIDER_KEY.get(_provider_name())
    return bool(entry and os.environ.get(entry[0]))


def _require_provider_key() -> None:
    entry = _PROVIDER_KEY.get(_provider_name())
    if entry is None:
        # Unknown provider: let _provider() surface the misconfiguration as 503.
        return
    env, url = entry
    if not os.environ.get(env):
        raise HTTPException(
            status_code=503,
            detail=(
                f"Sandbox provider is not configured: {env} is missing. "
                f"Add it to backend/.env (keys at {url})."
            ),
        )


def _provider():
    """Resolve the provider singleton, mapping config/import failures to 503."""
    try:
        return get_provider()
    except Exception as e:  # unknown PRISM_SANDBOX_PROVIDER, missing SDK, ...
        raise HTTPException(
            status_code=503, detail=f"Sandbox provider unavailable: {e}"
        )


async def _load_sandbox_row(user_id: str, strict: bool = False) -> dict:
    """The caller's stored sandbox columns; {} when no user_settings row yet.

    A missing row is NOT an exception: maybe_single() returns None for zero
    rows (verified against installed postgrest), so anything raised here is a
    real database error. strict=True surfaces that as a 503 — /setup must
    never mistake a DB blip for "no sandbox", or it would provision a
    duplicate and overwrite the stored ref, orphaning the user's logged-in
    sandbox (its auth key is unrecoverable) forever.
    """
    try:
        resp = await asyncio.to_thread(
            lambda: supabase.table("user_settings")
            .select(_SETTINGS_COLS)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return (resp.data if resp else None) or {}
    except Exception:
        if strict:
            raise HTTPException(
                status_code=503,
                detail="Could not read sandbox settings — please retry.",
            )
        # Lightweight probes (/status): non-fatal, report what we know.
        return {}


def _ref_from_row(row: dict) -> Optional[SandboxRef]:
    """Rebuild a SandboxRef from the stored columns, per the selected provider.

    E2B needs all three columns (id + noVNC password + stream URL). Browserbase
    (and any future browser-style adapter) stores only the durable Context id in
    sandbox_id; auth_key/stream_base are unused and a Session is minted per
    resume(). Requiring all three there would treat every provisioned Context as
    "not set up" and provision a fresh one on every call — orphaning the user's
    logged-in Context — so build a Context-only ref whenever the id is present.
    """
    sandbox_id = row.get("sandbox_id")
    if not sandbox_id:
        return None
    if _provider_name() == "e2b":
        auth_key = row.get("sandbox_auth_key")
        stream_base = row.get("sandbox_stream_url")
        if auth_key and stream_base:
            return SandboxRef(
                sandbox_id=sandbox_id, auth_key=auth_key, stream_base=stream_base
            )
        return None
    return SandboxRef(sandbox_id=sandbox_id, context_id=sandbox_id)


async def _persist_ref(user_id: str, ref: SandboxRef) -> None:
    await asyncio.to_thread(
        lambda: supabase.table("user_settings")
        .upsert(
            {
                "user_id": user_id,
                "sandbox_id": ref.sandbox_id,
                "sandbox_auth_key": ref.auth_key,
                "sandbox_stream_url": ref.stream_base,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id",
        )
        .execute()
    )


@router.post("/setup")
async def sandbox_setup(user_id: str = Depends(require_user_id)):
    """Get-or-create the caller's persistent sandbox and return its URLs.

    Idempotent: an alive (running OR paused) stored sandbox is resumed and
    reused; a missing/expired one is replaced by a fresh create, whose new
    ref (id + auth key + stream URL) is persisted immediately.
    """
    _require_db()
    _require_provider_key()
    # First _provider() call lazy-imports the provider SDK (slow, sync) — keep
    # it off the event loop like every other provider call.
    provider = await asyncio.to_thread(_provider)

    # Serialize per user: without this, two concurrent setups both read "no
    # sandbox" and provision two (the loser is orphaned, billed until its
    # idle-pause). The lock covers the read-create-persist window so the
    # second caller re-reads the row the first one just persisted.
    lock = _setup_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        existing = _ref_from_row(await _load_sandbox_row(user_id, strict=True))

        try:
            # Idempotent get-or-create: returns `existing` untouched when that
            # sandbox is still resumable, else provisions fresh (new id AND key).
            ref = await asyncio.to_thread(provider.ensure_sandbox, existing)
            created = existing is None or ref.sandbox_id != existing.sandbox_id
            if not created:
                # Reused workspace: resume so the interactive setup session is
                # live and usable (E2B: wake the paused sandbox + bump idle TTL;
                # Browserbase: mint/reuse a Session bound to the persistent
                # Context). A freshly-created one is already live (E2B) or has its
                # Session minted lazily by the URL getters below (Browserbase).
                await asyncio.to_thread(provider.resume, ref)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Sandbox provider error: {e}")

        if created:
            try:
                await _persist_ref(user_id, ref)
            except Exception:
                # An unpersisted ref means the auth key is lost after this
                # request — the sandbox would be forever unviewable. Park it
                # (billing stops) and surface the failure instead of handing
                # out URLs the next request can't rebuild.
                try:
                    await asyncio.to_thread(provider.pause, ref)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=502,
                    detail="Sandbox was provisioned but its credentials could not "
                    "be saved — please retry setup.",
                )

    # The URL getters are provider calls too: for Browserbase they mint/inspect a
    # Session (network I/O), so keep them off the event loop like every other
    # provider call. interactive_url is the responsive WebRTC login surface;
    # view_url is the (for now identical) watch URL — see the provider adapter.
    interactive_url = await asyncio.to_thread(provider.interactive_url, ref)
    view_url = await asyncio.to_thread(provider.view_url, ref)
    return {
        "interactive_url": interactive_url,
        "view_url": view_url,
        "created": created,
    }


@router.get("/status")
async def sandbox_status(user_id: str = Depends(require_user_id)):
    """Cheap probe: is a sandbox provisioned, and does it still exist?

    `running` is provider "alive" (running OR paused = resumable); null when
    nothing is provisioned or the provider can't be asked. Never creates.
    """
    _require_db()

    ref = _ref_from_row(await _load_sandbox_row(user_id))
    if ref is None:
        return {"provisioned": False, "running": None}
    if not _provider_key_present():
        # Can't ask the provider — report what the DB knows rather than
        # failing a lightweight dashboard poll.
        return {"provisioned": True, "running": None}

    try:
        provider = await asyncio.to_thread(_provider)  # lazy SDK import is sync
        alive = await asyncio.to_thread(provider.is_alive, ref)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sandbox provider error: {e}")
    return {"provisioned": True, "running": bool(alive)}

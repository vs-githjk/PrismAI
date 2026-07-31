import asyncio
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# Quiet pipecat's default DEBUG logging (loguru). Left at DEBUG it emits several lines
# PER SECOND per bot (every VAD start/stop, every turn boundary, every frame link) — a
# flood that backs up Render's log pipe (observed: logs arriving ~3 min late) and burns
# stdout I/O on a small instance. INFO keeps the useful reconnect/error lines and drops
# the per-frame noise. Our own diagnostics use print(), not loguru, so they're unaffected.
# Env-overridable back to DEBUG for a deep voice-pipeline debugging session.
try:
    import sys as _sys
    from loguru import logger as _loguru_logger
    _loguru_logger.remove()
    _loguru_logger.add(_sys.stderr, level=os.getenv("PRISM_PIPECAT_LOG_LEVEL", "INFO"))
except Exception as _log_exc:  # loguru absent / misconfigured must never block boot
    print(f"WARNING [main] could not set pipecat log level: {_log_exc!r}")

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from analysis_routes import create_analysis_router
from auth_routes import router as auth_helper_router
from calendar_routes import router as calendar_router
from ms_calendar_routes import router as ms_calendar_router
from chat_routes import create_chat_router, router as chat_router
from clients import DEFAULT_TIMEOUT, bind as bind_clients
from export_routes import router as export_router
from actions_routes import router as actions_router
from migrations import run_migrations
from present_routes import router as present_router
from realtime_routes import router as realtime_router
from recall_routes import router as recall_router
from knowledge_routes import router as knowledge_router
from sandbox_routes import router as sandbox_router
from storage_routes import router as storage_router
from warmup import warm_external_connections
from proxy_routes import router as proxy_router
from workspace_routes import router as workspace_router
from voice.audio_routes import router as voice_router
from pat_routes import router as pat_router
from notifications_routes import router as notifications_router


openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(run_migrations)
    app.state.http = httpx.AsyncClient(http2=True, timeout=DEFAULT_TIMEOUT)
    app.state.openai = openai_client
    bind_clients(app)
    # Pre-open the slow external connections (OpenAI ~9s cold, Supabase ~4s
    # cold) without blocking startup — fire-and-forget.
    asyncio.create_task(warm_external_connections("startup"))
    # Re-attach lifecycle pollers for any bots left mid-flight by a previous process
    # (restart / cold start) so headless stand-ins still get delivered, analysed, and
    # promoted to the dashboard without a browser or webhook. Best-effort, non-blocking.
    from recall_routes import recover_active_bots
    asyncio.create_task(recover_active_bots())
    # #9: server-side meeting_soon reminder scanner (fires 5-min-before even with
    # the tab closed). Opted-in users only; no-op when no push subscriptions exist.
    from reminders import reminder_loop
    asyncio.create_task(reminder_loop())
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="Prism", lifespan=lifespan)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,https://agentic-meeting-copilot.vercel.app,https://meetprismai.com,https://www.meetprismai.com")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Coarse global body-size backstop. Set ABOVE the largest legit upload (knowledge
# = 50MB + multipart overhead) so it only rejects absurd bodies; the per-route
# caps (25MB /transcribe, 50MB /upload) still do the fine-grained enforcement.
# Best-effort: relies on Content-Length (absent on chunked bodies).
_MAX_BODY_BYTES = 60 * 1024 * 1024


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large."})
        except ValueError:
            pass
    response = await call_next(request)
    # Defense-in-depth response headers. This is a JSON API (plus a couple of
    # small server-rendered pages); a strict CSP isn't set here to avoid breaking
    # those — the SPA's CSP belongs on the frontend host.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response

app.include_router(auth_helper_router)  # POST /auth/provider-hint — OAuth-only account hint for the login dialog
app.include_router(storage_router)
app.include_router(proxy_router)
app.include_router(knowledge_router)
app.include_router(workspace_router)
app.include_router(recall_router)
app.include_router(export_router)
app.include_router(actions_router)
app.include_router(calendar_router)
app.include_router(ms_calendar_router)
app.include_router(realtime_router)
app.include_router(sandbox_router)
app.include_router(present_router)
app.include_router(voice_router)  # /voice/audio-in + /voice/speaker + /voice/speaker-page
app.include_router(pat_router)  # /account/tokens — MCP connector credentials
app.include_router(notifications_router)  # /notifications — #9 notification center + Web Push
from mcp_server import router as mcp_router
app.include_router(mcp_router)  # POST /mcp — Claude/ChatGPT connector (Streamable HTTP)
from oauth_routes import router as oauth_router
app.include_router(oauth_router)  # OAuth 2.1 AS for the Claude connector

app.include_router(create_analysis_router(openai_client))
app.include_router(create_chat_router(openai_client))
app.include_router(chat_router)  # /chat/upload-image + /chat/sign (module-level router)


@app.get("/health")
async def health():
    from caches import cache_stats
    from personas import cache_stats as persona_cache_stats
    return {
        "status": "ok",
        "caches": {
            "workspace_ids": cache_stats(),
            "personas": persona_cache_stats(),
        },
    }

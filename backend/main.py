import asyncio
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from analysis_routes import create_analysis_router
from calendar_routes import router as calendar_router
from chat_routes import create_chat_router
from clients import DEFAULT_TIMEOUT, bind as bind_clients
from export_routes import router as export_router
from migrations import run_migrations
from realtime_routes import router as realtime_router
from recall_routes import router as recall_router
from knowledge_routes import router as knowledge_router
from storage_routes import router as storage_router
from workspace_routes import router as workspace_router


openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(run_migrations)
    app.state.http = httpx.AsyncClient(http2=True, timeout=DEFAULT_TIMEOUT)
    app.state.openai = openai_client
    bind_clients(app)
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="Prism", lifespan=lifespan)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,https://agentic-meeting-copilot.vercel.app")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(storage_router)
app.include_router(knowledge_router)
app.include_router(workspace_router)
app.include_router(recall_router)
app.include_router(export_router)
app.include_router(calendar_router)
app.include_router(realtime_router)

app.include_router(create_analysis_router(openai_client))
app.include_router(create_chat_router(openai_client))


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

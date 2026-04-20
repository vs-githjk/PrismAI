import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq

from analysis_routes import create_analysis_router
from calendar_routes import router as calendar_router
from chat_routes import create_chat_router
from export_routes import router as export_router
from realtime_routes import router as realtime_router
from recall_routes import router as recall_router
from storage_routes import router as storage_router

app = FastAPI(title="Agentic Meeting Copilot")

_raw_origins = os.getenv("ALLOWED_ORIGINS", "https://agentic-meeting-copilot.vercel.app,http://localhost:5173")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(storage_router)
app.include_router(recall_router)
app.include_router(export_router)
app.include_router(calendar_router)
app.include_router(realtime_router)

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
app.include_router(create_analysis_router(groq_client))
app.include_router(create_chat_router(groq_client))


@app.get("/health")
async def health():
    return {"status": "ok"}

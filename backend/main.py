import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import AsyncGroq

from agents import orchestrator, summarizer, action_items, sentiment, email_drafter, calendar_suggester, health_score

app = FastAPI(title="Agentic Meeting Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

AGENT_MAP = {
    "summarizer": summarizer.run,
    "action_items": action_items.run,
    "sentiment": sentiment.run,
    "email_drafter": email_drafter.run,
    "calendar_suggester": calendar_suggester.run,
    "health_score": health_score.run,
}

DEFAULT_RESULT = {
    "summary": "",
    "action_items": [],
    "sentiment": {"overall": "neutral", "score": 50, "notes": ""},
    "follow_up_email": {"subject": "", "body": ""},
    "calendar_suggestion": {"recommended": False, "reason": "", "suggested_timeframe": ""},
    "health_score": {"score": 0, "verdict": "", "badges": [], "breakdown": {"clarity": 0, "action_orientation": 0, "engagement": 0}},
    "agents_run": [],
}


class AnalyzeRequest(BaseModel):
    transcript: str


class ChatRequest(BaseModel):
    message: str
    transcript: str = ""


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    agents_to_run = await orchestrator.run_orchestrator(req.transcript)

    # Run selected agents in parallel
    valid_agents = [a for a in agents_to_run if a in AGENT_MAP]
    tasks = [AGENT_MAP[agent](req.transcript) for agent in valid_agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    result = dict(DEFAULT_RESULT)
    result["agents_run"] = valid_agents

    for agent_name, agent_result in zip(valid_agents, results):
        if isinstance(agent_result, Exception):
            # Skip failed agents gracefully
            continue
        if agent_name == "summarizer":
            result["summary"] = agent_result.get("summary", "")
        elif agent_name == "action_items":
            result["action_items"] = agent_result.get("action_items", [])
        elif agent_name == "sentiment":
            result["sentiment"] = agent_result.get("sentiment", DEFAULT_RESULT["sentiment"])
        elif agent_name == "email_drafter":
            result["follow_up_email"] = agent_result.get("follow_up_email", DEFAULT_RESULT["follow_up_email"])
        elif agent_name == "calendar_suggester":
            result["calendar_suggestion"] = agent_result.get("calendar_suggestion", DEFAULT_RESULT["calendar_suggestion"])
        elif agent_name == "health_score":
            result["health_score"] = agent_result.get("health_score", DEFAULT_RESULT["health_score"])

    return result


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 25MB.")
    try:
        transcription = await groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=(file.filename, content, file.content_type or "audio/mpeg"),
        )
        return {"transcript": transcription.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@app.post("/chat")
async def chat(req: ChatRequest):
    context = ""
    if req.transcript.strip():
        context = f"\n\nMeeting transcript for context:\n{req.transcript[:3000]}"

    response = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful meeting assistant. Answer questions about the meeting transcript concisely."
                    + context
                ),
            },
            {"role": "user", "content": req.message},
        ],
    )
    return {"response": response.choices[0].message.content}

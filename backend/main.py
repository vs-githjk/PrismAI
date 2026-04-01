import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import AsyncGroq

from agents import orchestrator, summarizer, action_items, decisions, sentiment, email_drafter, calendar_suggester, health_score

app = FastAPI(title="Agentic Meeting Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")

# In-memory store: bot_id → { status, result, error, transcript }
bot_store: dict = {}

AGENT_MAP = {
    "summarizer": summarizer.run,
    "action_items": action_items.run,
    "decisions": decisions.run,
    "sentiment": sentiment.run,
    "email_drafter": email_drafter.run,
    "calendar_suggester": calendar_suggester.run,
    "health_score": health_score.run,
}

DEFAULT_RESULT = {
    "summary": "",
    "action_items": [],
    "decisions": [],
    "sentiment": {"overall": "neutral", "score": 50, "arc": "stable", "notes": "", "speakers": [], "tension_moments": []},
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
        elif agent_name == "decisions":
            result["decisions"] = agent_result.get("decisions", [])
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


class JoinMeetingRequest(BaseModel):
    meeting_url: str


@app.post("/join-meeting")
async def join_meeting(req: JoinMeetingRequest):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")
    if not req.meeting_url.strip():
        raise HTTPException(status_code=400, detail="Meeting URL cannot be empty")

    webhook_url = f"{WEBHOOK_BASE_URL}/recall-webhook"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RECALL_API_BASE}/bot/",
            headers={
                "Authorization": f"Token {RECALL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "meeting_url": req.meeting_url,
                "bot_name": "PrismAI",
                "webhook_url": webhook_url,
            },
            timeout=15,
        )

    if resp.status_code not in (200, 201):
        detail = resp.json().get("detail") or resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai error: {detail}")

    data = resp.json()
    bot_id = data["id"]
    bot_store[bot_id] = {"status": "joining", "result": None, "error": None}

    # Send intro message once bot joins
    asyncio.create_task(_send_bot_intro(bot_id))

    return {"bot_id": bot_id, "status": "joining"}


@app.get("/bot-status/{bot_id}")
async def bot_status(bot_id: str):
    # Always check Recall.ai directly for live status
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RECALL_API_BASE}/bot/{bot_id}/",
            headers={"Authorization": f"Token {RECALL_API_KEY}"},
            timeout=10,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Bot not found")

    recall_data = resp.json()
    recall_status = recall_data.get("status_changes", [{}])[-1].get("code", "") if recall_data.get("status_changes") else ""

    # Map Recall status to our simplified states
    status_map = {
        "joining_call": "joining",
        "in_call_not_recording": "joining",
        "in_call_recording": "recording",
        "call_ended": "processing",
        "done": "done",
        "fatal_error": "error",
    }
    our_status = status_map.get(recall_status, bot_store.get(bot_id, {}).get("status", "joining"))

    # If call ended and we haven't processed yet, kick off processing
    if recall_status in ("call_ended", "done") and bot_id not in bot_store:
        bot_store[bot_id] = {"status": "processing", "result": None, "error": None}
        asyncio.create_task(_process_bot_transcript(bot_id))

    entry = bot_store.get(bot_id, {"status": our_status, "result": None, "error": None})
    entry["status"] = our_status if entry.get("status") not in ("done", "error") else entry["status"]
    return entry


@app.post("/recall-webhook")
async def recall_webhook(request: Request):
    payload = await request.json()

    # Recall.ai sends different event shapes — handle both v1 and v2
    bot_id = (
        payload.get("data", {}).get("bot", {}).get("id")
        or payload.get("bot_id")
        or payload.get("id")
    )
    event = (
        payload.get("event")
        or payload.get("data", {}).get("status", {}).get("code")
        or ""
    )

    if not bot_id:
        return {"ok": True}

    if bot_id not in bot_store:
        bot_store[bot_id] = {"status": "unknown", "result": None, "error": None}

    # Map Recall status codes to our simplified states
    if event in ("bot.joining_call", "joining_call"):
        bot_store[bot_id]["status"] = "joining"
    elif event in ("bot.in_call_recording", "in_call_recording"):
        bot_store[bot_id]["status"] = "recording"
    elif event in ("bot.call_ended", "call_ended", "bot.done", "done"):
        bot_store[bot_id]["status"] = "processing"
        asyncio.create_task(_process_bot_transcript(bot_id))
    elif event in ("bot.fatal_error", "fatal_error"):
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = "Bot encountered a fatal error"

    return {"ok": True}


async def _send_bot_intro(bot_id: str):
    """Wait for bot to join then send an intro message in the meeting chat."""
    await asyncio.sleep(20)  # Give the bot time to join before messaging
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{RECALL_API_BASE}/bot/{bot_id}/send_chat_message/",
                headers={
                    "Authorization": f"Token {RECALL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"message": "Hi, I'm PrismAI 👋 I'm here to observe and help you get the most out of this meeting. I'll send you a full analysis when we're done."},
                timeout=10,
            )
    except Exception:
        pass  # Non-critical — don't affect main flow


async def _process_bot_transcript(bot_id: str):
    """Fetch transcript from Recall.ai and run it through the agent pipeline."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{RECALL_API_BASE}/bot/{bot_id}/transcript/",
                headers={"Authorization": f"Token {RECALL_API_KEY}"},
                timeout=30,
            )
        if resp.status_code != 200:
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = "Failed to fetch transcript from Recall.ai"
            return

        words = resp.json()
        # Recall returns [{speaker, words: [{text, start_time, end_time}]}]
        transcript_lines = []
        for segment in words:
            speaker = segment.get("speaker") or "Speaker"
            text = " ".join(w.get("text", "") for w in segment.get("words", []))
            if text.strip():
                transcript_lines.append(f"{speaker}: {text.strip()}")
        transcript = "\n".join(transcript_lines)

        if not transcript.strip():
            bot_store[bot_id]["status"] = "error"
            bot_store[bot_id]["error"] = "No transcript content found"
            return

        bot_store[bot_id]["transcript"] = transcript

        # Run through existing agent pipeline
        agents_to_run = await orchestrator.run_orchestrator(transcript)
        valid_agents = [a for a in agents_to_run if a in AGENT_MAP]
        tasks = [AGENT_MAP[agent](transcript) for agent in valid_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result = dict(DEFAULT_RESULT)
        result["agents_run"] = valid_agents
        for agent_name, agent_result in zip(valid_agents, results):
            if isinstance(agent_result, Exception):
                continue
            if agent_name == "summarizer":
                result["summary"] = agent_result.get("summary", "")
            elif agent_name == "action_items":
                result["action_items"] = agent_result.get("action_items", [])
            elif agent_name == "decisions":
                result["decisions"] = agent_result.get("decisions", [])
            elif agent_name == "sentiment":
                result["sentiment"] = agent_result.get("sentiment", DEFAULT_RESULT["sentiment"])
            elif agent_name == "email_drafter":
                result["follow_up_email"] = agent_result.get("follow_up_email", DEFAULT_RESULT["follow_up_email"])
            elif agent_name == "calendar_suggester":
                result["calendar_suggestion"] = agent_result.get("calendar_suggestion", DEFAULT_RESULT["calendar_suggestion"])
            elif agent_name == "health_score":
                result["health_score"] = agent_result.get("health_score", DEFAULT_RESULT["health_score"])

        bot_store[bot_id]["result"] = result
        bot_store[bot_id]["status"] = "done"

    except Exception as e:
        bot_store[bot_id]["status"] = "error"
        bot_store[bot_id]["error"] = str(e)


class AgentRequest(BaseModel):
    agent: str
    transcript: str
    instruction: str = ""


@app.post("/agent")
async def run_agent(req: AgentRequest):
    if req.agent not in AGENT_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent}")
    # Append the user's instruction to the transcript as context
    augmented = req.transcript
    if req.instruction:
        augmented += f"\n\n[User instruction: {req.instruction}]"
    result = await AGENT_MAP[req.agent](augmented)
    return result


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

import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import AsyncGroq
from supabase import create_client, Client as SupabaseClient

from agents import orchestrator, summarizer, action_items, decisions, sentiment, email_drafter, calendar_suggester, health_score

app = FastAPI(title="Agentic Meeting Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

_sb_url = os.getenv("SUPABASE_URL", "")
_sb_key = os.getenv("SUPABASE_KEY", "")
supabase: SupabaseClient = create_client(_sb_url, _sb_key) if _sb_url and _sb_key else None

RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
RECALL_API_BASE = "https://us-west-2.recall.ai/api/v1"
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")

# In-memory store: bot_id → { status, result, error, transcript }
bot_store: dict = {}


def _extract_recall_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail

    text = (resp.text or "").strip()
    return text or f"Recall.ai request failed with status {resp.status_code}"

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
    speakers: list = []


class ChatRequest(BaseModel):
    message: str
    transcript: str = ""


class GlobalChatRequest(BaseModel):
    message: str
    limit: int = 10


class NotionExportRequest(BaseModel):
    token: str
    parent_page_id: str
    title: str
    result: dict


class SlackExportRequest(BaseModel):
    webhook_url: str
    title: str
    result: dict


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Meeting history ────────────────────────────────────────────────

class MeetingEntry(BaseModel):
    id: int
    date: str
    title: str = ""
    score: int = None
    transcript: str = ""
    result: dict = {}
    share_token: str = ""


@app.get("/meetings")
async def get_meetings(q: str = Query(default="")):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    query = supabase.table("meetings").select("id,date,title,score,transcript,result,share_token").order("id", desc=True).limit(50)
    if q.strip():
        query = query.ilike("title", f"%{q}%")
    res = query.execute()
    return res.data


@app.post("/meetings")
async def save_meeting(entry: MeetingEntry):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    supabase.table("meetings").upsert({
        "id": entry.id,
        "date": entry.date,
        "title": entry.title,
        "score": entry.score,
        "transcript": entry.transcript,
        "result": entry.result,
        "share_token": entry.share_token or None,
    }).execute()
    return {"ok": True}


@app.get("/share/{token}")
async def get_shared_meeting(token: str):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    res = supabase.table("meetings").select("title,date,result,score").eq("share_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Share link not found")
    return res.data[0]


@app.delete("/meetings/{meeting_id}")
async def delete_meeting(meeting_id: int):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    supabase.table("meetings").delete().eq("id", meeting_id).execute()
    return {"ok": True}


class MeetingPatch(BaseModel):
    result: dict


@app.patch("/meetings/{meeting_id}")
async def patch_meeting(meeting_id: int, patch: MeetingPatch):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    supabase.table("meetings").update({"result": patch.result}).eq("id", meeting_id).execute()
    return {"ok": True}


# ── Chat history ───────────────────────────────────────────────────

class ChatEntry(BaseModel):
    messages: list


@app.get("/chats")
async def get_all_chats():
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    res = supabase.table("chats").select("meeting_id,messages").execute()
    return {str(row["meeting_id"]): row["messages"] for row in res.data}


@app.get("/chats/{meeting_id}")
async def get_chat(meeting_id: int):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    res = supabase.table("chats").select("messages").eq("meeting_id", meeting_id).limit(1).execute()
    if res.data:
        return {"messages": res.data[0]["messages"]}
    return {"messages": []}


@app.post("/chats/{meeting_id}")
async def save_chat(meeting_id: int, entry: ChatEntry):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    existing = supabase.table("chats").select("id").eq("meeting_id", meeting_id).limit(1).execute()
    if existing.data:
        supabase.table("chats").update({"messages": entry.messages}).eq("meeting_id", meeting_id).execute()
    else:
        supabase.table("chats").insert({"meeting_id": meeting_id, "messages": entry.messages}).execute()
    return {"ok": True}


@app.delete("/chats/{meeting_id}")
async def delete_chat(meeting_id: int):
    if not supabase:
        raise HTTPException(status_code=503, detail="Storage not configured")
    supabase.table("chats").delete().eq("meeting_id", meeting_id).execute()
    return {"ok": True}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    transcript = req.transcript
    if req.speakers:
        lines = ["Meeting participants:"]
        for s in req.speakers:
            name = (s.get("name") or "").strip()
            role = (s.get("role") or "").strip()
            if name:
                lines.append(f"  - {name}: {role}" if role else f"  - {name}")
        transcript = "\n".join(lines) + "\n\n" + transcript

    agents_to_run = await orchestrator.run_orchestrator(transcript)

    # Run selected agents in parallel
    valid_agents = [a for a in agents_to_run if a in AGENT_MAP]
    tasks = [AGENT_MAP[agent](transcript) for agent in valid_agents]
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


AGENT_RESULT_KEY = {
    "summarizer": "summary",
    "action_items": "action_items",
    "decisions": "decisions",
    "sentiment": "sentiment",
    "email_drafter": "follow_up_email",
    "calendar_suggester": "calendar_suggestion",
    "health_score": "health_score",
}


@app.post("/analyze-stream")
async def analyze_stream(req: AnalyzeRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    transcript = req.transcript
    if req.speakers:
        lines = ["Meeting participants:"]
        for s in req.speakers:
            name = (s.get("name") or "").strip()
            role = (s.get("role") or "").strip()
            if name:
                lines.append(f"  - {name}: {role}" if role else f"  - {name}")
        transcript = "\n".join(lines) + "\n\n" + transcript

    agents_to_run = await orchestrator.run_orchestrator(transcript)
    valid_agents = [a for a in agents_to_run if a in AGENT_MAP]

    async def event_stream():
        # Send agents_run first so frontend knows what to expect
        yield f"data: {json.dumps({'agents_run': valid_agents})}\n\n"

        async def run_agent(name):
            result = await AGENT_MAP[name](transcript)
            return name, result

        tasks = {asyncio.ensure_future(run_agent(name)): name for name in valid_agents}
        pending = set(tasks.keys())
        succeeded_agents = []

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    agent_name, agent_result = task.result()
                    key = AGENT_RESULT_KEY.get(agent_name)
                    if key and key in agent_result:
                        payload = {"agent": agent_name, key: agent_result[key]}
                        yield f"data: {json.dumps(payload)}\n\n"
                        succeeded_agents.append(agent_name)
                except Exception:
                    pass

        # Correct agents_run to only include agents that actually succeeded
        yield f"data: {json.dumps({'agents_run': succeeded_agents})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai error: {detail}")

    data = resp.json()
    bot_id = data["id"]
    bot_store[bot_id] = {"status": "joining", "result": None, "error": None}

    # Send intro message once bot joins
    asyncio.create_task(_send_bot_intro(bot_id))

    return {"bot_id": bot_id, "status": "joining"}


@app.get("/bot-status/{bot_id}")
async def bot_status(bot_id: str):
    if not RECALL_API_KEY:
        raise HTTPException(status_code=500, detail="Recall.ai API key not configured")

    # Always check Recall.ai directly for live status
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{RECALL_API_BASE}/bot/{bot_id}/",
            headers={"Authorization": f"Token {RECALL_API_KEY}"},
            timeout=10,
        )

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Bot not found")
    if resp.status_code != 200:
        detail = _extract_recall_error(resp)
        raise HTTPException(status_code=resp.status_code, detail=f"Recall.ai status check failed: {detail}")

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
        if bot_store[bot_id].get("status") not in ("processing", "done"):
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
        # Give Recall.ai time to finalize the transcript after call ends
        await asyncio.sleep(5)

        resp = None
        for attempt in range(5):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{RECALL_API_BASE}/bot/{bot_id}/transcript/",
                    headers={"Authorization": f"Token {RECALL_API_KEY}"},
                    timeout=30,
                )
            if resp.status_code == 200:
                break
            await asyncio.sleep(5 * (attempt + 1))  # 5s, 10s, 15s, 20s backoff

        if resp is None or resp.status_code != 200:
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


@app.post("/chat/global")
async def chat_global(req: GlobalChatRequest):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    limit = max(1, min(req.limit, 20))
    rows = (
        supabase.table("meetings")
        .select("id,title,date,score,result")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    meetings = rows.data or []

    if not meetings:
        return {"response": "No meetings found in your history yet. Analyze a meeting first and I'll be able to answer questions across all of them."}

    # Build compact context — summary + action items + decisions per meeting
    # Hard cap: ~12k chars total across all meetings
    parts = []
    total_chars = 0
    for m in meetings:
        result = m.get("result") or {}
        title = m.get("title") or "Untitled"
        date = m.get("date") or "Unknown date"
        score = m.get("score")
        score_str = f"{score}/100" if score is not None else "N/A"

        summary = result.get("summary") or ""
        action_items_list = result.get("action_items") or []
        decisions_list = result.get("decisions") or []

        ai_str = "; ".join(
            f"{a.get('task','')} (owner: {a.get('owner','?')}, due: {a.get('due','?')})"
            for a in action_items_list[:8]
        )
        dec_str = "; ".join(d.get("decision", "") for d in decisions_list[:5])

        entry = (
            f"--- Meeting: {title} | Date: {date} | Health: {score_str} ---\n"
            f"Summary: {summary[:300]}\n"
        )
        if ai_str:
            entry += f"Action items: {ai_str}\n"
        if dec_str:
            entry += f"Decisions: {dec_str}\n"

        if total_chars + len(entry) > 12000:
            break
        parts.append(entry)
        total_chars += len(entry)

    context = "\n".join(parts)

    response = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a meeting intelligence assistant with access to the user's full meeting history. "
                    "Answer questions across all meetings — find patterns, track commitments, compare health scores, "
                    "surface recurring action items, and summarize trends. Be concise and specific. "
                    "Cite meeting titles and dates when referencing specific meetings.\n\n"
                    f"Meeting history ({len(parts)} meetings):\n{context}"
                ),
            },
            {"role": "user", "content": req.message},
        ],
    )
    return {"response": response.choices[0].message.content}


# ── Notion export ────────────────────────────────────────────────────

def _notion_rich_text(content: str) -> list:
    """Split long text into Notion rich_text chunks (max 2000 chars each)."""
    chunks = []
    for i in range(0, len(content), 2000):
        chunks.append({"type": "text", "text": {"content": content[i:i+2000]}})
    return chunks or [{"type": "text", "text": {"content": ""}}]


def _h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _notion_rich_text(text)}}


def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _notion_rich_text(text)}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _todo(text: str, checked: bool = False) -> dict:
    return {"object": "block", "type": "to_do", "to_do": {"rich_text": _notion_rich_text(text), "checked": checked}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _notion_rich_text(text)}}


def _build_notion_blocks(result: dict) -> list:
    blocks = []
    h = result.get("health_score") or {}
    if h.get("score") is not None:
        blocks.append(_h2(f"Meeting Health: {h['score']}/100"))
        if h.get("verdict"):
            blocks.append(_para(h["verdict"]))
        if h.get("badges"):
            blocks.append(_para("Badges: " + ", ".join(h["badges"])))
        blocks.append(_divider())

    if result.get("summary"):
        blocks.append(_h2("Summary"))
        blocks.append(_para(result["summary"]))
        blocks.append(_divider())

    items = result.get("action_items") or []
    if items:
        blocks.append(_h2(f"Action Items ({len(items)})"))
        for item in items:
            label = item.get("task", "")
            if item.get("owner") and item["owner"] != "Unassigned":
                label += f" — {item['owner']}"
            if item.get("due") and item["due"] != "TBD":
                label += f" (due {item['due']})"
            blocks.append(_todo(label, checked=bool(item.get("completed"))))
        blocks.append(_divider())

    decisions = result.get("decisions") or []
    if decisions:
        blocks.append(_h2("Decisions"))
        imp_map = {1: "Critical", 2: "Significant", 3: "Minor"}
        for d in sorted(decisions, key=lambda x: x.get("importance", 3)):
            label = d.get("decision", "")
            imp = imp_map.get(d.get("importance"), "")
            if imp:
                label += f" [{imp}]"
            if d.get("owner"):
                label += f" — {d['owner']}"
            blocks.append(_bullet(label))
        blocks.append(_divider())

    email = result.get("follow_up_email") or {}
    if email.get("subject") or email.get("body"):
        blocks.append(_h2("Follow-up Email"))
        if email.get("subject"):
            blocks.append(_para(f"Subject: {email['subject']}"))
        if email.get("body"):
            blocks.append(_para(email["body"]))
        blocks.append(_divider())

    cal = result.get("calendar_suggestion") or {}
    if cal.get("reason"):
        blocks.append(_h2("Calendar Suggestion"))
        blocks.append(_para(cal["reason"]))
        if cal.get("suggested_timeframe"):
            blocks.append(_para(f"Suggested timeframe: {cal['suggested_timeframe']}"))

    return blocks


@app.post("/export/notion")
async def export_to_notion(req: NotionExportRequest):
    import re
    parent_id = req.parent_page_id.strip()
    # Extract 32-char hex ID from URL (Notion URLs end in Title-{id} or just {id})
    match = re.search(r'([0-9a-f]{32})(?:[?#]|$)', parent_id.replace("-", ""), re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=400, detail="Could not extract a valid Notion page ID from the URL")
    raw = match.group(1)
    parent_id = f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"

    blocks = _build_notion_blocks(req.result)
    blocks = blocks[:100]  # Notion API limit per request

    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": req.title or "Meeting Analysis"}}]}
        },
        "children": blocks,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {req.token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20.0,
        )

    if resp.status_code not in (200, 201):
        detail = resp.json().get("message", "Notion API error") if resp.content else "Notion API error"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    page = resp.json()
    return {"url": page.get("url", ""), "page_id": page.get("id", "")}


# ── Slack export ─────────────────────────────────────────────────────

@app.post("/export/slack")
async def export_to_slack(req: SlackExportRequest):
    result = req.result
    h = result.get("health_score") or {}
    items = result.get("action_items") or []
    decisions = result.get("decisions") or []

    score_str = f"{h['score']}/100" if h.get("score") is not None else "N/A"
    verdict = h.get("verdict", "")

    lines = [f"*{req.title}* — PrismAI Analysis"]
    lines.append(f"*Health Score:* {score_str}{(' — ' + verdict) if verdict else ''}")

    if result.get("summary"):
        lines.append(f"\n*Summary*\n{result['summary']}")

    if items:
        lines.append(f"\n*Action Items ({len(items)})*")
        for item in items[:8]:
            owner = f" ({item['owner']})" if item.get("owner") and item["owner"] != "Unassigned" else ""
            due = f" — due {item['due']}" if item.get("due") and item["due"] != "TBD" else ""
            lines.append(f"• {item.get('task', '')}{owner}{due}")

    if decisions:
        lines.append(f"\n*Key Decisions*")
        for d in decisions[:5]:
            lines.append(f"• {d.get('decision', '')}")

    message = "\n".join(lines)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            req.webhook_url,
            json={"text": message},
            timeout=10.0,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Slack webhook failed")

    return {"ok": True}

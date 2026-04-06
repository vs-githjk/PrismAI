import json
import os
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import AsyncGroq

from auth import require_user_id, supabase
from analysis_service import AGENT_MAP, AGENT_RESULT_KEY, build_analysis_transcript, run_full_analysis
from recall_routes import router as recall_router
from storage_routes import router as storage_router

app = FastAPI(title="Agentic Meeting Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(storage_router)
app.include_router(recall_router)

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

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


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    transcript = build_analysis_transcript(req.transcript, req.speakers)
    return await run_full_analysis(transcript)


@app.post("/analyze-stream")
async def analyze_stream(req: AnalyzeRequest):
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    transcript = build_analysis_transcript(req.transcript, req.speakers)
    from agents import orchestrator
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
async def chat_global(req: GlobalChatRequest, user_id: str = Depends(require_user_id)):
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not configured")

    limit = max(1, min(req.limit, 20))
    rows = (
        supabase.table("meetings")
        .select("id,title,date,score,result")
        .eq("user_id", user_id)
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

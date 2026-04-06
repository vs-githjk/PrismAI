from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from groq import AsyncGroq

from auth import require_user_id, supabase
from analysis_service import AGENT_MAP


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    transcript: str = ""


class GlobalChatRequest(BaseModel):
    message: str
    limit: int = 10


class AgentRequest(BaseModel):
    agent: str
    transcript: str
    instruction: str = ""


def create_chat_router(groq_client: AsyncGroq) -> APIRouter:
    local_router = APIRouter(tags=["chat"])

    @local_router.post("/agent")
    async def run_agent(req: AgentRequest):
        if req.agent not in AGENT_MAP:
            raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent}")
        augmented = req.transcript
        if req.instruction:
            augmented += f"\n\n[User instruction: {req.instruction}]"
        result = await AGENT_MAP[req.agent](augmented)
        return result

    @local_router.post("/chat")
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

    @local_router.post("/chat/global")
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

        parts = []
        total_chars = 0
        for meeting in meetings:
            result = meeting.get("result") or {}
            title = meeting.get("title") or "Untitled"
            date = meeting.get("date") or "Unknown date"
            score = meeting.get("score")
            score_str = f"{score}/100" if score is not None else "N/A"

            summary = result.get("summary") or ""
            action_items_list = result.get("action_items") or []
            decisions_list = result.get("decisions") or []

            action_items = "; ".join(
                f"{item.get('task','')} (owner: {item.get('owner','?')}, due: {item.get('due','?')})"
                for item in action_items_list[:8]
            )
            decisions = "; ".join(decision.get("decision", "") for decision in decisions_list[:5])

            entry = (
                f"--- Meeting: {title} | Date: {date} | Health: {score_str} ---\n"
                f"Summary: {summary[:300]}\n"
            )
            if action_items:
                entry += f"Action items: {action_items}\n"
            if decisions:
                entry += f"Decisions: {decisions}\n"

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

    return local_router


router = create_chat_router

import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from groq import AsyncGroq

from auth import require_user_id, supabase
from analysis_service import AGENT_MAP, TIER2_AGENTS, _persona_text_for_agent
from agents.utils import _PERSONA_TEXT, get_persona_suffix
from personas import resolve_persona

# Server-side store for tools awaiting confirmation.
# Key: (user_id, pending_id) → {tool, arguments, expires_at}
# Client only ever gets the pending_id back — args stay server-side.
_pending_tools: dict[tuple[str, str], dict] = {}
_PENDING_TTL = 300  # 5 minutes


def _store_pending(user_id: str, tool: str, arguments: dict) -> str:
    pending_id = secrets.token_urlsafe(16)
    # Prune expired entries
    now = time.time()
    expired = [k for k, v in _pending_tools.items() if v["expires_at"] < now]
    for k in expired:
        del _pending_tools[k]
    _pending_tools[(user_id, pending_id)] = {
        "tool": tool,
        "arguments": arguments,
        "expires_at": now + _PENDING_TTL,
    }
    return pending_id


def _pop_pending(user_id: str, pending_id: str) -> dict | None:
    entry = _pending_tools.pop((user_id, pending_id), None)
    if entry and entry["expires_at"] < time.time():
        return None
    return entry

# Import tool modules to trigger registration
import tools.gmail  # noqa: F401
import tools.slack  # noqa: F401
import tools.calendar  # noqa: F401
import tools.linear  # noqa: F401
from tools.registry import get_available_tools, execute_tool, confirm_and_execute

router = APIRouter(tags=["chat"])

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY", "")


class ChatRequest(BaseModel):
    message: str
    transcript: str = ""


class GlobalChatRequest(BaseModel):
    message: str
    limit: int = 10


class AgentRequest(BaseModel):
    agent: str
    transcript: str = ""  # optional — Tier-2 agents (email, calendar, health) run from `result`
    instruction: str = ""
    existing_items: list | None = None
    # The current meeting result — lets a Tier-2 agent re-run with the same
    # context (summary, decisions, action_items, sentiment) the full pipeline
    # gives it, so chat re-runs match a fresh analysis instead of running blind.
    result: dict | None = None
    # Persona — resolved client-side. /agent is unauthenticated so the
    # frontend ships the active preset (and custom prompt if any) in the
    # payload.
    persona_preset: str | None = None
    persona_custom_prompt: str | None = None


class ConfirmToolRequest(BaseModel):
    pending_id: str


async def _get_user_settings(user_id: str) -> dict:
    """Fetch user settings from Supabase, including tokens for tool availability.

    Mirrors the meeting path's token-refresh logic: Google access tokens
    are valid for 1 hour. If the stored token is expired, get_valid_token
    refreshes it using the refresh_token. Without this, every Gmail /
    calendar tool call from the chat panel uses a stale access_token and
    fails with 401 Invalid Credentials.
    """
    if not supabase:
        return {}
    try:
        resp = supabase.table("user_settings").select("*").eq("user_id", user_id).maybe_single().execute()
        row = (resp.data if resp is not None else None) or {}
        # Refresh expired Google access token via refresh_token. Pass the
        # already-fetched row so get_valid_token skips its own Supabase
        # round-trip when the token is still fresh — same pattern as
        # realtime_routes._get_settings_for_bot.
        if row.get("google_access_token"):
            from calendar_routes import get_valid_token
            try:
                fresh_token = await get_valid_token(user_id, row=row)
                row["google_access_token"] = fresh_token
            except Exception as e:
                # get_valid_token raises if no refresh_token or refresh
                # fails. Fall back to the stored (possibly expired) token
                # so the failure surfaces as a clear Gmail 401 rather
                # than a 500 here.
                print(f"[chat] google token refresh failed for user={user_id[:8]}: {e}")
        # Merge env-level tokens so tools that use env fallback are available
        if SLACK_BOT_TOKEN and not row.get("slack_bot_token"):
            row["slack_bot_token"] = SLACK_BOT_TOKEN
        if LINEAR_API_KEY and not row.get("linear_api_key"):
            row["linear_api_key"] = LINEAR_API_KEY
        return row
    except Exception:
        return {}


async def _optional_user_id(request: Request) -> str | None:
    """Try to extract user_id from auth header, return None if not authenticated."""
    try:
        return await require_user_id(request)
    except HTTPException:
        return None


def build_rag_context(tool_result: dict) -> dict:
    """Normalize a knowledge_lookup result into a frontend-safe grounding payload.

    Whitelists fields only — never leaks raw internal metadata. Powers the
    Sources cards + conflict banner in ChatPanel so citations come from
    structured data, not from whatever prose the model happened to write.
    """
    matches = tool_result.get("matches", []) or []
    sources = []
    for m in matches[:5]:
        meta = m.get("metadata") or {}
        sources.append({
            "doc_id": m.get("doc_id"),
            "chunk_id": m.get("chunk_id"),
            "doc_name": m.get("doc_name"),
            "source_type": m.get("source_type"),
            "score": m.get("score"),
            "snippet": (m.get("content") or "")[:500],
            "metadata": {
                "page": meta.get("page"),
                "timestamp": meta.get("timestamp"),
                "meeting_title": meta.get("meeting_title"),
            },
        })
    return {"sources": sources, "has_conflict": bool(tool_result.get("has_conflict"))}


async def _tool_calling_loop(groq_client: AsyncGroq, messages: list, tools: list, user_id: str, user_settings: dict) -> dict:
    """
    LLM tool-calling loop: call LLM, if it wants tools execute them, feed results back.
    Returns { reply: str, tools_used: list[dict], rag_context: dict | None }
    """
    tools_used = []
    pending_confirmations = []
    rag_context = None  # structured grounding from knowledge_lookup, if it runs
    max_iterations = 3

    call_kwargs = {
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.7,
        "messages": messages,
    }
    if tools:
        call_kwargs["tools"] = tools
        call_kwargs["tool_choice"] = "auto"

    def _graceful():
        return {
            "reply": "Sorry, I had trouble processing that.",
            "tools_used": tools_used,
            "pending_confirmations": pending_confirmations,
            "rag_context": rag_context,
        }

    for _ in range(max_iterations):
        try:
            response = await groq_client.chat.completions.create(**call_kwargs)
        except Exception as groq_exc:
            # Llama 3.3 sometimes emits malformed tool calls → Groq rejects with a
            # 400 tool_use_failed; transient 429/5xx land here too. Strip tools and
            # retry once for a plain-text answer instead of 500-ing the whole chat
            # turn. Mirrors realtime_routes' proven recovery. (diagnose 2026-06-08)
            if "tools" in call_kwargs:
                print(f"[chat] groq tool-call error, retrying without tools: {groq_exc}")
                call_kwargs.pop("tools", None)
                call_kwargs.pop("tool_choice", None)
                try:
                    response = await groq_client.chat.completions.create(**call_kwargs)
                except Exception as retry_exc:
                    print(f"[chat] retry-without-tools also failed: {retry_exc}")
                    return _graceful()
            else:
                print(f"[chat] groq call failed: {groq_exc}")
                return _graceful()
        choice = response.choices[0]

        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            # Text response — we're done
            return {
                "reply": choice.message.content or "",
                "tools_used": tools_used,
                "pending_confirmations": pending_confirmations,
                "rag_context": rag_context,
            }

        # Process tool calls
        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            result = await execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                user_id=user_id,
                user_settings=user_settings,
            )

            if result.get("requires_confirmation"):
                pending_id = _store_pending(user_id, tool_call.function.name, result["preview"])
                pending_confirmations.append({
                    "pending_id": pending_id,
                    "tool": tool_call.function.name,
                    "preview": result["preview"],
                    "message": result["message"],
                    "tool_call_id": tool_call.id,
                })
                # Tell the LLM the action needs user confirmation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"status": "awaiting_user_confirmation", "preview": result["preview"]}),
                })
            else:
                tools_used.append({
                    "tool": tool_call.function.name,
                    "summary": result.get("summary", f"Executed {tool_call.function.name}"),
                })
                # Capture structured grounding so the UI can render Sources +
                # conflict warnings — independent of the model's prose.
                if tool_call.function.name == "knowledge_lookup" and result.get("matches"):
                    rag_context = build_rag_context(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

        # Update call_kwargs with new messages for next iteration
        call_kwargs["messages"] = messages

    # Fallback if we hit max iterations
    return {
        "reply": "I completed the requested actions.",
        "tools_used": tools_used,
        "pending_confirmations": pending_confirmations,
        "rag_context": rag_context,
    }


def create_chat_router(groq_client: AsyncGroq) -> APIRouter:
    local_router = APIRouter(tags=["chat"])

    @local_router.post("/agent")
    async def run_agent(req: AgentRequest):
        if req.agent not in AGENT_MAP:
            raise HTTPException(status_code=400, detail=f"Unknown agent: {req.agent}")
        # Apply per-agent whitelist + set the contextvar so llm_call appends
        # the safety-wrapped persona to the agent's system prompt.
        fake_state = {
            "persona_preset": req.persona_preset or "default",
            "persona_custom_prompt": req.persona_custom_prompt or "",
        }
        _PERSONA_TEXT.set(_persona_text_for_agent(req.agent, fake_state))
        augmented = req.transcript
        if req.existing_items is not None:
            try:
                existing_json = json.dumps(req.existing_items, ensure_ascii=False)
                augmented += f"\n\n[EXISTING ITEMS — preserve these and merge with any additions/removals the user requests: {existing_json}]"
            except Exception:
                pass
        if req.instruction:
            augmented += f"\n\n[User instruction: {req.instruction}]"

        # Tier-2 agents (email_drafter, health_score, calendar_suggester) take a
        # context dict in the pipeline. Rebuild it from the current result so a
        # chat re-run isn't context-blind (otherwise e.g. health_score would
        # re-judge tension without seeing sentiment's resolution).
        if req.agent in TIER2_AGENTS:
            r = req.result or {}
            decisions = r.get("decisions", []) or []
            links = r.get("decision_links", []) or []
            unactioned = [
                decisions[l["decision"]].get("decision", "")
                for l in links
                if not l.get("actions") and isinstance(l.get("decision"), int) and 0 <= l["decision"] < len(decisions)
            ]
            context = {
                "summary": r.get("summary", ""),
                "decisions": decisions,
                "action_items": r.get("action_items", []) or [],
                "sentiment": r.get("sentiment", {}) or {},
                "unactioned_decisions": [d for d in unactioned if d],
            }
            return await AGENT_MAP[req.agent](augmented, context)
        return await AGENT_MAP[req.agent](augmented)

    @local_router.post("/chat")
    async def chat(req: ChatRequest, request: Request):
        user_id = await _optional_user_id(request)
        # Resolve persona for the duration of this request. The contextvar
        # is per-task in asyncio — when this handler returns the value dies
        # with the task, so no reset is needed.
        if user_id and supabase:
            active_ws = request.headers.get("x-active-workspace") or None
            resolved = await resolve_persona(supabase, user_id, active_ws)
            _PERSONA_TEXT.set(resolved.text)
        user_settings = await _get_user_settings(user_id) if user_id else {}

        context = ""
        if req.transcript.strip():
            context = f"\n\nMeeting transcript for context:\n{req.transcript[:15000]}"

        # Get available tools for this user
        tools = get_available_tools(user_settings) if user_id else []

        system_content = (
            "You are PrismAI, an intelligent meeting assistant. Answer questions about the meeting transcript concisely."
        )
        if tools:
            system_content += (
                "\n\nYou have access to tools that can take real actions — send emails, post to Slack, "
                "create calendar events, create Linear issues. Use them when the user asks you to take an action. "
                "For read operations, go ahead and use the tool. For actions that send/post/create, the system will "
                "ask the user to confirm before executing."
            )
        system_content += context
        # Persona is appended LAST so it sits closest to the user turn —
        # gives the LLM the most-recent tone instruction context.
        system_content += get_persona_suffix()

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": req.message},
        ]

        if tools:
            result = await _tool_calling_loop(groq_client, messages, tools, user_id, user_settings)
            return {
                "response": result["reply"],
                "tools_used": result.get("tools_used", []),
                "pending_confirmations": result.get("pending_confirmations", []),
                "rag_context": result.get("rag_context"),
            }
        else:
            try:
                response = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    temperature=0.7,
                    messages=messages,
                )
                return {"response": response.choices[0].message.content}
            except Exception as exc:
                # Don't 500 the chat panel on a transient Groq error. (diagnose 2026-06-08)
                print(f"[chat] groq call failed: {exc}")
                return {"response": "Sorry, I had trouble processing that."}

    @local_router.post("/chat/global")
    async def chat_global(req: GlobalChatRequest, user_id: str = Depends(require_user_id)):
        if not supabase:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Persona is workspace-aware via the active-workspace header.
        active_ws = None  # global chat is cross-workspace; no specific workspace context
        resolved = await resolve_persona(supabase, user_id, active_ws)
        _PERSONA_TEXT.set(resolved.text)

        user_settings = await _get_user_settings(user_id)

        limit = max(1, min(req.limit, 20))
        rows = (
            supabase.table("meetings")
            .select("id,title,date,score,result")
            .eq("user_id", user_id)
            .order("id", desc=True)
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
                if isinstance(item, dict)
            )
            decisions = "; ".join(
                decision.get("decision", "")
                for decision in decisions_list[:5]
                if isinstance(decision, dict)
            )

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

        # Get available tools
        tools = get_available_tools(user_settings)

        system_content = (
            "You are PrismAI, a meeting intelligence assistant with access to the user's full meeting history. "
            "Answer questions across all meetings — find patterns, track commitments, compare health scores, "
            "surface recurring action items, and summarize trends. Be concise and specific. "
            "Cite meeting titles and dates when referencing specific meetings."
        )
        if tools:
            system_content += (
                "\n\nYou also have access to tools for taking actions — sending emails, posting to Slack, "
                "creating calendar events, and creating Linear issues. Use them when asked."
            )
        system_content += f"\n\nMeeting history ({len(parts)} meetings):\n{context}"
        system_content += get_persona_suffix()

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": req.message},
        ]

        if tools:
            result = await _tool_calling_loop(groq_client, messages, tools, user_id, user_settings)
            return {
                "response": result["reply"],
                "tools_used": result.get("tools_used", []),
                "pending_confirmations": result.get("pending_confirmations", []),
                "rag_context": result.get("rag_context"),
            }
        else:
            try:
                response = await groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    temperature=0.7,
                    messages=messages,
                )
                return {"response": response.choices[0].message.content}
            except Exception as exc:
                # Don't 500 the chat panel on a transient Groq error. (diagnose 2026-06-08)
                print(f"[chat] groq call failed: {exc}")
                return {"response": "Sorry, I had trouble processing that."}

    @local_router.post("/chat/confirm-tool")
    async def confirm_tool(req: ConfirmToolRequest, user_id: str = Depends(require_user_id)):
        """Execute a tool that was previously held for user confirmation."""
        entry = _pop_pending(user_id, req.pending_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Pending action not found or expired")
        user_settings = await _get_user_settings(user_id)
        result = await confirm_and_execute(entry["tool"], entry["arguments"], user_settings=user_settings)
        return result

    return local_router

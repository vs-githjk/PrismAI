"""knowledge_lookup tool — retrieves grounding chunks from the user's knowledge base."""

from typing import Optional

from auth import supabase as auth_supabase
from knowledge_service import search_knowledge

from .registry import register_tool


STRICT_INSTRUCTION = (
    "Answer ONLY using the content in `matches` above. "
    "When you answer, cite the source by saying \"According to {doc_name}: ...\". "
    "If the matches do not contain the answer, respond with exactly the token "
    "NO_GROUNDED_ANSWER so the system can fall back to web_search. "
    "Do not synthesize, infer, or guess beyond the provided content."
)

CONFLICT_INSTRUCTION = (
    " IMPORTANT: Multiple documents may contain conflicting information. "
    "If the matches disagree, present BOTH views with their respective doc_name "
    "and any date metadata. Do NOT pick one — let the user decide."
)


async def _log_query(user_id: str, bot_id: Optional[str], query: str,
                     matched_doc: Optional[str], match_score: Optional[float],
                     fallback: Optional[str]) -> None:
    try:
        if auth_supabase:
            auth_supabase.table("knowledge_queries").insert({
                "user_id": user_id,
                "bot_id": bot_id,
                "query_text": query[:500],
                "matched_doc": matched_doc,
                "match_score": match_score,
                "fallback": fallback,
            }).execute()
    except Exception:
        pass  # audit log never breaks the request


async def knowledge_lookup(args: dict, user_settings: Optional[dict] = None) -> dict:
    settings = user_settings or {}
    query = (args.get("query") or "").strip()
    user_id = settings.get("user_id") or args.get("user_id") or ""
    meeting_id = settings.get("meeting_id") or args.get("meeting_id")
    bot_id = settings.get("bot_id") or args.get("bot_id")
    if not query or not user_id:
        return {"error": "Both query and user_id are required"}

    matches = await search_knowledge(query, user_id, meeting_id=meeting_id, k=5, min_score=0.75)

    if not matches:
        await _log_query(user_id, bot_id, query, None, None, None)
        return {
            "no_match": True,
            "next_step": "Call web_search with this query. If web_search also fails, "
                         "compose a brief question to ask the meeting participants directly.",
        }

    has_conflict = any(m.get("possible_conflict") for m in matches)
    instruction = STRICT_INSTRUCTION + (CONFLICT_INSTRUCTION if has_conflict else "")

    top = matches[0]
    await _log_query(user_id, bot_id, query, top.get("doc_id"), top.get("score"), None)

    formatted = [
        {
            "doc_name": m.get("doc_name"),
            "content": m.get("content"),
            "source_type": m.get("source_type"),
            "score": round(float(m.get("score") or 0), 3),
            "metadata": m.get("metadata") or {},
        }
        for m in matches
    ]
    return {"matches": formatted, "instruction": instruction}


register_tool(
    name="knowledge_lookup",
    description=(
        "Look up information in the user's uploaded knowledge base "
        "(PDFs, documents, web pages, Notion, Google Drive). Use this FIRST when the "
        "user asks a factual question that might be in their documents. Returns "
        "matched content with source citations. If no match, falls back to web_search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The user's question or the topic to look up."},
        },
        "required": ["query"],
    },
    handler=knowledge_lookup,
    requires=None,
    confirm=False,
)

# backend/knowledge_transcript.py
"""Index a finished meeting's transcript into knowledge_chunks so it can be
searched alongside uploaded documents. Called from storage_routes.save_meeting
as a fire-and-forget background task."""

import uuid

from embeddings import embed_batch, QuotaExhausted
from knowledge_ingest.chunker import chunk_text
from knowledge_service import _supabase, INSERT_BATCH_SIZE, _execute, check_user_quota, QuotaExceeded


def _meeting_doc_name(date: str, title: str) -> str:
    """Stable display name shown in citations."""
    day = (date or "")[:10] or "unknown date"
    base = (title or "").strip() or "Meeting"
    return f"{base} ({day})"


async def index_meeting_transcript(
    meeting_id: int,
    user_id: str,
    workspace_id: str | None,
    date: str,
    title: str,
    transcript: str,
) -> None:
    """Chunk → embed → insert. Idempotent on meeting_id (skips if a doc row
    already exists for this meeting). Errors are swallowed and logged — this
    runs in the background and must not crash the calling request."""
    if not transcript or not transcript.strip():
        return

    sb = _supabase()
    try:
        existing = await _execute(
            sb.table("knowledge_docs")
            .select("id")
            .eq("meeting_id", meeting_id)
            .eq("source_type", "meeting_transcript")
        )
        if existing.data:
            return

        doc_id = str(uuid.uuid4())
        doc_name = _meeting_doc_name(date, title)
        await _execute(
            sb.table("knowledge_docs").insert({
                "id": doc_id,
                "user_id": user_id,
                "meeting_id": meeting_id,
                "workspace_id": workspace_id,
                "name": doc_name,
                "source_type": "meeting_transcript",
                "sensitivity": "internal",
                "status": "processing",
            })
        )

        chunks = chunk_text(transcript, base_metadata={"date": date, "title": title})
        if not chunks:
            await _execute(
                sb.table("knowledge_docs")
                .update({"status": "ready", "chunk_count": 0})
                .eq("id", doc_id)
            )
            return

        # Lightweight, deterministic preamble. Transcripts have no section
        # headings, so a Groq-generated preamble would just repeat title+date —
        # build it inline and skip the LLM cost.
        preamble = f"From your meeting '{title}' on {(date or '')[:10]}."
        for c in chunks:
            c["embedded_content"] = f"{preamble} {c['content']}"

        try:
            await check_user_quota(user_id, len(chunks))
        except QuotaExceeded as exc:
            await _execute(
                sb.table("knowledge_docs")
                .update({"status": "error", "error_message": str(exc)})
                .eq("id", doc_id)
            )
            return

        contents = [c["embedded_content"] for c in chunks]
        try:
            vectors = await embed_batch(contents)
        except QuotaExhausted:
            await _execute(
                sb.table("knowledge_docs")
                .update({"status": "error", "error_message": "OpenAI quota exhausted"})
                .eq("id", doc_id)
            )
            return

        rows = [
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "content": chunks[i]["content"],
                "embedded_content": chunks[i]["embedded_content"],
                "embedding": vectors[i],
                "chunk_index": chunks[i]["chunk_index"],
                "metadata": chunks[i]["metadata"],
            }
            for i in range(len(chunks))
        ]
        for i in range(0, len(rows), INSERT_BATCH_SIZE):
            await _execute(
                sb.table("knowledge_chunks").insert(rows[i : i + INSERT_BATCH_SIZE])
            )

        await _execute(
            sb.table("knowledge_docs")
            .update({"status": "ready", "chunk_count": len(rows)})
            .eq("id", doc_id)
        )

    except Exception as exc:
        print(f"[transcript-index] meeting {meeting_id} failed: {exc}")

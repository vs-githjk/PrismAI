# backend/knowledge_transcript.py
"""Index a finished meeting's transcript into knowledge_chunks so it can be
searched alongside uploaded documents. Called from storage_routes.save_meeting
as a fire-and-forget background task.

Sensitivity note: transcripts are tagged 'internal' on purpose. They inherit
the workspace via `workspace_id` (so workspace members can search them via
the existing scoping), but the 'internal' tier prevents proactive surfacing
into unrelated meetings unless the transcript-doc is explicitly pinned. If
we ever want a per-workspace 'transcript_sensitivity' default, add it to the
workspaces table and read it here — but the v1 default is the safer choice.
"""

import uuid

from embeddings import embed_batch, QuotaExhausted
from knowledge_ingest.chunker import chunk_text
from knowledge_service import (
    _supabase,
    INSERT_BATCH_SIZE,
    _execute,
    check_user_quota,
    QuotaExceeded,
)


def _meeting_doc_name(date: str, title: str) -> str:
    """Stable display name shown in citations."""
    day = (date or "")[:10] or "unknown date"
    base = (title or "").strip() or "Meeting"
    return f"{base} ({day})"


async def _mark_error(sb, doc_id: str, message: str) -> None:
    """Best-effort update of doc status to 'error'. Wrapped in its own try so
    a failure HERE (e.g. Supabase still down) doesn't propagate out of the
    background task — leaving the doc in 'processing' forever, which used to
    be the bug."""
    try:
        await _execute(
            sb.table("knowledge_docs")
            .update({"status": "error", "error_message": message[:500]})
            .eq("id", doc_id)
        )
    except Exception as exc:
        print(f"[transcript-index] failed to mark doc {doc_id} as error: {exc}")


async def index_meeting_transcript(
    meeting_id: int,
    user_id: str,
    workspace_id: str | None,
    date: str,
    title: str,
    transcript: str,
) -> None:
    """Chunk → embed → insert. Idempotent on meeting_id (skips if a doc row
    already exists for this meeting). Errors flow through `_mark_error` so the
    doc row never gets stuck in 'processing' state."""
    if not transcript or not transcript.strip():
        return

    sb = _supabase()
    doc_id: str | None = None
    try:
        # Idempotency check: skip if already indexed (or in flight).
        existing = await _execute(
            sb.table("knowledge_docs")
            .select("id")
            .eq("meeting_id", meeting_id)
            .eq("source_type", "meeting_transcript")
        )
        if existing.data:
            return

        # Chunk and quota-check FIRST so a quota-exceeded user doesn't leave
        # an orphan doc row behind. Empty transcripts are a no-op.
        chunks = chunk_text(transcript, base_metadata={"date": date, "title": title})
        if not chunks:
            return

        try:
            await check_user_quota(user_id, len(chunks))
        except QuotaExceeded as exc:
            # No doc row created yet — just log and bail. Storing an error
            # row would be misleading (the user never asked to index this
            # specifically; they hit the global quota).
            print(f"[transcript-index] quota exceeded for user {user_id}: {exc}")
            return

        # Lightweight, deterministic preamble. Transcripts have no section
        # headings, so a Groq-generated preamble would just repeat title+date —
        # build it inline and skip the LLM cost.
        preamble = f"From your meeting '{title or 'Meeting'}' on {(date or '')[:10]}."
        for c in chunks:
            c["embedded_content"] = f"{preamble} {c['content']}"

        contents = [c["embedded_content"] for c in chunks]
        try:
            vectors = await embed_batch(contents)
        except QuotaExhausted:
            # OpenAI billing — no doc row yet, nothing to mark.
            print(f"[transcript-index] OpenAI quota exhausted for meeting {meeting_id}")
            return

        # Now insert the doc row. We rely on Postgres' unique constraint
        # (knowledge_docs_meeting_transcript_unique) to catch any race where
        # two concurrent save_meeting calls both pass the SELECT idempotency
        # check above — see the migration.
        doc_id = str(uuid.uuid4())
        doc_name = _meeting_doc_name(date, title)
        try:
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
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                # Race lost — another worker already inserted this meeting's
                # transcript doc. Idempotent outcome.
                return
            raise

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
        # If we created a doc row before hitting the failure, mark it 'error'
        # so it doesn't appear stuck in 'processing'. _mark_error swallows its
        # own failures so background tasks never raise.
        print(f"[transcript-index] meeting {meeting_id} failed: {exc}")
        if doc_id is not None:
            await _mark_error(sb, doc_id, str(exc))

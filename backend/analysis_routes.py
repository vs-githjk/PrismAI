import json
import time
from collections import defaultdict

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from analysis_service import AGENT_RESULT_KEY, _GRAPH, build_analysis_transcript, run_full_analysis

# Simple IP-based rate limit for /transcribe (paid Whisper call, no auth required for demo)
_transcribe_log: dict[str, list[float]] = defaultdict(list)
_TRANSCRIBE_PER_MINUTE = 5

# Document text-extraction (.docx/.pdf/.txt → text) for the Article/Report input path.
_doc_extract_log: dict[str, list[float]] = defaultdict(list)
_DOC_EXTRACT_PER_MINUTE = 10
_DOC_MAX_BYTES = 15 * 1024 * 1024


class AnalyzeRequest(BaseModel):
    transcript: str
    speakers: list = []
    owner_name: str | None = None
    # Meeting type for the content-analysis lens: '' / 'auto' (detect), 'standard',
    # 'pitch', 'interview_content', 'interview_job'. See agents/content_analyst.py.
    meeting_type: str | None = None
    # Persona — resolved client-side (the analyze endpoint is unauthenticated,
    # so the server can't look up the user's effective persona on its own).
    persona_preset: str | None = None
    persona_custom_prompt: str | None = None


def create_analysis_router(openai_client: AsyncOpenAI) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    @router.post("/analyze")
    async def analyze(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers, req.owner_name)
        return await run_full_analysis(
            transcript,
            persona_preset=req.persona_preset,
            persona_custom_prompt=req.persona_custom_prompt,
            owner_name=req.owner_name,
            meeting_type=req.meeting_type,
        )

    @router.post("/analyze-stream")
    async def analyze_stream(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers, req.owner_name)

        async def event_stream():
            initial: dict = {"transcript": transcript, "agents_to_run": [], "results": {}, "context": {},
                             "owner_name": (req.owner_name or "").strip(),
                             "meeting_type": (req.meeting_type or "").strip().lower()}
            if req.persona_preset:
                initial["persona_preset"] = req.persona_preset
            if req.persona_custom_prompt:
                initial["persona_custom_prompt"] = req.persona_custom_prompt
            succeeded_agents = []

            async for chunk in _GRAPH.astream(initial, stream_mode="updates"):
                for node_name, update in chunk.items():
                    if node_name == "orchestrator":
                        yield f"data: {json.dumps({'agents_run': update.get('agents_to_run', [])})}\n\n"
                    elif node_name.startswith("t1_") or node_name.startswith("t2_"):
                        agent_name = node_name[3:]  # strip "t1_" or "t2_"
                        agent_result = update.get("results", {}).get(agent_name, {})
                        key = AGENT_RESULT_KEY.get(agent_name)
                        if key and key in agent_result:
                            payload = {"agent": agent_name, **agent_result}
                            yield f"data: {json.dumps(payload)}\n\n"
                            succeeded_agents.append(agent_name)
                        elif key:
                            print(f"[analyze] agent {agent_name} returned no '{key}' key")
                            yield f"data: {json.dumps({'agent_error': f'{agent_name}: missing result key'})}\n\n"
                    elif node_name == "tier1_barrier":
                        # Barrier runs the decision↔action linker; surface its
                        # links to the UI (other barrier state is internal).
                        dl = update.get("results", {}).get("decision_linker", {})
                        if dl:
                            yield f"data: {json.dumps({'agent': 'decision_linker', 'decision_links': dl.get('decision_links', [])})}\n\n"
                        # The barrier resolves the meeting type (explicit pick or
                        # classifier detection) — surface it so the UI knows the
                        # lens even before content_analyst finishes / for standard.
                        mt = update.get("context", {}).get("meeting_type")
                        if mt:
                            yield f"data: {json.dumps({'meeting_type': mt})}\n\n"

            yield f"data: {json.dumps({'agents_run': succeeded_agents})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/transcribe")
    async def transcribe_audio(request: Request, file: UploadFile = File(...)):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        _transcribe_log[client_ip] = [t for t in _transcribe_log[client_ip] if now - t < 60]
        if len(_transcribe_log[client_ip]) >= _TRANSCRIBE_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many transcription requests — try again in a minute")
        _transcribe_log[client_ip].append(now)

        content = await file.read()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File too large. Max 25MB.")
        try:
            transcription = await openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=(file.filename, content, file.content_type or "audio/mpeg"),
            )
            return {"transcript": transcription.text}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(exc)}")

    @router.post("/extract-document")
    async def extract_document(request: Request, file: UploadFile = File(...)):
        """Extract plain text from an uploaded document (.docx / .pdf / .txt) so it can
        be analyzed like a pasted transcript — the Article/Report "upload instead of
        paste" path. Reuses the knowledge-base loaders; no storage, just extract and
        return `{transcript}` (same shape as /transcribe so the frontend flow is shared).
        Unauthenticated to match the demo analyze flow; IP rate-limited + size-capped."""
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        _doc_extract_log[client_ip] = [t for t in _doc_extract_log[client_ip] if now - t < 60]
        if len(_doc_extract_log[client_ip]) >= _DOC_EXTRACT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many uploads — try again in a minute")
        _doc_extract_log[client_ip].append(now)

        content = await file.read()
        if len(content) > _DOC_MAX_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Max 15MB.")

        name = (file.filename or "").lower()
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        from knowledge_ingest.loaders_base import LoaderError
        try:
            if ext == "pdf":
                from knowledge_ingest import pdf_loader as loader
            elif ext == "docx":
                from knowledge_ingest import docx_loader as loader
            elif ext in ("txt", "md", "markdown", "text"):
                from knowledge_ingest import text_loader as loader
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file type. Upload a .docx, .pdf, or .txt (old .doc isn't supported — save as .docx).",
                )
            loaded = await loader.load(content)
        except HTTPException:
            raise
        except LoaderError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not read the document: {exc}")

        text = (loaded.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="No readable text found in the document.")
        return {"transcript": text, "filename": file.filename, "words": len(text.split())}

    return router

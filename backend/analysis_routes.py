import json
import time
from collections import defaultdict

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from groq import AsyncGroq
from pydantic import BaseModel

from analysis_service import AGENT_RESULT_KEY, _GRAPH, build_analysis_transcript, run_full_analysis

# Simple IP-based rate limit for /transcribe (paid Whisper call, no auth required for demo)
_transcribe_log: dict[str, list[float]] = defaultdict(list)
_TRANSCRIBE_PER_MINUTE = 5


class AnalyzeRequest(BaseModel):
    transcript: str
    speakers: list = []
    owner_name: str | None = None


def create_analysis_router(groq_client: AsyncGroq) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    @router.post("/analyze")
    async def analyze(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers, req.owner_name)
        return await run_full_analysis(transcript)

    @router.post("/analyze-stream")
    async def analyze_stream(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers, req.owner_name)

        async def event_stream():
            initial = {"transcript": transcript, "agents_to_run": [], "results": {}, "context": {}}
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
                    # tier1_barrier updates are silently skipped

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
            transcription = await groq_client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=(file.filename, content, file.content_type or "audio/mpeg"),
            )
            return {"transcript": transcription.text}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(exc)}")

    return router

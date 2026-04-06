import asyncio
import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from groq import AsyncGroq
from pydantic import BaseModel

from analysis_service import AGENT_MAP, AGENT_RESULT_KEY, build_analysis_transcript, run_full_analysis


class AnalyzeRequest(BaseModel):
    transcript: str
    speakers: list = []


def create_analysis_router(groq_client: AsyncGroq) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    @router.post("/analyze")
    async def analyze(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers)
        return await run_full_analysis(transcript)

    @router.post("/analyze-stream")
    async def analyze_stream(req: AnalyzeRequest):
        if not req.transcript.strip():
            raise HTTPException(status_code=400, detail="Transcript cannot be empty")

        transcript = build_analysis_transcript(req.transcript, req.speakers)
        from agents import orchestrator

        agents_to_run = await orchestrator.run_orchestrator(transcript)
        valid_agents = [agent for agent in agents_to_run if agent in AGENT_MAP]

        async def event_stream():
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

            yield f"data: {json.dumps({'agents_run': succeeded_agents})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/transcribe")
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
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {str(exc)}")

    return router

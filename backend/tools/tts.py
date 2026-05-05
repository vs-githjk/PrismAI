"""TTS: ElevenLabs primary, edge-tts free fallback."""

import io
import os

import httpx

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_API = "https://api.elevenlabs.io/v1"


async def _tts_elevenlabs(text: str) -> bytes | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{ELEVENLABS_API}/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                timeout=15,
            )
        if resp.status_code == 200:
            return resp.content
        print(f"[tts] ElevenLabs error {resp.status_code}: {resp.text[:100]}")
    except httpx.HTTPError as exc:
        print(f"[tts] ElevenLabs request failed: {exc}")
    return None


async def _tts_edge(text: str) -> bytes | None:
    try:
        import edge_tts  # pip install edge-tts

        communicate = edge_tts.Communicate(text, "en-US-JennyNeural")
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        return data if data else None
    except Exception as exc:
        print(f"[tts] edge-tts failed: {exc}")
    return None


async def text_to_speech(text: str) -> bytes | None:
    """Convert text to speech. Returns MP3 bytes or None on failure."""
    if ELEVENLABS_API_KEY:
        return await _tts_elevenlabs(text)
    return await _tts_edge(text)

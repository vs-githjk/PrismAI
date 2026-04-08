"""ElevenLabs TTS: convert text to speech audio bytes."""

import os

import httpx

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # default: Rachel
ELEVENLABS_API = "https://api.elevenlabs.io/v1"


async def text_to_speech(text: str) -> bytes | None:
    """Convert text to speech audio. Returns MP3 bytes or None on failure."""
    if not ELEVENLABS_API_KEY:
        return None

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
    except httpx.HTTPError:
        pass
    return None

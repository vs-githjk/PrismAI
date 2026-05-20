"""TTS: ElevenLabs primary, edge-tts free fallback."""

import io
import os
import time

from clients import get_http

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_API = "https://api.elevenlabs.io/v1"

# Circuit breaker: after a non-retryable failure (auth/quota/plan), stop trying
# ElevenLabs so every voice reply doesn't pay a wasted round-trip before falling
# back to edge-tts. 401/402/403 are permanent until the API key or plan is changed,
# so one failure is enough — no point burning a second round-trip to "confirm".
_ELEVEN_FAIL_THRESHOLD = 1
_ELEVEN_BREAKER_SECONDS = 1800  # 30 min
_PERMANENT_STATUS = {401, 402, 403}

_eleven_fail_count: int = 0
_eleven_blocked_until: float = 0.0


def _is_eleven_disabled() -> bool:
    return time.time() < _eleven_blocked_until


async def _tts_elevenlabs(text: str) -> bytes | None:
    global _eleven_fail_count, _eleven_blocked_until
    try:
        async with get_http() as client:
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
        if resp.status_code == 200 and resp.content:
            _eleven_fail_count = 0
            return resp.content
        print(f"[tts] ElevenLabs error {resp.status_code}: {resp.text[:200]}")
        if resp.status_code in _PERMANENT_STATUS:
            _eleven_fail_count += 1
            if _eleven_fail_count >= _ELEVEN_FAIL_THRESHOLD:
                _eleven_blocked_until = time.time() + _ELEVEN_BREAKER_SECONDS
                print(
                    f"[tts] ElevenLabs disabled for {_ELEVEN_BREAKER_SECONDS}s "
                    f"after {_eleven_fail_count} consecutive {resp.status_code} responses; using edge-tts"
                )
    except Exception as exc:
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
    """Convert text to speech. Returns MP3 bytes or None on failure.

    Tries ElevenLabs first (if a key is configured and the breaker is closed); falls
    back to edge-tts on any failure (quota, auth, network, empty response) so Prism
    never goes silent when a free fallback is available.
    """
    if ELEVENLABS_API_KEY and not _is_eleven_disabled():
        audio = await _tts_elevenlabs(text)
        if audio:
            return audio
        print("[tts] ElevenLabs failed, falling back to edge-tts")
    return await _tts_edge(text)

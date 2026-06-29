"""Pre-synthesized acknowledgment audio. edge-tts costs ~2.7s per clip, so ack
audio MUST be synthesized ahead of time — this cache is filled by warmup
(startup + bot-join) and read by the ack timer in realtime_routes."""

import asyncio

import ack_phrases
from tools.tts import text_to_speech

_CACHE: dict[str, bytes] = {}
_SYNTH_CONCURRENCY = 3


async def ensure_ack_audio() -> None:
    """Synthesize any missing phrases. Idempotent; failures are skipped (the
    ack timer just stays silent for a phrase with no audio)."""
    missing = [p for p in ack_phrases.all_phrases() if p not in _CACHE]
    if not missing:
        return
    sem = asyncio.Semaphore(_SYNTH_CONCURRENCY)

    async def _one(phrase: str) -> None:
        async with sem:
            try:
                audio = await text_to_speech(phrase)
                if audio:
                    _CACHE[phrase] = audio
            except Exception as e:
                print(f"[ack] synthesis failed for {phrase!r}: {type(e).__name__}: {e}")

    await asyncio.gather(*(_one(p) for p in missing))
    print(f"[ack] audio cache ready: {len(_CACHE)}/{len(ack_phrases.all_phrases())} phrases")


def get_ack_audio(phrase: str):
    return _CACHE.get(phrase)

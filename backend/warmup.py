"""Connection warm-up for the live-meeting hot path.

Measured 2026-06-12 (local, real providers): the FIRST call after idle pays
connection establishment that a spoken reply cannot afford —
  OpenAI embeddings  ~9.2s cold  vs ~250ms warm
  Supabase RPC       ~4.2s cold  vs ~1.2s warm
  edge-tts            ~2.7s      (DNS/TLS portion warmable)

Fired (fire-and-forget) at app startup and again at every bot join, so the
sockets are open before the first user-facing KB lookup or voice reply.
Strictly best-effort: every failure is logged and swallowed.
"""

import asyncio


async def _warm_embeddings() -> None:
    from embeddings import embed_text
    await embed_text("ok")


async def _warm_supabase() -> None:
    from knowledge_service import _supabase, _execute
    sb = _supabase()
    await _execute(sb.table("knowledge_docs").select("id").limit(1))


async def _warm_tts() -> None:
    from tools.tts import text_to_speech
    await text_to_speech("ok")


async def warm_external_connections(reason: str = "startup") -> None:
    results = await asyncio.gather(
        _warm_embeddings(), _warm_supabase(), _warm_tts(),
        return_exceptions=True,
    )
    failed = []
    for name, r in zip(("embeddings", "supabase", "tts"), results):
        if isinstance(r, Exception):
            failed.append(f"{name}: {type(r).__name__}")
    if failed:
        print(f"[warmup] partial ({reason}) — failed: {', '.join(failed)}")
    else:
        print(f"[warmup] connections warm ({reason})")

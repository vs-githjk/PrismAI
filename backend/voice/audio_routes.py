"""FastAPI surface for the voice loop — two WebSockets + the speaker page.

  WS  /voice/audio-in/{token}   Recall → us. Raw per-participant PCM. Builds and runs
                                the per-bot Pipecat pipeline (Flux ears). One socket per
                                bot (ingress guard). Blocks until Recall disconnects.
  WS  /voice/speaker/{token}    speaker page ↔ us. The page (loaded by Recall Output
                                Media) attaches here; we push Cartesia PCM out and read
                                its playout/pong control pings (stopwatch RTT loop).
  GET /voice/speaker-page/{token}  the "rented speaker" HTML Recall renders as the
                                bot's camera.

The two sockets connect independently and in any order, so a `VoiceSession` (holding a
late-bindable `SpeakerConnection`) is created on first contact and both sockets rendezvous
on it. The token→bot_id map is the existing per-bot realtime token (`register_realtime_token`).

Phase 2: only the ears are live-wired here (audio-in builds the pipeline, feeds finished
turns to `voice.bridge` → the old brain). The mouth is driven when the old brain calls
`voice.bridge.speak` (re-pointed in realtime_routes at live time — see phase-2 doc §5).
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from voice import bridge
from voice.pipeline import SpeakerConnection, VoicePipeline
from voice.speaker_page import speaker_page_html

router = APIRouter(tags=["voice"])


class VoiceSession:
    """Per-bot rendezvous for the audio-in and speaker sockets."""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.connection = SpeakerConnection(bot_id)
        self.pipeline: VoicePipeline | None = None
        self.audio_socket_active = False


_sessions: dict[str, VoiceSession] = {}


def get_session(bot_id: str) -> VoiceSession | None:
    return _sessions.get(bot_id)


def _session_for(bot_id: str) -> VoiceSession:
    s = _sessions.get(bot_id)
    if s is None:
        s = VoiceSession(bot_id)
        _sessions[bot_id] = s
    return s


def _resolve_bot(token: str) -> str | None:
    """token → bot_id via realtime_routes' per-bot token registry (same token the
    webhook door uses; reused for both voice sockets — see recall_routes bot-create)."""
    try:
        from realtime_routes import _realtime_token_index
        return _realtime_token_index.get(token)
    except Exception:
        return None


def _keyterms_for_bot(bot_id: str) -> list[str]:
    """Best-effort proper-noun grounding for Flux (custom_keyterms glossary + teammate
    names + doc/meeting terms). Flux supports keyterm prompting; returns [] on any
    failure so a DB hiccup never blocks the pipeline."""
    try:
        from recall_routes import bot_store, _gather_keyterms
        entry = bot_store.get(bot_id) or {}
        return _gather_keyterms(entry.get("user_id"), entry.get("workspace_id"))
    except Exception:
        return []


@router.get("/voice/speaker-page/{token}")
async def speaker_page(token: str) -> HTMLResponse:
    # Token is opaque to the page — echoed only into its speaker-WS URL. An invalid
    # token still serves the page; the speaker WS below rejects it (4404).
    return HTMLResponse(speaker_page_html(token))


@router.websocket("/voice/audio-in/{token}")
async def audio_in(ws: WebSocket, token: str) -> None:
    bot_id = _resolve_bot(token)
    if not bot_id:
        await ws.close(code=4404)
        return
    session = _session_for(bot_id)
    if session.audio_socket_active:
        # Ingress guard: exactly one audio socket per bot. A duplicate (Recall retry /
        # rogue client) is rejected rather than racing two Flux streams.
        await ws.close(code=4409)
        return

    await ws.accept()
    session.audio_socket_active = True
    session.pipeline = VoicePipeline(
        bot_id, ws, session.connection,
        on_final=bridge.make_on_final(bot_id),
        keyterms=_keyterms_for_bot(bot_id),
    )
    try:
        await session.pipeline.run()  # blocks until Recall closes the socket
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[voice] audio-in pipeline error bot={bot_id[:8]}: {exc}")
    finally:
        session.audio_socket_active = False
        try:
            await session.pipeline.stop()
        except Exception:
            pass
        session.pipeline = None


@router.websocket("/voice/speaker/{token}")
async def speaker(ws: WebSocket, token: str) -> None:
    bot_id = _resolve_bot(token)
    if not bot_id:
        await ws.close(code=4404)
        return
    session = _session_for(bot_id)
    await ws.accept()
    session.connection.attach(ws)
    try:
        while True:
            # Control channel: {"type":"playout"|"pong", ...}. The stopwatch RTT loop
            # consumes these at live time; here we drain them so the socket stays open.
            msg = await ws.receive_json()
            session.connection.on_control(msg)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[voice] speaker socket error bot={bot_id[:8]}: {exc}")
    finally:
        session.connection.detach(ws)

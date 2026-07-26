"""The "rented speaker" — a thin web page Recall's Output Media renders as the bot's
camera. It plays our streamed TTS audio into the meeting and shows Prism branding.

Recall loads this page (`GET /voice/speaker-page/{token}`) in a headless browser and
mixes its audio+video into the call. The page:

  1. opens `wss://<host>/voice/speaker/{token}` back to us,
  2. receives binary PCM frames (Int16 mono @ SAMPLE_RATE) — our Cartesia output —
     and plays them gaplessly by scheduling Web Audio buffers on a running cursor,
  3. on the FIRST audio of each utterance, sends a `{"type":"playout"}` ping so the
     backend can close the mix-hop latency loop (t4 → real playout),
  4. answers `{"type":"ping"}` with `{"type":"pong"}` for WS RTT measurement,
  5. drops everything already scheduled on `{"type":"stop"}` — the barge-in kill (Phase 5
     §1). Cartesia audio runs ahead of the ear, so cancelling the TTS turn server-side is
     only half the job; the buffers sitting in the page's Web Audio queue have to die too,
  6. renders branding (it owns the camera — this SUPERSEDES the static logo tile).

No product logic lives here: play + ping only (Q7 / master doc §3). ~110 lines of JS.

Format note (⚠ finalized at wire time): we send raw Int16 LE PCM, mono, at
`SPEAKER_SAMPLE_RATE`. The pipeline's output sink resamples Cartesia's output to this
rate before framing. Binary WS frames = audio; text WS frames = JSON control.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

# Must match the pipeline's output sink resample target (voice/pipeline.py).
SPEAKER_SAMPLE_RATE = int(os.getenv("PRISM_SPEAKER_SAMPLE_RATE", "24000"))

# Scheduling headroom for the first buffer of an utterance (and any mid-stream
# catch-up). Web Audio renders in fixed quantums, so a source started at exactly
# `currentTime` is already late by the time the audio thread reaches it and loses its
# leading samples. Cartesia streams many small frames, so without a cushion the first
# few all clip and the opening words come out cluttered — then clean, once the stream
# is far enough ahead that the cursor leads the clock on its own. This is the cost of
# a clean start: it delays first audio by exactly this much.
SPEAKER_LEAD_MS = int(os.getenv("PRISM_SPEAKER_LEAD_MS", "150"))

# The original branded bot tile (three-triangle prism logo, 16:9) — the same asset
# Recall's automatic_video_output used before Output Media took over the camera.
# Rendered full-bleed here so the speaking bot looks identical to the original tile.
_BOT_TILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "assets", "bot_tile.jpg"
)


@lru_cache(maxsize=1)
def _bot_tile_data_uri() -> str:
    """base64 data: URI of the branded tile, or "" if the asset is missing (the page
    then falls back to the CSS triangle — never a blank camera)."""
    try:
        with open(_BOT_TILE_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def speaker_page_html(token: str, sample_rate: int = SPEAKER_SAMPLE_RATE) -> str:
    """Return the full HTML document for the given bot token. `token` is echoed only
    into the WS URL; it is opaque to the page."""
    # token is URL-path-safe (token_urlsafe); embed it as a JS string literal.
    return (
        _TEMPLATE.replace("__SAMPLE_RATE__", str(sample_rate))
        .replace("__LEAD_S__", str(SPEAKER_LEAD_MS / 1000))
        .replace("__TOKEN__", token)
        .replace("__BOT_TILE__", _bot_tile_data_uri())
    )


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=1280, height=720" />
<title>PrismAI</title>
<style>
  html, body { margin: 0; height: 100%; background: #0a0f1e; overflow: hidden; }
  .stage {
    position: relative; width: 100vw; height: 100vh; overflow: hidden;
    background: radial-gradient(1200px 600px at 50% 40%, #12203f 0%, #0a0f1e 70%);
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    color: #e6f6ff;
    display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 28px;
  }
  /* Fallback CSS triangle — shows only when the branded tile asset is missing. */
  .prism-fallback {
    width: 0; height: 0; border-left: 70px solid transparent;
    border-right: 70px solid transparent; border-bottom: 120px solid #22d3ee;
    filter: drop-shadow(0 0 40px rgba(34,211,238,.55));
  }
  /* The original branded bot tile, rendered full-bleed as the bot's camera. */
  .tile {
    position: absolute; inset: 0; background-position: center; background-repeat: no-repeat;
    background-size: cover; transition: filter .2s ease, transform .2s ease;
  }
  .tile.speaking { filter: brightness(1.18) drop-shadow(0 0 60px rgba(103,232,249,.55)); transform: scale(1.012); }
  .status {
    position: absolute; bottom: 18px; right: 22px; font-size: 15px;
    color: #7fb7cc; opacity: .55; letter-spacing: .3px; z-index: 2;
  }
</style>
</head>
<body>
  <div class="stage">
    <div class="prism-fallback"></div>
    <div class="tile" id="prism" style="background-image:url('__BOT_TILE__')"></div>
    <div class="status" id="status">connecting…</div>
  </div>
<script>
(function () {
  var SAMPLE_RATE = __SAMPLE_RATE__;
  var LEAD = __LEAD_S__;     // scheduling headroom, seconds (see SPEAKER_LEAD_MS)
  var TOKEN = "__TOKEN__";
  var wsProto = location.protocol === "https:" ? "wss:" : "ws:";
  var wsUrl = wsProto + "//" + location.host + "/voice/speaker/" + TOKEN;

  var statusEl = document.getElementById("status");
  var prismEl = document.getElementById("prism");

  // Web Audio: schedule Int16 PCM buffers back-to-back on a running cursor so
  // playback is gapless. AudioContext is created at the target sample rate.
  var ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
  var cursor = 0;            // next start time on the audio timeline
  var playing = 0;          // count of scheduled-but-unfinished buffers
  var utteranceOpen = false; // have we pinged playout for the current utterance?
  var ws = null;
  var sources = [];          // scheduled-but-unfinished buffer sources, for barge-in

  function setStatus(s) { statusEl.textContent = s; }

  function connect() {
    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    ws.onopen = function () { setStatus("ready"); if (ctx.state === "suspended") ctx.resume(); };
    ws.onclose = function () { setStatus("disconnected"); setTimeout(connect, 1000); };
    ws.onerror = function () { setStatus("error"); };
    ws.onmessage = onMessage;
  }

  function onMessage(ev) {
    if (typeof ev.data === "string") {
      // Control channel (JSON): ping/pong RTT, and end-of-utterance reset.
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === "ping") { send({ type: "pong", t: m.t }); }
      else if (m.type === "flush") { utteranceOpen = false; }
      else if (m.type === "stop") { stopAll(); }
      return;
    }
    playPcm(ev.data);
  }

  function playPcm(arrayBuffer) {
    var i16 = new Int16Array(arrayBuffer);
    if (i16.length === 0) return;
    var f32 = new Float32Array(i16.length);
    for (var i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    var buf = ctx.createBuffer(1, f32.length, SAMPLE_RATE);
    buf.getChannelData(0).set(f32);
    var src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);

    var now = ctx.currentTime;
    // Starting (or resyncing) at exactly `now` means the audio thread is already past
    // the start of this buffer, which clips its opening samples. Give every fresh start
    // a cushion; mid-utterance the cursor is seconds ahead, so this is a no-op there.
    if (cursor < now + LEAD) cursor = now + LEAD;
    // First audio of an utterance → tell the backend playout has begun (mix-hop t4).
    if (!utteranceOpen) {
      utteranceOpen = true;
      prismEl.classList.add("speaking");
      send({ type: "playout", at: cursor });
    }
    src.start(cursor);
    cursor += buf.duration;
    playing++;
    sources.push(src);
    src.onended = function () {
      playing--;
      var i = sources.indexOf(src);
      if (i >= 0) sources.splice(i, 1);
      if (playing <= 0) { utteranceOpen = false; prismEl.classList.remove("speaking"); }
    };
  }

  // Barge-in: someone talked over the bot. Kill every buffer already scheduled and
  // reset the cursor so the next utterance starts at "now", not behind the dead queue.
  function stopAll() {
    for (var i = 0; i < sources.length; i++) {
      try { sources[i].onended = null; sources[i].stop(); } catch (e) {}
    }
    sources = [];
    playing = 0;
    cursor = 0;
    utteranceOpen = false;
    prismEl.classList.remove("speaking");
  }

  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  connect();
})();
</script>
</body>
</html>
"""

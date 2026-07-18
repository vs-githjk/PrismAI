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
  5. renders branding (it owns the camera — this SUPERSEDES the static logo tile).

No product logic lives here: play + ping only (Q7 / master doc §3). ~110 lines of JS.

Format note (⚠ finalized at wire time): we send raw Int16 LE PCM, mono, at
`SPEAKER_SAMPLE_RATE`. The pipeline's output sink resamples Cartesia's output to this
rate before framing. Binary WS frames = audio; text WS frames = JSON control.
"""

from __future__ import annotations

import os

# Must match the pipeline's output sink resample target (voice/pipeline.py).
SPEAKER_SAMPLE_RATE = int(os.getenv("PRISM_SPEAKER_SAMPLE_RATE", "24000"))


def speaker_page_html(token: str, sample_rate: int = SPEAKER_SAMPLE_RATE) -> str:
    """Return the full HTML document for the given bot token. `token` is echoed only
    into the WS URL; it is opaque to the page."""
    # token is URL-path-safe (token_urlsafe); embed it as a JS string literal.
    return _TEMPLATE.replace("__SAMPLE_RATE__", str(sample_rate)).replace(
        "__TOKEN__", token
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
    width: 100vw; height: 100vh; display: flex; align-items: center;
    justify-content: center; flex-direction: column; gap: 28px;
    background: radial-gradient(1200px 600px at 50% 40%, #12203f 0%, #0a0f1e 70%);
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    color: #e6f6ff;
  }
  .prism {
    width: 0; height: 0; border-left: 70px solid transparent;
    border-right: 70px solid transparent; border-bottom: 120px solid #22d3ee;
    filter: drop-shadow(0 0 40px rgba(34,211,238,.55));
    transition: transform .18s ease, filter .18s ease;
  }
  .prism.speaking { transform: scale(1.06); filter: drop-shadow(0 0 70px rgba(103,232,249,.9)); }
  .name { font-size: 44px; font-weight: 600; letter-spacing: .5px; }
  .status { font-size: 20px; color: #7fb7cc; height: 24px; }
</style>
</head>
<body>
  <div class="stage">
    <div class="prism" id="prism"></div>
    <div class="name">PrismAI</div>
    <div class="status" id="status">connecting…</div>
  </div>
<script>
(function () {
  var SAMPLE_RATE = __SAMPLE_RATE__;
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
    if (cursor < now) cursor = now; // fell behind → resync to avoid a growing gap
    // First audio of an utterance → tell the backend playout has begun (mix-hop t4).
    if (!utteranceOpen) {
      utteranceOpen = true;
      prismEl.classList.add("speaking");
      send({ type: "playout", at: cursor });
    }
    src.start(cursor);
    cursor += buf.duration;
    playing++;
    src.onended = function () {
      playing--;
      if (playing <= 0) { utteranceOpen = false; prismEl.classList.remove("speaking"); }
    };
  }

  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

  connect();
})();
</script>
</body>
</html>
"""

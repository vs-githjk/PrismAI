"""Present routes — Phase 2 of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("Wrapper page").

Recall (and the dashboard/live-share mirrors) must point at a thin page WE host,
not the provider's raw noVNC URL, for two spike-verified reasons:
  (i)  a PAUSED sandbox's stream URL serves "Sandbox Not Found" until something
       wakes it — so /vnc resumes the sandbox before handing back a URL;
  (ii) after a pause/resume cycle stock noVNC shows a manual "Connect" button
       instead of reconnecting — so the wrapper re-triggers the connection
       (backend-authoritative reconnect, see the wrapper JS below).

All endpoints are PUBLIC: the per-present token IS the capability (no login),
mirroring the live-share possession model. The token resolves to a SandboxRef
whose auth_key is the VNC password, so this module NEVER logs the resolved URL,
the ref, or the key.
"""

import asyncio

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from present_tokens import resolve_present_token
from sandbox import get_provider

router = APIRouter(tags=["present"])


def _provider():
    """Resolve the provider singleton, mapping config/import failures to 503."""
    try:
        return get_provider()
    except Exception as e:  # unknown PRISM_SANDBOX_PROVIDER, missing SDK, ...
        raise HTTPException(status_code=503, detail=f"Sandbox provider unavailable: {e}")


async def _poll_until_200(url: str, tries: int = 3, delay: float = 0.8) -> bool:
    """Bounded GET poll on the freshly-resumed stream URL until it answers 200.

    A resume returns in ~0.4s but the noVNC endpoint can lag a beat behind the
    sandbox waking, so we give it a few short tries. Never logs `url`."""
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for attempt in range(tries):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            if attempt < tries - 1:
                await asyncio.sleep(delay)
    return False


async def _pre_resume_asleep(provider, ref) -> bool:
    """Whether the sandbox was NOT actively serving before we resume it.

    This is the wrapper's reconnect signal (`resumed`): a paused sandbox's noVNC
    WebSocket is dead, so the iframe must reload to reconnect. Getting an HONEST
    answer is subtle — verified live against E2B:
      - provider.is_alive() is an existence check that returns True for a PAUSED
        sandbox too, so it can't distinguish paused from running;
      - a probe of the stream URL can't either — the sandbox's create-time
        auto_resume wakes it on ANY HTTP request, so a paused URL answers 200.
    The one reliable discriminator is the sandbox's own `state`, which the
    provider abstraction deliberately doesn't surface (and this phase must not
    modify it). So read it best-effort via the E2B SDK, lazily so present_routes
    stays importable without the SDK. Falls back to `not is_alive` (sandbox gone
    == asleep) when state is unreadable — e.g. a future non-E2B provider.
    """
    try:
        from e2b_desktop import Sandbox as _DesktopSandbox

        info = await asyncio.to_thread(_DesktopSandbox.get_info, ref.sandbox_id)
        raw = getattr(info, "state", None)
        state = getattr(raw, "value", raw)  # enum -> "paused"/"running", or str
        if state is not None:
            return "pause" in str(state).lower()
    except Exception:
        pass
    try:
        return not await asyncio.to_thread(provider.is_alive, ref)
    except Exception:
        return False


@router.get("/present/{token}", response_class=HTMLResponse)
async def present_page(token: str):
    """Serve the wrapper page (fast first paint — does NOT resume the sandbox).

    A dead/expired token gets a small 'ended' page with 410 so a scraped or
    chat-posted stale link resolves to nothing."""
    if resolve_present_token(token) is None:
        return HTMLResponse(_ENDED_HTML, status_code=410)
    return HTMLResponse(_WRAPPER_HTML.replace("__PRESENT_TOKEN__", token))


@router.get("/present/{token}/vnc")
async def present_vnc(token: str):
    """Resolve the token, GUARANTEE the sandbox is awake, and return a live URL.

    Returns {"url", "resumed"} where `resumed` is whether the sandbox was asleep
    (paused/gone) before this call woke it — the wrapper reloads its iframe when
    it sees resumed:true or a changed URL. Every provider call is wrapped in
    to_thread — the E2B SDK is synchronous and would otherwise block the loop.
    """
    entry = resolve_present_token(token)
    if entry is None:
        raise HTTPException(status_code=410, detail="This presentation has ended.")

    ref = entry["ref"]
    provider = await asyncio.to_thread(_provider)

    # Was the sandbox asleep before this call? (drives the wrapper's iframe
    # reload — see _pre_resume_asleep for why is_alive alone can't answer this.)
    asleep = await _pre_resume_asleep(provider, ref)

    # Load-bearing: resume before handing back any URL so the sandbox is
    # guaranteed awake (a paused sandbox's stream can serve a stale/not-found
    # page until woken — spike observation).
    try:
        await asyncio.to_thread(provider.resume, ref)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not wake the presentation sandbox — it may have expired.",
        )

    if entry["view_only"]:
        url = await asyncio.to_thread(provider.view_url, ref)
    else:
        url = await asyncio.to_thread(provider.interactive_url, ref)

    if not await _poll_until_200(url):
        raise HTTPException(
            status_code=503,
            detail="Presentation stream is not responding yet — retry shortly.",
        )

    return JSONResponse({"url": url, "resumed": asleep})


# --------------------------------------------------------------------- pages

_ENDED_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Presentation ended</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       background:#0a0e14;color:#94a3b8;
       font:500 15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  .card{text-align:center;padding:40px}
  .dot{width:10px;height:10px;border-radius:50%;background:#475569;
       display:inline-block;margin-bottom:16px}
</style></head>
<body><div class="card"><div class="dot"></div><div>This presentation has ended.</div></div></body></html>"""


# The wrapper is a full-viewport dark shell around a full-bleed cross-origin
# iframe (the provider's noVNC stream). {token} is injected server-side into
# __PRESENT_TOKEN__.
#
# ponytail: this wrapper + /vnc reconnect loop is E2B/noVNC-shaped (paused-sandbox
# wake, manual-"Connect" reconnect). It TOLERATES a Browserbase ref today — /vnc
# hands back the Session's live URL and the iframe loads it (the _pre_resume_asleep
# e2b_desktop probe is already lazy + guarded, falling back to not-is_alive for a
# non-E2B ref) — but re-pointing it at a proper WebRTC embed with a Session minted
# per-present, plus driving the computer-use loop over CDP, is the NEXT task, gated
# on ANTHROPIC_API_KEY + a live meeting (ADR 0003). Not built or verified here.
_WRAPPER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrismAI — Presenting</title>
<style>
  html,body{height:100%;margin:0;background:#0a0e14;overflow:hidden}
  #screen{position:fixed;inset:0;width:100%;height:100%;border:0;
          background:#0a0e14;display:block}
  #msg{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
       background:#0a0e14;color:#94a3b8;text-align:center;padding:32px;
       font:500 15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  #msg .spin{width:14px;height:14px;border-radius:50%;
             border:2px solid #1e293b;border-top-color:#22d3ee;
             display:inline-block;margin-right:10px;vertical-align:-2px;
             animation:spin 0.8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body>
  <iframe id="screen" allow="fullscreen" title="Presentation"></iframe>
  <div id="msg"><span class="spin"></span>Connecting to the presentation&hellip;</div>
<script>
(function () {
  var TOKEN = "__PRESENT_TOKEN__";
  var VNC = "/present/" + TOKEN + "/vnc";
  var screen = document.getElementById("screen");
  var msg = document.getElementById("msg");
  var currentUrl = null;      // the URL currently loaded in the iframe
  var pollTimer = null;
  var ended = false;

  function show(html) { msg.innerHTML = html; msg.style.display = "flex"; }
  function hide() { msg.style.display = "none"; }

  // We compare host+path (not the query, which carries the rotating password)
  // to detect "point at a DIFFERENT stream" (sandbox replaced -> new id -> new
  // host). A changed origin/id means reload; same stream means leave it alone.
  function sameStream(a, b) {
    if (!a || !b) return false;
    try {
      var ua = new URL(a), ub = new URL(b);
      return ua.host === ub.host && ua.pathname === ub.pathname;
    } catch (e) { return a === b; }
  }

  function ended_() {
    ended = true;
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    screen.removeAttribute("src");
    screen.style.display = "none";
    show("This presentation has ended.");
  }

  // Initial connect: retry transient failures (503 = resume/poll not ready yet)
  // with capped backoff; 410/404 is terminal.
  function connect(attempt) {
    if (ended) return;
    fetch(VNC, { headers: { "accept": "application/json" } })
      .then(function (r) {
        if (r.status === 410 || r.status === 404) { ended_(); return null; }
        if (!r.ok) { retry(attempt); return null; }
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        currentUrl = data.url;
        screen.src = data.url;
        hide();
        startPolling();
      })
      .catch(function () { retry(attempt); });
  }
  function retry(attempt) {
    if (ended || attempt >= 5) {
      if (!ended) show("Still waiting for the presentation to come online&hellip;");
      if (attempt >= 5 && !ended) {
        // keep trying slowly rather than give up entirely
        setTimeout(function () { connect(0); }, 8000);
      }
      return;
    }
    var wait = Math.min(1000 * Math.pow(1.6, attempt), 8000);
    setTimeout(function () { connect(attempt + 1); }, wait);
  }

  // BACKEND-AUTHORITATIVE RECONNECT.
  // WHY: stock noVNC does NOT self-reconnect after the sandbox pauses/resumes
  // (it shows a manual "Connect" button — spike observation), and the iframe is
  // cross-origin so we CANNOT read its WebSocket/connection state from here. So
  // the backend is the single source of truth: every 15s we re-hit /vnc, which
  // resumes the sandbox and reports resumed:true when it had to wake it (or
  // hands back a different URL if the sandbox was replaced). Either signal =>
  // reload the iframe onto the live stream. Otherwise we touch nothing, so a
  // healthy stream never flickers.
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(poll, 15000);
  }
  function poll() {
    if (ended) return;
    fetch(VNC, { headers: { "accept": "application/json" } })
      .then(function (r) {
        if (r.status === 410 || r.status === 404) { ended_(); return null; }
        if (!r.ok) return null;   // transient — keep current frame, try next tick
        return r.json();
      })
      .then(function (data) {
        if (!data) return;
        if (data.resumed || !sameStream(data.url, currentUrl)) {
          currentUrl = data.url;
          screen.src = data.url;  // reload onto the freshly-woken / new stream
          hide();
        }
      })
      .catch(function () { /* network blip — keep current frame, retry next tick */ });
  }

  connect(0);
})();
</script>
</body></html>"""

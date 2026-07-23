"""Browserbase adapter for SandboxProvider (ADR 0003 — the E2B→browser pivot).

Spec: docs/adr/0003-present-via-managed-browser-not-e2b-desktop.md.
Render spike (ran live, PASS): backend/spikes/spike_browserbase_render.py.

WHY: the E2B desktop went live and was unusable — laggy XFCE over noVNC,
keystrokes dropped, couldn't press Enter. Browserbase streams a single real
Chrome viewport over WebRTC: smooth, responsive input, and it *looks like a
browser*, not an old Linux OS. Log in once via a persistent Context; every
later meeting reuses it.

PERSISTENCE MODEL — differs from E2B (see SandboxRef):
  - E2B: one persistent sandbox, pause/resume.
  - Browserbase: a persistent CONTEXT (per user, holds logins, ~0 idle cost) +
    an EPHEMERAL SESSION per use.
  Mapped onto the protocol:
    ensure_sandbox → get-or-create the user's Context; ref carries context_id
                     (also stored in sandbox_id so it lands in the same DB col).
    resume         → create/reuse a Session bound to that Context; returns the
                     live session handle (session_id + connect_url + live_url).
    pause          → release (kill) the Session; the Context persists. Removes
                     idle cost entirely (there is no billed idle VM to snapshot).
    view_url /     → the Session's debugger_fullscreen_url (+?navbar=false). The
    interactive_url  same interactive URL for now — a view-only variant is a
                     LATER wrapper concern (ADR 0003, "Phase 2 re-pointed").
    screenshot/act → driven over CDP with Playwright (connect_over_cdp).
    is_alive       → does the Context still exist (running OR resumable).

TIER / GRACEFUL DEGRADATION (ADR 0003): persistent Contexts + a residential
egress proxy are Developer-tier ($20/mo, the accepted prod floor). The FREE
tier has neither. So this adapter BUILDS persist/proxy support but degrades:
if a Context or a context-bound Session is rejected, it falls back to an
EPHEMERAL session so the login browser still works for the demo (with a clear
log note that persistence needs the paid tier). The residential proxy is a
prod-only hook, left OFF in this build.

SESSION LIFETIME (learned live): a Browserbase session ends the instant its
controlling CDP connection drops — UNLESS it was created with keep_alive=True
(a paid-tier feature). So resume() creates keep_alive sessions, which lets
screenshot/act open a fresh CDP connection per call and reuse the same running
browser (with its navigation intact) across calls. The interactive login URL
needs no keep_alive: the human's open browser tab is itself the connection
holding the session up. pause() ends the session explicitly (REQUEST_RELEASE).

SYNC by design (matches the protocol / E2B adapter): the Browserbase REST calls
and Playwright's sync API are synchronous, so async callers wrap every method in
asyncio.to_thread. Playwright's sync API has thread affinity, so screenshot/act
DISCONNECT (never .close(), which would quit the remote Chrome) a fresh CDP
connection per call; the keep_alive session and its page state live on. The
persistent thing (the Session) is tracked in-adapter, keyed by Context id.

SECURITY: connect_url and live_url are live capabilities (signing key / an
interactive debugger). This module NEVER logs them, the API key, or any ref.

Self-check (costs one short-lived Browserbase session; free-tier safe):
    cd backend && python -m sandbox.browserbase_provider
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from .provider import SandboxRef

T = TypeVar("T")

# = Recall's output_media render surface (matches the E2B adapter + the spike).
_VIEWPORT = {"width": 1280, "height": 720}

# Frankfurt is the nearest region to a Dubai user (no ME compute region exists —
# ADR 0003). Overridable, but clamped to the SDK's known region literals.
_REGIONS = {"us-west-2", "us-east-1", "eu-central-1", "ap-southeast-1"}
_DEFAULT_REGION = "eu-central-1"

# Cap on a computer-use `wait` so a runaway duration can't wedge the worker
# thread act() runs on (the CU loop maps the model's `wait` here). Mirrors E2B.
_WAIT_CAP_S = 5.0

# computer_20250124 emits X-keysym-style keys ("Return", "ctrl+l", "Page_Down");
# Playwright wants its own names ("Enter", "Control+l", "PageDown"). Translate
# the common ones; unknown single tokens pass through (Playwright takes "a").
_KEY_ALIASES = {
    "return": "Enter",
    "enter": "Enter",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "space": "Space",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "home": "Home",
    "end": "End",
    "page_up": "PageUp",
    "prior": "PageUp",
    "page_down": "PageDown",
    "next": "PageDown",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "ctrl": "Control",
    "control": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "super": "Meta",
    "meta": "Meta",
    "cmd": "Meta",
}
# A key token is word chars only (letters/digits/_) — same guard shape as E2B.
_KEY_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _translate_key(key: Any) -> str:
    """"ctrl+l" / "Return" → Playwright "Control+l" / "Enter" (validated)."""
    if isinstance(key, list):
        tokens = [str(k) for k in key]
    else:
        tokens = str(key or "").split("+")
    out = []
    for tok in tokens:
        tok = tok.strip()
        if not tok or not _KEY_TOKEN_RE.fullmatch(tok):
            raise ValueError(f"Invalid key for browser press: {key!r}")
        out.append(_KEY_ALIASES.get(tok.lower(), tok))
    if not out:
        raise ValueError(f"Invalid key for browser press: {key!r}")
    return "+".join(out)


@dataclass
class _Session:
    """The live, ephemeral Browserbase Session behind one Context.

    `persisted` records whether the context-bound (login-persisting) create
    succeeded — False means an ephemeral fallback (free tier), so nothing typed
    into it survives the next resume. `keep_alive` records whether the session
    was created keep-alive — a Browserbase session ends the moment its
    controlling CDP connection drops UNLESS keep-alive is on, so with it False
    (free tier) screenshot/act's per-call connect can't reuse the session (each
    call would spin a fresh one). The interactive login URL is unaffected: the
    human's browser tab is itself the connection that keeps that session up."""

    session_id: str
    connect_url: str
    live_url: str
    persisted: bool
    keep_alive: bool


class BrowserbaseProvider:
    def __init__(self) -> None:
        self._bb: Any = None            # lazily-built Browserbase client
        self._project_id_cache: Optional[str] = None
        # Active session per Context (== ref.sandbox_id). Mirrors E2B's
        # `_handles`: the durable ref points at the Context; the live Session is
        # in-adapter state, recreated on resume, dropped on pause.
        self._sessions: dict[str, _Session] = {}

    # -------------------------------------------------------------- client

    def _client(self) -> Any:
        if self._bb is None:
            key = os.environ.get("BROWSERBASE_API_KEY")
            if not key:
                raise RuntimeError(
                    "BROWSERBASE_API_KEY is missing — add it to backend/.env "
                    "(keys at https://www.browserbase.com/settings)."
                )
            from browserbase import Browserbase  # lazy: keep SDK off boot path

            self._bb = Browserbase(api_key=key)
        return self._bb

    def _project_id(self) -> str:
        # The user gave no project id; resolve it from the key (spike-verified)
        # and cache it — it never changes for a key.
        if self._project_id_cache is None:
            projects = list(self._client().projects.list())
            if not projects:
                raise RuntimeError(
                    "Browserbase key has no projects — create one in the dashboard."
                )
            self._project_id_cache = projects[0].id
        return self._project_id_cache

    def _region(self) -> str:
        r = (os.getenv("PRISM_BROWSERBASE_REGION") or _DEFAULT_REGION).strip()
        return r if r in _REGIONS else _DEFAULT_REGION

    def _proxies(self) -> Any:
        """Egress-proxy hook (ADR 0003). Residential proxy is a PROD-only
        Developer-tier feature and is deliberately OFF in this build — flipping
        PRISM_BROWSERBASE_PROXY=1 turns on Browserbase's *managed* proxy only.
        Returns a value for `sessions.create(proxies=...)` or None to omit."""
        return True if os.getenv("PRISM_BROWSERBASE_PROXY") == "1" else None

    # ------------------------------------------------------------ lifecycle

    def ensure_sandbox(self, existing: Optional[SandboxRef] = None) -> SandboxRef:
        """Get-or-create the user's persistent Context. The Context is the
        durable identity (holds logins); its id lands in sandbox_id so it
        persists in the same user_settings column the E2B adapter used."""
        if existing and existing.sandbox_id and self.is_alive(existing):
            return existing

        client = self._client()
        pid = self._project_id()
        try:
            ctx = client.contexts.create(project_id=pid)
            return SandboxRef(sandbox_id=ctx.id, context_id=ctx.id)
        except Exception as exc:  # noqa: BLE001
            # Free tier: persistent Contexts are Developer-tier. Fall back to an
            # ephemeral marker so the login browser still WORKS (no cross-session
            # persistence). context_id stays None → resume() makes a plain session.
            print(
                "[browserbase] persistent Context unavailable "
                f"({type(exc).__name__}) — using an ephemeral session; login "
                "persistence needs the Developer tier ($20/mo, ADR 0003)."
            )
            return SandboxRef(sandbox_id=f"ephemeral-{secrets.token_hex(8)}")

    def resume(self, ref: SandboxRef) -> _Session:
        """Ensure a live Session for this Context and return the handle.

        Reuses a still-RUNNING tracked session; otherwise mints a fresh
        keep-alive session bound to the Context (degrading down the tier ladder
        to keep-alive-only, then ephemeral, on a free-tier rejection)."""
        return self._ensure_session(ref)

    def pause(self, ref: SandboxRef) -> None:
        """Release (kill) the Session; the Context persists. Idempotent."""
        live = self._sessions.pop(ref.sandbox_id, None)
        session_id = live.session_id if live else ref.session_id
        if not session_id:
            return
        try:
            self._client().sessions.update(session_id, status="REQUEST_RELEASE")
        except Exception as exc:  # noqa: BLE001
            # A session that's already ended/released answers an error — benign.
            print(f"[browserbase] session release skipped: {type(exc).__name__}")

    def is_alive(self, ref: SandboxRef) -> bool:
        """True if the persistent Context still exists (resumable).

        An ephemeral ref (no real Context — free-tier fallback) has nothing
        durable, so it reports False, forcing ensure_sandbox to re-provision.

        A definitive client error means the id is not a usable Context → False:
        a deleted/expired Context answers 404, and a free-tier ephemeral marker
        (or any malformed id) answers 400 (both verified live). But a TRANSIENT
        error (connection/timeout/5xx/429 rate-limit) must NOT be read as "gone":
        doing so would make ensure_sandbox provision a fresh EMPTY Context and
        overwrite the persisted id, silently destroying the user's logged-in
        Context (the whole "log in once" value prop). So re-raise those — the
        caller surfaces a retryable error instead of orphaning the login. Mirrors
        the E2B adapter, which only maps NotFoundException to False."""
        cid = ref.context_id
        if not cid:
            return False
        try:
            self._client().contexts.retrieve(cid)
            return True
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status_code", None)
            if status in (400, 404):
                return False
            raise

    # ----------------------------------------------------------------- urls

    def view_url(self, ref: SandboxRef) -> str:
        # For now the same interactive live-view (ADR 0003: a view-only variant
        # is a later wrapper concern). Lazily ensures a session so callers that
        # skip resume() still get a live URL.
        return self._ensure_session(ref).live_url

    def interactive_url(self, ref: SandboxRef) -> str:
        # The responsive login surface: debugger_fullscreen_url is fully
        # interactive (type/click), which is exactly the once-ever login flow.
        return self._ensure_session(ref).live_url

    # -------------------------------------------------------------- actions

    def screenshot(self, ref: SandboxRef) -> bytes:
        live = self._ensure_session(ref)
        return self._with_page(live, lambda page: page.screenshot(type="png"))

    def act(self, ref: SandboxRef, action: dict) -> None:
        live = self._ensure_session(ref)
        self._with_page(live, lambda page: self._do_act(page, action))

    def _do_act(self, page: Any, action: dict) -> None:
        kind = (action.get("type") or "").lower()
        x, y = action.get("x"), action.get("y")
        x = int(x) if x is not None else None
        y = int(y) if y is not None else None

        if kind == "click":
            page.mouse.click(x, y)
        elif kind == "double_click":
            page.mouse.dblclick(x, y)
        elif kind == "right_click":
            page.mouse.click(x, y, button="right")
        elif kind == "middle_click":
            page.mouse.click(x, y, button="middle")
        elif kind == "triple_click":
            page.mouse.click(x, y, click_count=3)
        elif kind == "mouse_move":
            if x is None or y is None:
                raise ValueError("mouse_move requires x and y")
            page.mouse.move(x, y)
        elif kind == "type":
            page.keyboard.type(action.get("text") or "")
        elif kind == "key":
            page.keyboard.press(_translate_key(action.get("key") or action.get("keys")))
        elif kind == "scroll":
            if x is not None and y is not None:
                page.mouse.move(x, y)
            ticks = int(action.get("amount") or 3)
            dy = ticks * 100 * (-1 if action.get("direction") == "up" else 1)
            page.mouse.wheel(0, dy)
        elif kind == "navigate":
            page.goto(str(action["url"]), wait_until="domcontentloaded")
        elif kind == "left_click_drag":
            sx, sy = action.get("start_x"), action.get("start_y")
            sx = int(sx) if sx is not None else None
            sy = int(sy) if sy is not None else None
            if None in (sx, sy, x, y):
                raise ValueError("left_click_drag requires start_x/start_y and x/y")
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(x, y)
            page.mouse.up()
        elif kind in ("left_mouse_down", "left_mouse_up"):
            if x is not None and y is not None:
                page.mouse.move(x, y)
            page.mouse.down() if kind == "left_mouse_down" else page.mouse.up()
        elif kind == "wait":
            secs = action.get("seconds")
            try:
                secs = float(secs) if secs is not None else 1.0
            except (TypeError, ValueError):
                secs = 1.0
            time.sleep(max(0.0, min(secs, _WAIT_CAP_S)))
        elif kind == "cursor_position":
            pass  # observation-only; the CU loop re-observes with a screenshot
        else:
            raise ValueError(f"Unknown sandbox action type: {kind!r}")

    # -------------------------------------------------------------- helpers

    def _ensure_session(self, ref: SandboxRef) -> _Session:
        key = ref.sandbox_id
        live = self._sessions.get(key)
        if live and self._session_running(live.session_id):
            return live
        if live:
            self._sessions.pop(key, None)  # tracked handle went stale
        live = self._create_session(ref)
        self._sessions[key] = live
        return live

    def _create_session(self, ref: SandboxRef) -> _Session:
        client = self._client()
        common: dict[str, Any] = {
            "project_id": self._project_id(),
            "region": self._region(),
        }
        proxies = self._proxies()
        if proxies is not None:
            common["proxies"] = proxies
        vp = {"viewport": _VIEWPORT}

        # Degradation ladder, richest first (ADR 0003). keep_alive lets the
        # session outlive a CDP disconnect (needed so screenshot/act can connect
        # per-call and reuse it); the context bind persists logins. Both are
        # paid-tier — on free tier the create is rejected and we drop down a rung
        # so the login browser still works (just without persistence/keep-alive).
        ladder: list[tuple[str, dict, bool, bool]] = []
        if ref.context_id:
            ladder.append((
                "keep_alive + persistent context",
                {"keep_alive": True,
                 "browser_settings": {**vp, "context": {"id": ref.context_id,
                                                         "persist": True}}},
                True, True,
            ))
        ladder.append(("keep_alive", {"keep_alive": True, "browser_settings": vp},
                       False, True))
        ladder.append(("ephemeral", {"browser_settings": vp}, False, False))

        last_exc: Optional[Exception] = None
        for i, (label, kwargs, persisted, keep_alive) in enumerate(ladder):
            try:
                session = client.sessions.create(**common, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
            if i > 0:  # a richer tier was rejected — say so, once
                print(
                    f"[browserbase] session created at fallback tier '{label}' "
                    "(a richer tier was rejected; persistent login + keep-alive "
                    "need the Developer tier, $20/mo, ADR 0003)."
                )
            return _Session(
                session_id=session.id,
                connect_url=session.connect_url,
                live_url=self._live_url(session.id),
                persisted=persisted,
                keep_alive=keep_alive,
            )
        raise RuntimeError(
            f"Browserbase session create failed at every tier: {last_exc}"
        )

    def _session_running(self, session_id: str) -> bool:
        try:
            s = self._client().sessions.retrieve(session_id)
            return str(getattr(s, "status", "")).upper() == "RUNNING"
        except Exception:  # noqa: BLE001
            return False

    def _live_url(self, session_id: str) -> str:
        # debugger_fullscreen_url is the clean, interactive, embeddable viewport
        # (spike-verified: 200, no X-Frame-Options/CSP). ?navbar=false hides the
        # devtools chrome. NEVER logged — it's a live capability.
        dbg = self._client().sessions.debug(session_id)
        return self._with_navbar_false(dbg.debugger_fullscreen_url)

    @staticmethod
    def _with_navbar_false(url: str) -> str:
        if not url:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}navbar=false"

    def _with_page(self, live: _Session, fn: Callable[[Any], T]) -> T:
        # Fresh Playwright CDP connection per call: the sync API has thread
        # affinity and act()/screenshot() run under asyncio.to_thread (any pool
        # thread), so a connection can't be cached across calls. connect_over_cdp
        # is sub-second (the remote Chrome is already up).
        #
        # NEVER call browser.close() here: that sends Browser.close and quits the
        # remote Chrome, ending the session (verified live). We only DISCONNECT —
        # exiting the sync_playwright context drops the local driver + WS. A
        # keep_alive session survives that disconnect (verified), so the next
        # call reconnects to the same browser with its navigation intact. On a
        # non-keep_alive (free-tier) session the disconnect ends it — a known,
        # accepted degradation for screenshot/act (a paid-tier CU-loop feature).
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(live.connect_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return fn(page)


# --------------------------------------------------------------------- demo


def demo() -> int:
    """Live self-check (ADR 0003 acceptance gate): resolve project → ensure
    Context → create login Session (resume) → print the INTERACTIVE login URL →
    screenshot via CDP (assert a real, non-blank page) → release Session → PASS.

    Fully self-cleaning: releases its Session and deletes the Context it made,
    so a released URL is dead afterwards. For a LIVE URL a human can open, run
    mint_review_url() (the __main__ block does, after this passes)."""
    if not os.environ.get("BROWSERBASE_API_KEY"):
        print(
            "ERROR: BROWSERBASE_API_KEY is not set — add it to backend/.env "
            "(https://www.browserbase.com/settings)",
            file=sys.stderr,
        )
        return 2

    provider = BrowserbaseProvider()
    ref: Optional[SandboxRef] = None

    def step(label: str, fn: Callable[[], T]) -> T:
        t0 = time.perf_counter()
        out = fn()
        print(f"[demo] {label} in {time.perf_counter() - t0:.2f}s")
        return out

    try:
        pid = step("resolve project (from key)", provider._project_id)
        print(f"[demo]   project_id : {pid}")
        print(f"[demo]   region     : {provider._region()}")

        ref = step("ensure_sandbox (Context get-or-create)",
                   lambda: provider.ensure_sandbox(None))
        print(f"[demo]   sandbox_id : {ref.sandbox_id}")
        print(f"[demo]   context_id : {ref.context_id}  "
              f"(None == free-tier ephemeral fallback)")

        live = step("resume (create login Session bound to Context)",
                    lambda: provider.resume(ref))
        print(f"[demo]   session_id : {live.session_id}")
        print(f"[demo]   persisted  : {live.persisted}  "
              f"(False == ephemeral; login won't persist on free tier)")

        # The interactive, responsive login surface — printed for a human to
        # open. The PROVIDER never logs this; the demo is a manual dev tool.
        interactive = provider.interactive_url(ref)
        print("=" * 72)
        print(f"INTERACTIVE_LOGIN_URL {interactive}")
        print("=" * 72)

        # Prove a real page renders through CDP (not a blank tab): navigate,
        # let it paint, screenshot, assert PNG magic + non-trivial size.
        step("act navigate -> example.com",
             lambda: provider.act(ref, {"type": "navigate",
                                        "url": "https://example.com"}))
        time.sleep(3)
        shot = step("screenshot (via CDP)", lambda: provider.screenshot(ref))
        print(f"[demo]   screenshot : {len(shot)} bytes")
        assert shot[:8] == b"\x89PNG\r\n\x1a\n", "screenshot is not a PNG"
        assert len(shot) > 3000, "screenshot too small to be a real rendered page"

        assert provider.is_alive(ref) == bool(ref.context_id), \
            "is_alive should track Context existence"

        step("pause (release Session; Context persists)",
             lambda: provider.pause(ref))

        print("PASS")
        return 0
    finally:
        # Release any still-tracked session (covers the failure paths) and
        # delete the Context so the self-check leaks nothing.
        if ref is not None:
            try:
                provider.pause(ref)
            except Exception:  # noqa: BLE001
                pass
            cid = ref.context_id
            if cid:
                try:
                    provider._client().contexts.delete(cid)
                    print(f"[demo] deleted context {cid}")
                except Exception as exc:  # noqa: BLE001
                    # A just-released session can still hold the Context for a
                    # beat (BadRequest). Contexts are ~$0 and meant to persist,
                    # so this leak is benign — delete it from the dashboard if
                    # you care: https://www.browserbase.com/contexts
                    print(f"[demo] context cleanup skipped ({type(exc).__name__}); "
                          f"stray test context id={cid}")


def mint_review_url() -> int:
    """Mint ONE session and leave it RUNNING so a human/orchestrator can open a
    live interactive URL and eyeball responsiveness. Intentionally does not
    clean up — the session expires on its own (free-tier idle / 15-min cap);
    re-run to mint another. Prints REVIEW_LIVE_URL."""
    provider = BrowserbaseProvider()
    ref = provider.ensure_sandbox(None)
    provider.resume(ref)
    print("=" * 72)
    print(f"REVIEW_LIVE_URL {provider.interactive_url(ref)}")
    print("[demo] review session left running (expires on its own).")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    # Windows consoles default to cp1252 and choke on any non-ASCII in output —
    # force UTF-8 so the self-check never dies on an arrow/emoji in a log line.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if "--review" in sys.argv:
        sys.exit(mint_review_url())
    code = demo()
    if code == 0:
        try:
            mint_review_url()
        except Exception as exc:  # noqa: BLE001
            print(f"[demo] review URL mint skipped: {type(exc).__name__}: {exc}")
    sys.exit(code)

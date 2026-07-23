"""E2B adapter for SandboxProvider (spike-verified: backend/spikes/spike1_report.json).

SYNC by design: e2b-desktop 2.4.1 ships only a sync desktop Sandbox — the
AsyncSandbox that e2b re-exports is the base sandbox without the XFCE boot,
stream server, or xdotool input helpers (checked against installed source).
Async callers must wrap every method in asyncio.to_thread.

Self-check (the Phase-1 acceptance gate — costs one short-lived sandbox):
    cd backend && python -m sandbox.e2b_provider
"""

import os
import re
import shlex
import sys
import time
from typing import Callable, Optional, TypeVar

from e2b import NotFoundException
from e2b_desktop import Sandbox as DesktopSandbox

from .provider import SandboxRef

_NOVNC_PORT = 6080  # _VNCServer default; get_host(6080) == the stream host

# Cap on a computer-use `wait` so a runaway/hostile duration can't wedge the
# worker thread that act() runs on (the CU loop maps the model's `wait` here).
_WAIT_CAP_S = 5.0

# X keysyms / modifiers are word characters only (Return, Page_Down, F5, ctrl).
# The SDK f-strings the key straight into `xdotool key {key}` under bash -c,
# so anything outside this set must be rejected, not executed.
_KEYSYM_RE = re.compile(r"[A-Za-z0-9_]+")

T = TypeVar("T")


def _idle_seconds() -> int:
    try:
        return int(os.getenv("PRISM_SANDBOX_IDLE_S", "600"))
    except ValueError:
        return 600


class E2BProvider:
    def __init__(self) -> None:
        # Live handles by sandbox_id — connect() is cheap (~0.35s) but not
        # free, and act() arrives in bursts during a computer-use loop.
        self._handles: dict[str, DesktopSandbox] = {}

    # ------------------------------------------------------------ lifecycle

    def ensure_sandbox(self, existing: Optional[SandboxRef] = None) -> SandboxRef:
        if existing and existing.sandbox_id and self.is_alive(existing):
            return existing

        sbx = DesktopSandbox.create(
            resolution=(1280, 720),  # = Recall's output_media render surface
            timeout=_idle_seconds(),
            lifecycle={
                # Idle teardown is the provider's job: full-memory auto-pause
                # keeps the VNC server + browser resident in the snapshot.
                "on_timeout": {"action": "pause", "keep_memory": True},
                # Spike observation: WITHOUT auto_resume a paused sandbox's
                # stream URL serves "Sandbox Not Found" — with it, Recall
                # merely loading the page wakes the desktop. The explicit
                # resume() below stays the load-bearing path regardless.
                "auto_resume": True,
            },
        )
        try:
            # stream.start happens HERE and ONLY here: the auth key is
            # generated CLIENT-side inside start() and is unrecoverable later
            # (reconnected handles never get a .stream object) — the caller
            # must persist the returned ref immediately.
            sbx.stream.start(require_auth=True)
            ref = SandboxRef(
                sandbox_id=sbx.sandbox_id,
                auth_key=sbx.stream.get_auth_key(),
                stream_base=f"https://{sbx.get_host(_NOVNC_PORT)}/vnc.html",
            )
        except Exception:
            # A sandbox whose auth key we never captured is permanently
            # unviewable — reap it rather than leak a billed, unusable VM.
            try:
                sbx.kill()
            except Exception:
                pass
            raise
        self._handles[ref.sandbox_id] = sbx
        return ref

    def resume(self, ref: SandboxRef) -> DesktopSandbox:
        # connect() auto-resumes a paused sandbox from its memory snapshot;
        # the VNC server is already running inside it, so NEVER call
        # stream.start again (it would raise "Stream is already running" —
        # and reconnected handles have no .stream anyway). URLs keep working:
        # they're rebuilt from the persisted ref, not the handle.
        self._handles.pop(ref.sandbox_id, None)
        sbx = DesktopSandbox.connect(ref.sandbox_id, timeout=_idle_seconds())
        # connect(timeout=) only extends; set_timeout guarantees a fresh full
        # idle window even if a longer TTL was somehow still pending.
        sbx.set_timeout(_idle_seconds())
        self._handles[ref.sandbox_id] = sbx
        return sbx

    def pause(self, ref: SandboxRef) -> None:
        self._handles.pop(ref.sandbox_id, None)  # handle goes stale on pause
        DesktopSandbox.pause(ref.sandbox_id)  # keep_memory=True default

    def is_alive(self, ref: SandboxRef) -> bool:
        try:
            DesktopSandbox.get_info(ref.sandbox_id)  # works running OR paused
            return True
        except NotFoundException:
            return False

    # ----------------------------------------------------------------- urls

    def view_url(self, ref: SandboxRef) -> str:
        # Raw provider URL for Phase 1. The Phase-2 wrapper must front this:
        # stock noVNC shows a "Connect" button after a pause/resume cycle
        # instead of reconnecting (spike observation).
        return (
            f"{ref.stream_base}?autoconnect=true&resize=scale"
            f"&view_only=true&password={ref.auth_key}"
        )

    def interactive_url(self, ref: SandboxRef) -> str:
        return (
            f"{ref.stream_base}?autoconnect=true&resize=scale"
            f"&password={ref.auth_key}"
        )

    # -------------------------------------------------------------- actions

    def screenshot(self, ref: SandboxRef) -> bytes:
        return bytes(self._with_handle(ref, lambda s: s.screenshot(format="bytes")))

    def act(self, ref: SandboxRef, action: dict) -> None:
        kind = (action.get("type") or "").lower()
        x, y = action.get("x"), action.get("y")
        # Coordinates end up inside f-string shell commands in the SDK
        # (`xdotool mousemove --sync {x} {y}`) — coerce to int so a hostile
        # or malformed value fails here instead of reaching bash.
        x = int(x) if x is not None else None
        y = int(y) if y is not None else None
        if kind == "click":
            self._move_first(ref, x, y)
            self._with_handle(ref, lambda s: s.left_click())
        elif kind == "double_click":
            self._move_first(ref, x, y)
            self._with_handle(ref, lambda s: s.double_click())
        elif kind == "right_click":
            self._move_first(ref, x, y)
            self._with_handle(ref, lambda s: s.right_click())
        elif kind == "type":
            self._with_handle(ref, lambda s: s.write(action.get("text") or ""))
        elif kind == "key":
            key = action.get("key") or action.get("keys")
            if isinstance(key, str) and "+" in key:
                key = key.split("+")  # "ctrl+l" → chord
            parts = key if isinstance(key, list) else [key]
            if not parts or not all(
                isinstance(k, str) and _KEYSYM_RE.fullmatch(k) for k in parts
            ):
                raise ValueError(f"Invalid key for sandbox press: {key!r}")
            self._with_handle(ref, lambda s: s.press(key))
        elif kind == "scroll":
            direction = "up" if action.get("direction") == "up" else "down"
            amount = int(action.get("amount") or 3)
            if x is not None and y is not None:
                self._with_handle(ref, lambda s: s.move_mouse(x, y))
            self._with_handle(ref, lambda s: s.scroll(direction, amount))
        elif kind == "navigate":
            # The SDK interpolates unquoted into `xdg-open {url}` (bash -c) —
            # quote here so a hostile URL can't smuggle shell commands into
            # the sandbox (it holds the user's logged-in sessions).
            url = shlex.quote(str(action["url"]))
            self._with_handle(ref, lambda s: s.open(url))
        # --- computer-use verbs the CU loop needs beyond the Phase-1 set. ---
        elif kind == "mouse_move":
            if x is None or y is None:
                raise ValueError("mouse_move requires x and y")
            self._with_handle(ref, lambda s: s.move_mouse(x, y))
        elif kind == "middle_click":
            self._move_first(ref, x, y)
            self._with_handle(ref, lambda s: s.middle_click())
        elif kind == "triple_click":
            # e2b-desktop has no triple_click; approximate with three bare
            # clicks at the same point (move once, so a 0-coordinate edge click
            # still lands — same falsy-0 guard as _move_first).
            self._move_first(ref, x, y)
            for _ in range(3):
                self._with_handle(ref, lambda s: s.left_click())
        elif kind == "left_click_drag":
            sx, sy = action.get("start_x"), action.get("start_y")
            sx = int(sx) if sx is not None else None
            sy = int(sy) if sy is not None else None
            if None in (sx, sy, x, y):
                raise ValueError("left_click_drag requires start_x/start_y and x/y")
            self._with_handle(ref, lambda s: s.drag((sx, sy), (x, y)))
        elif kind in ("left_mouse_down", "left_mouse_up"):
            if x is not None and y is not None:
                self._with_handle(ref, lambda s: s.move_mouse(x, y))
            if kind == "left_mouse_down":
                self._with_handle(ref, lambda s: s.mouse_press("left"))
            else:
                self._with_handle(ref, lambda s: s.mouse_release("left"))
        elif kind == "wait":
            # A CU pause (e.g. letting a page paint). Local sleep — the sandbox
            # needs to do nothing during it — capped so a huge duration can't
            # wedge the worker thread. Runs under asyncio.to_thread from the loop.
            secs = action.get("seconds")
            try:
                secs = float(secs) if secs is not None else 1.0
            except (TypeError, ValueError):
                secs = 1.0
            time.sleep(max(0.0, min(secs, _WAIT_CAP_S)))
        elif kind == "cursor_position":
            # No-op: the CU loop answers a cursor-position request by re-observing
            # (a fresh screenshot), so there is nothing to drive here. Recognised
            # explicitly so act() never raises on it.
            pass
        else:
            raise ValueError(f"Unknown sandbox action type: {kind!r}")

    def _move_first(self, ref: SandboxRef, x: Optional[int], y: Optional[int]) -> None:
        # The SDK's click helpers gate the move on `if x and y:` — coordinate
        # 0 is falsy, so a click at the screen edge would silently land
        # wherever the cursor last was. Move explicitly, then click bare.
        if x is not None and y is not None:
            self._with_handle(ref, lambda s: s.move_mouse(x, y))

    # -------------------------------------------------------------- helpers

    def _with_handle(self, ref: SandboxRef, fn: Callable[[DesktopSandbox], T]) -> T:
        cached = self._handles.get(ref.sandbox_id)
        if cached is None:
            return fn(self._connect(ref))
        try:
            return fn(cached)
        except NotFoundException:
            raise  # sandbox is gone — reconnecting won't help
        except Exception:
            # Cached handle went stale (sandbox auto-paused since we
            # connected) — one fresh connect (auto-resumes) and retry.
            self._handles.pop(ref.sandbox_id, None)
            return fn(self._connect(ref))

    def _connect(self, ref: SandboxRef) -> DesktopSandbox:
        sbx = DesktopSandbox.connect(ref.sandbox_id, timeout=_idle_seconds())
        self._handles[ref.sandbox_id] = sbx
        return sbx


# --------------------------------------------------------------------- demo


def demo() -> int:
    """Live self-check: fresh sandbox → URLs → screenshot A → navigate →
    screenshot B (must differ) → pause → resume → screenshot C (post-resume
    usability) → kill. Prints PASS on success."""
    if not os.environ.get("E2B_API_KEY"):
        print(
            "ERROR: E2B_API_KEY is not set — add it to backend/.env "
            "(https://e2b.dev/dashboard)",
            file=sys.stderr,
        )
        return 2

    provider = E2BProvider()
    ref: Optional[SandboxRef] = None

    def step(label: str, fn: Callable[[], T]) -> T:
        t0 = time.perf_counter()
        out = fn()
        print(f"[demo] {label} in {time.perf_counter() - t0:.2f}s")
        return out

    try:
        ref = step("ensure_sandbox (fresh create + stream.start)",
                   lambda: provider.ensure_sandbox(None))
        print(f"[demo]   sandbox_id      : {ref.sandbox_id}")
        print(f"[demo]   view_url        : {provider.view_url(ref)}")
        print(f"[demo]   interactive_url : {provider.interactive_url(ref)}")

        import httpx  # repo dependency; proves the stream endpoint is live
        status = httpx.get(provider.view_url(ref), timeout=10.0).status_code
        print(f"[demo] view_url GET -> {status}")
        assert status == 200, f"view_url answered {status}, expected 200"

        ref2 = provider.ensure_sandbox(ref)
        assert ref2 is ref, "ensure_sandbox with a live ref must be a no-op"
        print("[demo] ensure_sandbox(existing) idempotent: OK")

        shot_a = step("screenshot A", lambda: provider.screenshot(ref))
        print(f"[demo]   A = {len(shot_a)} bytes")

        provider.act(ref, {"type": "navigate", "url": "https://example.com"})
        print("[demo] navigate -> https://example.com; waiting for paint...")
        time.sleep(10)

        shot_b = step("screenshot B", lambda: provider.screenshot(ref))
        print(f"[demo]   B = {len(shot_b)} bytes")
        assert shot_a != shot_b, "A == B — navigate had no visible effect"

        step("pause", lambda: provider.pause(ref))
        step("resume (connect + set_timeout)", lambda: provider.resume(ref))

        shot_c = step("screenshot C (post-resume)", lambda: provider.screenshot(ref))
        print(f"[demo]   C = {len(shot_c)} bytes")
        assert shot_c, "post-resume screenshot is empty"
        assert provider.is_alive(ref), "is_alive false after resume"

        print("PASS")
        return 0
    finally:
        if ref is not None:
            try:
                killed = DesktopSandbox.kill(ref.sandbox_id)
                print(f"[demo] killed {ref.sandbox_id} -> {killed}")
            except Exception as e:  # noqa: BLE001
                print(f"[demo] cleanup failed for {ref.sandbox_id}: {e} — kill it "
                      f"at https://e2b.dev/dashboard (auto-expires after timeout)")


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    sys.exit(demo())

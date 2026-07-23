"""Sandbox provider abstraction — the bot's presentation screen (Phase 1).

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md.
Pivot: docs/adr/0003-present-via-managed-browser-not-e2b-desktop.md.

Two concrete adapters, both spike-verified, swapped via PRISM_SANDBOX_PROVIDER
without touching callers: `browserbase` (a managed cloud Chrome over WebRTC —
the default since ADR 0003) and `e2b` (the original Linux/XFCE desktop over
noVNC — kept as a fallback). The two have different persistence shapes but the
SAME protocol below (see SandboxRef for how the fields map to each).

This module owns NO persistence: routes read the user's `user_settings`
columns (sandbox_id / sandbox_auth_key / sandbox_stream_url) into a
SandboxRef, call the provider, and persist any NEW ref that comes back.
"""

import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class SandboxRef:
    """Everything needed to reach a sandbox WITHOUT a live SDK handle.

    Two adapters map onto this shape:

    E2B (desktop): one persistent sandbox (pause/resume). `auth_key` is the
    noVNC password, generated client-side at the one and only stream.start()
    and unrecoverable afterwards — whoever calls ensure_sandbox must persist a
    fresh ref immediately. Column mapping: sandbox_id → user_settings.sandbox_id,
    auth_key → sandbox_auth_key, stream_base → sandbox_stream_url (the bare
    noVNC page URL, e.g. https://6080-{sandbox_id}.e2b.app/vnc.html).

    Browserbase (browser): a persistent Context (per user, holds logins) + an
    ephemeral Session per use (ADR 0003). The DURABLE identity is the Context
    id, stored in `sandbox_id` (== `context_id`) so it lands in the same
    user_settings.sandbox_id column; `auth_key`/`stream_base` are unused (""),
    and the per-session fields (`session_id`/`connect_url`/`live_url`) are
    minted at resume() and tracked in-adapter, not persisted (a Session dies on
    pause). They live on the ref only as an optional carry for callers that
    want the live handle without going back through the adapter.

    The generalized fields default to None/"" so an E2B ref built with the
    original three positional-by-keyword args is unchanged, and a Browserbase
    ref can be built from a Context id alone. All fields are hashable (str/None)
    so the frozen dataclass stays hashable.
    """

    sandbox_id: str
    auth_key: str = ""
    stream_base: str = ""
    # --- generalized provider fields (Browserbase + future adapters) ---
    context_id: Optional[str] = None   # persistent login profile (Browserbase Context)
    session_id: Optional[str] = None   # ephemeral session, minted per resume()
    connect_url: Optional[str] = None  # CDP endpoint for the active session
    live_url: Optional[str] = None     # per-session live/interactive view URL


class SandboxProvider(Protocol):
    """Per-user persistent desktop sandboxes.

    All methods are SYNCHRONOUS: e2b-desktop 2.4.1 has no async desktop
    Sandbox (base e2b's AsyncSandbox lacks the XFCE/stream/input helpers),
    so async callers must wrap every call in asyncio.to_thread.
    """

    def ensure_sandbox(self, existing: Optional[SandboxRef] = None) -> SandboxRef:
        """Idempotent get-or-create. Returns `existing` untouched when that
        sandbox is still resumable; otherwise provisions a fresh one (new id
        AND new auth key — the caller must re-persist)."""
        ...

    def resume(self, ref: SandboxRef) -> Any:
        """Connect (auto-resumes a paused sandbox) and bump the idle timeout.
        Returns the live provider handle."""
        ...

    def pause(self, ref: SandboxRef) -> None:
        """Full-state memory snapshot; billing stops."""
        ...

    def view_url(self, ref: SandboxRef) -> str:
        """View-only stream URL (what Recall shares / the mirrors embed).
        Raw provider URL in Phase 1 — the wrapper page fronts it in Phase 2."""
        ...

    def interactive_url(self, ref: SandboxRef) -> str:
        """Full-input desktop URL (workspace setup / future takeover). Must
        never appear in any meeting-facing payload."""
        ...

    def screenshot(self, ref: SandboxRef) -> bytes:
        ...

    def act(self, ref: SandboxRef, action: dict) -> None:
        """One desktop action: {type: click|double_click|right_click|
        middle_click|triple_click|type|key|scroll|navigate|mouse_move|
        left_click_drag|left_mouse_down|left_mouse_up|wait|cursor_position, ...}
        — the Phase-3 computer-use loop's verbs (computer_use.translate_action
        maps every computer_20250124 tool action onto one of these)."""
        ...

    def is_alive(self, ref: SandboxRef) -> bool:
        """True if the sandbox still exists (running OR paused = resumable)."""
        ...


_provider: Optional[SandboxProvider] = None


def get_provider() -> SandboxProvider:
    """Process-wide provider singleton selected by PRISM_SANDBOX_PROVIDER
    (default browserbase since ADR 0003; `e2b` for the desktop fallback) —
    mirrors the shared-client pattern in clients.py.

    The adapter SDK is imported lazily inside each branch so the unselected
    provider's SDK never has to be installed/importable for the app to boot.
    """
    global _provider
    if _provider is None:
        name = (os.getenv("PRISM_SANDBOX_PROVIDER") or "browserbase").strip().lower()
        if name == "browserbase":
            from .browserbase_provider import BrowserbaseProvider

            _provider = BrowserbaseProvider()
        elif name == "e2b":
            from .e2b_provider import E2BProvider

            _provider = E2BProvider()
        else:
            raise ValueError(
                f"Unknown PRISM_SANDBOX_PROVIDER: {name!r} "
                "(supported: browserbase, e2b)"
            )
    return _provider

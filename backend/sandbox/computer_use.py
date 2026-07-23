"""Computer-use agent loop — Phase 3C of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("computer_use.py
— the agent loop") + ADR docs/adr/0002. This is the open-ended driver: Claude
looks at the sandbox desktop (screenshot), picks an action, we execute it via
the SandboxProvider, feed a fresh screenshot back, and repeat until the goal is
on screen — or a bound trips.

`run_computer_use` yields short MILESTONE narration strings only (an arrival
line, walkthrough sentences, errors, and a final one-line summary) — NOT
per-step spam. The presentation manager routes those to voice/chat; the step
trail is a dashboard concern, out of scope here.

This loop does NOT go through agents.utils.llm_call (that's the text-only
Groq/OpenAI path): computer use needs the Anthropic *beta* Messages API with
the `computer` tool, so it calls the shared AsyncAnthropic client directly.
That is the sanctioned exception the spec calls out (precedent: chat_routes →
Groq). The shared client is agents.utils._get_anthropic() — the process-wide,
memoized AsyncAnthropic (clients.py exposes the HTTP/OpenAI singletons but no
Anthropic one today; agents.utils is where it lives).

CU model is PRISM_CU_MODEL (default claude-haiku-4-5), which supports computer
use on the older `computer_20250124` tool version behind the
`computer-use-2025-01-24` beta header (the enhanced `computer_20251124` is
Sonnet 5 / Opus 4.5+). Sandbox display is 1280x720 — Recall's render surface
and the cost-efficient CU screenshot resolution.

No ANTHROPIC_API_KEY is available in CI, so the loop is unit-tested with a fake
provider + a stubbed Anthropic client (backend/spikes/phase3_cu_loop_check.py);
the live run against a real sandbox + key is deferred.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any, AsyncIterator, Optional

from .provider import SandboxRef, get_provider

# Recall's render surface AND the cost-efficient CU screenshot resolution.
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 720

_BETA = "computer-use-2025-01-24"
_TOOL_VERSION = "computer_20250124"
_DEFAULT_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 1024
_MEDIA_TYPE = "image/png"

# Upper bound on a single scroll's tick count. e2b maps scroll onto
# `xdotool click --repeat {n} {4|5}` — ONE command whose runtime scales with n,
# executed under a plain asyncio.to_thread that the loop's per-turn wall-clock
# guard (asyncio.wait_for on the MODEL call only) does NOT cover. An unbounded n
# would let one action scroll for minutes past timeout_s; bound it like coords.
_MAX_SCROLL_TICKS = 30


def _cu_model(model: Optional[str]) -> str:
    return model or os.getenv("PRISM_CU_MODEL", _DEFAULT_MODEL)


def _tool_def() -> dict:
    """The computer_20250124 tool definition, sized to the sandbox display."""
    return {
        "type": _TOOL_VERSION,
        "name": "computer",
        "display_width_px": DISPLAY_WIDTH,
        "display_height_px": DISPLAY_HEIGHT,
    }


def _system_prompt(walkthrough: bool) -> str:
    if walkthrough:
        mode = (
            "You were asked to WALK THE MEETING THROUGH this. Once the target is "
            "on screen, briefly narrate what's visible in a few short sentences as "
            "you go — what it is and the key points a viewer should notice — then "
            "stop."
        )
    else:
        mode = (
            "When the target is on screen, give a SINGLE one-line arrival note "
            '(e.g. "Here\'s the auth PR.") and then stop. Do not narrate step by '
            "step."
        )
    return (
        "You are PrismAI's in-meeting presenter, driving a Linux desktop web "
        "browser that is screenshared live into a meeting. Your only job is to "
        "REACH and SHOW the target. The display is "
        f"{DISPLAY_WIDTH}x{DISPLAY_HEIGHT}. Use the `computer` tool to screenshot, "
        "navigate, scroll, and click your way to the target, taking the shortest "
        "path.\n\n"
        "STRICT LIMITS — you are a READ-ONLY presenter:\n"
        "- NEVER perform a destructive, irreversible, or state-changing action: "
        "do not send, submit, post, reply, delete, buy, pay, merge, deploy, "
        "approve, or change any setting.\n"
        "- NEVER type a password or attempt to sign in. If you hit a login/auth "
        "wall, STOP immediately — say the account looks logged out and the owner "
        "needs to re-run workspace setup. Do not try to work around it.\n"
        "- NEVER enter credentials, card numbers, or other secrets into any "
        "field.\n"
        "- If reaching the goal would require any of the above, do NOT do it — "
        'say "that needs confirmation" and stop.\n\n'
        f"{mode}"
    )


# --------------------------------------------------------------- action mapping


def _clamp(value: Any, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(v, hi))


def _coord(pair: Any) -> tuple[Optional[int], Optional[int]]:
    """Clamp a [x, y] pair to the display; ([None, None] if absent/malformed)."""
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return _clamp(pair[0], DISPLAY_WIDTH - 1), _clamp(pair[1], DISPLAY_HEIGHT - 1)
    return None, None


def translate_action(inp: dict) -> Optional[dict]:
    """Map a computer_20250124 tool `input` dict to a provider.act() action.

    Returns None for pure-observation actions (`screenshot`, `cursor_position`)
    that have no side effect — the loop answers those with a fresh screenshot.
    Coordinates are clamped to the 1280x720 display so an out-of-bounds guess
    can't reach shell interpolation as a wild value. Raises ValueError for an
    action the provider can't perform, so the loop returns an is_error result
    and the model adapts rather than the step being silently dropped.
    """
    action = str(inp.get("action") or "").strip()
    x, y = _coord(inp.get("coordinate"))

    if action in ("screenshot", "cursor_position"):
        return None
    if action == "left_click":
        return {"type": "click", "x": x, "y": y}
    if action == "double_click":
        return {"type": "double_click", "x": x, "y": y}
    if action == "right_click":
        return {"type": "right_click", "x": x, "y": y}
    if action == "middle_click":
        return {"type": "middle_click", "x": x, "y": y}
    if action == "triple_click":
        return {"type": "triple_click", "x": x, "y": y}
    if action == "mouse_move":
        return {"type": "mouse_move", "x": x, "y": y}
    if action in ("left_mouse_down", "left_mouse_up"):
        return {"type": action, "x": x, "y": y}
    if action == "left_click_drag":
        sx, sy = _coord(inp.get("start_coordinate"))
        return {"type": "left_click_drag", "start_x": sx, "start_y": sy, "x": x, "y": y}
    if action == "type":
        return {"type": "type", "text": inp.get("text") or ""}
    if action in ("key", "hold_key"):
        # hold_key's duration has no e2b equivalent — best-effort key press.
        return {"type": "key", "key": inp.get("text") or ""}
    if action == "scroll":
        # Bound the tick count (see _MAX_SCROLL_TICKS): a runaway value would run
        # a single long xdotool command outside the loop's wall-clock guard.
        amount = _clamp(inp.get("scroll_amount") or 3, _MAX_SCROLL_TICKS) or 3
        act: dict = {
            "type": "scroll",
            "direction": inp.get("scroll_direction") or "down",
            "amount": amount,
        }
        if x is not None and y is not None:
            act["x"], act["y"] = x, y
        return act
    if action == "wait":
        return {"type": "wait", "seconds": inp.get("duration")}
    raise ValueError(f"unsupported computer action: {action!r}")


# ------------------------------------------------------------- message plumbing


def _screenshot_result(tool_use_id: Any, shot: bytes) -> dict:
    b64 = base64.standard_b64encode(shot).decode("ascii")
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": _MEDIA_TYPE, "data": b64},
            }
        ],
    }


def _text_of(content: Any) -> str:
    """Concatenate the `text` blocks of a response's content, trimmed."""
    parts = []
    for block in content or []:
        if getattr(block, "type", None) == "text":
            parts.append((getattr(block, "text", "") or "").strip())
    return " ".join(p for p in parts if p).strip()


def _get_shared_client():
    """The process-wide AsyncAnthropic client (memoized in agents.utils).

    Lazy import keeps the anthropic SDK off this module's import path until a
    present actually runs, and keeps offline unit tests — which inject their own
    stub — from needing the SDK or a key at all. Returns None when no
    ANTHROPIC_API_KEY is configured.
    """
    from agents.utils import _get_anthropic

    return _get_anthropic()


# ---------------------------------------------------------------------- the loop


async def run_computer_use(
    goal: str,
    ref: SandboxRef,
    cancel: asyncio.Event,
    *,
    max_steps: int = 25,
    timeout_s: int = 300,
    walkthrough: bool = False,
    model: Optional[str] = None,
    provider: Any = None,
    client: Any = None,
) -> AsyncIterator[str]:
    """Drive the sandbox toward `goal`, yielding milestone narration.

    `provider` / `client` default to the shared singletons but are injectable so
    the loop can be unit-tested offline with fakes. Yields short strings only at
    milestones (arrival line, walkthrough sentences, errors); the final yield is
    a one-line summary. Stops on goal-done, `max_steps`, wall-clock `timeout_s`,
    a set `cancel` event (silently — a human preempting the share wins), or an
    unrecoverable error.

    All SandboxProvider calls are synchronous, so they run under
    asyncio.to_thread; `cancel.is_set()` is checked every step so "stop sharing"
    (which the manager routes into this event) halts the loop promptly.
    """
    provider = provider or get_provider()
    client = client or _get_shared_client()
    if client is None:
        yield "I couldn't reach the presentation model — that needs an API key set up."
        return

    if cancel.is_set():
        return

    model_id = _cu_model(model)
    tools = [_tool_def()]
    betas = [_BETA]
    system = _system_prompt(walkthrough)
    deadline = time.monotonic() + max(1, timeout_s)

    # Initial observation — the model needs the current screen with the goal.
    try:
        shot = await asyncio.to_thread(provider.screenshot, ref)
    except Exception as exc:  # noqa: BLE001
        yield f"I couldn't open the screen to present — {exc}."
        return

    messages: list[dict] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Goal: {goal}\n\n"
                        "Here is the current screen. Take it from here."
                    ),
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _MEDIA_TYPE,
                        "data": base64.standard_b64encode(shot).decode("ascii"),
                    },
                },
            ],
        }
    ]

    for _step in range(max(1, max_steps)):
        if cancel.is_set():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield "This is taking longer than I can hold the screen for — stopping here."
            return

        try:
            response = await asyncio.wait_for(
                client.beta.messages.create(
                    model=model_id,
                    max_tokens=_MAX_TOKENS,
                    system=system,
                    tools=tools,
                    betas=betas,
                    messages=messages,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            yield "This is taking longer than I can hold the screen for — stopping here."
            return
        except Exception as exc:  # noqa: BLE001
            yield f"I ran into a problem while presenting — {exc}."
            return

        # A cancel that arrived during the model call: stop before driving.
        if cancel.is_set():
            return

        content = getattr(response, "content", None) or []
        stop_reason = getattr(response, "stop_reason", None)
        tool_uses = [b for b in content if getattr(b, "type", None) == "tool_use"]

        if not tool_uses:
            # Terminal turn: the model's text is the arrival line / summary.
            summary = _text_of(content)
            if stop_reason == "refusal" and not summary:
                summary = "I can't do that part — it needs confirmation."
            yield summary or f"Done — {goal}."
            return

        # Walkthrough narration is yielded only on turns still driving; the
        # terminal turn's text is the final summary (above), so no duplication.
        if walkthrough:
            narration = _text_of(content)
            if narration:
                yield narration

        # Record the assistant turn verbatim, then execute each requested action
        # and feed a fresh screenshot back per tool_use.
        messages.append({"role": "assistant", "content": content})
        tool_results = []
        for block in tool_uses:
            tool_use_id = getattr(block, "id", None)
            inp = getattr(block, "input", None) or {}
            try:
                action = translate_action(inp)
                if action is not None:
                    await asyncio.to_thread(provider.act, ref, action)
                shot = await asyncio.to_thread(provider.screenshot, ref)
                tool_results.append(_screenshot_result(tool_use_id, shot))
            except Exception as exc:  # noqa: BLE001
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"That action couldn't be performed: {exc}",
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    yield "I've used up my step budget for this — stopping here."

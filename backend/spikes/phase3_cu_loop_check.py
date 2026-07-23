"""Phase 3C offline check — the acceptance gate for the computer-use loop.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("computer_use.py
— the agent loop"; "Loop bounds" under Verification).

This runs with NO ANTHROPIC_API_KEY and NO real sandbox — it drives
sandbox.computer_use.run_computer_use with a FAKE SandboxProvider (records
act() calls, returns a tiny PNG for screenshot) and a STUBBED Anthropic client
(returns a scripted sequence of beta-messages responses). It asserts:

  1. computer_20250124 actions map onto provider.act() correctly, and screen
     coordinates are clamped to the 1280x720 display (bounds).
  2. The request carries the computer-use beta + the computer tool at 1280x720.
  3. A set `cancel` event stops the loop within one step (no further model call).
  4. `max_steps` bounds the loop.
  5. The loop yields milestone narration (arrival line, walkthrough sentences,
     step-budget notice).

The live run against a real sandbox + Anthropic key is DEFERRED (no key here).

    cd backend && python spikes/phase3_cu_loop_check.py
"""

import asyncio
import base64
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))  # flat imports (sandbox, ...)

from sandbox import SandboxRef  # noqa: E402
from sandbox.computer_use import run_computer_use, translate_action  # noqa: E402

REF = SandboxRef(
    sandbox_id="sbx_test", auth_key="key", stream_base="https://example/vnc.html"
)

# A real 1x1 PNG — the loop base64-encodes whatever screenshot() returns.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# ------------------------------------------------------------------- fakes


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(inp, tid="toolu_1", name="computer"):
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=inp)


def _msg(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeMessages:
    """Stubbed client.beta.messages — records kwargs, returns scripted msgs."""

    def __init__(self, script, default=None):
        self._script = list(script)
        self._default = default
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._script:
            item = self._script.pop(0)
        elif self._default is not None:
            item = self._default
        else:
            item = _msg([_text("done")], "end_turn")
        return item() if callable(item) else item


class _FakeClient:
    def __init__(self, script, default=None):
        self.beta = SimpleNamespace(messages=_FakeMessages(script, default))

    @property
    def calls(self):
        return self.beta.messages.calls


class _FakeProvider:
    """Records act() calls; returns a tiny PNG for screenshot(); optionally
    trips a cancel event the first time act() runs."""

    def __init__(self, cancel_on_act=None):
        self.acts = []
        self.screens = 0
        self._cancel = cancel_on_act

    def screenshot(self, ref):
        self.screens += 1
        return _TINY_PNG

    def act(self, ref, action):
        self.acts.append(action)
        if self._cancel is not None:
            self._cancel.set()


async def _collect(agen):
    out = []
    async for s in agen:
        out.append(s)
    return out


# ------------------------------------------------------------------- tests


def test_translate_table():
    """The action-mapping table + coordinate clamping + unsupported-action error."""
    assert translate_action({"action": "screenshot"}) is None
    assert translate_action({"action": "cursor_position"}) is None
    assert translate_action({"action": "double_click", "coordinate": [3, 4]}) == {
        "type": "double_click", "x": 3, "y": 4,
    }
    assert translate_action({"action": "type", "text": "hi"}) == {
        "type": "type", "text": "hi",
    }
    assert translate_action({"action": "key", "text": "ctrl+l"}) == {
        "type": "key", "key": "ctrl+l",
    }
    assert translate_action(
        {"action": "left_click_drag", "start_coordinate": [1, 2], "coordinate": [9, 9]}
    ) == {"type": "left_click_drag", "start_x": 1, "start_y": 2, "x": 9, "y": 9}
    assert translate_action({"action": "mouse_move", "coordinate": [7, 8]}) == {
        "type": "mouse_move", "x": 7, "y": 8,
    }
    assert translate_action({"action": "wait", "duration": 2}) == {
        "type": "wait", "seconds": 2,
    }
    # Bounds: negative clamps to 0, over-max clamps to display-1.
    assert translate_action({"action": "left_click", "coordinate": [-5, -5]}) == {
        "type": "click", "x": 0, "y": 0,
    }
    assert translate_action({"action": "left_click", "coordinate": [5000, 9000]}) == {
        "type": "click", "x": 1279, "y": 719,
    }
    # Bounds: a runaway scroll magnitude is clamped (single long xdotool command
    # runs outside the loop's per-turn wall-clock guard).
    assert translate_action(
        {"action": "scroll", "scroll_direction": "down", "scroll_amount": 999999}
    )["amount"] == 30
    assert translate_action(
        {"action": "scroll", "scroll_direction": "down", "scroll_amount": -4}
    )["amount"] == 3  # negative -> clamp 0 -> falls back to default 3
    try:
        translate_action({"action": "definitely_not_a_real_action"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unsupported action")


async def test_maps_click_and_yields_summary():
    """One click action → provider.act (mapped + clamped); end_turn → summary."""
    client = _FakeClient([
        _msg([_tool({"action": "left_click", "coordinate": [5000, 9000]})], "tool_use"),
        _msg([_text("Here's the auth PR.")], "end_turn"),
    ])
    provider = _FakeProvider()
    cancel = asyncio.Event()

    yields = await _collect(
        run_computer_use("open the auth PR", REF, cancel, provider=provider, client=client)
    )

    assert provider.acts == [{"type": "click", "x": 1279, "y": 719}], provider.acts
    assert len(client.calls) == 2, len(client.calls)
    assert yields == ["Here's the auth PR."], yields

    first = client.calls[0]
    assert first["betas"] == ["computer-use-2025-01-24"], first.get("betas")
    tool0 = first["tools"][0]
    assert tool0["type"] == "computer_20250124", tool0
    assert tool0["name"] == "computer", tool0
    assert tool0["display_width_px"] == 1280 and tool0["display_height_px"] == 720, tool0
    # The follow-up request must include the executed turn + its tool_result.
    assert len(client.calls[1]["messages"]) == 3, client.calls[1]["messages"]


async def test_cancel_stops_within_one_step():
    """A cancel tripped mid-step halts before the next model call (silently)."""
    cancel = asyncio.Event()
    client = _FakeClient([
        _msg([_tool({"action": "left_click", "coordinate": [10, 20]})], "tool_use"),
        _msg([_text("should never be reached")], "end_turn"),
    ])
    provider = _FakeProvider(cancel_on_act=cancel)  # first act trips cancel

    yields = await _collect(
        run_computer_use("goal", REF, cancel, provider=provider, client=client)
    )

    assert len(client.calls) == 1, len(client.calls)  # stopped before 2nd call
    assert len(provider.acts) == 1, len(provider.acts)
    assert yields == [], yields  # cancel = silent stop (human preempts the share)


async def test_cancel_before_start():
    """A cancel already set at entry does nothing at all."""
    cancel = asyncio.Event()
    cancel.set()
    client = _FakeClient([_msg([_text("nope")], "end_turn")])
    provider = _FakeProvider()

    yields = await _collect(
        run_computer_use("goal", REF, cancel, provider=provider, client=client)
    )
    assert client.calls == [], client.calls
    assert provider.acts == [], provider.acts
    assert yields == [], yields


async def test_respects_max_steps():
    """A model that always drives is cut off at max_steps with a step-budget note."""
    client = _FakeClient(
        [],
        default=lambda: _msg(
            [_tool({"action": "left_click", "coordinate": [1, 2]})], "tool_use"
        ),
    )
    provider = _FakeProvider()
    cancel = asyncio.Event()

    yields = await _collect(
        run_computer_use("goal", REF, cancel, max_steps=3, provider=provider, client=client)
    )

    assert len(client.calls) == 3, len(client.calls)
    assert len(provider.acts) == 3, len(provider.acts)
    assert yields and "step budget" in yields[-1].lower(), yields


async def test_walkthrough_narrates_then_summarizes():
    """Walkthrough mode yields mid-loop narration, then a final summary."""
    client = _FakeClient([
        _msg(
            [
                _text("This is the CI dashboard."),
                _tool({
                    "action": "scroll",
                    "coordinate": [100, 100],
                    "scroll_direction": "down",
                    "scroll_amount": 3,
                }),
            ],
            "tool_use",
        ),
        _msg([_text("All checks are green.")], "end_turn"),
    ])
    provider = _FakeProvider()
    cancel = asyncio.Event()

    yields = await _collect(
        run_computer_use(
            "walk us through CI", REF, cancel, walkthrough=True,
            provider=provider, client=client,
        )
    )

    assert yields == ["This is the CI dashboard.", "All checks are green."], yields
    assert provider.acts == [
        {"type": "scroll", "direction": "down", "amount": 3, "x": 100, "y": 100}
    ], provider.acts


async def test_no_client_yields_error():
    """With no client and no API key, the loop yields one error milestone."""
    cancel = asyncio.Event()
    # client=None forces the shared-client path; no ANTHROPIC_API_KEY here → None.
    yields = await _collect(
        run_computer_use("goal", REF, cancel, provider=_FakeProvider(), client=None)
    )
    assert len(yields) == 1 and "API key" in yields[0], yields


def main():
    sync_tests = [test_translate_table]
    async_tests = [
        test_maps_click_and_yields_summary,
        test_cancel_stops_within_one_step,
        test_cancel_before_start,
        test_respects_max_steps,
        test_walkthrough_narrates_then_summarizes,
        test_no_client_yields_error,
    ]
    failures = []
    for t in sync_tests:
        try:
            t()
            print(f"[ok] {t.__name__}")
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"[FAIL] {t.__name__}: {e!r}")
    for t in async_tests:
        try:
            asyncio.run(t())
            print(f"[ok] {t.__name__}")
        except AssertionError as e:
            failures.append(t.__name__)
            print(f"[FAIL] {t.__name__}: {e!r}")

    if failures:
        print(f"\nFAIL — {len(failures)} test(s) failed: {', '.join(failures)}")
        return 1
    print(
        "\nPASS — computer-use loop checks green "
        "(fake provider + stubbed Anthropic; live run deferred, needs a key)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Presentation manager — Phase 3 of Bot Screen Presentation.

Spec: docs/specs/2026-07-07-bot-screen-presentation-design.md ("Architecture",
"Solo mode", "Failure contract") + ADR docs/adr/0002.

`start_presentation` is the background orchestrator the live-bot command path
spawns (never inline) when the model picks the `presents=True` `computer_use`
tool: it resumes the bot owner's persistent sandbox, points Recall's screenshare
at our tokenized wrapper page, runs the open-ended computer-use loop, and streams
its milestone narration to voice (+ the final summary to chat). One present per
bot; a `stop sharing` kill phrase (or bot teardown) trips the loop's cancel event.

Narration policy (grill Jul 2026):
  - VOICE = milestones only: arrival line, walkthrough sentences, errors, the
    one-line summary — never per-step. (The ask-time ack, armed in
    _process_command, covers the spin-up gap; the manager does not re-ack.)
  - CHAT  = start line + final summary. The step trail is a dashboard concern,
    out of scope here.

Circular-import discipline (repo convention): realtime_routes + recall_routes are
imported at FUNCTION level — realtime_routes imports THIS module, and recall_routes
is imported by realtime_routes, so a module-level import either way would cycle.
Everything imported at module level here (sandbox, present_tokens, present_gate,
sandbox.computer_use) is cycle-free.

SECURITY: the SandboxRef built from the owner's settings carries `auth_key` (the
noVNC password). It is never logged, and the wrapper URL (which embeds a
per-present token, not the key) is never logged either.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from sandbox import SandboxRef, get_provider
from sandbox.computer_use import run_computer_use
from present_tokens import mint_present_token, revoke_for_bot
from tools.present_gate import is_walkthrough_request
from personas import DEFAULT_BOT_NAME

# bot_id -> {"cancel": asyncio.Event, "goal": str}. Presence == "a present is
# active for this bot" (the solo-suspend signal is_presenting reads). Registered
# BEFORE the first await in start_presentation so a concurrent second call sees
# it (single-threaded asyncio makes the check-then-set atomic).
_active: dict[str, dict] = {}


def is_presenting(bot_id: str) -> bool:
    """True while a present is active for this bot (drives solo-free-flow suspension)."""
    return bool(bot_id) and bot_id in _active


def active_present_info(bot_id: str) -> Optional[dict]:
    """Read-only view of the active present for a bot: {"goal", "token"} or None.

    The /live screenshare mirror uses this to expose a members-only watch URL
    (built from `token` via recall_routes.present_wrapper_url) without touching
    the manager's run behavior. `token` is the per-present view-only token minted
    in start_presentation; it may be "" for the brief window before the share
    starts. Returns None when nothing is presenting."""
    entry = _active.get(bot_id)
    if not entry:
        return None
    return {"goal": entry.get("goal", "") or "", "token": entry.get("token", "") or ""}


def request_stop(bot_id: str) -> bool:
    """Trip the active present's cancel event (SYNC — safe from teardown paths that
    have no event loop to await on). Returns True if a present was active. The
    running loop sees the set event and its finally stops the screenshare + revokes
    the token; this call does not itself tear down the share."""
    entry = _active.get(bot_id)
    if entry is not None:
        entry["cancel"].set()
        return True
    return False


async def stop_presentation(bot_id: str) -> None:
    """Kill-phrase entry point: signal the active present to stop. The background
    loop unwinds and its finally does the actual screenshare teardown."""
    request_stop(bot_id)


def _ref_from_settings(settings: Optional[dict]) -> Optional[SandboxRef]:
    """Rebuild the owner's SandboxRef from their user_settings, per provider.

    E2B (desktop): all three columns — id + noVNC password + stream URL.
    Browserbase (browser, ADR 0003): only sandbox_id, the persistent Context id;
    auth_key/stream_base are unused. Guard the E2B-only field reads so a
    Browserbase ref (which has neither) still BUILDS instead of None-ing out and
    wrongly reporting "no screen set up" to a user who did set one up.

    ponytail: this only makes the present PATH TOLERATE a Browserbase ref. The
    full present-over-Browserbase surface — the wrapper's WebRTC embed
    (present_routes), a Session minted per-present, and run_computer_use driving
    over CDP — is the NEXT task, gated on ANTHROPIC_API_KEY + a live meeting
    (ADR 0003). Not built or verified here; the E2B present path is unchanged.
    """
    s = settings or {}
    sid = s.get("sandbox_id")
    if not sid:
        return None
    key = s.get("sandbox_auth_key")
    base = s.get("sandbox_stream_url")
    if key and base:
        return SandboxRef(sandbox_id=sid, auth_key=key, stream_base=base)
    return SandboxRef(sandbox_id=sid, context_id=sid)


def _owner_name(bot_id: str) -> str:
    try:
        import recall_routes
        name = (recall_routes.bot_store.get(bot_id) or {}).get("owner_name")
        if name:
            return str(name).split()[0]  # first name reads better in a chat line
    except Exception:
        pass
    return "the meeting owner"


def _bot_name(bot_id: str) -> str:
    try:
        import realtime_routes
        return realtime_routes._BOT_WAKE_ALIAS.get(bot_id, "") or DEFAULT_BOT_NAME
    except Exception:
        return DEFAULT_BOT_NAME


async def start_presentation(
    bot_id: str,
    state: dict,
    goal: str,
    requester_is_owner: bool,
    workspace_scope: bool,
    settings: dict,
) -> None:
    """Drive one on-screen presentation for `goal`. Never raises; every terminal
    path stops the screenshare so a dead present can't linger as the room's screen.

    `requester_is_owner` / `workspace_scope` implement the ADR-0002 ask-gate;
    `settings` is the bot OWNER's user_settings (the sandbox is always the owner's).
    """
    import realtime_routes as rt
    import recall_routes as rc

    goal = (goal or "").strip()

    # ── Per-bot serialization ─────────────────────────────────────────────────
    # One present at a time. A second presents-call (or a verb-gate-matching ask
    # mid-present) gets one chat-only line pointing at the kill phrase.
    if is_presenting(bot_id):
        await rt._send_chat_response(
            bot_id,
            'I\'m already presenting — say "stop sharing" first if you\'d like me '
            "to show something else.",
        )
        return

    # ── Ask-gate (ADR 0002) ───────────────────────────────────────────────────
    # Any workspace member may trigger in a workspace-scope meeting; owner-only in
    # personal scope. (Anyone may STOP — that's the kill phrase, handled upstream.)
    if not (requester_is_owner or workspace_scope):
        await rt._send_chat_response(
            bot_id, f"Only {_owner_name(bot_id)} can ask me to put something on screen."
        )
        return

    # ── Sandbox availability ──────────────────────────────────────────────────
    ref = _ref_from_settings(settings)
    if ref is None:
        await rt._send_chat_response(
            bot_id,
            f"I don't have a screen set up yet — {_owner_name(bot_id)} can enable it "
            'from the Prism dashboard ("Set up my AI workspace").',
        )
        return

    # Commit the active entry (+ cancel event) before any further await.
    cancel = asyncio.Event()
    _active[bot_id] = {"cancel": cancel, "goal": goal}

    bot_name = _bot_name(bot_id)
    final_line = ""
    try:
        # Spoken latency-cover, said ONLY now that a present is confirmed (owner/
        # member gate + provisioned sandbox both passed). This replaces the old
        # speculative `present` ack, which fired on phrase-match alone and so
        # promised a screen even when computer_use wasn't available — the bot
        # would say "Let me pull that up on screen—" then "I can't share screens".
        # Cancels any pending generic ack internally. Covers the resume wait below.
        try:
            await rt._send_voice_response(bot_id, "Let me pull that up on screen—")
        except Exception as exc:  # noqa: BLE001
            print(f"[present] opening voice failed bot={bot_id[:8]}: {exc}")

        # Resume the sandbox (sync SDK → to_thread). A gone/expired sandbox gets
        # the actionable failure-contract nudge.
        try:
            provider = get_provider()
            await asyncio.to_thread(provider.resume, ref)
        except Exception as exc:  # noqa: BLE001
            print(f"[present] resume failed bot={bot_id[:8]}: {type(exc).__name__}")
            await rt._send_chat_response(
                bot_id,
                f"I couldn't wake the presentation screen — {_owner_name(bot_id)} may "
                'need to re-run "Set up my AI workspace".',
            )
            return

        # Mint a per-present token → wrapper URL → Recall screenshare. The wrapper
        # URL embeds the token (a live capability) — never logged.
        token = mint_present_token(ref, view_only=True, bot_id=bot_id)
        # Record the token on the active entry so active_present_info (the /live
        # screenshare mirror getter) can hand members a view-only watch URL.
        # Data-only: does not change the present's run behavior.
        entry = _active.get(bot_id)
        if entry is not None:
            entry["token"] = token
        wrapper_url = rc.present_wrapper_url(token)
        share = await rc.start_screenshare(bot_id, wrapper_url)
        if share.get("success"):
            await rt._send_chat_response(bot_id, f"Starting the screen — pulling up: {goal}")
        else:
            # Failure contract: the platform's "who can share" setting can block
            # the bot. Post the tokenized watch-along link (dies with the present)
            # and drive anyway so link-holders still see it.
            print(f"[present] screenshare not started bot={bot_id[:8]} status={share.get('status')}")
            await rt._send_chat_response(
                bot_id,
                f"I can't share my screen in this meeting — watch along here: {wrapper_url}",
            )

        # ── The loop ──────────────────────────────────────────────────────────
        walkthrough = is_walkthrough_request(goal)
        async for line in run_computer_use(goal, ref, cancel, walkthrough=walkthrough):
            line = (line or "").strip()
            if not line:
                continue
            final_line = line
            try:
                await rt._send_voice_response(bot_id, rt._spoken_version(line))
            except Exception as exc:  # noqa: BLE001
                print(f"[present] milestone voice failed bot={bot_id[:8]}: {exc}")

        # CHAT: final summary. Skipped on cancel — the kill-phrase handler already
        # said "stopping the screen", so we don't tack a summary onto a preemption.
        if final_line and not cancel.is_set():
            await rt._send_chat_response(bot_id, final_line)
            try:
                import perception_state
                async with perception_state.get_memory_lock(state):
                    rt._record_bot_line(bot_id, state, final_line, bot_name)
            except Exception as exc:  # noqa: BLE001
                print(f"[present] record final line failed bot={bot_id[:8]}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"[present] presentation error bot={bot_id[:8]}: {type(exc).__name__}: {exc}")
        try:
            await rt._send_chat_response(
                bot_id,
                "I ran into a problem while presenting, so I've taken the screen down.",
            )
        except Exception:
            pass
    finally:
        # A dead present must NEVER linger — stop the share and kill the token
        # unconditionally, then drop the active entry (frees the serialization
        # slot + clears the solo-suspend signal).
        try:
            await rc.stop_screenshare(bot_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[present] stop_screenshare failed bot={bot_id[:8]}: {exc}")
        try:
            revoke_for_bot(bot_id)
        except Exception:
            pass
        _active.pop(bot_id, None)

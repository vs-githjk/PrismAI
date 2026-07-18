"""Phase 3 — the agent channel: ALL tools, plain Python, OUTSIDE Pipecat.

This is `_process_command`'s tool loop re-homed (KRC item 12), stripped of everything
that belonged to the mouth or the old transport: no streaming-to-TTS, no perception_state
barge-in sessions, no chat/voice delivery. It runs the gpt-4o-mini tool-calling loop and
RETURNS the result; the voice channel narrates it (item ②: voice reads results, never
calls tools). The safety-critical pieces come with it verbatim (re-homed, not rewritten):

  · owner-gate on confirm-tools (item 16) — side-effect tools only obey the owner
  · capability-block memory (item 15) — dead integrations don't get re-attempted; a
    `blocked_cap` is returned so the voice channel can say "Gmail isn't connected"
  · malformed-tool-call recovery + taint-strip (item 14)
  · think_loop verb-gate / artifact handoff (destructive-misfire guard)

Status events (dispatched → running → done/blocked/error) go on the bus. Returns:
  {"reply": str|None, "tools_used": [str], "blocked_cap": str|None, "error": bool}
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.registry import get_available_tools, get_tool, execute_tool, confirm_and_execute

from voice import bus


def _rr():
    """Lazy import — realtime_routes owns the shared live-bot helpers + state."""
    import realtime_routes as rr
    return rr


async def run(bot_id: str, command: str, speaker: str = "") -> dict:
    rr = _rr()
    import meeting_memory
    import perception_state
    import think_loop
    from voice import prompts

    state = rr._get_bot_state(bot_id)
    result = {"reply": None, "tools_used": [], "blocked_cap": None, "error": False}
    bus.emit_status(bot_id, "dispatched", command=command[:60], speaker=speaker)

    # Capability-block short-circuit — this command targets an integration whose auth
    # already failed this session. Don't burn a tool-loop round trip; tell the voice
    # channel which capability is dead so it narrates naturally.
    blocked_cap = rr._blocked_capability_for_command(command, state)
    if blocked_cap:
        bus.emit_status(bot_id, "blocked", cap=blocked_cap)
        result["blocked_cap"] = blocked_cap
        return result

    try:
        user_settings = await rr._get_settings_for_bot(bot_id)
        persona_text = user_settings.get("persona_text", "")
        bot_name = user_settings.get("bot_name", rr.DEFAULT_BOT_NAME)
        tools = get_available_tools(user_settings)

        blocked_caps = state.get("blocked_capabilities") or {}
        if blocked_caps:
            tools = [t for t in tools if rr._capability_of(t["function"]["name"]) not in blocked_caps]
        valid_tool_names = {t["function"]["name"] for t in tools}

        if not rr.OPENAI_API_KEY:
            result["reply"] = "Sorry, I can't run that right now."
            return result

        openai_client = rr.get_openai()
        memory_context = meeting_memory.build_memory_context(state, command)

        now = datetime.now(ZoneInfo("America/New_York"))
        hour_12 = now.hour % 12 or 12
        now_str = (
            f"{now.strftime('%A, %B')} {now.day}, {now.year} at "
            f"{hour_12}:{now.strftime('%M %p')} {now.strftime('%Z')} "
            f"(IANA timezone: America/New_York)"
        )
        has_gmail = any(t["function"]["name"].startswith("gmail") for t in tools)
        has_calendar = any(t["function"]["name"].startswith("calendar") for t in tools)

        owner_full = (rr.bot_store.get(bot_id) or {}).get("owner_name", "")
        is_owner = perception_state.is_owner_speaker(speaker, owner_full)
        owner_email = rr._owner_email_for_bot(bot_id)

        messages = prompts.build_agent_messages(
            has_gmail=has_gmail,
            has_calendar=has_calendar,
            now_str=now_str,
            memory_context=memory_context,
            speaker=speaker,
            command=command,
            is_owner=is_owner,
            persona_text=persona_text,
            bot_name=bot_name,
            owner_name=owner_full,
            owner_email=owner_email,
            recent_turns=state.get("recent_turns", []),
            image_urls=rr._fresh_image_urls(state),
        )
        # Artifact handoff: a prior draft + a "send it" follow-up → inject the draft so
        # the model reuses the body in its tool call (cache-safe: after the system msgs).
        if think_loop.think_loop_on():
            _prior = think_loop.get_fresh_artifact(state)
            if _prior and any(p in (command or "").lower() for p in think_loop.FOLLOWUP_ACT_PHRASES):
                messages.insert(-1, {"role": "system", "content": think_loop.artifact_system_hint(_prior)})

        tools_used = result["tools_used"]
        newly_blocked: list[str] = []
        call_kwargs = {"model": "gpt-4o-mini", "temperature": 0.3, "messages": messages}
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        actual_user_id = (rr.bot_store.get(bot_id) or {}).get("user_id")
        user_id = actual_user_id or bot_id
        tool_settings = dict(user_settings)
        tool_settings["bot_id"] = bot_id

        async def _run_tool_calls(tc_specs):
            for tc_id, tc_name, tc_args in tc_specs:
                # Owner-gate: confirm=True tools have side effects on the owner's accounts;
                # only the owner may fire them. Always on now (utterances are always wrapped).
                _tool_def = get_tool(tc_name) or {}
                if _tool_def.get("confirm") and not is_owner:
                    bus.emit_status(bot_id, "owner_gate_block", tool=tc_name, speaker=speaker)
                    tools_used.append(tc_name)
                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": json.dumps({
                        "error": ("Refused: this tool can only be invoked by the owner of this "
                                  "Prism instance. The current speaker is not the owner. If a "
                                  "non-owner needs it, draft it in chat and let the owner send."),
                    })})
                    continue
                # Verb-gate: block destructive calls when the command lacked an authorizing
                # verb (catches "draft email" → gmail_send), unless a prior draft exists.
                if think_loop.think_loop_on():
                    _reason = think_loop.verb_gate(
                        command=command, tool_name=tc_name,
                        has_prior_artifact=think_loop.get_fresh_artifact(state) is not None,
                    )
                    if _reason:
                        tools_used.append(tc_name)
                        messages.append({"role": "tool", "tool_call_id": tc_id,
                                         "content": json.dumps({"error": _reason})})
                        continue

                res = await execute_tool(tc_name, tc_args, user_id=user_id, user_settings=tool_settings)
                if res.get("requires_confirmation"):
                    res = await confirm_and_execute(tc_name, res["preview"], user_settings=user_settings)
                if res.get("external_ref") and rr.supabase and actual_user_id:
                    try:
                        rr.supabase.table("action_refs").insert({
                            "user_id": actual_user_id, "action_item": command,
                            "tool": res["external_ref"]["tool"],
                            "external_id": res["external_ref"]["external_id"],
                        }).execute()
                    except Exception as exc:
                        print(f"[agent] action_ref persist failed (action already ran): {exc!r}")
                tools_used.append(tc_name)
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": json.dumps(res)})

                if rr._is_auth_failure(res):
                    _cap = rr._capability_of(tc_name)
                    if _cap in rr._CAP_TERSE and _cap not in state.get("blocked_capabilities", {}):
                        state.setdefault("blocked_capabilities", {})[_cap] = time.time()
                        newly_blocked.append(_cap)
                        bus.emit_status(bot_id, "capability_blocked", cap=_cap, tool=tc_name)

        bus.emit_status(bot_id, "running")
        reply = None
        for iteration in range(3):
            response = None
            synth_calls = None
            try:
                response = await openai_client.chat.completions.create(**call_kwargs)
            except Exception as llm_exc:
                err_str = str(llm_exc)
                if ("400" in err_str or "tool_use_failed" in err_str) and "tools" in call_kwargs:
                    recovered = rr._recover_tool_calls(rr._extract_failed_generation(llm_exc), valid_tool_names)
                    if recovered:
                        synth_calls = recovered
                if synth_calls is None:
                    if "tools" in call_kwargs:
                        call_kwargs.pop("tools", None)
                        call_kwargs.pop("tool_choice", None)
                        try:
                            response = await openai_client.chat.completions.create(**call_kwargs)
                        except Exception:
                            reply = "Sorry, I had trouble processing that."
                            break
                    else:
                        reply = "Sorry, I had trouble processing that."
                        break

            if synth_calls is None and response is not None and "tools" in call_kwargs:
                msg = response.choices[0].message
                if not msg.tool_calls and msg.content and "<function=" in msg.content:
                    synth_calls = rr._recover_tool_calls(msg.content, valid_tool_names)

            if synth_calls:
                tc_payload = []
                ts_ms = int(time.time() * 1000)
                for idx, call in enumerate(synth_calls):
                    tc_payload.append({"id": f"call_synth_{iteration}_{idx}_{ts_ms}", "type": "function",
                                       "function": {"name": call["name"], "arguments": call["arguments"]}})
                messages.append({"role": "assistant", "content": None, "tool_calls": tc_payload})
                await _run_tool_calls([(tc["id"], tc["function"]["name"], tc["function"]["arguments"])
                                       for tc in tc_payload])
                rr._strip_tools_if_tainted(call_kwargs, [tc["function"]["name"] for tc in tc_payload])
                call_kwargs["messages"] = messages
                continue

            choice = response.choices[0]
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                reply = choice.message.content or f"Got it — {command}."
                break
            messages.append(choice.message)
            executed_names = [tc.function.name for tc in choice.message.tool_calls]
            await _run_tool_calls([(tc.id, tc.function.name, tc.function.arguments)
                                   for tc in choice.message.tool_calls])
            rr._strip_tools_if_tainted(call_kwargs, executed_names)
            call_kwargs["messages"] = messages
        else:
            try:
                summary_resp = await openai_client.chat.completions.create(
                    model="gpt-4o-mini", temperature=0.3,
                    messages=messages + [{"role": "user", "content": "Summarise in one sentence what you just did."}],
                )
                reply = summary_resp.choices[0].message.content or "Done."
            except Exception:
                reply = "Done."

        # Strip hidden <thinking>; stash a draft artifact / clear on a completed ACT.
        if think_loop.think_loop_on() and reply:
            visible, _hidden = think_loop.strip_thinking(reply)
            if visible:
                reply = visible
            if think_loop.looks_like_compose_command(command) and think_loop.looks_like_artifact(reply):
                think_loop.set_artifact(state, reply, command)
            elif tools_used:
                think_loop.clear_artifact(state)

        result["reply"] = reply
        # A tool auth-failed this turn with no salvage reply → surface the block so the
        # voice channel narrates it instead of reading a vague error.
        if newly_blocked and not reply:
            result["blocked_cap"] = newly_blocked[0]
        bus.emit_status(bot_id, "done", tools=tools_used, reply=(reply or "")[:60])
        return result

    except Exception as exc:
        # Transient overload → Haiku fallback (same as the fused path).
        err_str = str(exc)
        status_code = getattr(exc, "status_code", None)
        if status_code in {429, 500, 502, 503, 504} or any(
            kw in err_str for kw in ("rate_limit", "overloaded", "capacity")
        ):
            try:
                from agents.utils import _get_anthropic
                anthropic_client = _get_anthropic()
                if anthropic_client:
                    haiku = await anthropic_client.messages.create(
                        model="claude-haiku-4-5-20251001", max_tokens=256,
                        messages=[{"role": "user", "content": f"{speaker}: {command}" if speaker else command}],
                    )
                    result["reply"] = haiku.content[0].text
                    bus.emit_status(bot_id, "done", via="haiku_fallback")
                    return result
            except Exception as haiku_exc:
                print(f"[agent] haiku fallback failed: {haiku_exc}")
        bus.emit_status(bot_id, "error", exc=err_str[:120])
        result["error"] = True
        result["reply"] = f"Sorry, I ran into an error: {err_str[:100]}"
        return result

"""Unit tests for the presentation manager (Phase 3 — Bot Screen Presentation).

Offline: NO Anthropic key, NO sandbox, NO Recall, NO network. The real
realtime_routes + recall_routes modules are imported (so we exercise the actual
function-level import wiring), but their I/O helpers — chat/voice/record and the
Recall screenshare start/stop — are monkeypatched to in-memory recorders, and the
sandbox provider + computer-use loop + present-token minting are faked.

The modules are resolved from ``sys.modules`` at setUp time (not the top-level
import names), because start_presentation resolves realtime_routes/recall_routes
via ``import X`` (i.e. sys.modules) — patching the exact objects it will resolve
makes the test immune to cross-test module-identity drift in the full suite.

Asserts the manager's contract:
  - ADR-0002 ask-gate (owner-only in personal scope; any member in workspace scope).
  - Missing-sandbox nudge.
  - Happy path: resume → mint token → start_screenshare(wrapper_url) → "starting"
    chat → milestone voice → final summary to chat + _record_bot_line → finally
    ALWAYS stops the screenshare + revokes the token + clears the active slot.
  - Walkthrough goal → walkthrough=True into the loop; mid-lines voiced, last to chat.
  - Per-bot serialization ("already presenting").
  - Screenshare-denied → watch-along link fallback, loop still drives, share stopped.
  - Resume failure → actionable nudge, no share, slot cleared.
  - stop_presentation trips the cancel event → loop unwinds → share torn down.
"""

import asyncio
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure the modules exist in sys.modules; we resolve the live objects in setUp.
import presentation  # noqa: E402,F401
import realtime_routes  # noqa: E402,F401
import recall_routes  # noqa: E402,F401

BOT = "bot_test_123"
REF_SETTINGS = {
    "sandbox_id": "sbx_1",
    "sandbox_auth_key": "key_1",
    "sandbox_stream_url": "https://6080-sbx_1.e2b.app/vnc.html",
}


class _FakeProvider:
    def __init__(self, resume_raises=False):
        self.resumed = []
        self._raise = resume_raises

    def resume(self, ref):
        if self._raise:
            raise RuntimeError("sandbox gone")
        self.resumed.append(ref)


class PresentationManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Resolve the EXACT module objects start_presentation will use (via its
        # function-level `import realtime_routes` / `import recall_routes`) — these
        # are the sys.modules entries, which may differ from stale top-level names.
        self.pres = sys.modules["presentation"]
        self.rt = sys.modules["realtime_routes"]
        self.rc = sys.modules["recall_routes"]

        self.pres._active.clear()
        self.chats = []
        self.voices = []
        self.recorded = []
        self.stopped = []
        self.revoked = []
        self.cu_calls = []
        self.provider = _FakeProvider()
        self._share_result = {"success": True, "status": 200}
        self._cu_script = ["Here's the auth PR."]
        self._cu_wait_cancel = False  # loop runs until cancel when True

        async def _chat(bot_id, msg):
            self.chats.append(msg)

        async def _voice(bot_id, text):
            self.voices.append(text)

        def _record(bot_id, state, text, bot_name):
            self.recorded.append((text, bot_name))

        def _wrapper(token):
            return f"https://webhook.example/present/{token}"

        async def _start_share(bot_id, url):
            self.share_url = url
            return dict(self._share_result)

        async def _stop_share(bot_id):
            self.stopped.append(bot_id)
            return {"success": True, "status": 200}

        def _mint(ref, view_only=True, ttl_s=3600, bot_id=None):
            self.minted = {"ref": ref, "view_only": view_only, "bot_id": bot_id}
            return "tok_abc"

        def _revoke(bot_id):
            self.revoked.append(bot_id)
            return 1

        def _get_provider():
            return self.provider

        outer = self

        async def _fake_cu(goal, ref, cancel, *, walkthrough=False, **kw):
            outer.cu_calls.append({"goal": goal, "walkthrough": walkthrough, "ref": ref})
            if outer._cu_wait_cancel:
                yield "Starting."
                while not cancel.is_set():
                    await asyncio.sleep(0.005)
                return
            for line in outer._cu_script:
                if cancel.is_set():
                    return
                yield line

        # (module, attr, replacement) — patched on the live sys.modules objects.
        self._patches = [
            (self.rt, "_send_chat_response", _chat),
            (self.rt, "_send_voice_response", _voice),
            (self.rt, "_record_bot_line", _record),
            (self.rc, "present_wrapper_url", _wrapper),
            (self.rc, "start_screenshare", _start_share),
            (self.rc, "stop_screenshare", _stop_share),
            (self.pres, "mint_present_token", _mint),
            (self.pres, "revoke_for_bot", _revoke),
            (self.pres, "get_provider", _get_provider),
            (self.pres, "run_computer_use", _fake_cu),
        ]
        self._saved = []
        for mod, attr, val in self._patches:
            self._saved.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, val)

        # Owner name for the ask-gate / nudge messages.
        self._saved_bot = self.rc.bot_store.get(BOT)
        self.rc.bot_store[BOT] = {"owner_name": "Abhinav Dasari"}
        self.rt._BOT_WAKE_ALIAS[BOT] = "Flash"

    def tearDown(self):
        for mod, attr, val in self._saved:
            setattr(mod, attr, val)
        if self._saved_bot is None:
            self.rc.bot_store.pop(BOT, None)
        else:
            self.rc.bot_store[BOT] = self._saved_bot
        self.rt._BOT_WAKE_ALIAS.pop(BOT, None)
        self.pres._active.clear()

    async def _start(self, goal, *, owner, ws, settings=REF_SETTINGS):
        await self.pres.start_presentation(
            BOT, {}, goal, requester_is_owner=owner, workspace_scope=ws, settings=settings,
        )

    # ------------------------------------------------------------------ gate

    async def test_personal_scope_non_owner_refused(self):
        await self._start("pull up the PR", owner=False, ws=False)
        self.assertEqual(self.cu_calls, [])
        self.assertFalse(hasattr(self, "share_url"))
        self.assertTrue(any("Only" in c and "Abhinav" in c for c in self.chats), self.chats)
        self.assertFalse(self.pres.is_presenting(BOT))

    async def test_workspace_member_allowed(self):
        await self._start("pull up the PR", owner=False, ws=True)
        self.assertEqual(len(self.cu_calls), 1)
        self.assertFalse(self.pres.is_presenting(BOT))  # cleared in finally

    async def test_missing_sandbox_nudge(self):
        await self._start("pull up the PR", owner=True, ws=False, settings={})
        self.assertEqual(self.cu_calls, [])
        self.assertTrue(any("set up" in c.lower() for c in self.chats), self.chats)
        self.assertFalse(self.pres.is_presenting(BOT))

    # ------------------------------------------------------------- happy path

    async def test_happy_path_owner(self):
        await self._start("open the auth PR", owner=True, ws=False)
        # Resumed the owner's sandbox, minted a token for THIS bot, pointed Recall
        # at the wrapper URL built from that token.
        self.assertEqual(len(self.provider.resumed), 1)
        self.assertEqual(self.minted["bot_id"], BOT)
        self.assertTrue(self.minted["view_only"])
        self.assertEqual(self.share_url, "https://webhook.example/present/tok_abc")
        # Loop ran (non-walkthrough), the arrival line was spoken AND posted to chat.
        self.assertEqual(len(self.cu_calls), 1)
        self.assertFalse(self.cu_calls[0]["walkthrough"])
        self.assertIn("Here's the auth PR.", self.voices)
        self.assertIn("Here's the auth PR.", self.chats)
        self.assertTrue(any("Starting the screen" in c for c in self.chats), self.chats)
        # Final summary recorded into the transcript under the persona name.
        self.assertEqual(self.recorded, [("Here's the auth PR.", "Flash")])
        # Finally always tears the share down + revokes + clears the slot.
        self.assertEqual(self.stopped, [BOT])
        self.assertEqual(self.revoked, [BOT])
        self.assertFalse(self.pres.is_presenting(BOT))

    async def test_walkthrough_flag_and_narration(self):
        self._cu_script = ["This is the CI dashboard.", "All checks are green."]
        await self._start("walk us through the CI dashboard", owner=True, ws=False)
        self.assertTrue(self.cu_calls[0]["walkthrough"])
        # Opening latency-cover line (the manager's own "pull that up on screen"
        # voice, replacing the old speculative `present` ack) is spoken first, then
        # every milestone; only the LAST milestone goes to chat as the summary.
        self.assertEqual(
            self.voices,
            ["Let me pull that up on screen—", "This is the CI dashboard.", "All checks are green."],
        )
        self.assertIn("All checks are green.", self.chats)
        self.assertNotIn("This is the CI dashboard.", self.chats)

    # ---------------------------------------------------------- serialization

    async def test_already_presenting(self):
        self.pres._active[BOT] = {"cancel": asyncio.Event(), "goal": "prior"}
        await self._start("pull up something else", owner=True, ws=False)
        self.assertEqual(self.cu_calls, [])  # did not start a second loop
        self.assertTrue(any("already presenting" in c.lower() for c in self.chats), self.chats)
        # The pre-existing slot is untouched (not torn down by the rejected call).
        self.assertTrue(self.pres.is_presenting(BOT))
        self.assertEqual(self.stopped, [])

    # -------------------------------------------------------- failure contract

    async def test_screenshare_denied_falls_back_to_link(self):
        self._share_result = {"success": False, "status": 403, "error": "host denied"}
        await self._start("pull up the PR", owner=True, ws=False)
        # Posted the tokenized watch-along link (contains the wrapper URL)...
        self.assertTrue(any("watch along" in c.lower() and "tok_abc" in c for c in self.chats), self.chats)
        # ...and still drove the loop so link-holders see activity.
        self.assertEqual(len(self.cu_calls), 1)
        # Share still torn down in finally (idempotent).
        self.assertEqual(self.stopped, [BOT])
        self.assertFalse(self.pres.is_presenting(BOT))

    async def test_resume_failure_nudges_and_cleans_up(self):
        self.provider = _FakeProvider(resume_raises=True)
        await self._start("pull up the PR", owner=True, ws=False)
        self.assertEqual(self.cu_calls, [])
        self.assertFalse(hasattr(self, "share_url"))  # never started a share
        self.assertTrue(any("Set up my AI workspace" in c for c in self.chats), self.chats)
        self.assertFalse(self.pres.is_presenting(BOT))

    # ------------------------------------------------------------------ cancel

    async def test_stop_presentation_trips_cancel(self):
        self._cu_wait_cancel = True
        task = asyncio.create_task(self._start("pull up the PR", owner=True, ws=False))
        # Wait until the present is live and driving.
        for _ in range(200):
            if self.pres.is_presenting(BOT) and "Starting." in self.voices:
                break
            await asyncio.sleep(0.005)
        self.assertTrue(self.pres.is_presenting(BOT))

        await self.pres.stop_presentation(BOT)  # trips the cancel event
        await asyncio.wait_for(task, timeout=2.0)

        # Cancel = silent preemption: no final summary posted, but the share IS
        # torn down and the slot cleared.
        self.assertEqual(self.recorded, [])
        self.assertEqual(self.stopped, [BOT])
        self.assertEqual(self.revoked, [BOT])
        self.assertFalse(self.pres.is_presenting(BOT))

    def test_request_stop_returns_false_when_idle(self):
        self.assertFalse(self.pres.request_stop("no_such_bot"))


if __name__ == "__main__":
    unittest.main()

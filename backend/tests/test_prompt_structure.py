import asyncio
import hashlib
import os
import sys
import types
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_a, **_k: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

# pysbd is required transitively by realtime_routes → voice_pipeline. Stub it.
if "pysbd" not in sys.modules:
    _fake_pysbd = types.ModuleType("pysbd")
    class _FakeSegmenter:
        def __init__(self, *_a, **_k): pass
        def segment(self, text): return [text]
    _fake_pysbd.Segmenter = _FakeSegmenter
    sys.modules["pysbd"] = _fake_pysbd

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")


import perception_state
import realtime_routes as rr


def _run(coro):
    return asyncio.run(coro)


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


class StaticPrefixCacheStabilityTests(unittest.TestCase):
    """Phase C.2 — Groq prompt-caching requires the cacheable prefix to be
    byte-identical across consecutive commands. We assert SHA1 equality on
    the static system message between two builds with evolving state.
    A future regression that interpolates state["meeting_start_ts"] or a
    bot_id slug into the static prefix will fail this test, not silently
    nuke cache hits."""

    def test_static_prefix_hash_stable_across_two_commands(self):
        # Same tool grants, different per-call values (now_str, memory, command).
        msgs1 = rr._build_command_messages(
            has_gmail=True,
            has_calendar=True,
            now_str="Friday, May 14, 2026 at 9:00 AM EDT",
            memory_context="(memory snapshot 1)",
            speaker="Alice",
            command="check the weather",
            prompt_cache_on=True,
        )
        # Evolve state between calls — different time, different memory.
        msgs2 = rr._build_command_messages(
            has_gmail=True,
            has_calendar=True,
            now_str="Friday, May 14, 2026 at 9:08 AM EDT",
            memory_context="(memory snapshot 2 — Alice asked about weather)",
            speaker="Alice",
            command="now what's on my calendar",
            prompt_cache_on=True,
        )
        # Static prefix (msgs[0]) is byte-identical.
        self.assertEqual(_h(msgs1[0]["content"]), _h(msgs2[0]["content"]))

    def test_dynamic_message_does_change(self):
        # Sanity-check the other side: msgs[1] must vary, otherwise the
        # restructure is broken in the wrong direction.
        msgs1 = rr._build_command_messages(
            has_gmail=True, has_calendar=True,
            now_str="A", memory_context="X",
            speaker="A", command="c1", prompt_cache_on=True,
        )
        msgs2 = rr._build_command_messages(
            has_gmail=True, has_calendar=True,
            now_str="B", memory_context="Y",
            speaker="A", command="c2", prompt_cache_on=True,
        )
        self.assertNotEqual(msgs1[1]["content"], msgs2[1]["content"])

    def test_tool_grant_change_DOES_change_prefix(self):
        # Negative case: if has_gmail flips, the prefix MUST change. Otherwise
        # we'd be lying about the user's tool grants in the cached prefix.
        msgs1 = rr._build_command_messages(
            has_gmail=True, has_calendar=True,
            now_str="t", memory_context="m",
            speaker="A", command="c", prompt_cache_on=True,
        )
        msgs2 = rr._build_command_messages(
            has_gmail=False, has_calendar=True,
            now_str="t", memory_context="m",
            speaker="A", command="c", prompt_cache_on=True,
        )
        self.assertNotEqual(_h(msgs1[0]["content"]), _h(msgs2[0]["content"]))

    def test_legacy_layout_when_flag_off(self):
        msgs = rr._build_command_messages(
            has_gmail=True, has_calendar=True,
            now_str="t", memory_context="m",
            speaker="A", command="c", prompt_cache_on=False,
        )
        # Legacy: single system message, then user.
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        # All content (persona + now_str + memory) in the one system message.
        self.assertIn("PrismAI", msgs[0]["content"])
        self.assertIn("Current date and time:", msgs[0]["content"])

    def test_user_message_contains_speaker_when_present(self):
        msgs = rr._build_command_messages(
            has_gmail=False, has_calendar=False,
            now_str="t", memory_context="m",
            speaker="Bob", command="hello", prompt_cache_on=True,
        )
        self.assertEqual(msgs[-1]["content"], "Bob: hello")

    def test_user_message_no_speaker_prefix_when_empty(self):
        msgs = rr._build_command_messages(
            has_gmail=False, has_calendar=False,
            now_str="t", memory_context="m",
            speaker="", command="hello", prompt_cache_on=True,
        )
        self.assertEqual(msgs[-1]["content"], "hello")


class MemoryLockTests(unittest.TestCase):
    """Phase C.1 — per-bot memory lock. Critical sections serialize."""

    def test_memory_lock_is_lazy_and_per_bot(self):
        s1: dict = {}
        s2: dict = {}
        l1a = perception_state.get_memory_lock(s1)
        l1b = perception_state.get_memory_lock(s1)
        l2 = perception_state.get_memory_lock(s2)
        self.assertIs(l1a, l1b)               # same bot → same lock
        self.assertIsNot(l1a, l2)             # different bot → different lock

    def test_concurrent_writes_serialize(self):
        # Two coroutines try to mutate state[buffer] under the lock; the
        # second one must observe the first's write — i.e., the second
        # one's pre-mutation read sees [first_item], not [].
        async def go():
            state: dict = {"buffer": []}
            seen_by_second: list[list] = []

            async def writer(name: str, hold_ms: int):
                async with perception_state.get_memory_lock(state):
                    if name == "second":
                        seen_by_second.append(list(state["buffer"]))
                    state["buffer"].append(name)
                    # Hold the lock briefly to force the second coroutine
                    # to wait on it.
                    await asyncio.sleep(hold_ms / 1000)

            await asyncio.gather(
                writer("first", 5),
                asyncio.sleep(0.001),  # ensure first acquires lock first
                writer("second", 0),
            )
            return state["buffer"], seen_by_second

        buffer, seen = _run(go())
        self.assertEqual(buffer, ["first", "second"])
        # The second writer observed the first's write before its own mutation.
        self.assertEqual(seen, [["first"]])

    def test_lock_ordering_rule_documented(self):
        # The ordering rule (memory before session) must be present in the
        # module docstring or function docstring so it doesn't get lost.
        import inspect
        src = inspect.getsource(perception_state)
        self.assertIn("acquire memory_lock", src.lower())
        self.assertIn("session_lock", src)


if __name__ == "__main__":
    unittest.main()

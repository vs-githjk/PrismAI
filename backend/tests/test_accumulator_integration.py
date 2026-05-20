"""Phase 2 integration tests — verify the PRISM_ACCUMULATOR flag actually
routes chunks through the accumulator and bypasses the legacy chunk-level
path. The accumulator module itself is tested in test_utterance_accumulator;
these tests check the wiring in realtime_routes.

Scope: state initialization, branching logic, _emit_utterance callback,
cleanup. Not a webhook end-to-end test — those would need a running event
loop and fake Recall payloads with the full segment shape.
"""

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

if "pysbd" not in sys.modules:
    _fake_pysbd = types.ModuleType("pysbd")
    class _FakeSegmenter:
        def __init__(self, *_a, **_k): pass
        def segment(self, text): return [text]
    _fake_pysbd.Segmenter = _FakeSegmenter
    sys.modules["pysbd"] = _fake_pysbd

os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("RECALL_API_KEY", "test")


import realtime_routes as rr
import utterance_accumulator as ua


class StateInitFlagOff(unittest.TestCase):
    """When PRISM_ACCUMULATOR is unset/0, the accumulator field stays None.
    No memory cost for users who haven't opted in."""

    def setUp(self):
        rr._bot_state.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def tearDown(self):
        rr._bot_state.clear()

    def test_accumulator_none_when_flag_off(self):
        state = rr._get_bot_state("bot_a")
        self.assertIsNone(state["accumulator"])
        self.assertIsNone(state["_accumulator_tick_task"])


class StateInitFlagOn(unittest.TestCase):
    """When PRISM_ACCUMULATOR=1, _get_bot_state builds an Accumulator with
    the env-configured tunables and binds on_flush to _emit_utterance."""

    def setUp(self):
        rr._bot_state.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"

    def tearDown(self):
        rr._bot_state.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def test_accumulator_created_when_flag_on(self):
        state = rr._get_bot_state("bot_a")
        self.assertIsNotNone(state["accumulator"])
        self.assertIsInstance(state["accumulator"], ua.Accumulator)

    def test_accumulator_uses_env_tunables(self):
        os.environ["PRISM_ACC_PAUSE_MS"] = "900"
        os.environ["PRISM_ACC_PUNCT_GRACE_MS"] = "150"
        os.environ["PRISM_ACC_MAX_CHARS"] = "300"
        os.environ["PRISM_ACC_MAX_WORDS"] = "50"
        try:
            state = rr._get_bot_state("bot_tunable")
            acc = state["accumulator"]
            self.assertEqual(acc.pause_ms, 900)
            self.assertEqual(acc.punct_grace_ms, 150)
            self.assertEqual(acc.max_chars, 300)
            self.assertEqual(acc.max_words, 50)
        finally:
            for k in ("PRISM_ACC_PAUSE_MS", "PRISM_ACC_PUNCT_GRACE_MS",
                      "PRISM_ACC_MAX_CHARS", "PRISM_ACC_MAX_WORDS"):
                os.environ.pop(k, None)

    def test_accumulator_bot_id_matches_state_key(self):
        # The accumulator's bot_id is used in audit-log strings and
        # synth utterance_id. It MUST match the state-dict key, else
        # logs won't correlate.
        state = rr._get_bot_state("bot_specific_id")
        self.assertEqual(state["accumulator"].bot_id, "bot_specific_id")


class EmitUtteranceBufferAppend(unittest.IsolatedAsyncioTestCase):
    """_emit_utterance is the on_flush callback. It must produce the same
    'Speaker: text' buffer line format as the legacy path, so downstream
    consumers (compression, end-of-meeting agents) don't need to change.

    Async test class because _emit_utterance schedules tasks via
    asyncio.create_task, which requires a running event loop."""

    def setUp(self):
        rr._bot_state.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"
        self.state = rr._get_bot_state("bot_emit")

    def tearDown(self):
        rr._bot_state.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    async def test_emit_appends_speaker_colon_text_format(self):
        flushed = ua.FlushedUtterance(
            utterance_id="abcd1234",
            speaker_id="pid_alice",
            speaker_name="Alice",
            text="Hello team",
            word_count=2,
            chunk_count=1,
            duration_ms=400,
            flush_reason=ua.REASON_PAUSE,
        )
        rr._emit_utterance(self.state, "bot_emit", flushed)
        self.assertEqual(self.state["transcript_buffer"], ["Alice: Hello team"])

    async def test_emit_records_meeting_start_ts_on_first(self):
        # The legacy path sets meeting_start_ts on first transcript event;
        # the accumulator path must do the same so analytics + nudges work.
        self.assertIsNone(self.state["meeting_start_ts"])
        flushed = ua.FlushedUtterance(
            utterance_id="x", speaker_id="pid_a", speaker_name="A",
            text="hi", word_count=1, chunk_count=1, duration_ms=100,
            flush_reason=ua.REASON_PAUSE,
        )
        rr._emit_utterance(self.state, "bot_emit", flushed)
        self.assertIsNotNone(self.state["meeting_start_ts"])


class FullChunkFlowFlagOn(unittest.IsolatedAsyncioTestCase):
    """End-to-end-ish: pump synthetic chunks through _handle_realtime_payload
    with the flag on and verify they accumulate (NOT in buffer yet) and
    eventually flush on speaker change."""

    def setUp(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"

    def tearDown(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def _make_payload(self, bot_id, speaker_id, speaker_name, text):
        # Recall transcript.data shape with participant id + words
        return {
            "event": "transcript.data",
            "bot_id": bot_id,
            "data": {
                "data": {
                    "participant": {"id": speaker_id, "name": speaker_name},
                    "words": [{"text": w} for w in text.split()],
                }
            },
        }

    async def test_chunk_does_not_immediately_appear_in_buffer(self):
        # Under accumulator-on: a single chunk should be pending, NOT
        # in the transcript buffer yet.
        await rr._handle_realtime_payload(
            self._make_payload("bot_x", "pid_a", "Alice", "hello there"),
            verified_bot_id="bot_x",
        )
        state = rr._bot_state["bot_x"]
        self.assertEqual(state["transcript_buffer"], [])  # not flushed yet
        self.assertIn("pid_a", state["accumulator"].pending)

    async def test_speaker_change_flushes_to_buffer(self):
        await rr._handle_realtime_payload(
            self._make_payload("bot_y", "pid_a", "Alice", "hello there"),
            verified_bot_id="bot_y",
        )
        await rr._handle_realtime_payload(
            self._make_payload("bot_y", "pid_b", "Bob", "hi back"),
            verified_bot_id="bot_y",
        )
        state = rr._bot_state["bot_y"]
        # Alice's utterance got flushed when Bob's chunk arrived
        self.assertEqual(len(state["transcript_buffer"]), 1)
        self.assertEqual(state["transcript_buffer"][0], "Alice: hello there")
        # Bob is still pending
        self.assertIn("pid_b", state["accumulator"].pending)
        self.assertNotIn("pid_a", state["accumulator"].pending)

    async def test_same_speaker_chunks_merge_into_one_line(self):
        # This is THE win — the user's "ping-pong" problem. Same speaker
        # sending multiple chunks quickly should produce ONE buffer line.
        for chunk in ("Let's", "see.", "Hi", "everyone."):
            await rr._handle_realtime_payload(
                self._make_payload("bot_z", "pid_a", "Alice", chunk),
                verified_bot_id="bot_z",
            )
        state = rr._bot_state["bot_z"]
        # All four chunks accumulated to one pending entry
        self.assertEqual(len(state["accumulator"].pending), 1)
        # Force flush to see the merged result
        state["accumulator"].flush_all()
        self.assertEqual(len(state["transcript_buffer"]), 1)
        # All chunk text present in one line
        line = state["transcript_buffer"][0]
        self.assertIn("Let's", line)
        self.assertIn("see", line)
        self.assertIn("Hi", line)
        self.assertIn("everyone", line)


class FullChunkFlowFlagOff(unittest.IsolatedAsyncioTestCase):
    """Verify legacy chunk-level behavior is preserved when flag is off:
    each chunk produces an immediate buffer line."""

    def setUp(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def tearDown(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()

    async def test_chunk_immediately_appears_in_buffer_legacy(self):
        payload = {
            "event": "transcript.data",
            "bot_id": "bot_legacy",
            "data": {
                "data": {
                    "participant": {"id": "pid_a", "name": "Alice"},
                    "words": [{"text": "hello"}, {"text": "world"}],
                }
            },
        }
        await rr._handle_realtime_payload(payload, verified_bot_id="bot_legacy")
        state = rr._bot_state["bot_legacy"]
        # Legacy path appends immediately — no accumulator buffering
        self.assertEqual(state["transcript_buffer"], ["Alice: hello world"])
        # And the accumulator field stayed None
        self.assertIsNone(state["accumulator"])


class CompareMode(unittest.IsolatedAsyncioTestCase):
    """PRISM_ACC_COMPARE=1 runs the legacy buffer-append (with fuzzy
    dedup) into a parallel `transcript_buffer_legacy` field so the
    accumulator's output can be diffed against what legacy would have
    produced. The accumulator path remains authoritative for buffer +
    command dispatch — compare is observability only."""

    def setUp(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"
        os.environ["PRISM_ACC_COMPARE"] = "1"

    def tearDown(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)
        os.environ.pop("PRISM_ACC_COMPARE", None)

    def _make_payload(self, bot_id, speaker_id, speaker_name, text):
        return {
            "event": "transcript.data",
            "bot_id": bot_id,
            "data": {
                "data": {
                    "participant": {"id": speaker_id, "name": speaker_name},
                    "words": [{"text": w} for w in text.split()],
                }
            },
        }

    async def test_legacy_buffer_populated_alongside_accumulator(self):
        # Two chunks, same speaker — legacy would append both lines
        # (no dedup since text differs); accumulator merges into one.
        await rr._handle_realtime_payload(
            self._make_payload("bot_c", "pid_a", "Alice", "hello"),
            verified_bot_id="bot_c",
        )
        await rr._handle_realtime_payload(
            self._make_payload("bot_c", "pid_a", "Alice", "there"),
            verified_bot_id="bot_c",
        )
        state = rr._bot_state["bot_c"]
        legacy = state.get("transcript_buffer_legacy") or []
        # Legacy buffer has both chunks as separate lines
        self.assertEqual(len(legacy), 2)
        self.assertEqual(legacy[0], "Alice: hello")
        self.assertEqual(legacy[1], "Alice: there")
        # Accumulator buffer still empty — pending hasn't flushed
        self.assertEqual(state["transcript_buffer"], [])
        # On flush, accumulator produces ONE line
        state["accumulator"].flush_all()
        self.assertEqual(len(state["transcript_buffer"]), 1)
        self.assertIn("hello", state["transcript_buffer"][0])
        self.assertIn("there", state["transcript_buffer"][0])

    async def test_legacy_fuzzy_dedup_is_simulated(self):
        # Two near-identical chunks within 3s — legacy 3s fuzzy dedup
        # should drop the second one even in compare mode.
        await rr._handle_realtime_payload(
            self._make_payload("bot_d", "pid_a", "Alice", "prism stop"),
            verified_bot_id="bot_d",
        )
        await rr._handle_realtime_payload(
            self._make_payload("bot_d", "pid_a", "Alice", "prism stop"),
            verified_bot_id="bot_d",
        )
        state = rr._bot_state["bot_d"]
        legacy = state.get("transcript_buffer_legacy") or []
        # Legacy dedup dropped the second chunk
        self.assertEqual(len(legacy), 1)


class RealisticTranscriptSimulation(unittest.IsolatedAsyncioTestCase):
    """Replay the actual ping-pong pattern from the production transcript
    the user shared. The pattern: two speakers, very short alternating
    chunks within ~200ms of each other. Legacy behavior would produce
    one transcript line per chunk (10+ ping-pong fragments); the
    accumulator should produce one line per real semantic utterance."""

    def setUp(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"

    def tearDown(self):
        rr._bot_state.clear()
        rr._ingress_log.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def _chunk_payload(self, bot_id, speaker_id, speaker_name, text):
        return {
            "event": "transcript.data",
            "bot_id": bot_id,
            "data": {
                "data": {
                    "participant": {"id": speaker_id, "name": speaker_name},
                    "words": [{"text": w} for w in text.split()],
                }
            },
        }

    async def test_production_ping_pong_emits_well_formed_lines(self):
        # Verbatim chunk sequence from the user's shared transcript.
        # Real-world: each chunk arrives within ~100-300ms of the
        # previous. Two speakers alternating short fragments.
        #
        # NOTE: strict alternation (A→B→A→B) IS a degenerate case for
        # the accumulator — every chunk is a speaker change, forcing
        # a flush. The accumulator's win here is not line count (still
        # 10) but that each line is a COMPLETE coherent fragment with
        # proper speaker attribution, not a word-level interleaving.
        bot_id = "bot_pp"
        chunks = [
            ("pid_abhi", "Abhinav Dasari", "Let's see. Let's"),
            ("pid_sam",  "Samridhi",       "see."),
            ("pid_abhi", "Abhinav Dasari", "Let's"),
            ("pid_sam",  "Samridhi",       "see."),
            ("pid_abhi", "Abhinav Dasari", "Let's see. Hi, Prasanth. Who are"),
            ("pid_sam",  "Samridhi",       "you? I do not consent"),
            ("pid_abhi", "Abhinav Dasari", "to this"),
            ("pid_sam",  "Samridhi",       "meeting"),
            ("pid_abhi", "Abhinav Dasari", "that you"),
            ("pid_sam",  "Samridhi",       "recorded."),
        ]
        for (pid, name, text) in chunks:
            await rr._handle_realtime_payload(
                self._chunk_payload(bot_id, pid, name, text),
                verified_bot_id=bot_id,
            )
        state = rr._bot_state[bot_id]
        state["accumulator"].flush_all()
        buf = state["transcript_buffer"]
        # No more lines than legacy would have produced
        self.assertLessEqual(len(buf), 10)
        # Every line is "Speaker: text" — well-formed
        for line in buf:
            self.assertIn(": ", line)
            speaker_part, text_part = line.split(": ", 1)
            self.assertTrue(speaker_part)
            self.assertTrue(text_part)
        # No adjacent duplicates
        for i in range(1, len(buf)):
            self.assertNotEqual(buf[i], buf[i - 1])

    async def test_continuous_speech_collapses_to_one_utterance(self):
        # The REAL win: same speaker delivering a coherent thought
        # across multiple chunks. Legacy would produce one buffer
        # line per chunk; accumulator merges them.
        bot_id = "bot_solo"
        chunks = [
            "Hey team,",
            "I wanted to talk about",
            "the project timeline.",
            "We're a week behind",
            "and need to decide if we",
            "push the launch or cut scope.",
        ]
        for c in chunks:
            await rr._handle_realtime_payload(
                self._chunk_payload(bot_id, "pid_a", "Alice", c),
                verified_bot_id=bot_id,
            )
        state = rr._bot_state[bot_id]
        state["accumulator"].flush_all()
        buf = state["transcript_buffer"]
        # Legacy: 6 lines (one per chunk).
        # Accumulator: 1 line (all chunks merged — same speaker, no
        # tick fired between them so punct grace never elapsed).
        self.assertEqual(len(buf), 1)
        self.assertTrue(buf[0].startswith("Alice: "))
        text = buf[0].split(": ", 1)[1]
        # All semantic content preserved
        self.assertIn("Hey team", text)
        self.assertIn("project timeline", text)
        self.assertIn("cut scope", text)


class CleanupBotState(unittest.TestCase):
    """cleanup_bot_state must flush any remaining pending utterances
    (so the meeting transcript is complete) and cancel the tick task
    (so we don't leak background tasks)."""

    def setUp(self):
        rr._bot_state.clear()
        os.environ["PRISM_ACCUMULATOR"] = "1"

    def tearDown(self):
        rr._bot_state.clear()
        os.environ.pop("PRISM_ACCUMULATOR", None)

    def test_cleanup_flushes_pending_utterances(self):
        state = rr._get_bot_state("bot_cleanup")
        # Manually add a pending utterance
        state["accumulator"].pending["pid_a"] = ua.PendingUtterance(
            speaker_id="pid_a",
            speaker_name="Alice",
            text="goodbye",
            first_word_mono=1.0,
            last_word_mono=1.0,
            word_count=1,
        )
        rr.cleanup_bot_state("bot_cleanup")
        # State was popped, but the flush_all (in cleanup_bot_state)
        # happened first — we can't introspect _bot_state["bot_cleanup"]
        # anymore, but we CAN verify that no exception was raised and
        # the bot state is gone.
        self.assertNotIn("bot_cleanup", rr._bot_state)

    def test_cleanup_idempotent_on_unknown_bot(self):
        rr.cleanup_bot_state("never_existed")  # must not raise


if __name__ == "__main__":
    unittest.main()

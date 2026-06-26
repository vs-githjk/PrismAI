"""Private live catch-up (Feature B): streaming generator + rate limiter."""
import json
import types
import unittest
from unittest import mock

import realtime_routes as rr


def _collect(sse_lines):
    """Parse a list of SSE 'data: {json}\\n\\n' strings into payload dicts."""
    out = []
    for ln in sse_lines:
        assert ln.startswith("data: ") and ln.endswith("\n\n")
        out.append(json.loads(ln[len("data: "):].strip()))
    return out


class _FakeStream:
    def __init__(self, tokens):
        self._tokens = tokens

    def __aiter__(self):
        async def gen():
            for t in self._tokens:
                yield types.SimpleNamespace(
                    choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=t))]
                )
        return gen()


def _fake_openai(tokens):
    async def _create(**kwargs):
        assert kwargs.get("stream") is True
        return _FakeStream(tokens)
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))
    )


async def _drain(gen):
    return [chunk async for chunk in gen]


class LiveCatchupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        rr._CATCHUP_RATE.clear()

    def tearDown(self):
        rr._CATCHUP_RATE.clear()

    async def test_empty_meeting_says_just_started(self):
        with mock.patch.object(rr, "_get_bot_state", lambda bot_id: {"transcript_buffer": []}):
            chunks = _collect(await _drain(rr.stream_catchup_answer("b1", "catchup", "")))
        self.assertTrue(any("just started" in c.get("token", "") for c in chunks))
        self.assertEqual(chunks[-1], {"done": True, "sources": []})

    async def test_streams_tokens_and_done(self):
        state = {"memory_summary": "Talked about pricing.", "transcript_buffer": ["Bob: hi"]}
        with mock.patch.object(rr, "_get_bot_state", lambda bot_id: state), \
             mock.patch.object(rr, "get_openai", lambda: _fake_openai(["They ", "chose ", "$49."])):
            chunks = _collect(await _drain(rr.stream_catchup_answer("b1", "qa", "what was decided?")))
        tokens = "".join(c.get("token", "") for c in chunks)
        self.assertIn("They chose $49.", tokens)
        self.assertTrue(chunks[-1]["done"])

    async def test_rag_skipped_for_anonymous(self):
        called = {"n": 0}

        async def _fake_search(*a, **k):
            called["n"] += 1
            return []

        state = {"memory_summary": "x", "transcript_buffer": ["a: b"]}
        import knowledge_service
        with mock.patch.object(rr, "_get_bot_state", lambda bot_id: state), \
             mock.patch.object(rr, "get_openai", lambda: _fake_openai(["ok"])), \
             mock.patch.object(knowledge_service, "search_knowledge", _fake_search):
            await _drain(rr.stream_catchup_answer("b1", "qa", "anything?", member_user_id=None))
        self.assertEqual(called["n"], 0)

    async def test_rag_runs_for_member(self):
        called = {"n": 0}

        async def _fake_search(query, user_id, k=4, **kw):
            called["n"] += 1
            return [{"doc_name": "Pricing.pdf", "content": "Enterprise tier is $99."}]

        state = {"memory_summary": "x", "transcript_buffer": ["a: b"]}
        import knowledge_service
        with mock.patch.object(rr, "_get_bot_state", lambda bot_id: state), \
             mock.patch.object(rr, "get_openai", lambda: _fake_openai(["ok"])), \
             mock.patch.object(knowledge_service, "search_knowledge", _fake_search):
            chunks = _collect(await _drain(
                rr.stream_catchup_answer("b1", "qa", "enterprise price?", member_user_id="u1")
            ))
        self.assertEqual(called["n"], 1)
        self.assertEqual(chunks[-1]["sources"], ["Pricing.pdf"])

    def test_rate_limit_min_interval(self):
        self.assertTrue(rr._catchup_rate_ok("tok"))
        self.assertFalse(rr._catchup_rate_ok("tok"))  # immediate retry blocked


if __name__ == "__main__":
    unittest.main()

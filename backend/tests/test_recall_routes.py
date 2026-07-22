import importlib
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


fake_supabase_module = types.ModuleType("supabase")
fake_supabase_module.create_client = lambda *_args, **_kwargs: None
fake_supabase_module.Client = object
sys.modules.setdefault("supabase", fake_supabase_module)

fake_analysis_service = types.ModuleType("analysis_service")


async def _fake_run_full_analysis(_transcript: str, **_kwargs):
    return {"summary": "ok", "agents_run": []}


fake_analysis_service.run_full_analysis = _fake_run_full_analysis
fake_analysis_service.build_analysis_transcript = lambda transcript, speakers=None, owner_name=None: transcript
sys.modules["analysis_service"] = fake_analysis_service

recall_routes = importlib.import_module("recall_routes")


class DummyResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *_args, **_kwargs):
        return self.response


class RecallRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(recall_routes.router)
        self.client = TestClient(self.app)
        self.original_api_key = recall_routes.RECALL_API_KEY
        recall_routes.RECALL_API_KEY = "test-key"
        recall_routes.bot_store.clear()

    def tearDown(self):
        recall_routes.RECALL_API_KEY = self.original_api_key
        recall_routes.bot_store.clear()

    def test_recall_webhook_sets_recording_state(self):
        payload = {"bot_id": "bot-1", "event": "in_call_recording"}

        response = self.client.post("/recall-webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(recall_routes.bot_store["bot-1"]["status"], "recording")

    def test_recall_webhook_marks_fatal_error(self):
        payload = {"bot_id": "bot-2", "event": "fatal_error"}

        response = self.client.post("/recall-webhook", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(recall_routes.bot_store["bot-2"]["status"], "error")
        self.assertEqual(recall_routes.bot_store["bot-2"]["error"], "Bot encountered a fatal error")

    def test_bot_status_404_is_preserved(self):
        with patch("recall_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyResponse(404))):
            response = self.client.get("/bot-status/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Bot not found")

    def test_bot_status_returns_live_recording_state(self):
        payload = {"status_changes": [{"code": "in_call_recording"}]}
        with patch("recall_routes.httpx.AsyncClient", return_value=FakeAsyncClient(DummyResponse(200, payload))):
            response = self.client.get("/bot-status/bot-live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "recording")

    def test_call_ended_webhook_starts_processing(self):
        # recall_webhook now reads request.body() (bytes) and parses JSON itself,
        # so it can verify the HMAC signature on the raw bytes when configured.
        payload_bytes = b'{"bot_id": "bot-3", "event": "call_ended"}'
        request = types.SimpleNamespace(
            body=AsyncMock(return_value=payload_bytes),
            headers={},
        )
        original_process = recall_routes._process_bot_transcript

        async def fake_process(bot_id):
            recall_routes.bot_store[bot_id]["result"] = {"summary": "done"}
            recall_routes.bot_store[bot_id]["status"] = "done"

        recall_routes._process_bot_transcript = fake_process
        try:
            response = asyncio.run(recall_routes.recall_webhook(request))
        finally:
            recall_routes._process_bot_transcript = original_process

        self.assertEqual(response, {"ok": True})
        self.assertEqual(recall_routes.bot_store["bot-3"]["status"], "done")
        self.assertEqual(recall_routes.bot_store["bot-3"]["result"], {"summary": "done"})


class LeaveReasonTestCase(unittest.TestCase):
    """The bot's disconnect reason is captured from Recall's status sub_code."""

    def test_extract_detail_from_status_node(self):
        payload = {"data": {"status": {"code": "call_ended", "sub_code": "bot_removed", "message": "m"}}}
        self.assertEqual(recall_routes._extract_status_detail(payload),
                         ("call_ended", "bot_removed", "m"))

    def test_extract_detail_from_data_node(self):
        payload = {"data": {"data": {"code": "call_ended", "sub_code": "recording_permission_denied"}}}
        code, sub, _ = recall_routes._extract_status_detail(payload)
        self.assertEqual((code, sub), ("call_ended", "recording_permission_denied"))

    def test_extract_detail_absent(self):
        self.assertEqual(recall_routes._extract_status_detail({"data": {}}), ("", "", ""))

    def test_reason_text_known_subcode(self):
        self.assertIn("removed Prism",
                      recall_routes._leave_reason_text("call_ended", "bot_removed", ""))

    def test_reason_text_falls_back_to_message_then_code(self):
        self.assertEqual(recall_routes._leave_reason_text("call_ended", "weird_code", "Custom msg"),
                         "Custom msg")
        self.assertIn("weird_code",
                      recall_routes._leave_reason_text("call_ended", "weird_code", ""))
        self.assertTrue(recall_routes._leave_reason_text("call_ended", "", ""))  # never empty

    def test_webhook_records_leave_reason(self):
        recall_routes.bot_store["bot-leave"] = {"status": "recording", "result": None, "error": None, "commands": []}
        payload_bytes = b'{"bot_id": "bot-leave", "event": "call_ended", "data": {"status": {"code": "call_ended", "sub_code": "bot_removed"}}}'
        request = types.SimpleNamespace(body=AsyncMock(return_value=payload_bytes), headers={})
        with patch.object(recall_routes, "_db_save"), \
             patch.object(recall_routes, "_mb_update_status"), \
             patch.object(recall_routes, "_process_bot_transcript", new=AsyncMock()):
            asyncio.run(recall_routes.recall_webhook(request))
        self.assertIn("removed Prism", recall_routes.bot_store["bot-leave"]["leave_reason"])

    def test_notable_leave_flags_and_stamps(self):
        recall_routes.bot_store["bot-notable"] = {"status": "recording"}
        with patch.object(recall_routes, "_db_save"):
            recall_routes._record_leave_reason("bot-notable", "call_ended", "bot_removed", "")
        bs = recall_routes.bot_store["bot-notable"]
        self.assertTrue(bs["leave_notable"])           # removal is notable
        self.assertEqual(bs["leave_sub_code"], "bot_removed")
        self.assertTrue(bs["left_at"])                 # timestamp captured
        recall_routes.bot_store.pop("bot-notable", None)

    def test_normal_ending_not_notable(self):
        recall_routes.bot_store["bot-clean"] = {"status": "recording"}
        with patch.object(recall_routes, "_db_save"):
            recall_routes._record_leave_reason("bot-clean", "call_ended", "meeting_ended", "")
        self.assertFalse(recall_routes.bot_store["bot-clean"]["leave_notable"])
        recall_routes.bot_store.pop("bot-clean", None)

    def test_leave_command_subcode_is_notable(self):
        recall_routes.bot_store["bot-lc"] = {"status": "recording"}
        with patch.object(recall_routes, "_db_save"):
            recall_routes._record_leave_reason("bot-lc", "", "bot_received_leave_call", "")
        self.assertTrue(recall_routes.bot_store["bot-lc"]["leave_notable"])
        recall_routes.bot_store.pop("bot-lc", None)

    def test_notable_reason_is_sticky(self):
        # A specific notable exit (asked to leave) must survive a later generic
        # call_ended that Recall fires moments after — don't downgrade it.
        recall_routes.bot_store["bot-sticky"] = {"status": "recording"}
        with patch.object(recall_routes, "_db_save"):
            recall_routes._record_leave_reason("bot-sticky", "", "bot_received_leave_call", "")
            recall_routes._record_leave_reason("bot-sticky", "call_ended", "", "")
        bs = recall_routes.bot_store["bot-sticky"]
        self.assertTrue(bs["leave_notable"])
        self.assertEqual(bs["leave_sub_code"], "bot_received_leave_call")
        recall_routes.bot_store.pop("bot-sticky", None)

    def _capture_posts(self):
        """A fake httpx.AsyncClient that records .post() calls (message payloads)."""
        posts = []

        class _Cap:
            async def __aenter__(self_inner):
                return self_inner
            async def __aexit__(self_inner, *_):
                return False
            async def post(self_inner, *_args, **kwargs):
                posts.append(kwargs.get("json") or {})
                return DummyResponse(200)

        return posts, _Cap

    def test_late_join_link_noop_before_intro(self):
        # Intro not yet sent → initial roster is covered by the intro broadcast,
        # so a late-join re-post must NOT fire.
        recall_routes.bot_store["bot-lj1"] = {"status": "recording", "live_token": "tok1"}
        posts, Cap = self._capture_posts()
        with patch("recall_routes.httpx.AsyncClient", Cap):
            asyncio.run(recall_routes.post_late_join_link("bot-lj1", "Sam"))
        self.assertEqual(posts, [])

    def test_late_join_link_posts_after_intro(self):
        recall_routes.bot_store["bot-lj2"] = {"status": "recording", "live_token": "tok2", "intro_sent": True}
        posts, Cap = self._capture_posts()
        with patch("recall_routes.httpx.AsyncClient", Cap):
            asyncio.run(recall_routes.post_late_join_link("bot-lj2", "Sam"))
        self.assertEqual(len(posts), 1)
        msg = posts[0].get("message", "")
        self.assertIn("tok2", msg)      # the persistent live/notes link
        self.assertIn("Sam", msg)       # personalized welcome

    def test_late_join_link_noop_without_token(self):
        recall_routes.bot_store["bot-lj3"] = {"status": "recording", "intro_sent": True}
        posts, Cap = self._capture_posts()
        with patch("recall_routes.httpx.AsyncClient", Cap):
            asyncio.run(recall_routes.post_late_join_link("bot-lj3", "Sam"))
        self.assertEqual(posts, [])


class KeytermGroundingTestCase(unittest.TestCase):
    """Lever A — Deepgram nova-3 keyterm prompting from KB/workspace/meeting names."""

    def test_payload_omits_keyterm_when_empty(self):
        body = recall_routes._recall_bot_create_json(
            "https://meet/x", "rt", "wh", keyterms=[])
        dg = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
        self.assertNotIn("keyterm", dg)
        self.assertEqual(dg["model"], "nova-3")

    def test_payload_omits_keyterm_by_default(self):
        # Live-streaming keyterm is OFF by default (it broke Deepgram transcription).
        terms = [f"Term{i}" for i in range(10)]
        body = recall_routes._recall_bot_create_json(
            "https://meet/x", "rt", "wh", keyterms=terms)
        dg = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
        self.assertNotIn("keyterm", dg)

    def test_payload_includes_and_clamps_keyterms_when_enabled(self):
        terms = [f"Term{i}" for i in range(60)]
        with patch.object(recall_routes, "_LIVE_KEYTERM_ENABLED", True):
            body = recall_routes._recall_bot_create_json(
                "https://meet/x", "rt", "wh", keyterms=terms)
        dg = body["recording_config"]["transcript"]["provider"]["deepgram_streaming"]
        self.assertIn("keyterm", dg)
        self.assertEqual(len(dg["keyterm"]), 50)  # clamped to Deepgram's budget

    def test_gather_keyterms_rejects_titles_and_dates(self):
        # The regression: long titles with dates/parens must NOT become keyterms.
        class _Resp:
            def __init__(self, data): self.data = data

        class _Query:
            def __init__(self, data): self._data = data
            def select(self, *_): return self
            def eq(self, *_): return self
            def in_(self, *_): return self
            def is_(self, *_): return self
            def gte(self, *_): return self
            def order(self, *_, **__): return self
            def limit(self, *_): return self
            def execute(self): return _Resp(self._data)

        class _SB:
            def table(self, name):
                if name == "workspace_members":
                    return _Query([{"user_email": "vidyut@galent.com"}])
                if name == "knowledge_docs":
                    return _Query([
                        {"name": "Prism App Development Sprint Planning (2026-06-26)"},
                        {"name": "Vidyut Sriram Resume"},
                    ])
                return _Query([])

        with patch.object(recall_routes, "supabase", _SB()), \
             patch("caches.get_user_workspace_ids", return_value=["ws1"]):
            terms = recall_routes._gather_keyterms("user-1", "ws1")

        self.assertIn("Vidyut", terms)  # clean name kept
        # Title with a date/parens must be dropped.
        self.assertNotIn("Prism App Development Sprint Planning (2026-06-26)", terms)
        for t in terms:
            self.assertFalse(any(c.isdigit() for c in t), f"digit leaked into keyterm: {t!r}")
            self.assertNotIn("(", t)

    def test_name_from_email(self):
        self.assertEqual(recall_routes._name_from_email("jane.doe@acme.com"), "Jane Doe")
        self.assertEqual(recall_routes._name_from_email("vidyut0712@gmail.com"), "Vidyut")
        self.assertEqual(recall_routes._name_from_email("ravi_kumar@x.io"), "Ravi Kumar")

    def test_gather_keyterms_dedups_filters_and_caps(self):
        class _Resp:
            def __init__(self, data): self.data = data

        class _Query:
            def __init__(self, data): self._data = data
            def select(self, *_): return self
            def eq(self, *_): return self
            def in_(self, *_): return self
            def is_(self, *_): return self
            def gte(self, *_): return self
            def order(self, *_, **__): return self
            def limit(self, *_): return self
            def execute(self): return _Resp(self._data)

        class _SB:
            def table(self, name):
                if name == "workspace_members":
                    return _Query([{"user_email": "jane.doe@acme.com"},
                                   {"user_email": "jane.doe@acme.com"}])  # dup
                if name == "knowledge_docs":
                    return _Query([{"name": "Acme Roadmap.pdf"}, {"name": "document"}])
                if name == "meetings":
                    return _Query([{"result": {
                        "sentiment": {"speakers": [{"name": "Kanishq"}]},
                        "action_items": [{"owner": "Unassigned"}, {"owner": "Devajsinh"}],
                    }}])
                return _Query([])

        with patch.object(recall_routes, "supabase", _SB()), \
             patch("caches.get_user_workspace_ids", return_value=["ws1"]):
            terms = recall_routes._gather_keyterms("user-1", "ws1")

        # Jane Doe (deduped to one), Acme Roadmap (ext stripped), Kanishq, Devajsinh.
        self.assertIn("Jane Doe", terms)
        self.assertIn("Acme Roadmap", terms)
        self.assertIn("Kanishq", terms)
        self.assertIn("Devajsinh", terms)
        # Stopwords / "Unassigned" dropped; no duplicates.
        self.assertNotIn("document", terms)
        self.assertNotIn("Unassigned", terms)
        self.assertEqual(len(terms), len(set(t.lower() for t in terms)))

    def test_gather_keyterms_returns_empty_without_supabase(self):
        with patch.object(recall_routes, "supabase", None):
            self.assertEqual(recall_routes._gather_keyterms("u", "w"), [])

    def test_proper_nouns_from_content_ranks_strong_signals(self):
        texts = [
            "The pipeline uses Reciprocal Rank Fusion to merge results. "
            "We also run CodeQL and KLEE on the code. Reciprocal Rank Fusion is key.",
            "OpenSearch integrates CodeQL for static analysis. The team met to discuss it.",
        ]
        terms = recall_routes._proper_nouns_from_texts(texts, limit=10)
        # Multi-word Title Case + camelCase are strong signals and kept.
        self.assertIn("Reciprocal Rank Fusion", terms)
        self.assertIn("CodeQL", terms)
        self.assertIn("OpenSearch", terms)
        # Sentence-initial common words are filtered (not surfaced as terms).
        self.assertNotIn("The", terms)
        self.assertNotIn("We", terms)

    def test_gather_keyterms_mines_doc_content(self):
        class _Resp:
            def __init__(self, data): self.data = data

        class _Query:
            def __init__(self, data): self._data = data
            def select(self, *_): return self
            def eq(self, *_): return self
            def in_(self, *_): return self
            def is_(self, *_): return self
            def gte(self, *_): return self
            def order(self, *_, **__): return self
            def limit(self, *_): return self
            def execute(self): return _Resp(self._data)

        class _SB:
            def table(self, name):
                if name == "knowledge_chunks":
                    return _Query([
                        {"content": "The system uses CodeQL and Reciprocal Rank Fusion. "
                                    "Reciprocal Rank Fusion improves recall."},
                    ])
                return _Query([])

        with patch.object(recall_routes, "supabase", _SB()), \
             patch("caches.get_user_workspace_ids", return_value=["ws1"]):
            terms = recall_routes._gather_keyterms("user-1", "ws1")

        # Proper nouns from the doc BODY (not just titles) are grounded now.
        self.assertIn("CodeQL", terms)
        self.assertIn("Reciprocal Rank Fusion", terms)


class BrandedBotTestCase(unittest.TestCase):
    """#4 — branded bot join: display name + logo camera tile."""

    def test_default_display_name_is_branded(self):
        body = recall_routes._recall_bot_create_json("https://meet/x", "rt", "wh")
        self.assertEqual(body["bot_name"], recall_routes.BOT_DISPLAY_NAME)
        self.assertEqual(recall_routes.BOT_DISPLAY_NAME, "PrismAI")

    def test_explicit_bot_name_wins(self):
        body = recall_routes._recall_bot_create_json(
            "https://meet/x", "rt", "wh", bot_name="Jane (PrismAI stand-in)")
        self.assertEqual(body["bot_name"], "Jane (PrismAI stand-in)")

    def test_output_media_supersedes_the_static_tile(self):
        # Voice agent (Phase 2): the bot's camera now renders the speaker page, which owns
        # the branding AND carries the bot's audio into the call. Both target the camera,
        # so the static logo tile is deliberately no longer sent — even when one is
        # available. If this ever regresses, Recall picks one and the mouth may go silent.
        recall_routes._bot_video_output.cache_clear()
        with patch.object(recall_routes, "_BOT_TILE_ENABLED", True):
            tile = {"in_call_recording": {"kind": "jpeg", "b64_data": "abc"}}
            with patch.object(recall_routes, "_bot_video_output", return_value=tile):
                body = recall_routes._recall_bot_create_json("https://meet/x", "rt", "wh")
        self.assertNotIn("automatic_video_output", body)
        self.assertEqual(body["output_media"]["camera"]["kind"], "webpage")

    def test_video_output_omitted_when_disabled(self):
        recall_routes._bot_video_output.cache_clear()
        with patch.object(recall_routes, "_BOT_TILE_ENABLED", False):
            recall_routes._bot_video_output.cache_clear()
            body = recall_routes._recall_bot_create_json("https://meet/x", "rt", "wh")
        self.assertNotIn("automatic_video_output", body)
        recall_routes._bot_video_output.cache_clear()

    def test_tile_asset_loads_as_raw_base64(self):
        recall_routes._bot_video_output.cache_clear()
        with patch.object(recall_routes, "_BOT_TILE_ENABLED", True):
            out = recall_routes._bot_video_output()
        self.assertIsNotNone(out)
        self.assertEqual(out["in_call_recording"]["kind"], "jpeg")
        # Raw base64 — no data-URI prefix (Recall requirement).
        self.assertFalse(out["in_call_recording"]["b64_data"].startswith("data:"))
        recall_routes._bot_video_output.cache_clear()


class LeaveCallTestCase(unittest.TestCase):
    """#3 — /leave command: graceful leave without tearing down analysis."""

    def test_leave_call_posts_and_keeps_bot_store(self):
        recall_routes.bot_store["bot-leave-cmd"] = {"status": "recording"}

        class _Resp:
            status_code = 200

        class _Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): return _Resp()

        with patch.object(recall_routes, "RECALL_API_KEY", "key"), \
             patch.object(recall_routes.httpx, "AsyncClient", lambda *a, **k: _Client()):
            ok = asyncio.run(recall_routes.leave_call("bot-leave-cmd"))
        self.assertTrue(ok)
        # leave_call must NOT tear down bot_store (analysis still needs to run).
        self.assertIn("bot-leave-cmd", recall_routes.bot_store)
        recall_routes.bot_store.pop("bot-leave-cmd", None)


class HumanWordCountTestCase(unittest.TestCase):
    """No-show guard: only real human dialogue counts toward persisting a meeting."""

    def test_bot_lines_and_leave_command_are_not_substantive(self):
        transcript = "\n".join([
            "PrismAI: Hey, Glint here. I'll take notes.",
            "Glint: I'll send a debrief after.",
            "SRI KRISHNA ADITHYA K: /leave",
        ])
        # Only bot lines + a bare /leave -> zero human words -> no-show.
        self.assertLess(recall_routes._human_word_count(transcript), recall_routes._MIN_HUMAN_WORDS)

    def test_real_dialogue_is_substantive(self):
        transcript = "\n".join([
            "PrismAI: I'll take notes.",
            "Vidyut Sriram: Let's walk through the product roadmap and the planned changes for next quarter.",
            "SRI KRISHNA ADITHYA K: Sounds good, I have some thoughts on the image analysis feature.",
        ])
        self.assertGreaterEqual(recall_routes._human_word_count(transcript), recall_routes._MIN_HUMAN_WORDS)

    def test_empty_transcript_is_zero(self):
        self.assertEqual(recall_routes._human_word_count(""), 0)


class AnonymousSpeakerRecoveryTestCase(unittest.TestCase):
    """deepgram_async diarization emits numeric speaker IDs with no participant names;
    the two per-speaker agents (sentiment, speaker_coach) then analyse nameless speakers.
    These guard the detection + name-recovery logic."""

    def test_numeric_diarization_labels_are_anonymous(self):
        transcript = "\n".join([
            "500-1: So there's two important things.",
            "100-0: Fine. What's this meeting for?",
            "200-2: Hello.",
        ])
        self.assertTrue(recall_routes._speakers_anonymous(transcript))

    def test_speaker_word_form_is_anonymous(self):
        transcript = "speaker 0: hi\nspeaker 1: hey there"
        self.assertTrue(recall_routes._speakers_anonymous(transcript))

    def test_real_names_are_not_anonymous(self):
        transcript = "\n".join([
            "Vidyut Sriram: Let's spend the budget on screens.",
            "Ishaan Narang: Sounds good to me.",
            "Glow: I'll take notes.",
        ])
        self.assertFalse(recall_routes._speakers_anonymous(transcript))

    def test_mixed_below_threshold_not_anonymous(self):
        # One numeric line among real names stays under the 0.6 anon threshold.
        transcript = "\n".join([
            "Vidyut Sriram: hi",
            "Ishaan Narang: hey",
            "500-1: yeah",
        ])
        self.assertFalse(recall_routes._speakers_anonymous(transcript))

    def test_relabel_by_overlap_recovers_names(self):
        anon = [
            {"speaker": "500-1", "start": 0.0, "end": 5.0, "text": "budget talk"},
            {"speaker": "100-0", "start": 5.0, "end": 9.0, "text": "what's this for"},
        ]
        named = [
            {"speaker": "Vidyut Sriram", "start": 0.2, "end": 4.8, "text": "budget"},
            {"speaker": "Ishaan Narang", "start": 5.1, "end": 8.9, "text": "what for"},
        ]
        out = recall_routes._relabel_segments_by_overlap(anon, named)
        self.assertEqual(out[0]["speaker"], "Vidyut Sriram")
        self.assertEqual(out[1]["speaker"], "Ishaan Narang")
        # Text (async wording) is preserved — only the label changes.
        self.assertEqual(out[0]["text"], "budget talk")

    def test_relabel_keeps_label_when_no_overlap(self):
        anon = [{"speaker": "500-1", "start": 100.0, "end": 105.0, "text": "x"}]
        named = [{"speaker": "Vidyut Sriram", "start": 0.0, "end": 5.0, "text": "y"}]
        out = recall_routes._relabel_segments_by_overlap(anon, named)
        self.assertEqual(out[0]["speaker"], "500-1")


if __name__ == "__main__":
    unittest.main()

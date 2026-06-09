import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub_supabase():
    fake = types.ModuleType("supabase")
    fake.create_client = lambda *_a, **_k: None
    fake.Client = object
    sys.modules["supabase"] = fake


_stub_supabase()


class _FakeQuery:
    def __init__(self, data):
        self._data = data
    def select(self, *_a, **_k): return self
    def insert(self, *_a, **_k): return self
    def update(self, *_a, **_k): return self
    def delete(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def single(self): return self
    def execute(self): return MagicMock(data=self._data, count=len(self._data) if isinstance(self._data, list) else 0)


class _FakeSupabase:
    def __init__(self, tables: dict):
        self._tables = tables
        self.rpc_calls = []
    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))
    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeQuery(self._tables.get(f"rpc:{name}", []))


class KnowledgeServiceTests(unittest.TestCase):
    def test_search_knowledge_uses_rpc_with_embedding(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        user_id = uuid.uuid4()
        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": str(uuid.uuid4()), "doc_id": str(uuid.uuid4()),
             "doc_name": "Budget.pdf", "source_type": "pdf",
             "sensitivity": "internal", "content": "Q2 budget is $50k",
             "metadata": {}, "score": 0.91},
        ]})

        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what was the budget", str(user_id), meeting_id=None, hybrid=False
                ))

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["doc_name"], "Budget.pdf")
        self.assertEqual(fake_sb.rpc_calls[0][0], "knowledge_search")

    def test_search_returns_empty_below_min_score(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": []})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.0] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "unknown", str(uuid.uuid4()), hybrid=False
                ))
        self.assertEqual(matches, [])

    def test_conflict_detection_flags_top_two_close_scores(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)

        fake_sb = _FakeSupabase({"rpc:knowledge_search": [
            {"chunk_id": "c1", "doc_id": "d1", "doc_name": "Q1.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on enterprise", "metadata": {}, "score": 0.90},
            {"chunk_id": "c2", "doc_id": "d2", "doc_name": "Q2.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "Focus on SMB", "metadata": {}, "score": 0.88},
        ]})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb):
            with patch.object(knowledge_service, "embed_text",
                              new=AsyncMock(return_value=[0.1] * 1536)):
                matches = asyncio.run(knowledge_service.search_knowledge(
                    "what's the strategy", str(uuid.uuid4()), hybrid=False
                ))
        self.assertTrue(matches[0].get("possible_conflict"))

    def test_search_caps_transcript_results(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)

        rows = [
            {"chunk_id": "1", "doc_id": "d1", "doc_name": "Mtg A (2026-05-01)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.95},
            {"chunk_id": "2", "doc_id": "d2", "doc_name": "Mtg B (2026-05-02)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.94},
            {"chunk_id": "3", "doc_id": "d3", "doc_name": "Mtg C (2026-05-03)",
             "source_type": "meeting_transcript", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.93},
            {"chunk_id": "4", "doc_id": "d4", "doc_name": "Budget.pdf",
             "source_type": "pdf", "sensitivity": "internal",
             "content": "...", "metadata": {}, "score": 0.92},
        ]
        fake_sb = _FakeSupabase({"rpc:knowledge_search": rows})
        with patch.object(knowledge_service, "_supabase", lambda: fake_sb), \
             patch.object(knowledge_service, "embed_text",
                          new=AsyncMock(return_value=[0.1] * 1536)):
            matches = asyncio.run(knowledge_service.search_knowledge(
                "anything", str(uuid.uuid4()), k=5, hybrid=False
            ))

        # At most 2 meeting_transcript results, then PDFs fill remaining slots
        transcripts = [m for m in matches if m["source_type"] == "meeting_transcript"]
        self.assertLessEqual(len(transcripts), 2)
        self.assertEqual(matches[-1]["source_type"], "pdf")


class ExecuteRetryTests(unittest.TestCase):
    """Regression: a stale Supabase keep-alive socket surfaces as
    httpx.RemoteProtocolError ('Server disconnected') with no status_code.
    _execute must retry these transients instead of letting them bubble up and
    kill the whole knowledge_lookup / proactive search. See diagnose 2026-06-08."""

    def _module(self):
        import importlib, knowledge_service
        importlib.reload(knowledge_service)
        return knowledge_service

    def test_execute_retries_connection_drop_then_succeeds(self):
        ks = self._module()

        class RemoteProtocolError(Exception):
            pass

        attempts = {"n": 0}

        class _FlakyQuery:
            def execute(self_inner):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise RemoteProtocolError("Server disconnected without sending a response.")
                return MagicMock(data=[{"ok": True}])

        with patch.object(ks.asyncio, "sleep", new=AsyncMock()):
            res = asyncio.run(ks._execute(_FlakyQuery()))

        self.assertEqual(attempts["n"], 3)
        self.assertEqual(res.data, [{"ok": True}])

    def test_execute_does_not_retry_non_connection_errors(self):
        ks = self._module()

        attempts = {"n": 0}

        class _BadQuery:
            def execute(self_inner):
                attempts["n"] += 1
                raise ValueError("genuine bug, not a connection blip")

        with patch.object(ks.asyncio, "sleep", new=AsyncMock()):
            with self.assertRaises(ValueError):
                asyncio.run(ks._execute(_BadQuery()))

        self.assertEqual(attempts["n"], 1)  # no retry on non-transient errors


class _IngestQuery:
    """Records every (op, table) pair on a fake Supabase so tests can assert
    the full sequence ingest_doc executes (status update → select → quota
    check → batched inserts → final status). Captures the LAST update payload
    per table for status-transition assertions."""

    def __init__(self, recorder, table_name):
        self._rec = recorder
        self._table = table_name
        self._op = "select"  # default
        self._last_update_payload = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload, *_a, **_k):
        self._op = "insert"
        self._rec.calls.append(("insert", self._table, len(payload) if isinstance(payload, list) else 1))
        return self

    def update(self, payload, *_a, **_k):
        self._op = "update"
        self._last_update_payload = payload
        return self

    def delete(self, *_a, **_k):
        self._op = "delete"
        return self

    def eq(self, *_a, **_k): return self
    def single(self): return self

    def execute(self):
        if self._op == "update":
            self._rec.calls.append(("update", self._table, self._last_update_payload))
        elif self._op == "select":
            self._rec.calls.append(("select", self._table, None))
        elif self._op == "delete":
            self._rec.calls.append(("delete", self._table, None))
        # Hand back the canned row for select-by-id flows
        data = self._rec.tables.get(self._table)
        count = self._rec.tables.get(f"{self._table}_count", 0)
        return MagicMock(data=data, count=count)


class _IngestRecorder:
    def __init__(self):
        self.tables: dict = {}
        self.calls: list = []  # list of (op, table, payload-or-meta)

    def table(self, name):
        return _IngestQuery(self, name)


def _last_status(recorder, table="knowledge_docs"):
    """Return the most recent update payload pushed to `table`, or None."""
    for op, t, payload in reversed(recorder.calls):
        if op == "update" and t == table:
            return payload
    return None


class IngestDocTests(unittest.TestCase):
    """Locks in the happy path + 3 error paths after the asyncio.to_thread rewrite.

    What we're proving:
      1. happy: status transitions processing → ready, chunks inserted in batches
      2. unknown source_type: status → error with LoaderError message
      3. quota exceeded: status → error with QuotaExceeded message
      4. error-path DB failure: ingest_doc must NOT propagate (background task
         would otherwise leave the doc stuck in "processing" with a stack trace
         in stdout — every loophole the user asked us to close).
    """

    def _ingest_module(self):
        import importlib
        import knowledge_service
        importlib.reload(knowledge_service)
        return knowledge_service

    def test_happy_path_writes_chunks_and_flips_status_to_ready(self):
        ks = self._ingest_module()
        rec = _IngestRecorder()
        # select knowledge_docs returns the doc row with a user_id
        rec.tables["knowledge_docs"] = {"id": "doc-1", "user_id": "user-1", "workspace_id": None}
        # quota check returns count=0
        rec.tables["knowledge_chunks_count"] = 0

        fake_loaded = MagicMock(text="hello world. chunk two.", page_metadata=[{"source": "x.txt"}])
        fake_chunks = [
            {"content": "hello world.", "chunk_index": 0, "metadata": {}},
            {"content": "chunk two.", "chunk_index": 1, "metadata": {}},
        ]

        with patch.object(ks, "_supabase", lambda: rec), \
             patch.object(ks, "chunk_text", lambda *_a, **_k: fake_chunks), \
             patch.object(ks, "embed_batch", new=AsyncMock(return_value=[[0.0] * 1536, [0.0] * 1536])):
            # Stub the text loader to return our fake doc.
            text_loader_mod = types.ModuleType("knowledge_ingest.text_loader")
            text_loader_mod.load = AsyncMock(return_value=fake_loaded)
            with patch.dict(sys.modules, {"knowledge_ingest.text_loader": text_loader_mod}):
                asyncio.run(ks.ingest_doc("doc-1", b"hello world. chunk two.", "txt", {}))

        # Status transitions: at least one "processing" update, ending with "ready".
        statuses = [p.get("status") for op, t, p in rec.calls if op == "update" and t == "knowledge_docs"]
        self.assertEqual(statuses[0], "processing")
        self.assertEqual(statuses[-1], "ready")
        # Final update carries chunk_count
        final = _last_status(rec)
        self.assertEqual(final["chunk_count"], 2)
        # Insert happened on knowledge_chunks
        inserts = [c for c in rec.calls if c[0] == "insert" and c[1] == "knowledge_chunks"]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][2], 2)

    def test_unknown_source_type_marks_status_error(self):
        ks = self._ingest_module()
        rec = _IngestRecorder()
        rec.tables["knowledge_docs"] = {"id": "doc-1", "user_id": "user-1", "workspace_id": None}

        with patch.object(ks, "_supabase", lambda: rec):
            asyncio.run(ks.ingest_doc("doc-1", b"data", "unsupported_type", {}))

        final = _last_status(rec)
        self.assertEqual(final["status"], "error")
        self.assertIn("unsupported_type", final["error_message"])

    def test_quota_exceeded_marks_status_error(self):
        ks = self._ingest_module()
        rec = _IngestRecorder()
        rec.tables["knowledge_docs"] = {"id": "doc-1", "user_id": "user-1", "workspace_id": None}
        rec.tables["knowledge_chunks_count"] = ks.MAX_CHUNKS_PER_USER  # already at limit

        fake_loaded = MagicMock(text="x", page_metadata=[{}])
        fake_chunks = [{"content": "x", "chunk_index": 0, "metadata": {}}]

        with patch.object(ks, "_supabase", lambda: rec), \
             patch.object(ks, "chunk_text", lambda *_a, **_k: fake_chunks):
            text_loader_mod = types.ModuleType("knowledge_ingest.text_loader")
            text_loader_mod.load = AsyncMock(return_value=fake_loaded)
            with patch.dict(sys.modules, {"knowledge_ingest.text_loader": text_loader_mod}):
                asyncio.run(ks.ingest_doc("doc-1", b"x", "txt", {}))

        final = _last_status(rec)
        self.assertEqual(final["status"], "error")
        self.assertIn("Quota", final["error_message"])

    def test_error_path_db_failure_does_not_propagate(self):
        """If the doc is stuck in some state AND the DB is down when we try
        to write the error status, ingest_doc still completes silently —
        background tasks raising uncaught is the loophole we explicitly
        closed via _record_doc_error's inner try/except."""
        ks = self._ingest_module()

        class TotallyBrokenSupabase:
            def table(self, _name):
                raise RuntimeError("DB is down")

        # Should complete without raising despite every Supabase call failing.
        asyncio.run(ks.ingest_doc("doc-1", b"x", "unsupported_type", {}))  # uses _supabase()
        # Now wire the broken one and re-run — direct path
        with patch.object(ks, "_supabase", lambda: TotallyBrokenSupabase()):
            try:
                asyncio.run(ks.ingest_doc("doc-1", b"x", "unsupported_type", {}))
            except Exception as exc:
                self.fail(f"ingest_doc must swallow all errors but raised: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# soft_delete_doc — permission model (uploader OR workspace owner)
# ─────────────────────────────────────────────────────────────────────────────

class _DeleteFakeQuery:
    """Tiny query fake that tracks the operation chain (table, action, eq's)
    so tests can verify the deletes/updates actually fired. Supports
    .maybe_single() for the lookup queries soft_delete_doc uses."""
    def __init__(self, store):
        self._store = store
        self._eq = {}
        self._action = None   # 'select' | 'update' | 'delete'
        self._table_name = None
        self._select_cols = None
        self._update_payload = None
        self._maybe_single = False

    def _bind_table(self, name):
        self._table_name = name
        return self

    def select(self, *cols, **_k):
        self._action = "select"
        self._select_cols = cols
        return self
    def update(self, payload, **_k):
        self._action = "update"
        self._update_payload = payload
        return self
    def delete(self, **_k):
        self._action = "delete"
        return self
    def eq(self, k, v):
        self._eq[k] = v
        return self
    def is_(self, *_a, **_k):
        return self
    def maybe_single(self):
        self._maybe_single = True
        return self
    def single(self):
        return self

    def execute(self):
        # Record the operation so tests can introspect.
        self._store["ops"].append({
            "table": self._table_name, "action": self._action, "eq": dict(self._eq),
            "payload": self._update_payload, "single": self._maybe_single,
        })
        if self._action == "select":
            return self._lookup_select()
        # update / delete don't return interesting data here.
        return MagicMock(data=[], count=0)

    def _lookup_select(self):
        rows = self._store["tables"].get(self._table_name, [])
        for row in rows:
            if all(row.get(k) == v for k, v in self._eq.items()):
                return MagicMock(data=row if self._maybe_single else [row])
        return MagicMock(data=None if self._maybe_single else [])


class _DeleteFakeSupabase:
    def __init__(self, tables):
        self.store = {"tables": tables, "ops": []}
    def table(self, name):
        return _DeleteFakeQuery(self.store)._bind_table(name)


class SoftDeleteDocPermissionTests(unittest.TestCase):
    """Option A: uploader OR workspace owner can delete; otherwise 403."""

    def _make_fake(self, *, doc=None, members=None):
        tables = {}
        if doc is not None:
            tables["knowledge_docs"] = [doc]
        if members is not None:
            tables["workspace_members"] = members
        return _DeleteFakeSupabase(tables)

    def test_uploader_deletes_personal_doc(self):
        import knowledge_service
        fake = self._make_fake(doc={
            "id": "d1", "user_id": "alice", "workspace_id": None,
        })
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            asyncio.run(knowledge_service.soft_delete_doc("d1", "alice"))
        # Verify both writes fired: chunks DELETE + docs UPDATE
        write_actions = [(op["table"], op["action"]) for op in fake.store["ops"]
                         if op["action"] in ("delete", "update")]
        self.assertIn(("knowledge_chunks", "delete"), write_actions)
        self.assertIn(("knowledge_docs", "update"), write_actions)

    def test_uploader_deletes_own_workspace_doc(self):
        import knowledge_service
        fake = self._make_fake(doc={
            "id": "d2", "user_id": "alice", "workspace_id": "ws1",
        })
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            asyncio.run(knowledge_service.soft_delete_doc("d2", "alice"))
        write_actions = [(op["table"], op["action"]) for op in fake.store["ops"]
                         if op["action"] in ("delete", "update")]
        self.assertIn(("knowledge_docs", "update"), write_actions)

    def test_workspace_owner_can_delete_teammates_doc(self):
        # Alice uploaded; Bob is the workspace owner. Bob should be allowed.
        import knowledge_service
        fake = self._make_fake(
            doc={"id": "d3", "user_id": "alice", "workspace_id": "ws1"},
            members=[{"workspace_id": "ws1", "user_id": "bob", "role": "owner"}],
        )
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            asyncio.run(knowledge_service.soft_delete_doc("d3", "bob"))
        write_actions = [(op["table"], op["action"]) for op in fake.store["ops"]
                         if op["action"] in ("delete", "update")]
        self.assertIn(("knowledge_docs", "update"), write_actions)
        # Chunks filter must use the UPLOADER's id (alice), not the caller (bob).
        chunk_delete_op = next(op for op in fake.store["ops"]
                               if op["table"] == "knowledge_chunks" and op["action"] == "delete")
        self.assertEqual(chunk_delete_op["eq"].get("user_id"), "alice")

    def test_non_owner_member_cannot_delete_teammates_doc(self):
        # Alice uploaded; Carol is just a member (not owner) → 403.
        import knowledge_service
        fake = self._make_fake(
            doc={"id": "d4", "user_id": "alice", "workspace_id": "ws1"},
            members=[{"workspace_id": "ws1", "user_id": "carol", "role": "member"}],
        )
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            with self.assertRaises(knowledge_service.DeletePermissionDenied):
                asyncio.run(knowledge_service.soft_delete_doc("d4", "carol"))
        # And no writes happened.
        write_actions = [op["action"] for op in fake.store["ops"]
                         if op["action"] in ("delete", "update")]
        self.assertEqual(write_actions, [])

    def test_random_user_cannot_delete_someone_elses_personal_doc(self):
        # Doc has no workspace; only Alice (uploader) should be able to delete.
        import knowledge_service
        fake = self._make_fake(doc={
            "id": "d5", "user_id": "alice", "workspace_id": None,
        })
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            with self.assertRaises(knowledge_service.DeletePermissionDenied):
                asyncio.run(knowledge_service.soft_delete_doc("d5", "mallory"))

    def test_nonexistent_doc_raises_DocNotFound(self):
        import knowledge_service
        fake = self._make_fake(doc=None)  # knowledge_docs table empty
        with patch.object(knowledge_service, "_supabase", return_value=fake):
            with self.assertRaises(knowledge_service.DocNotFound):
                asyncio.run(knowledge_service.soft_delete_doc("does-not-exist", "alice"))


if __name__ == "__main__":
    unittest.main()

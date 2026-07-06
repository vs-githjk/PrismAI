import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import tools.jira as jira


class AdfRenderingTests(unittest.TestCase):
    def test_headings_and_bullets(self):
        adf = jira._to_adf("Context:\nWhy this exists\nAcceptance Criteria:\n- done when x\n- and y")
        types = [c["type"] for c in adf["content"]]
        self.assertIn("bulletList", types)
        # A short line ending in ':' is a bold heading.
        bolded = [c["content"][0]["text"] for c in adf["content"]
                  if c["content"] and c["content"][0].get("marks")]
        self.assertIn("Context:", bolded)
        self.assertIn("Acceptance Criteria:", bolded)

    def test_empty_description_safe(self):
        adf = jira._to_adf("")
        self.assertEqual(adf["content"], [{"type": "paragraph", "content": []}])


class _Resp:
    status_code = 201
    def json(self): return {"key": "ABC-1"}
    text = ""


class _FakeClient:
    def __init__(self): self.captured = None
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, headers=None, json=None, timeout=None):
        self.captured = json
        return _Resp()


class CreateIssueTests(unittest.TestCase):
    settings = {"jira_base_url": "https://x.atlassian.net", "jira_email": "e@x.com",
                "jira_api_token": "t", "jira_project_key": "ABC"}

    def test_prism_prefix_and_label_applied(self):
        fake = _FakeClient()
        with patch.object(jira.httpx, "AsyncClient", return_value=fake):
            out = asyncio.run(jira.jira_create_issue({"title": "Fix the thing", "description": "Details:\n- a"}, self.settings))
        self.assertTrue(out["success"])
        fields = fake.captured["fields"]
        self.assertTrue(fields["summary"].startswith("[Prism] "))
        self.assertIn("prism", fields["labels"])
        # provenance footer present in description text
        flat = str(fields["description"])
        self.assertIn("Created by PrismAI", flat)

    def test_prefix_not_doubled(self):
        fake = _FakeClient()
        with patch.object(jira.httpx, "AsyncClient", return_value=fake):
            asyncio.run(jira.jira_create_issue({"title": "[Prism] Already tagged"}, self.settings))
        self.assertEqual(fake.captured["fields"]["summary"].count("[Prism]"), 1)


if __name__ == "__main__":
    unittest.main()

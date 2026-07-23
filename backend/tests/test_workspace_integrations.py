"""Per-workspace integrations resolver (#2) — overlay + routing gates."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import workspace_integrations as wi


PERSONAL = {
    "jira_base_url": "https://me.atlassian.net",
    "jira_email": "me@personal.com",
    "jira_api_token": "personal-jira",
    "jira_project_key": "MINE",
    "linear_api_key": "personal-linear",
    "google_access_token": "personal-google",   # OAuth — must never be overlaid
    "persona_preset": "warm",
}


class OverlayTests(unittest.TestCase):
    def test_complete_workspace_jira_overrides_personal(self):
        ws = {"jira": {"jira_base_url": "https://acme.atlassian.net", "jira_email": "team@acme.com",
                       "jira_api_token": "acme-jira", "jira_project_key": "ACME"}}
        out = wi.apply_workspace_overlay(PERSONAL, ws)
        self.assertEqual(out["jira_base_url"], "https://acme.atlassian.net")
        self.assertEqual(out["jira_api_token"], "acme-jira")
        self.assertEqual(out["jira_project_key"], "ACME")

    def test_incomplete_workspace_jira_falls_back_to_personal(self):
        # Missing token → not usable → personal Jira stays intact (no field-mixing).
        ws = {"jira": {"jira_base_url": "https://acme.atlassian.net", "jira_email": "team@acme.com"}}
        out = wi.apply_workspace_overlay(PERSONAL, ws)
        self.assertEqual(out["jira_api_token"], "personal-jira")
        self.assertEqual(out["jira_base_url"], "https://me.atlassian.net")

    def test_optional_absent_in_workspace_is_cleared(self):
        # Workspace Jira complete but no project key → personal MINE must NOT leak through.
        ws = {"jira": {"jira_base_url": "https://acme.atlassian.net", "jira_email": "team@acme.com",
                       "jira_api_token": "acme-jira"}}
        out = wi.apply_workspace_overlay(PERSONAL, ws)
        self.assertEqual(out["jira_api_token"], "acme-jira")
        self.assertIsNone(out["jira_project_key"])   # cleared — true all-or-nothing

    def test_oauth_never_overlaid(self):
        ws = {"jira": {"jira_base_url": "https://acme.atlassian.net", "jira_email": "team@acme.com",
                       "jira_api_token": "acme-jira"}}
        out = wi.apply_workspace_overlay(PERSONAL, ws)
        self.assertEqual(out["google_access_token"], "personal-google")
        self.assertEqual(out["persona_preset"], "warm")   # non-integration fields untouched

    def test_linear_and_multi_provider(self):
        ws = {"linear": {"linear_api_key": "acme-linear"},
              "slack": {"slack_bot_token": "xoxb-acme"}}
        out = wi.apply_workspace_overlay(PERSONAL, ws)
        self.assertEqual(out["linear_api_key"], "acme-linear")
        self.assertEqual(out["slack_bot_token"], "xoxb-acme")
        self.assertEqual(out["jira_api_token"], "personal-jira")   # jira not in ws → personal

    def test_empty_workspace_is_noop(self):
        self.assertEqual(wi.apply_workspace_overlay(PERSONAL, {}), PERSONAL)


class ResolveGateTests(unittest.TestCase):
    def test_no_workspace_returns_personal(self):
        out = asyncio.run(wi.resolve_tool_settings(PERSONAL, "u1", None))
        self.assertEqual(out, PERSONAL)

    def test_flag_off_returns_personal(self):
        with patch.dict("os.environ", {"PRISM_WORKSPACE_INTEGRATIONS": "0"}):
            out = asyncio.run(wi.resolve_tool_settings(PERSONAL, "u1", "ws1"))
        self.assertEqual(out, PERSONAL)

    def test_non_member_returns_personal(self):
        with patch.object(wi, "_is_member", return_value=False), \
             patch.object(wi, "_load_workspace_integrations", return_value={"jira": {"jira_base_url": "x", "jira_email": "y", "jira_api_token": "z"}}):
            out = asyncio.run(wi.resolve_tool_settings(PERSONAL, "u1", "ws1"))
        self.assertEqual(out["jira_api_token"], "personal-jira")   # not overlaid

    def test_member_with_config_overlays(self):
        ws = {"jira": {"jira_base_url": "https://acme.atlassian.net", "jira_email": "team@acme.com", "jira_api_token": "acme-jira"}}
        with patch.object(wi, "_is_member", return_value=True), \
             patch.object(wi, "_load_workspace_integrations", return_value=ws):
            out = asyncio.run(wi.resolve_tool_settings(PERSONAL, "u1", "ws1"))
        self.assertEqual(out["jira_api_token"], "acme-jira")

    def test_member_no_rows_returns_personal(self):
        with patch.object(wi, "_is_member", return_value=True), \
             patch.object(wi, "_load_workspace_integrations", return_value={}):
            out = asyncio.run(wi.resolve_tool_settings(PERSONAL, "u1", "ws1"))
        self.assertEqual(out, PERSONAL)


if __name__ == "__main__":
    unittest.main()

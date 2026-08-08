"""_is_auth_failure — which tool errors block a capability, and which get retried.

Regression guard for a silent-failure class: status codes used to be matched as the
substrings " 401"/" 403" (leading space), which miss the common `failed (401)` spelling
because the preceding character is a paren. web_search returns exactly that, so a bad
Tavily key was never recognised as an auth failure: no capability block, no terse
"not connected" reply, no log line — the tool just failed into the void on every ask.

The two directions matter equally. A miss is invisible breakage; a false positive blocks
a working integration for the rest of the meeting on a transient error.
"""

import unittest

import realtime_routes as rr


class AuthFailureMatchTests(unittest.TestCase):

    def test_matches_paren_wrapped_status_codes(self):
        """The exact strings tools/web_search.py produces."""
        self.assertTrue(rr._is_auth_failure({"error": "Web search failed (401)"}))
        self.assertTrue(rr._is_auth_failure({"error": "Web search failed (403)"}))

    def test_matches_bare_and_spaced_status_codes(self):
        self.assertTrue(rr._is_auth_failure({"error": "Request failed 401"}))
        self.assertTrue(rr._is_auth_failure({"error": "403 Forbidden"}))

    def test_matches_unconfigured_tool(self):
        self.assertTrue(rr._is_auth_failure(
            {"error": "Web search is not configured (TAVILY_API_KEY missing)"}))

    def test_matches_existing_phrasings(self):
        for err in ("Google Calendar not connected", "invalid_grant",
                    "Token expired", "insufficient permission", "Unauthorized"):
            with self.subTest(err=err):
                self.assertTrue(rr._is_auth_failure({"error": err}))

    def test_transient_failures_are_retried_not_blocked(self):
        """5xx and rate limits must NOT block — the integration is fine, the call wasn't."""
        for err in ("Web search failed (500)", "Web search failed (429)",
                    "Service Unavailable (503)"):
            with self.subTest(err=err):
                self.assertFalse(rr._is_auth_failure({"error": err}))

    def test_embedded_digits_do_not_fire(self):
        """Word boundaries, so an id containing 401 isn't read as an auth failure."""
        self.assertFalse(rr._is_auth_failure({"error": "order 1401 not found"}))
        self.assertFalse(rr._is_auth_failure({"error": "code 4013 invalid"}))

    def test_non_errors(self):
        self.assertFalse(rr._is_auth_failure({"no_results": True}))
        self.assertFalse(rr._is_auth_failure({"error": ""}))
        self.assertFalse(rr._is_auth_failure({}))
        self.assertFalse(rr._is_auth_failure("not a dict"))


if __name__ == "__main__":
    unittest.main()

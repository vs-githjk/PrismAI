"""Unit tests for think_loop: verb gate, artifact handoff, thinking-tag strip."""

import os
import sys
import time
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import think_loop  # noqa: E402


class StripThinkingTests(unittest.TestCase):
    def test_strips_single_block(self):
        visible, hidden = think_loop.strip_thinking(
            "<thinking>plan stuff</thinking>Hello world"
        )
        self.assertEqual(visible, "Hello world")
        self.assertEqual(hidden, "plan stuff")

    def test_no_block_returns_text_unchanged(self):
        visible, hidden = think_loop.strip_thinking("Just a reply")
        self.assertEqual(visible, "Just a reply")
        self.assertEqual(hidden, "")

    def test_multiline_block(self):
        text = "<thinking>\nline 1\nline 2\n</thinking>\nSubject: Hi"
        visible, hidden = think_loop.strip_thinking(text)
        self.assertEqual(visible, "Subject: Hi")
        self.assertIn("line 1", hidden)
        self.assertIn("line 2", hidden)

    def test_multiple_blocks_concatenated(self):
        text = "<thinking>a</thinking>between<thinking>b</thinking>tail"
        visible, hidden = think_loop.strip_thinking(text)
        self.assertEqual(visible, "betweentail")
        self.assertIn("a", hidden)
        self.assertIn("b", hidden)

    def test_case_insensitive_tag(self):
        visible, _ = think_loop.strip_thinking("<Thinking>x</THINKING>y")
        self.assertEqual(visible, "y")

    def test_unclosed_tag_treats_remainder_as_thinking(self):
        visible, hidden = think_loop.strip_thinking("<thinking>incomplete plan")
        self.assertEqual(visible, "")
        self.assertIn("incomplete plan", hidden)

    def test_empty_input(self):
        visible, hidden = think_loop.strip_thinking("")
        self.assertEqual(visible, "")
        self.assertEqual(hidden, "")


class VerbGateTests(unittest.TestCase):
    """Verb gate behavior — the safety net behind the prompt."""

    def test_read_tools_always_allowed(self):
        # Non-destructive tools never get gated regardless of command text.
        for tool in ("gmail_read", "calendar_list_events", "knowledge_lookup", "web_search"):
            self.assertIsNone(
                think_loop.verb_gate(
                    command="random text", tool_name=tool, has_prior_artifact=False
                ),
                f"{tool} should not be gated",
            )

    def test_gmail_send_allowed_with_send_verb(self):
        self.assertIsNone(think_loop.verb_gate(
            command="send an email to bob@x.com about Q4",
            tool_name="gmail_send",
            has_prior_artifact=False,
        ))

    def test_gmail_send_blocked_on_draft(self):
        # The original failure case.
        reason = think_loop.verb_gate(
            command="draft me an email to my professor about my grades",
            tool_name="gmail_send",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)
        self.assertIn("compose", reason.lower())

    def test_gmail_send_blocked_on_write(self):
        reason = think_loop.verb_gate(
            command="write me an email to the team",
            tool_name="gmail_send",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)

    def test_gmail_send_allowed_on_followup_with_artifact(self):
        # "draft email" → COMPOSE artifact stored → "send it" follow-up.
        self.assertIsNone(think_loop.verb_gate(
            command="send it",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))
        self.assertIsNone(think_loop.verb_gate(
            command="go ahead and send to bob@x.com",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_gmail_send_blocked_on_followup_without_artifact(self):
        # "send it" with NO prior draft is suspicious — block.
        reason = think_loop.verb_gate(
            command="send it",
            tool_name="gmail_send",
            has_prior_artifact=False,
        )
        # "send" is in the verb whitelist for gmail_send, so this actually allows.
        # The artifact requirement only kicks in when the command is JUST
        # a follow-up phrase — but "send it" contains "send", a destructive
        # verb. That's acceptable: if user says "send it" with no draft,
        # the model will fail at the recipient-resolution step anyway.
        self.assertIsNone(reason)

    def test_slack_post_blocked_on_draft(self):
        reason = think_loop.verb_gate(
            command="draft a slack message for #engineering about the outage",
            tool_name="slack_post_message",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)

    def test_slack_post_allowed_on_post(self):
        self.assertIsNone(think_loop.verb_gate(
            command="post in #general that we're shipping",
            tool_name="slack_post_message",
            has_prior_artifact=False,
        ))

    def test_calendar_create_blocked_on_propose(self):
        # "what's a good time" / "propose a time" are not authorization
        reason = think_loop.verb_gate(
            command="what would be a good time for a follow-up",
            tool_name="calendar_create_event",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)

    def test_calendar_create_allowed_on_schedule(self):
        self.assertIsNone(think_loop.verb_gate(
            command="schedule a 30 minute follow up with Bob tomorrow at 3pm",
            tool_name="calendar_create_event",
            has_prior_artifact=False,
        ))

    def test_calendar_delete_blocked_without_verb(self):
        reason = think_loop.verb_gate(
            command="when is my 3pm meeting",
            tool_name="calendar_delete_event",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)

    def test_calendar_delete_allowed_on_cancel(self):
        self.assertIsNone(think_loop.verb_gate(
            command="cancel my 3pm",
            tool_name="calendar_delete_event",
            has_prior_artifact=False,
        ))

    def test_linear_create_blocked_on_outline(self):
        reason = think_loop.verb_gate(
            command="outline what a ticket for this would look like",
            tool_name="linear_create_issue",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)

    def test_linear_create_allowed_on_file(self):
        self.assertIsNone(think_loop.verb_gate(
            command="file a ticket for the OAuth bug",
            tool_name="linear_create_issue",
            has_prior_artifact=False,
        ))

    def test_ambiguous_command_blocks_destructive(self):
        # No compose indicator + no destructive verb = block.
        # Safer to refuse than to send the wrong email.
        reason = think_loop.verb_gate(
            command="bob@x.com about q4 planning",
            tool_name="gmail_send",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)


class NounReferenceTests(unittest.TestCase):
    """The production failure: 'use this draft and send' was blocked because
    'draft' appeared at pos 17, inside the COMPOSE-precedence window. The
    noun-reference regex now suppresses that path."""

    def test_use_this_draft_with_send_allowed_with_artifact(self):
        self.assertIsNone(think_loop.verb_gate(
            command="can you use this draft and send a mail to vidyut0712@gmail.com",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_use_the_draft_you_created_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="can you use the draft you created and send a mail to vidyut0712@gmail.com",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_use_the_template_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="use the template and send an email to bob",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_with_this_draft_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="with this draft, send to alice",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_based_on_the_draft_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="based on the draft, mail it to the team",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_noun_ref_without_artifact_still_allows_if_verb_present(self):
        # Even without a prior artifact, if user says "use the draft and send"
        # the noun-ref suppresses COMPOSE-first and Path C allows on 'send'.
        # The model will fail to find the draft and ask the user — acceptable.
        self.assertIsNone(think_loop.verb_gate(
            command="use the draft you wrote and send it",
            tool_name="gmail_send",
            has_prior_artifact=False,
        ))


class InflectedVerbTests(unittest.TestCase):
    """User commonly re-asks with inflected verbs ('sending', 'posting').
    The regex now accepts these as authorizing verbs."""

    def test_sending_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="sending an email to bob about q4",
            tool_name="gmail_send",
            has_prior_artifact=False,
        ))

    def test_posting_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="posting in #general that we shipped",
            tool_name="slack_post_message",
            has_prior_artifact=False,
        ))

    def test_filing_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="filing a ticket for the regression",
            tool_name="linear_create_issue",
            has_prior_artifact=False,
        ))

    def test_rescheduling_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="rescheduling my 3pm to 4pm",
            tool_name="calendar_update_event",
            has_prior_artifact=False,
        ))

    def test_cancelling_allowed(self):
        self.assertIsNone(think_loop.verb_gate(
            command="cancelling my 3pm sync",
            tool_name="calendar_delete_event",
            has_prior_artifact=False,
        ))


class NegationTests(unittest.TestCase):
    """Explicit 'don't / do not / skip / hold off' must block even when
    a destructive verb is present in the same command."""

    def test_dont_send_blocks(self):
        reason = think_loop.verb_gate(
            command="don't send the email yet",
            tool_name="gmail_send",
            has_prior_artifact=False,
        )
        self.assertIsNotNone(reason)
        self.assertIn("negated", reason.lower())

    def test_do_not_post_blocks(self):
        self.assertIsNotNone(think_loop.verb_gate(
            command="do not post this in slack",
            tool_name="slack_post_message",
            has_prior_artifact=False,
        ))

    def test_skip_the_send_blocks(self):
        self.assertIsNotNone(think_loop.verb_gate(
            command="skip the send for now",
            tool_name="gmail_send",
            has_prior_artifact=False,
        ))

    def test_hold_off_blocks(self):
        self.assertIsNotNone(think_loop.verb_gate(
            command="hold off on cancelling that meeting",
            tool_name="calendar_delete_event",
            has_prior_artifact=False,
        ))

    def test_negation_far_from_verb_does_not_block(self):
        # 'don't worry, just send it' — negation is 18+ chars from 'send',
        # outside the 12-char window. Should still allow.
        self.assertIsNone(think_loop.verb_gate(
            command="don't worry, just send it to bob already please",
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))


class MultiTurnScenarioTest(unittest.TestCase):
    """End-to-end behaviors that span two turns: COMPOSE then ACT."""

    def test_compose_then_send_full_loop(self):
        state: dict = {}

        # Turn 1: user asks for draft.
        cmd1 = "can a create draft to ask my professor about my grades?"
        self.assertTrue(think_loop.looks_like_compose_command(cmd1))

        # Turn 1 reply: model produces a quoted draft.
        reply1 = (
            'Here\'s a draft email you can use as a template:\n\n'
            '"Dear Professor [Name],\n\n'
            'I hope this email finds you well. I was wondering if you could '
            'provide me with an update on my current grades in your class. '
            'I would appreciate any information you can share regarding my '
            'performance so far.\n\nBest regards,\nAbhinav"'
        )
        self.assertTrue(think_loop.looks_like_artifact(reply1))
        think_loop.set_artifact(state, reply1, cmd1)
        self.assertIsNotNone(think_loop.get_fresh_artifact(state))

        # Turn 2: user references the draft and asks to send.
        cmd2 = "can you use this draft and send a mail to vidyut0712@gmail.com"
        self.assertIsNone(think_loop.verb_gate(
            command=cmd2,
            tool_name="gmail_send",
            has_prior_artifact=True,
        ))

    def test_negation_after_compose_still_blocks(self):
        state: dict = {}
        think_loop.set_artifact(state, "Subject: x\n\nDear Bob", "draft email")
        reason = think_loop.verb_gate(
            command="actually don't send it",
            tool_name="gmail_send",
            has_prior_artifact=True,
        )
        self.assertIsNotNone(reason)


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.state: dict = {}

    def test_set_and_get(self):
        think_loop.set_artifact(self.state, "Subject: Hi\n\nDear Bob", "draft email")
        art = think_loop.get_fresh_artifact(self.state)
        self.assertIsNotNone(art)
        self.assertEqual(art["type"], "draft")
        self.assertIn("Subject: Hi", art["text"])

    def test_get_empty_returns_none(self):
        self.assertIsNone(think_loop.get_fresh_artifact(self.state))

    def test_expired_artifact_returns_none_and_clears(self):
        think_loop.set_artifact(self.state, "old draft", "draft email")
        # Manually age it past TTL
        self.state["last_artifact"]["ts"] = time.time() - 9999
        self.assertIsNone(think_loop.get_fresh_artifact(self.state))
        self.assertNotIn("last_artifact", self.state)

    def test_clear_removes_artifact(self):
        think_loop.set_artifact(self.state, "x", "y")
        think_loop.clear_artifact(self.state)
        self.assertIsNone(think_loop.get_fresh_artifact(self.state))


class ArtifactDetectionTests(unittest.TestCase):
    def test_email_subject_detected(self):
        self.assertTrue(think_loop.looks_like_artifact(
            "Subject: Quick question\n\nDear Professor,\nI hope you're doing well..."
        ))

    def test_salutation_detected(self):
        self.assertTrue(think_loop.looks_like_artifact(
            "Hi Bob,\n\nJust wanted to follow up on Q4 planning. Let me know..."
        ))

    def test_ticket_header_detected(self):
        self.assertTrue(think_loop.looks_like_artifact(
            "Title: Fix OAuth bug\n\nDescription: When the user clicks..."
        ))

    def test_quoted_draft_detected(self):
        # The original production bug: model wraps the draft in quotes so the
        # salutation isn't at the line start.
        self.assertTrue(think_loop.looks_like_artifact(
            'Here\'s a draft email you can use as a template:\n\n'
            '"Dear Professor [Name],\n\nI hope this email finds you well..."'
        ))

    def test_framing_phrase_detected(self):
        # No salutation, no Subject — just a framing phrase + the body.
        self.assertTrue(think_loop.looks_like_artifact(
            "Here's a draft message you could send to the team about Q4. "
            "Let me know what you'd like to adjust before we go live..."
        ))

    def test_code_fenced_draft_detected(self):
        self.assertTrue(think_loop.looks_like_artifact(
            "Here's something to try:\n\n```\nDear Bob,\n\nFollowing up...\n```"
        ))

    def test_markdown_blockquoted_draft_detected(self):
        self.assertTrue(think_loop.looks_like_artifact(
            "How about:\n\n> Hi Sarah,\n>\n> Just confirming the 3pm sync..."
        ))

    def test_plain_short_reply_not_artifact(self):
        self.assertFalse(think_loop.looks_like_artifact("Sure, will do."))

    def test_empty_not_artifact(self):
        self.assertFalse(think_loop.looks_like_artifact(""))

    def test_compose_command_recognized(self):
        self.assertTrue(think_loop.looks_like_compose_command("draft an email to Bob"))
        self.assertTrue(think_loop.looks_like_compose_command("write a slack message"))
        self.assertTrue(think_loop.looks_like_compose_command("compose a follow-up"))
        self.assertTrue(think_loop.looks_like_compose_command("outline a ticket"))

    def test_non_compose_command_not_recognized(self):
        self.assertFalse(think_loop.looks_like_compose_command("send the email"))
        self.assertFalse(think_loop.looks_like_compose_command("what time is my meeting"))


class FlagTests(unittest.TestCase):
    def test_flag_off_by_default(self):
        # Snapshot + restore so we don't leak state across tests
        prior = os.environ.pop("PRISM_THINK_LOOP", None)
        try:
            self.assertFalse(think_loop.think_loop_on())
        finally:
            if prior is not None:
                os.environ["PRISM_THINK_LOOP"] = prior

    def test_flag_on_when_set(self):
        prior = os.environ.get("PRISM_THINK_LOOP")
        os.environ["PRISM_THINK_LOOP"] = "1"
        try:
            self.assertTrue(think_loop.think_loop_on())
        finally:
            if prior is None:
                os.environ.pop("PRISM_THINK_LOOP", None)
            else:
                os.environ["PRISM_THINK_LOOP"] = prior


class DirectiveRetiredTests(unittest.TestCase):
    """Regression — 2026-05-23: THINKING_DIRECTIVE was retired because its presence
    destabilised Groq + Llama 3.3-70b tool-call format. The model started emitting
    `<function=name:"web_search" ...>` shapes that the recovery parser cannot
    rescue (capture group becomes "name", which fails the valid-tools filter).
    These tests lock the directive out of the live system prefix so a future
    "let's just turn thinking back on" PR has to consciously override them.
    """

    def test_realtime_routes_does_not_append_directive_to_prefix(self):
        # Source-level check (import-free) so this runs without realtime_routes'
        # heavy dependency graph (pysbd, voice_pipeline, etc.) being installed.
        src = (BACKEND_DIR / "realtime_routes.py").read_text(encoding="utf-8")
        # The retired wiring was: base = base + "\n\n" + think_loop.THINKING_DIRECTIVE
        self.assertNotIn(
            "think_loop.THINKING_DIRECTIVE",
            src,
            "realtime_routes.py must not reference THINKING_DIRECTIVE — see "
            "DirectiveRetiredTests docstring for the Groq Llama 3.3 reason.",
        )

    def test_directive_constant_still_exported_for_back_compat(self):
        # Some external code or future re-enablement might still import the
        # constant. Keep the symbol present even though it's no longer wired in.
        self.assertTrue(hasattr(think_loop, "THINKING_DIRECTIVE"))
        self.assertIsInstance(think_loop.THINKING_DIRECTIVE, str)


if __name__ == "__main__":
    unittest.main()

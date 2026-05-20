import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from voice_pipeline import StreamingSegmenter, TtsDispatcher


def _segment_full_text(text: str) -> list[str]:
    """Helper: feed the entire text in one call, then flush, returning every
    emitted sentence. Used by the fixture tests to assert sentence count."""
    seg = StreamingSegmenter()
    out = list(seg.feed(text))
    out.extend(seg.flush())
    return out


class SegmenterFixtureTests(unittest.TestCase):
    """Gating fixtures from the PR-3 spec. If any of these regress, the
    segmenter is not safe to put in front of TTS."""

    def test_abbreviation_decimal_and_url_stay_single(self):
        sentences = _segment_full_text(
            "Dr. Smith said the cost is $3.14 to read example.com/path.html."
        )
        self.assertEqual(len(sentences), 1)

    def test_em_dash_stays_single(self):
        sentences = _segment_full_text("Sure — let me know who to send it to.")
        self.assertEqual(len(sentences), 1)

    def test_three_periods_three_sentences(self):
        sentences = _segment_full_text("Yes. The weather is sunny. It's 26°C.")
        self.assertEqual(len(sentences), 3)

    def test_url_with_em_dash_stays_single(self):
        sentences = _segment_full_text(
            "Visit https://example.com/foo.html — it's a great resource."
        )
        self.assertEqual(len(sentences), 1)


class SegmenterStreamingTests(unittest.TestCase):
    def test_last_sentence_held_until_successor_arrives(self):
        # Feeds token-by-token and verifies:
        #   - ordered emission
        #   - the *most recent* sentence is held by feed() (it may still grow)
        #   - flush() releases the held sentence
        seg = StreamingSegmenter()
        emitted = []
        for tok in ["Hello. ", "World ", "is ", "great. ", "Bye."]:
            emitted.extend(seg.feed(tok))
        # "Bye." has not been emitted yet — it's the last sentence and is held.
        self.assertEqual(len(emitted), 2)
        self.assertEqual(emitted[0], "Hello.")
        self.assertEqual(emitted[1], "World is great.")
        # flush() releases the tail.
        tail = seg.flush()
        self.assertEqual(tail, ["Bye."])

    def test_flush_is_idempotent(self):
        seg = StreamingSegmenter()
        seg.feed("Hello. World.")
        first = seg.flush()
        self.assertGreaterEqual(len(first), 1)
        second = seg.flush()
        self.assertEqual(second, [])

    def test_empty_feed_returns_empty(self):
        seg = StreamingSegmenter()
        self.assertEqual(seg.feed(""), [])

    def test_single_unterminated_sentence_only_emits_on_flush(self):
        seg = StreamingSegmenter()
        out = seg.feed("This sentence has no period yet")
        self.assertEqual(out, [])
        tail = seg.flush()
        self.assertEqual(len(tail), 1)


class DispatcherTests(unittest.TestCase):
    def test_buffers_until_min_chars_reached(self):
        d = TtsDispatcher(min_chars=25)
        self.assertEqual(d.push("Hi."), [])         # 3 chars
        self.assertEqual(d.push("How are you?"), []) # buffered: "Hi. How are you?" (16 chars)
        out = d.push("I'm doing well today!")        # crosses threshold
        self.assertEqual(len(out), 1)
        self.assertIn("Hi.", out[0])
        self.assertIn("How are you?", out[0])
        self.assertIn("I'm doing well today!", out[0])

    def test_long_sentence_dispatched_immediately(self):
        d = TtsDispatcher(min_chars=25)
        long_one = "This is a sentence that is comfortably longer than the minimum."
        out = d.push(long_one)
        self.assertEqual(out, [long_one])

    def test_flush_emits_residual_below_threshold(self):
        d = TtsDispatcher(min_chars=25)
        d.push("Hi.")
        d.push("Bye.")
        out = d.flush()
        self.assertEqual(out, ["Hi. Bye."])
        # Second flush is idempotent.
        self.assertEqual(d.flush(), [])

    def test_flush_when_empty_returns_empty(self):
        d = TtsDispatcher(min_chars=25)
        self.assertEqual(d.flush(), [])

    def test_uniform_policy_applies_to_opener(self):
        # The very first sentence must also clear min_chars before dispatch.
        # No "opener escapes early" exception in PR-3. (Held in reserve for PR-4.)
        d = TtsDispatcher(min_chars=25)
        self.assertEqual(d.push("Hello."), [])  # 6 chars — would slip through if opener was special
        self.assertNotEqual(d.flush(), [])      # but flush at end-of-reply emits it


if __name__ == "__main__":
    unittest.main()

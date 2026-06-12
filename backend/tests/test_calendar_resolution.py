import sys
import unittest
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from calendar_resolution import resolve_relative_date


class CalendarResolutionTestCase(unittest.TestCase):
    def test_resolves_this_weekday(self):
        result = resolve_relative_date("this Friday", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-10")
        self.assertEqual(result["resolved_day"], "Friday")

    def test_resolves_in_two_weeks(self):
        result = resolve_relative_date("in 2 weeks", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-20")
        self.assertEqual(result["resolved_day"], "Monday")

    def test_resolves_explicit_month_day(self):
        result = resolve_relative_date("week of March 15th", reference_date=date(2026, 3, 1))
        self.assertEqual(result["resolved_date"], "2026-03-15")
        self.assertEqual(result["resolved_day"], "Sunday")

    def test_returns_empty_when_unresolved(self):
        result = resolve_relative_date("sometime soon", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "")
        self.assertEqual(result["resolved_day"], "")

    # ── New behavior: time-of-day + more phrasings (all hand-rolled, no dateparser) ──
    def test_parses_clock_time_with_weekday(self):
        # Apr 6 2026 is a Monday → "next Tuesday" is the coming Tuesday (Apr 7).
        result = resolve_relative_date("next Tuesday at 3pm", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-07")
        self.assertEqual(result["resolved_time"], "15:00")

    def test_parses_named_time_of_day(self):
        result = resolve_relative_date("this Friday morning", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-10")
        self.assertEqual(result["resolved_time"], "09:00")

    def test_end_of_week(self):
        result = resolve_relative_date("end of the week", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-10")  # upcoming Friday

    def test_end_of_month(self):
        result = resolve_relative_date("by end of the month", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-04-30")

    def test_numeric_date(self):
        result = resolve_relative_date("let's meet 6/15", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_date"], "2026-06-15")

    def test_no_time_returns_empty_time(self):
        result = resolve_relative_date("next week", reference_date=date(2026, 4, 6))
        self.assertEqual(result["resolved_time"], "")

    def test_next_weekday_is_the_coming_one(self):
        # On Thursday Jun 11, "next Monday" is the COMING Monday (Jun 15), not Jun 22.
        result = resolve_relative_date("next Monday", reference_date=date(2026, 6, 11))
        self.assertEqual(result["resolved_date"], "2026-06-15")

    def test_next_weekday_rolls_when_today_is_that_day(self):
        # Saying "next Monday" ON a Monday means next week's Monday.
        result = resolve_relative_date("next Monday", reference_date=date(2026, 6, 15))
        self.assertEqual(result["resolved_date"], "2026-06-22")


if __name__ == "__main__":
    unittest.main()

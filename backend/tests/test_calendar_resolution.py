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


if __name__ == "__main__":
    unittest.main()

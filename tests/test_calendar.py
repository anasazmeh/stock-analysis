import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.events import calendar_status


class MacroCalendarTests(unittest.TestCase):
    def test_dates_valid_sorted_and_on_the_right_weekday(self):
        dates = [e["date"] for e in config.MACRO_EVENTS]
        self.assertEqual(dates, sorted(dates))
        for e in config.MACRO_EVENTS:
            d = date.fromisoformat(e["date"])
            if e["name"].startswith("FOMC"):
                self.assertEqual(d.weekday(), 2, e)    # Fed statement: second meeting day, a Wednesday
            if e["name"].startswith("ECB"):
                self.assertEqual(d.weekday(), 3, e)    # ECB decision: Thursday

    def test_covers_2027(self):
        self.assertEqual(sum(e["name"].startswith("FOMC") and e["date"].startswith("2027") for e in config.MACRO_EVENTS), 8)
        self.assertEqual(sum(e["name"].startswith("ECB") and e["date"].startswith("2027") for e in config.MACRO_EVENTS), 8)

    def test_expiry_warning(self):
        self.assertEqual(calendar_status(date(2026, 10, 5))[0], "ok")
        self.assertEqual(calendar_status(date(2027, 10, 1))[0], "partial")
        self.assertEqual(calendar_status(date(2028, 1, 1))[0], "failed")
        with mock.patch.object(config, "MACRO_EVENTS", [{"date": "2027-03-17", "name": "FOMC decision", "themes": []},
                                                        {"date": "2027-12-08", "name": "FOMC decision", "themes": []}]):
            status, detail = calendar_status(date(2027, 1, 5))
            self.assertEqual(status, "partial")
            self.assertIn("no US CPI date", detail)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import price_check, alerts  # noqa: E402
from src.models import Opportunity, PortfolioHolding  # noqa: E402
from src.report import _price_check_str  # noqa: E402

QUOTE = {"price": 100.0, "prev_close": 95.0, "as_of": "2026-10-02 20:00 UTC"}


class CompareTests(unittest.TestCase):
    def test_within_tolerance_of_live(self):
        self.assertEqual(price_check.compare(101.5, QUOTE, 2.0), ("Verified", 1.5))

    def test_matches_previous_close(self):
        status, diff = price_check.compare(95.2, QUOTE, 2.0)
        self.assertEqual(status, "Verified")
        self.assertEqual(diff, -4.8)

    def test_mismatch(self):
        self.assertEqual(price_check.compare(135.0, QUOTE, 2.0)[0], "Mismatch")

    def test_parse_quote_unknown_symbol(self):
        self.assertEqual(price_check.parse_quote({"c": 0, "pc": 0, "t": 0}), {})
        q = price_check.parse_quote({"c": 162.0, "pc": 158.0, "t": 1790000000})
        self.assertEqual(q["price"], 162.0)
        self.assertTrue(q["as_of"].endswith("UTC"))


class CrossCheckTests(unittest.TestCase):
    def test_no_key_marks_single_source(self):
        opps = [Opportunity(ticker="NVDA", price=180), Opportunity(ticker="2222.SR", price=25)]
        with mock.patch.object(config, "FINNHUB_API_KEY", ""):
            price_check.cross_check_prices(opps)
        self.assertEqual([o.price_check for o in opps], ["Single source", "Single source"])

    def test_statuses_and_non_us(self):
        quotes = {"NVDA": {"price": 180.0, "prev_close": 178.0, "as_of": "t"},
                  "SPCX": {"price": 162.0, "prev_close": 160.0, "as_of": "t"},
                  "AUR": {}}
        opps = [Opportunity(ticker="NVDA", price=180.5), Opportunity(ticker="SPCX", price=135.0),
                Opportunity(ticker="AUR", price=6.0), Opportunity(ticker="SAP.DE", price=150.0)]
        with mock.patch.object(config, "FINNHUB_API_KEY", "k"), \
             mock.patch.object(price_check, "fetch_quote", side_effect=lambda t: quotes[t]):
            price_check.cross_check_prices(opps)
        self.assertEqual([o.price_check for o in opps],
                         ["Verified", "Mismatch", "Unchecked", "Single source"])
        self.assertEqual(opps[1].price_alt, 162.0)

    def test_rate_limit_leaves_rest_unchecked(self):
        opps = [Opportunity(ticker="A", price=10), Opportunity(ticker="B", price=10)]
        with mock.patch.object(config, "FINNHUB_API_KEY", "k"), \
             mock.patch.object(price_check, "fetch_quote", side_effect=price_check.RateLimited):
            price_check.cross_check_prices(opps)
        self.assertEqual([o.price_check for o in opps], ["Unchecked", "Unchecked"])

    def test_fetch_quote_uses_dot_symbol_and_hides_key_on_error(self):
        with mock.patch.object(config, "FINNHUB_API_KEY", "secret-key"), \
             mock.patch.object(price_check.time, "sleep"), \
             mock.patch.object(price_check.requests, "get",
                               side_effect=price_check.requests.ConnectionError("https://x?token=secret-key")) as get, \
             mock.patch("builtins.print") as printed:
            self.assertEqual(price_check.fetch_quote("BRK-B"), {})
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "BRK.B")
        self.assertNotIn("token", get.call_args.kwargs["params"])
        self.assertNotIn("secret-key", str(printed.call_args_list))


class OutputTests(unittest.TestCase):
    def test_mismatch_holds_back_price_alerts(self):
        opp = Opportunity(ticker="NIO", price=4.0, upside=80, target=7.2, w52_low=3.9,
                          price_check="Mismatch", price_alt=5.0, price_diff_pct=-20.0,
                          portfolio=PortfolioHolding(ticker="NIO", pl_pct=-90.0))
        found = alerts._check_conditions([opp])
        self.assertEqual([a["level"] for a in found], ["WARN"])
        self.assertIn("Price mismatch", found[0]["message"])

    def test_verified_keeps_price_alerts(self):
        opp = Opportunity(ticker="NIO", price=4.0, upside=80, adj_upside=80, target=7.2, price_check="Verified")
        self.assertTrue(any(a["level"] == "BUY" for a in alerts._check_conditions([opp])))

    def test_report_strings(self):
        self.assertIn("MISMATCH", _price_check_str(
            Opportunity(price_check="Mismatch", price_alt=162.0, price_diff_pct=-16.7, price_as_of="t")))
        self.assertIn("Yahoo only", _price_check_str(Opportunity(price_check="Single source")))


if __name__ == "__main__":
    unittest.main()

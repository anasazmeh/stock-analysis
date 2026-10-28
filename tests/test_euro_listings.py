"""Euro home listings (ASML.AS, SAP.DE): priced in EUR, SEC / Alpha Vantage / Finnhub data via the US symbol."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import alphavantage, filings, news, sec, shariah, xbrl  # noqa: E402
from src.models import Opportunity  # noqa: E402


class EuroListingTests(unittest.TestCase):
    def test_sec_symbol(self):
        self.assertEqual(sec.sec_symbol("ASML.AS"), "ASML")
        self.assertEqual(sec.sec_symbol("SAP.DE"), "SAP")
        self.assertEqual(sec.sec_symbol("NVDA"), "NVDA")
        self.assertEqual(sec.sec_symbol("2222.SR"), "")
        self.assertEqual(sec.cik_for("ASML.AS", {"ASML": "0000937966"}), "0000937966")

    def test_profile_holds_the_euro_lines(self):
        import portfolio_data
        tickers = {h["ticker"] for h in portfolio_data.HOLDINGS}
        self.assertTrue({"ASML.AS", "SAP.DE"} <= tickers)
        self.assertFalse({"ASML", "SAP"} & tickers)
        self.assertTrue({"ASML.AS", "SAP.DE"} <= {o["ticker"] for o in portfolio_data.OPEN_ORDERS})
        self.assertIn("ASML.AS", config.CURATED_WATCHLIST)
        self.assertIn("ASML.AS", config.SUPPLY_CHAIN_GEO)

    def test_second_opinion_links_use_us_symbol(self):
        self.assertIn("musaffa.com/stock/ASML", shariah.second_opinion_links("ASML.AS")["Musaffa"])
        self.assertEqual(shariah.second_opinion_links("2222.SR"), {})

    def test_filings_and_xbrl_include_mapped_listing(self):
        opp = Opportunity(ticker="ASML.AS", price=1477.0, shariah_inputs={})
        with mock.patch.object(filings, "_load_ticker_cik_map", return_value={"ASML": "0000937966"}), \
             mock.patch.object(filings, "_get_recent_submissions", return_value={}) as subs, \
             mock.patch.object(filings.time, "sleep"):
            filings.fetch_recent_filings([opp])
        subs.assert_called_once_with("0000937966")
        with mock.patch("src.sec.load_ticker_cik_map", return_value={"ASML": "0000937966"}), \
             mock.patch.object(xbrl, "fill_missing", return_value={"x": 1}) as fill:
            xbrl.fill_from_sec([opp])
        fill.assert_called_once()

    def test_alpha_vantage_dates_and_surprise_but_not_usd_target(self):
        opp = Opportunity(ticker="ASML.AS", price=1477.0, currency="EUR")
        calls = []

        def fake_get(params):
            calls.append(params)
            if params["function"] == "EARNINGS_CALENDAR":
                return "symbol,name,reportDate,fiscalDateEnding,estimate,currency\nASML,ASML,2027-01-20,2026-12-31,,USD\n"
            if params["function"] == "EARNINGS":
                return {"quarterlyEarnings": [{"surprisePercentage": "4.2"}]}
            return {"AnalystTargetPrice": "1900"}
        with mock.patch.object(config, "ALPHA_VANTAGE_API_KEY", "demo"), \
             mock.patch.object(alphavantage, "_get", side_effect=fake_get):
            alphavantage.run_alpha_vantage([opp])
        self.assertEqual(opp.earnings_date, "2027-01-20")
        self.assertEqual(opp.eps_surprise, 4.2)
        self.assertEqual(opp.target, 0.0)                         # a USD target would be wrong for the EUR line
        self.assertNotIn("OVERVIEW", [c["function"] for c in calls])

    def test_finnhub_news_uses_us_symbol(self):
        with mock.patch.object(config, "FINNHUB_API_KEY", "k"), \
             mock.patch("requests.get", side_effect=RuntimeError("offline")) as get:
            news._fetch_finnhub_news("SAP.DE")
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "SAP")


if __name__ == "__main__":
    unittest.main()

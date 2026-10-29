"""Fixes from the 17 Oct 2026 run log: duplicate listings, GDELT queries and 429s,
the Nasdaq-100 source, the insider signal and library log levels."""
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import gdelt, insider, output_gate, runlog, symbols, tech_debt, universe  # noqa: E402
from src.models import AnalysisResult, MacroContext, Opportunity  # noqa: E402


class NameTests(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(symbols.clean_name("Siemens Energy AG             N"), "Siemens Energy AG")
        self.assertEqual(symbols.clean_name("EMAAR PROPERTIES PJSC AED1"), "EMAAR PROPERTIES PJSC")
        self.assertEqual(symbols.clean_name("ASML Holding N.V. - New York Re"), "ASML Holding N.V.")
        self.assertEqual(symbols.clean_name(None), "")

    def test_us_and_home_listing_of_asml_collapse(self):
        opps = [Opportunity(ticker="ASML", name="ASML Holding N.V. - New York Re", country="Netherlands",
                            price=1600.0, avg_volume=1e6),
                Opportunity(ticker="ASML.AS", name="ASML HOLDING", country="Netherlands", price=1470.0, avg_volume=5e5)]
        with mock.patch.object(config, "CURATED_WATCHLIST", ["ASML"]):
            kept, dropped = symbols.dedupe_listings(opps)
        self.assertEqual(dropped, {"ASML.AS": "ASML"})            # your curated listing wins
        with mock.patch.object(config, "CURATED_WATCHLIST", []):
            kept, dropped = symbols.dedupe_listings(opps)
        self.assertEqual([o.ticker for o in kept], ["ASML.AS"])   # otherwise the home listing
        self.assertEqual(dropped, {"ASML": "ASML.AS"})

    def test_siemens_and_siemens_energy_stay_apart(self):
        self.assertNotEqual(symbols.company_key("Siemens AG"), symbols.company_key("Siemens Energy AG             N"))


class GdeltQueryTests(unittest.TestCase):
    def test_short_names_use_phrases_gdelt_accepts(self):
        for name, ticker in (("BYD Company Limited", "BYDDY"), ("NIO Inc.", "NIO")):
            q = gdelt.company_query(name, ticker)
            short = name.split()[0]
            self.assertIn(f'"{short} shares"', q)
            self.assertNotIn(f'"{short}" ', q)   # a lone 3-letter phrase is rejected as "too short"

    def test_messy_names_cleaned(self):
        self.assertEqual(gdelt.company_query("Siemens Energy AG             N", "ENR.DE"),
                         '"Siemens Energy" sourcelang:english')
        self.assertEqual(gdelt.company_query("EMAAR PROPERTIES PJSC AED1", "EMAAR.AE"), '"EMAAR PROPERTIES"')


class GdeltRateLimitTests(unittest.TestCase):
    def setUp(self):
        gdelt.STATE.update(refused=0, paused=False, skipped=0)

    def tearDown(self):
        gdelt.STATE.update(refused=0, paused=False, skipped=0)

    def test_retry_once_then_succeed(self):
        limited = mock.Mock(status_code=429, text="Please limit requests")
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"articles": [{"title": "Story", "seendate": "20261017T100000Z"}]}
        with mock.patch.object(gdelt.requests, "get", side_effect=[limited, ok]) as get, \
             mock.patch.object(gdelt.time, "sleep"):
            self.assertEqual(len(gdelt.search("retry-query-1")), 1)
        self.assertEqual(get.call_count, 2)

    def test_pauses_after_repeated_refusals(self):
        limited = mock.Mock(status_code=429, text="Please limit requests")
        with mock.patch.object(gdelt.requests, "get", return_value=limited) as get, \
             mock.patch.object(gdelt.time, "sleep"):
            for i in range(gdelt._MAX_REFUSALS + 4):
                self.assertEqual(gdelt.search(f"pause-query-{i}"), [])
        self.assertTrue(gdelt.STATE["paused"])
        self.assertEqual(get.call_count, gdelt._MAX_REFUSALS * 2)   # nothing sent once paused
        self.assertEqual(gdelt.STATE["skipped"], 4)


class UniverseJsonTests(unittest.TestCase):
    def test_parse_nasdaq_list_api(self):
        payload = {"data": {"data": {"rows": [{"symbol": "AAPL"}, {"symbol": "BRK.B"}, {"symbol": ""}]}}}
        self.assertEqual(universe.parse_index_json(payload), ["AAPL", "BRK-B"])
        self.assertEqual(universe.parse_index_json({}), [])

    def test_nasdaq_100_no_longer_points_at_wikipedia(self):
        self.assertIn("api.nasdaq.com", config.UNIVERSE_INDICES["Nasdaq-100"])


class InsiderTests(unittest.TestCase):
    XML = (b"<ownershipDocument>%s<nonDerivativeTable><nonDerivativeTransaction><transactionCoding>"
           b"<transactionCode>S</transactionCode></transactionCoding><transactionAmounts><transactionShares>"
           b"<value>%d</value></transactionShares></transactionAmounts></nonDerivativeTransaction>"
           b"</nonDerivativeTable></ownershipDocument>")

    def test_10b5_1_plan_sales_are_not_a_signal(self):
        txns = insider.parse_form4_xml(self.XML % (b"<aff10b5One>1</aff10b5One>", 1_000_000))
        self.assertTrue(txns[0]["plan"])
        self.assertEqual(insider.compute_signal(txns), ("Neutral", 0))
        self.assertEqual(insider.planned_sales(txns), 1_000_000)

    def test_small_sales_at_a_giant_are_neutral(self):
        txns = insider.parse_form4_xml(self.XML % (b"<aff10b5One>0</aff10b5One>", 1_431_378))
        self.assertEqual(insider.compute_signal(txns, shares_outstanding=24_300_000_000)[0], "Neutral")

    def test_material_discretionary_sales_are_bearish(self):
        txns = insider.parse_form4_xml(self.XML % (b"", 29_369_611))
        self.assertEqual(insider.compute_signal(txns, shares_outstanding=1_800_000_000),
                         ("Bearish", -29_369_611))


class LibraryLogTests(unittest.TestCase):
    def test_missing_fundamentals_is_a_warning_not_an_error(self):
        collector = runlog._Collector()
        handler = runlog._LibraryHandler(None, collector)
        record = logging.LogRecord("yfinance", logging.ERROR, __file__, 1,
                                   "HTTP Error 404: No fundamentals data found for symbol: DEWA.AE", None, None)
        handler.emit(record)
        self.assertEqual(collector.issues[-1]["level"], "WARNING")
        self.assertTrue(collector.issues[-1]["text"].startswith("WARNING [yfinance]"))



class AvoidListInputTests(unittest.TestCase):
    """A headline or a Claude sentence naming an avoided company must not fail the run or hide a stock."""

    def test_mentions_removed_where_they_enter(self):
        o = Opportunity(ticker="NVDA", name="NVIDIA", price=200.0,
                        news=[{"title": "Palantir and Nvidia sign AI deal"}, {"title": "Nvidia beats estimates"}],
                        analysis=AnalysisResult(thesis="Data-centre demand is strong. Peers like PLTR also gain. Margins hold.",
                                                catalysts=["Blackwell ramp", "Contract shared with Palantir"]))
        macro = MacroContext(themes=["AI capex", "Grab Holdings IPO lock-up"],
                             macro_news=[{"title": "PLTR jumps"}, {"title": "Fed holds rates"}])
        self.assertEqual(output_gate.scrub_inputs([o], macro), 5)
        self.assertEqual([a["title"] for a in o.news], ["Nvidia beats estimates"])   # the stock stays, the headline goes
        self.assertEqual(o.analysis.thesis, "Data-centre demand is strong. Margins hold.")
        self.assertEqual(o.analysis.catalysts, ["Blackwell ramp"])
        self.assertEqual(macro.themes, ["AI capex"])
        self.assertEqual(macro.macro_news, [{"title": "Fed holds rates"}])
        self.assertEqual(output_gate.scrub_inputs([o], macro), 0)

    def test_gate_message_is_visible_on_the_dashboard(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")) as f:
            line = next(l for l in f if "Avoid-list gate removed" in l)
        self.assertEqual(output_gate.find_violations(line), [])
        self.assertNotIn("AVOID_LIST)}", line)


class SecretRedactionTests(unittest.TestCase):
    AV_REPLY = ("We have detected your API key as DEMOKEY0EXAMPLE1 and our standard API rate limit "
                "is 25 requests per day.")

    def test_alpha_vantage_reply_hides_the_key(self):
        self.assertNotIn("DEMOKEY0EXAMPLE1", runlog.redact(self.AV_REPLY))
        self.assertIn("API key as ***", runlog.redact(self.AV_REPLY))

    def test_configured_secrets_hidden(self):
        with mock.patch.object(config, "FINNHUB_API_KEY", "fh_secret_value_123"):
            self.assertEqual(runlog.redact("token fh_secret_value_123 rejected"), "token *** rejected")

    def test_tech_debt_cleans_new_and_stored_keys(self):
        d = tempfile.mkdtemp()
        path, md = os.path.join(d, "td.json"), os.path.join(d, "TD.md")
        tech_debt.update([{"level": "WARNING", "text": "  [av] " + self.AV_REPLY, "source": "stdout"}],
                         path=path, md_path=md)
        with open(md) as f:
            self.assertNotIn("DEMOKEY0EXAMPLE1", f.read())
        with open(path) as f:
            self.assertNotIn("DEMOKEY0EXAMPLE1", f.read())



class HealthDetailTests(unittest.TestCase):
    def test_claude_login_error_stops_the_run_early_and_is_reported(self):
        from src import intelligence
        from src.models import MacroContext
        intelligence.LAST_ERROR.update(text="", fatal=False)
        opps = [Opportunity(ticker=f"T{i}", name=f"T{i}", price=10.0, data_ok=True, rank_score=50 - i) for i in range(8)]
        calls = []

        def fail(*a, **k):
            calls.append(1)
            raise RuntimeError("claude exited 1: Invalid API key · Please run /login")
        with mock.patch.object(intelligence, "_call", side_effect=fail), \
             mock.patch.object(intelligence, "ai_available", return_value=True), \
             mock.patch.object(config, "AI_PARALLEL", 1), mock.patch.object(config, "BATCH_SIZE", 4):
            intelligence.analyze_tickers(opps, MacroContext())
        self.assertEqual(len(calls), 1)                     # no retries, no further batches
        self.assertTrue(intelligence.LAST_ERROR["fatal"])
        self.assertIn("/login", intelligence.LAST_ERROR["text"])
        intelligence.LAST_ERROR.update(text="", fatal=False)

    def test_gate_names_the_unusable_holding(self):
        from src import data_quality
        good = Opportunity(ticker="AAA", price=10.0)
        bad = Opportunity(ticker="LOGC", price=0.0)
        with mock.patch.object(data_quality, "check_ticker",
                               side_effect=lambda o, now: [] if o.ticker == "AAA" else [next(iter(data_quality.CRITICAL))]):
            health = data_quality.apply_gate([good, bad], ["LOGC"])
        status, detail = health.sources["Data-quality gate"]
        self.assertEqual(status, "failed")
        self.assertIn("LOGC (", detail)
        self.assertIn("Holding affected: LOGC", detail)


    def test_held_etc_in_usd_on_london_passes(self):
        from datetime import datetime, timezone
        from src import data_quality
        from src.models import PortfolioHolding
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        gold = Opportunity(ticker="PHAU.L", price=376.0, currency="USD", quote_type="EQUITY", mcap=0.0,
                           price_time="2026-10-28 11:00 UTC", hist_prices=[1.0] * 300, financial_currency="USD",
                           portfolio=PortfolioHolding(ticker="PHAU.L", bep_currency="USD", asset_type="ETC"))
        flags = data_quality.check_ticker(gold, now)
        self.assertNotIn("no market cap", flags)
        self.assertNotIn("wrong listing", flags)
        gold.portfolio = None                                   # not held: a USD quote on .L is still suspicious
        self.assertIn("wrong listing", data_quality.check_ticker(gold, now))



class ModelChoiceTests(unittest.TestCase):
    def test_latest_opus_alias_and_no_credit_models(self):
        from src import intelligence
        self.assertEqual(config.CLAUDE_CLI_MODEL, "opus")
        for m in ("fable", "best", "claude-fable-5-1", "FABLE"):
            with mock.patch.object(config, "CLAUDE_CLI_MODEL", m), \
                 mock.patch.object(config, "AI_BACKEND", "claude-cli"):   # CI runs with AI_BACKEND=off
                self.assertTrue(intelligence._credit_model(), m)
                self.assertIn("usage credits", intelligence.ai_unavailable_reason())
        for m in ("opus", "sonnet", "claude-opus-5-5"):
            with mock.patch.object(config, "CLAUDE_CLI_MODEL", m):
                self.assertFalse(intelligence._credit_model(), m)


if __name__ == "__main__":
    unittest.main()

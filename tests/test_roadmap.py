import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import (fx as fxmod, portfolio, shariah, xbrl, data_quality, risk, ranking, news, newsapi_client,
                 alphavantage, argaam, sec, insider, events, theses, journal, output_gate, broker_import,
                 ipo, intelligence, geo_watch, alerts, report)  # noqa: E402
from src.models import Opportunity, PortfolioHolding, MacroContext, ShariahStatus, RiskProfile, AnalysisResult  # noqa: E402

FX = fxmod.parse_ecb_xml("<Cube time='2026-10-01'><Cube currency='USD' rate='1.15'/>"
                         "<Cube currency='TWD' rate='36.0'/><Cube currency='GBP' rate='0.86'/></Cube>")
NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def _hist(n=260, start=100.0, step=0.2):
    return [start + i * step for i in range(n)]


def _stock(**kw):
    base = dict(ticker="AAA", name="Alpha Corp", price=150.0, currency="USD", financial_currency="USD",
                price_time="2026-10-01 20:00 UTC", price_type="last close", price_source="Yahoo Finance",
                mcap=1e11, hist_prices=_hist(), sector="Technology", industry="Software",
                quote_type="EQUITY", target=200.0, upside=33.3, analyst_count=20,
                target_high=240.0, target_low=170.0)
    base.update(kw)
    return Opportunity(**base)


class FxPortfolioTests(unittest.TestCase):
    def test_ecb_parse_and_pegs(self):
        self.assertEqual(FX.date, "2026-10-01")
        self.assertAlmostEqual(FX.rates["SAR"], 1.15 * 3.75)
        self.assertIsNone(fxmod.FxTable().rate("USD", "EUR"))

    def test_sap_pl_in_eur(self):
        p = portfolio.value_holding(portfolio._holding({"ticker": "SAP", "shares": 20, "bep": 147, "bep_currency": "EUR"}),
                                    167.81, "USD", FX)
        self.assertAlmostEqual(p.pl_pct, -0.7, places=1)

    def test_no_fx_leaves_pl_empty(self):
        p = portfolio.value_holding(portfolio._holding({"ticker": "X", "shares": 1, "bep": 10, "bep_currency": "EUR"}),
                                    12, "USD", fxmod.FxTable())
        self.assertIsNone(p.pl_pct)
        self.assertIn("FX", p.note)

    def test_exposure_and_caps(self):
        a = _stock(ticker="NVDA", portfolio=PortfolioHolding(value_eur=8000, cost_eur=4000, weight_pct=80, themes=["AI / Semiconductors"]))
        b = _stock(ticker="MSFT", portfolio=PortfolioHolding(value_eur=2000, cost_eur=2000, weight_pct=20, themes=["Cloud"]))
        exp = portfolio.exposure([a, b])
        self.assertEqual(exp["themes"]["AI / Semiconductors"], 80.0)
        self.assertTrue(any("NVDA" in x for x in exp["breaches"]))
        self.assertTrue(portfolio.breaches_after_add(a, exp))

    def test_purification(self):
        o = _stock(dividend_rate=2.0, portfolio=PortfolioHolding(shares=10),
                   shariah=ShariahStatus(compliant="Yes", income_ratio=0.02))
        r = portfolio.purification(o, FX)
        self.assertAlmostEqual(r["amount"], 0.4)


class ShariahTests(unittest.TestCase):
    INPUTS = {"interest_bearing_debt": 1e10, "cash_and_securities": 5e9, "receivables": 3e9,
              "interest_income": 1e8, "revenue": 5e10, "currency": "USD", "period": "2025-12-31",
              "source": "Yahoo annual statements"}

    def test_pass(self):
        s = shariah.screen(_stock(shariah_inputs=dict(self.INPUTS)), FX)
        self.assertEqual(s.compliant, "Yes")

    def test_debt_breach_is_no_not_partial(self):
        s = shariah.screen(_stock(shariah_inputs={**self.INPUTS, "interest_bearing_debt": 4e10}), FX)
        self.assertEqual(s.compliant, "No")

    def test_missing_input_is_unknown(self):
        inp = dict(self.INPUTS)
        inp["interest_income"] = None
        self.assertEqual(shariah.screen(_stock(shariah_inputs=inp), FX).compliant, "Unknown")

    def test_currency_normalised(self):
        # TWD debt 9e11 = ~2.9e10 USD on a 1.5e12 USD mcap
        s = shariah.screen(_stock(mcap=1.5e12, shariah_inputs={**self.INPUTS, "interest_bearing_debt": 9e11,
                                                                "currency": "TWD"}), FX)
        self.assertLess(s.debt_ratio, 0.03)

    def test_pre_revenue_interest(self):
        s = shariah.screen(_stock(shariah_inputs={**self.INPUTS, "revenue": 0, "interest_income": 5e7}), FX)
        self.assertEqual(s.compliant, "No")

    def test_activity_labels(self):
        self.assertEqual(shariah.activity_screen("X", "Consumer Defensive", "Beverages—Brewers")[0], "Fail")
        self.assertEqual(shariah.activity_screen("X", "Consumer Cyclical", "Resorts & Casinos")[0], "Fail")
        self.assertEqual(shariah.activity_screen("1120.SR", "Financial Services", "Banks - Regional")[0], "Pass")
        self.assertEqual(shariah.activity_screen("MC.PA", "Consumer Cyclical", "Luxury Goods")[0], "Fail")
        self.assertEqual(shariah.activity_screen("X", "Industrials", "Aerospace & Defense")[0], "Review")

    def test_debt_event_review(self):
        o = _stock(shariah_inputs=dict(self.INPUTS),
                   filings=[{"form": "8-K", "date": "2026-09-30", "items": ["2.03"], "labels": [], "red_flag": False}])
        self.assertEqual(shariah.screen(o, FX).compliant, "Review")

    def test_history_previous(self):
        path = os.path.join(tempfile.mkdtemp(), "h.jsonl")
        o = _stock(shariah_inputs=dict(self.INPUTS))
        shariah.check_shariah([o], FX, history_path=path)
        o2 = _stock(shariah_inputs={**self.INPUTS, "interest_bearing_debt": 4e10})
        shariah.check_shariah([o2], FX, history_path=path)
        self.assertEqual(o2.shariah.previous, "Yes")
        self.assertEqual(o2.shariah.compliant, "No")

    def test_xbrl_latest_annual(self):
        facts = {"facts": {"us-gaap": {"InvestmentIncomeInterest": {"units": {"USD": [
            {"val": 1, "end": "2024-12-31", "form": "10-K", "fp": "FY", "filed": "2025-02-01"},
            {"val": 2, "end": "2025-12-31", "form": "10-K", "fp": "FY", "filed": "2026-02-01"},
            {"val": 9, "end": "2026-06-30", "form": "10-Q", "fp": "Q2", "filed": "2026-08-01"}]}}}}}
        self.assertEqual(xbrl.latest_annual(facts, "us-gaap", "InvestmentIncomeInterest")[0], 2.0)


class GateRiskRankTests(unittest.TestCase):
    def test_flags(self):
        self.assertIn("stale quote", data_quality.check_ticker(_stock(price_time="2026-09-20 20:00 UTC"), NOW))
        self.assertIn("wrong listing", data_quality.check_ticker(_stock(ticker="EMAAR.AE", currency="USD"), NOW))
        self.assertIn("short history", data_quality.check_ticker(_stock(hist_prices=_hist(30)), NOW))
        self.assertEqual(data_quality.tradability("2222.SR"), "Watch only")
        self.assertEqual(data_quality.tradability("SAP.DE"), "Yes")

    def test_degraded_when_holding_missing(self):
        h = data_quality.apply_gate([_stock(), _stock(ticker="NIO", price=0)], ["NIO"], NOW)
        self.assertTrue(h.degraded)

    def test_risk_none_aware(self):
        r = risk.build_risk(_stock(beta=None, de=None, hist_prices=_hist(20)))
        self.assertIsNone(r.volatility_30d)
        self.assertIsNone(r.composite_score)  # geo + nothing else is under 50% coverage

    def test_trend(self):
        o = _stock()
        risk.compute_trend(o, {"SPY": _hist(260, 100, 0.05)})
        self.assertEqual(o.trend, "Uptrend")
        self.assertGreater(o.rel_strength["SPY"], 0)

    def test_consensus_quality(self):
        self.assertEqual(ranking.consensus_quality(_stock(analyst_count=3))[0], "Thin")
        self.assertEqual(ranking.consensus_quality(_stock(target_high=400, target_low=100))[0], "Wide")
        label, adj = ranking.consensus_quality(_stock(rating_changes_90d={"up": 0, "down": 3}))
        self.assertIn("Downgrades", label)
        self.assertLess(adj, 33.3)

    def test_rank_missing_data_lowers(self):
        full = _stock(adj_upside=30, finbert_score=4.0, risk=RiskProfile(composite_score=4.0), trend="Uptrend")
        sparse = _stock(adj_upside=30)
        self.assertGreater(ranking.rank_score(full), ranking.rank_score(sparse))

    def test_rating_changes(self):
        import pandas as pd
        df = pd.DataFrame({"Action": ["up", "down", "main", "up"]},
                          index=pd.to_datetime(["2026-09-01", "2026-08-15", "2026-09-10", "2025-01-01"]))
        self.assertEqual(ranking.count_rating_changes(df, "2026-10-01"), {"up": 1, "down": 1})


class NewsTests(unittest.TestCase):
    def test_yahoo_nested_schema(self):
        raw = [{"id": "1", "content": {"title": "TSMC sales jump", "summary": "s", "pubDate": "2026-10-01T10:00:00Z",
                                       "provider": {"displayName": "Reuters"}, "canonicalUrl": {"url": "https://r.com/a"}}},
               {"content": {"title": ""}}]
        out = news.parse_yahoo_news(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "Reuters")
        self.assertEqual(out[0]["date"], "2026-10-01")

    def test_normalize(self):
        arts = [{"title": "Nvidia rises - Reuters", "date": "2026-10-01", "url": "https://reuters.com/x"},
                {"title": "Nvidia rises - MarketWatch", "date": "2026-10-01", "url": "https://marketwatch.com/x"},
                {"title": "Old story", "date": "2026-08-01"},
                {"title": "INVESTOR ALERT: class action against Nvidia", "date": "2026-10-01"},
                {"title": "Shareholder alert: Rosen Law Firm", "date": "2026-10-01"},
                {"title": "Blog post", "date": "2026-10-01", "url": "https://blog.example/x"}]
        out = news.normalize_articles(arts, today=date(2026, 10, 2))
        titles = [a["title"] for a in out]
        self.assertEqual(titles[0], "Nvidia rises - Reuters")
        self.assertNotIn("Old story", titles)
        self.assertEqual(sum("alert" in t.lower() for t in titles), 1)
        self.assertEqual(len(out), 3)

    def test_keyword_negation(self):
        self.assertGreater(newsapi_client._score_text("Lucid cuts losses"), 0)
        self.assertLess(newsapi_client._score_text("Results did not beat estimates"), 0)


class SourceParsingTests(unittest.TestCase):
    def test_av_errors(self):
        self.assertTrue(alphavantage.is_error_reply({"Information": "Thank you for using Alpha Vantage! rate limit"}))
        self.assertEqual(alphavantage.parse_calendar('{"Information": "x"}'), [])
        self.assertEqual(len(alphavantage.parse_calendar("symbol,name,reportDate\nNVDA,Nvidia,2026-11-19\n")), 1)

    def test_av_budget(self):
        with mock.patch.object(config, "AV_DAILY_BUDGET", 0):
            with self.assertRaises(alphavantage.QuotaExhausted):
                alphavantage._spend()

    def test_argaam_recent(self):
        recs = [{"targetPrice": 30, "date": "2026-09-01"}, {"targetPrice": 50, "date": "2024-01-01"}, {"targetPrice": 40}]
        self.assertEqual(argaam.recent_targets(recs, date(2026, 10, 2)), [30.0])

    def test_sec_helpers(self):
        self.assertEqual(sec.raw_document("xslF345X05/wk-form4_1.xml"), "wk-form4_1.xml")
        self.assertTrue(sec.is_foreign_issuer({"form": ["6-K", "20-F", "SC 13G"]}))
        self.assertFalse(sec.is_foreign_issuer({"form": ["10-Q", "4", "8-K"]}))
        xml = (b"<ownershipDocument><nonDerivativeTable><nonDerivativeTransaction><transactionCoding>"
               b"<transactionCode>S</transactionCode></transactionCoding><transactionAmounts><transactionShares>"
               b"<value>12000</value></transactionShares></transactionAmounts></nonDerivativeTransaction>"
               b"</nonDerivativeTable></ownershipDocument>")
        self.assertEqual(insider.compute_signal(insider.parse_form4_xml(xml)), ("Bearish", -12000))

    def test_broker_csvs(self):
        degiro = ("Date,Time,Product,ISIN,Reference exchange,Venue,Quantity,Price,,Local value,,Value EUR\n"
                  "02-04-2026,10:00,SAP SE,DE0007164600,XET,XETA,20,147.00,EUR,-2940,EUR,-2940\n"
                  "05-04-2026,10:00,SAP SE,DE0007164600,XET,XETA,-5,150.00,EUR,750,EUR,750\n")
        pos = broker_import.parse_degiro(degiro)
        self.assertEqual(pos["DE0007164600"].shares, 15)
        self.assertAlmostEqual(pos["DE0007164600"].avg_cost, 147.0)
        revolut = ("Date,Ticker,Type,Quantity,Price per share,Total Amount,Currency,FX Rate\n"
                   "2026-04-15T10:00:00Z,MSFT,BUY - MARKET,12,USD 381.20,USD 4574.40,USD,1.1\n"
                   "2026-05-01T10:00:00Z,MSFT,DIVIDEND,,,USD 5,USD,1.1\n")
        rpos = broker_import.parse_revolut(revolut)
        self.assertEqual(rpos["MSFT"].shares, 12)
        diffs = broker_import.reconcile(
            [{"ticker": "MSFT", "shares": 12, "bep": 381.2, "bep_currency": "USD"},
             {"ticker": "SAP", "isin": "DE0007164600", "shares": 20, "bep": 147, "bep_currency": "EUR"}],
            list(pos.values()) + list(rpos.values()))
        self.assertEqual(len(diffs), 1)
        self.assertIn("shares 20", diffs[0]["issue"])

    def test_ipo_terms(self):
        text = ("The initial public offering price is $135.00 per share. We are offering 100,000,000 shares offered "
                "hereby. Lock-up: 180 days after the date of this prospectus. We earn interest income on cash.")
        t = ipo.extract_terms(text)
        self.assertEqual(t["offer_price"], 135.0)
        self.assertEqual(t["lockup_days"], 180)
        self.assertEqual(ipo.activity_checklist(text)["interest income / lending"], 1)

    def test_ipo_dossier_labels_prices(self):
        with mock.patch.object(ipo, "find_prospectus", return_value={}), \
             mock.patch.object(ipo, "market_quote", return_value={"price": 150.0, "currency": "USD",
                                                                 "time": "t", "type": "last close"}):
            text = ipo.build_dossier("SpaceX", broker_price=162.0, ticker="SPCX", amount=2000)
        self.assertIn("Your broker's quote", text)
        self.assertIn("no single price is given", text)


class EventsThesesJournalTests(unittest.TestCase):
    def test_trading_days_and_blackout(self):
        self.assertEqual(events.trading_days_between(date(2026, 10, 2), date(2026, 10, 9)), 5)
        o = _stock(next_event="Earnings 2026-10-08", days_to_event=4)
        self.assertTrue(events.earnings_blackout(o))

    def test_attach_events_user_file(self):
        path = os.path.join(tempfile.mkdtemp(), "events.json")
        with open(path, "w") as f:
            json.dump([{"date": "2026-10-20", "name": "SpaceX lock-up ends", "tickers": ["AAA"]}], f)
        o = _stock(earnings_date="2026-11-30")
        with mock.patch.object(events, "_USER_EVENTS", path), \
             mock.patch.object(events, "_finnhub_calendar", return_value={}):
            macro = events.attach_events([o], MacroContext(), today=date(2026, 10, 2))
        self.assertEqual(o.next_event, "SpaceX lock-up ends 2026-10-20")
        self.assertTrue(any(e["name"].startswith("TSMC") for e in macro.events))

    def test_thesis_rules(self):
        o = _stock(trend="Downtrend", shariah=ShariahStatus(compliant="Unknown"),
                   portfolio=PortfolioHolding(weight_pct=5))
        self.assertEqual(theses.evaluate(o, config.DEFAULT_THESIS_RULES, date(2026, 10, 2))[0], "Review")
        o.shariah.compliant = "No"
        self.assertEqual(theses.evaluate(o, config.DEFAULT_THESIS_RULES, date(2026, 10, 2))[0], "Broken")

    def test_journal_changes_and_scorecard(self):
        runs = tempfile.mkdtemp()
        health = data_quality.RunHealth()
        a = _stock(ticker="AAA", shariah=ShariahStatus(compliant="Yes"))
        journal.write_snapshot([a], [a], health, runs_dir=runs, now=datetime(2026, 9, 1),
                               portfolio_value_eur=10000, benchmark_close=50)
        b = _stock(ticker="AAA", price=180, shariah=ShariahStatus(compliant="No"))
        changes = journal.what_changed([b], [], journal.latest_snapshot(runs))
        self.assertTrue(any("Shariah Yes → No" in c for c in changes))
        self.assertTrue(any("Dropped from Top 10" in c for c in changes))
        card = journal.scorecard(11000, 52, runs_dir=runs, now=datetime(2026, 10, 2))
        self.assertEqual(card["portfolio_pct"], 10.0)
        self.assertEqual(card["benchmark_pct"], 4.0)

    def test_output_gate(self):
        clean, removed = output_gate.scrub("NVDA looks fine\nPLTR is great\nPalantir rally\nGrab a coffee")
        self.assertEqual(removed, 2)
        self.assertIn("Grab a coffee", clean)


class IntelligenceTests(unittest.TestCase):
    def test_evidence_pack_omits_missing(self):
        pack = intelligence.evidence_pack(_stock(fpe=None, news=[{"title": "T", "source": "Reuters", "date": "2026-10-01"}]))
        self.assertNotIn("forward_pe", pack["facts"])
        self.assertEqual(pack["facts"]["news_1"]["source"], "Reuters")

    def test_validate(self):
        packs = {"AAA": intelligence.evidence_pack(_stock()),
                 "BBB": intelligence.evidence_pack(_stock(ticker="BBB", portfolio=PortfolioHolding()))}
        raw = {"analyses": [
            {"ticker": "AAA", "status": "OK", "thesis": "t", "bull_case": "b", "bear_case": "r",
             "invalidation_triggers": ["x"], "sentiment_score": 15, "catalysts": [], "risk_flags": [],
             "holder_action": "ADD", "new_buyer_action": "BUY", "confidence": "medium",
             "evidence_used": ["price", "made_up_fact"]},
            {"ticker": "BBB", "status": "INSUFFICIENT_DATA", "thesis": "", "bull_case": "", "bear_case": "",
             "invalidation_triggers": [], "sentiment_score": 0, "catalysts": [], "risk_flags": [],
             "holder_action": "N/A", "new_buyer_action": "WATCH", "confidence": "low", "evidence_used": []},
            {"ticker": "ZZZ", "status": "OK"}]}
        out = intelligence.validate(raw, packs)
        self.assertEqual(set(out), {"AAA", "BBB"})
        self.assertEqual(out["AAA"].sentiment_score, 10)
        self.assertEqual(out["AAA"].holder_action, "N/A")       # not held
        self.assertEqual(out["AAA"].evidence_used, ["price"])
        self.assertEqual(out["BBB"].holder_action, "HOLD")
        self.assertIsNone(out["BBB"].sentiment_score)


class AlertsGeoReportTests(unittest.TestCase):
    def test_blackout_and_caps(self):
        exp = {"total_value_eur": 10000, "themes": {"AI": 45.0}, "breaches": []}
        a = _stock(ticker="AAA", adj_upside=70, next_event="Earnings 2026-10-05", days_to_event=2)
        b = _stock(ticker="NVDA", adj_upside=70, portfolio=PortfolioHolding(value_eur=4500, themes=["AI"]))
        found = alerts.check_conditions([a, b], exposure=exp)
        msgs = {x["ticker"]: x for x in found if "upside" in x["message"]}
        self.assertEqual(msgs["AAA"]["level"], "INFO")
        self.assertEqual(msgs["NVDA"]["level"], "WARN")

    def test_degraded_suppresses_buy(self):
        h = data_quality.RunHealth(degraded=True, degraded_reasons=["x"])
        found = alerts.check_conditions([_stock(adj_upside=90)], health=h)
        self.assertFalse(any(x["level"] == "BUY" for x in found))
        self.assertEqual(found[0]["level"], "DANGER")

    def test_thesis_change_alert_once(self):
        o = _stock(ticker="NIO", thesis_status="Broken", thesis_notes=["trend is Downtrend"],
                   portfolio=PortfolioHolding(pl_pct=-50))
        prev = {"tickers": [{"ticker": "NIO", "thesis_status": "Review"}]}
        self.assertTrue(any("Thesis Review → Broken" in x["message"] for x in alerts.check_conditions([o], previous=prev)))
        prev["tickers"][0]["thesis_status"] = "Broken"
        self.assertFalse(any("Thesis" in x["message"] for x in alerts.check_conditions([o], previous=prev)))

    def test_geo_watch(self):
        o = _stock(ticker="NVDA", risk=RiskProfile(geo_exposure="Medium"),
                   portfolio=PortfolioHolding(value_eur=1000))
        doc = [{"title": "Revisions to export controls on advanced computing", "date": "2026-09-25", "url": "u", "type": "Rule"}]
        with mock.patch.object(geo_watch, "fetch_documents", return_value=doc):
            macro = geo_watch.apply_geo_watch([o], MacroContext(), date(2026, 10, 2))
        self.assertEqual(o.risk.geo_exposure, "High")
        self.assertEqual(macro.geo_themes[0]["portfolio_exposed_pct"], 100.0)

    def test_report_renders(self):
        o = _stock(ticker="NVDA", shariah=ShariahStatus(compliant="Yes", reasons=[], second_opinion={"Musaffa": "u"}),
                   risk=RiskProfile(composite_score=4.0, volatility_30d=30, rsi_14=55, geo_exposure="High"),
                   analysis=AnalysisResult(thesis="t", bull_case="b", bear_case="r", sentiment_score=5,
                                           holder_action="HOLD", new_buyer_action="WATCH", confidence="medium"),
                   portfolio=PortfolioHolding(shares=30, bep=99, bep_currency="USD", pl_pct=50, value_eur=4000,
                                              cost_eur=2600, pl_value_eur=1400, weight_pct=40, themes=["AI"]),
                   trend="Uptrend", rank_score=70)
        md, top10 = report.generate_report([o], MacroContext(regime="neutral"), health=data_quality.RunHealth(),
                                           fx=FX, exposure=portfolio.exposure([o]), unpriced=[],
                                           changes=["First recorded run — nothing to compare yet."])
        self.assertIn("NVDA", md)
        self.assertIn("Not financial advice", md)
        self.assertEqual(top10[0].ticker, "NVDA")


class EndToEndTests(unittest.TestCase):
    """Runs main() offline: discovery/enrichment/FX are stubbed, every HTTP call fails."""

    def test_main_offline(self):
        import main
        tmp = tempfile.mkdtemp()
        holdings = ["NIO", "TSM", "SAP"]

        def fake_enrich(tickers):
            opps = []
            for t in tickers:
                if t == "NIO":
                    opps.append(Opportunity(ticker=t))  # holding without data → DEGRADED
                    continue
                opps.append(_stock(ticker=t, name=f"{t} Inc", mcap=5e10,
                                   shariah_inputs=dict(ShariahTests.INPUTS)))
            return opps, {b: _hist() for b in config.BENCHMARKS}

        def no_network(*a, **k):
            raise __import__("requests").ConnectionError("offline")

        patches = [
            mock.patch("src.discovery.discover_candidates", return_value=["AAA", "PLTR"]),
            mock.patch("src.enrichment.enrich_tickers", side_effect=fake_enrich),
            mock.patch("src.fx.get_fx", return_value=FX),
            mock.patch("src.portfolio.HOLDINGS", [{"ticker": t, "shares": 10, "bep": 100,
                                                   "bep_currency": "EUR" if t == "SAP" else "USD"} for t in holdings]),
            mock.patch("requests.get", side_effect=no_network),
            mock.patch("requests.post", side_effect=no_network),
            mock.patch("src.news._fetch_ticker_news", return_value=[]),
            mock.patch("src.news._fetch_rss_news", return_value=[]),
            mock.patch("src.ranking.fetch_rating_changes"),
            mock.patch("src.events._yahoo_earnings_date", return_value=""),
            mock.patch("src.article_reader._get_classifier", return_value=None),
            mock.patch.object(config, "GDELT_ENABLED", False),
            mock.patch.object(config, "REPORT_DIR", tmp),
            mock.patch.object(config, "ANTHROPIC_API_KEY", ""),
            mock.patch("src.journal.RUNS_DIR", os.path.join(tmp, "runs")),
            mock.patch("src.journal.DECISIONS", os.path.join(tmp, "decisions.jsonl")),
            mock.patch("src.shariah._HISTORY_PATH", os.path.join(tmp, "sh.jsonl")),
            mock.patch("src.broker_import._DIR", os.path.join(tmp, "broker")),
            mock.patch("src.events._USER_EVENTS", os.path.join(tmp, "events.json")),
            mock.patch.object(sys, "argv", ["main.py"]),
        ]
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        code = main.main()
        self.assertEqual(code, 2)  # NIO has no data → degraded
        with open(os.path.join(tmp, f"{date.today().isoformat()}.md")) as f:
            report_md = f.read()
        print("\n" + report_md[:6000]) if os.environ.get("SHOW_REPORT") else None
        self.assertIn("DEGRADED RUN", report_md)
        self.assertNotIn("PLTR", report_md)
        self.assertIn("Data Health", report_md)
        self.assertIn("SAP", report_md)
        self.assertTrue(os.listdir(os.path.join(tmp, "runs")))


if __name__ == "__main__":
    unittest.main()

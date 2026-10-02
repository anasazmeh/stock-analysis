import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import universe, filings, gdelt, article_reader, discovery, alerts  # noqa: E402
from src.models import Opportunity, PortfolioHolding, MacroContext  # noqa: E402
from src.report import _rank_score  # noqa: E402


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


class UniverseTests(unittest.TestCase):
    def test_parse_index_html_finds_symbol_table(self):
        rows = "".join(f"<tr><td>T{i}</td><td>Co {i}</td></tr>" for i in range(25))
        html = ("<table><tr><th>Other</th></tr><tr><td>x</td></tr></table>"
                "<table><tr><th>Symbol</th><th>Security</th></tr>"
                "<tr><td>BRK.B</td><td>Berkshire</td></tr>" + rows + "</table>")
        tickers = universe.parse_index_html(html)
        self.assertIn("BRK-B", tickers)
        self.assertEqual(len(tickers), 26)

    def test_parse_holdings_csv_skips_preamble_and_cash(self):
        text = ("SP Funds S&P 500 Sharia Industry Exclusions ETF\nAs of 09/30/2026\n\n"
                "Name,Ticker,Weight\nNVIDIA Corp,NVDA,10.1\nMicrosoft,MSFT,9.0\n"
                "Cash,CASH,0.2\nBerkshire,BRK.B,1.0\n")
        self.assertEqual(universe.parse_holdings_csv(text), ["NVDA", "MSFT", "BRK-B"])

    def test_universe_candidates_excludes_avoid_and_known(self):
        tags = {"PLTR": ["S&P 500"], "NVDA": ["S&P 500"], "MU": ["S&P 500"], "LRCX": ["SPUS"]}
        with mock.patch.object(universe, "get_universe_tags", return_value=tags), \
             mock.patch.object(universe, "pick_by_momentum", side_effect=lambda pool, n: pool) as pick:
            result = universe.universe_candidates(exclude={"NVDA"})
        self.assertEqual(sorted(result), ["LRCX", "MU"])
        self.assertNotIn("PLTR", pick.call_args[0][0])


class DiscoveryTests(unittest.TestCase):
    def test_curated_always_kept_and_extras_capped_in_order(self):
        with mock.patch.object(discovery, "universe_candidates", return_value=["AAA", "BBB"]), \
             mock.patch.object(discovery, "_screener_tickers", return_value=["CCC", "GRAB", "AAA"]), \
             mock.patch.object(discovery, "_regional_tickers", return_value=[]), \
             mock.patch.object(config, "MAX_DISCOVERED", 2), \
             mock.patch.object(discovery.cache, "get", return_value=None), \
             mock.patch.object(discovery.cache, "set"):
            result = discovery.discover_candidates()
        curated = [t for t in config.CURATED_WATCHLIST if t not in config.AVOID_LIST]
        self.assertEqual(result, curated + ["AAA", "BBB"])
        self.assertNotIn("GRAB", result)


class FilingsTests(unittest.TestCase):
    RECENT = {
        "form":            ["8-K", "4", "6-K", "8-K", "NT 10-Q", "10-K"],
        "filingDate":      [_days_ago(2), _days_ago(3), _days_ago(5), _days_ago(6), _days_ago(9), _days_ago(200)],
        "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001-26-000003",
                            "0001-26-000004", "0001-26-000005", "0001-25-000006"],
        "primaryDocument": ["a.htm", "f4.xml", "b.htm", "c.htm", "d.htm", "e.htm"],
        "items":           ["2.02,9.01", "", "", "4.02", "", ""],
    }

    def test_parse_labels_red_flags_and_cutoff(self):
        result = filings.parse_recent_filings("0001045810", self.RECENT, 30, config.FILINGS_FORMS)
        self.assertEqual([f["form"] for f in result], ["8-K", "6-K", "8-K", "NT 10-Q"])
        self.assertEqual(result[0]["labels"], ["Results"])
        self.assertFalse(result[0]["red_flag"])
        self.assertTrue(result[2]["red_flag"])           # 4.02 prior financials unreliable
        self.assertTrue(result[3]["red_flag"])           # late filing
        self.assertEqual(result[0]["url"],
                         "https://www.sec.gov/Archives/edgar/data/1045810/000126000001/a.htm")

    def test_fetch_attaches_to_us_tickers_only(self):
        opps = [Opportunity(ticker="NVDA"), Opportunity(ticker="2222.SR")]
        with mock.patch.object(filings, "_load_ticker_cik_map", return_value={"NVDA": "0001045810"}), \
             mock.patch.object(filings, "_get_recent_submissions", return_value=self.RECENT), \
             mock.patch.object(filings.time, "sleep"):
            filings.fetch_recent_filings(opps)
        self.assertEqual(len(opps[0].filings), 4)
        self.assertEqual(opps[1].filings, [])


class GdeltTests(unittest.TestCase):
    def test_company_query(self):
        self.assertEqual(gdelt.company_query("NVIDIA Corporation", "NVDA"),
                         'NVIDIA sourcelang:english')
        self.assertEqual(gdelt.company_query("Taiwan Semiconductor Manufacturing Company Limited", "TSM"),
                         '"Taiwan Semiconductor Manufacturing" sourcelang:english')
        self.assertEqual(gdelt.company_query("SAP SE", "SAP"),
                         '"SAP" (stock OR shares OR earnings) sourcelang:english')
        self.assertEqual(gdelt.company_query("Amazon.com, Inc.", "AMZN"),
                         'Amazon sourcelang:english')
        self.assertNotIn("sourcelang", gdelt.company_query("Saudi Arabian Oil Company", "2222.SR"))

    def test_parse_artlist(self):
        payload = {"articles": [
            {"url": "https://x.com/a", "title": "Nvidia beats estimates", "seendate": "20261001T121500Z",
             "domain": "x.com", "language": "English"},
            {"url": "https://y.com/b", "title": "", "seendate": "20261001T121500Z"},
        ]}
        result = gdelt.parse_artlist(payload, 8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-10-01")
        self.assertEqual(result[0]["provider"], "GDELT")

    def test_search_handles_plain_text_error(self):
        resp = mock.Mock(status_code=200, text="Please limit requests to one every 5 seconds")
        resp.json.side_effect = ValueError
        with mock.patch.object(gdelt.requests, "get", return_value=resp), \
             mock.patch.object(gdelt.time, "sleep"):
            self.assertEqual(gdelt.search("unique-error-query"), [])

    def test_attach_prioritises_holdings_and_dedupes(self):
        held = Opportunity(ticker="ZZZ", name="Zeta Holdings Inc", price=10,
                           portfolio=PortfolioHolding(ticker="ZZZ"),
                           news=[{"title": "Same headline"}])
        other = Opportunity(ticker="AAA", name="Alpha Corp", price=5)
        found = [{"title": "Same headline"}, {"title": "New headline"}]
        with mock.patch.object(gdelt, "search", return_value=found) as search, \
             mock.patch.object(config, "GDELT_MAX_TICKERS", 1):
            gdelt.attach_gdelt_news([other, held])
        self.assertEqual(search.call_count, 1)
        self.assertEqual([a["title"] for a in held.news], ["Same headline", "New headline"])
        self.assertEqual(other.news, [])

    def test_macro_items_go_first(self):
        macro = MacroContext(macro_news=[{"title": "old rss"}])
        with mock.patch.object(gdelt, "search", return_value=[{"title": "fresh gdelt"}]):
            gdelt.add_gdelt_macro(macro)
        self.assertEqual(macro.macro_news[0]["title"], "fresh gdelt")
        self.assertEqual(macro.macro_news[-1]["title"], "old rss")


class ArticleReaderTests(unittest.TestCase):
    def test_extract_text(self):
        body = " ".join(["ASML reported record bookings driven by AI demand for EUV tools."] * 8)
        html = (f"<html><head><title>t</title></head><body><nav>Menu Login</nav>"
                f"<article><h1>ASML results</h1><p>{body}</p><p>{body}</p></article>"
                f"<footer>Cookie policy</footer></body></html>")
        text = article_reader.extract_text(html)
        self.assertIn("record bookings", text)
        self.assertNotIn("Cookie policy", text)

    def test_score_from_probs(self):
        probs = [{"label": "positive", "score": 0.7}, {"label": "negative", "score": 0.1},
                 {"label": "neutral", "score": 0.2}]
        self.assertEqual(article_reader.score_from_probs(probs), 6.0)

    def test_google_news_links_skipped(self):
        self.assertEqual(article_reader.fetch_article_text("https://news.google.com/rss/articles/x"), "")

    def test_attach_scores_english_articles(self):
        def fake_clf(texts, **kwargs):
            return [[{"label": "positive", "score": 0.9}, {"label": "negative", "score": 0.1}]
                    for _ in texts]
        opp = Opportunity(ticker="ASML", news=[
            {"title": "Good news", "url": "", "text": "already read"},
            {"title": "خبر", "url": "", "language": "Arabic"},
        ])
        with mock.patch.object(article_reader, "_get_classifier", return_value=fake_clf):
            article_reader.attach_fulltext_sentiment([opp])
        self.assertEqual(opp.finbert_score, 8.0)
        self.assertNotIn("finbert", opp.news[1])

    def test_missing_model_is_skipped(self):
        opp = Opportunity(ticker="X", news=[{"title": "t", "url": ""}])
        with mock.patch.object(article_reader, "_get_classifier", return_value=None):
            article_reader.attach_fulltext_sentiment([opp])
        self.assertIsNone(opp.finbert_score)


class ReportAndAlertTests(unittest.TestCase):
    def test_rank_uses_finbert_when_no_ai(self):
        base = Opportunity(ticker="A", upside=20)
        with_fb = Opportunity(ticker="B", upside=20, finbert_score=8.0)
        self.assertGreater(_rank_score(with_fb), _rank_score(base))

    def test_red_flag_filing_raises_danger_alert(self):
        opp = Opportunity(ticker="LCID", price=2.5, filings=[
            {"form": "8-K", "date": _days_ago(1), "labels": ["Delisting notice"],
             "red_flag": True, "url": "u"}])
        found = alerts._check_conditions([opp])
        self.assertTrue(any(a["level"] == "DANGER" and "Delisting" in a["message"] for a in found))

    def test_share_sale_filing_warns_holders_only(self):
        filing = {"form": "S-3", "date": _days_ago(1), "labels": ["Shelf registration"],
                  "red_flag": False, "url": "u"}
        held = Opportunity(ticker="NIO", price=4, filings=[filing], portfolio=PortfolioHolding(ticker="NIO"))
        not_held = Opportunity(ticker="XYZ", price=4, filings=[filing])
        found = alerts._check_conditions([held, not_held])
        sec = [a["ticker"] for a in found if "SEC S-3" in a["message"]]
        self.assertEqual(sec, ["NIO"])


if __name__ == "__main__":
    unittest.main()

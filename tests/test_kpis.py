"""KPIs tab: account statement, XIRR, goal pace, drawdown, costs, decisions, page."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import account_statement, kpis, portfolio, dashboard_data  # noqa: E402
from src.fx import parse_ecb_xml  # noqa: E402
from src.models import Opportunity, PortfolioHolding, ShariahStatus  # noqa: E402

FX = parse_ecb_xml("<Cube time='2026-10-27'><Cube currency='USD' rate='1.10'/></Cube>")
HEAD = "Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id\n"
# Made-up account statement, newest first like DEGIRO's export
STATEMENT = HEAD + (
    '02-10-2026,05:22,01-10-2026,,,DEGIRO Real-Time Koersen Kosten (Nasdaq),,EUR,"-5,00",EUR,"-5,00",\n'
    '09-09-2026,07:35,08-09-2026,ALPHA,US1,Dividendbelasting,,USD,"-3,00",USD,"17,00",\n'
    '09-09-2026,07:35,08-09-2026,ALPHA,US1,Dividend,,USD,"20,00",USD,"20,00",\n'
    '02-09-2026,10:00,02-09-2026,,,SEPA Instant Terugstorting,,EUR,"-1000,00",EUR,"0,00",\n'
    '01-09-2026,10:00,01-09-2026,,,Terugstorting geweigerd,,EUR,"-990,00",EUR,"0,00",\n'
    '02-09-2026,10:01,02-09-2026,,,Terugstorting geweigerd,,EUR,"990,00",EUR,"0,00",\n'
    '08-04-2026,12:00,08-04-2026,,,iDEAL Deposit,,EUR,"2000,00",EUR,"4000,00",\n'
    '08-04-2026,12:00,08-04-2026,,,iDEAL Deposit,,EUR,"2000,00",EUR,"2000,00",\n'
    '08-04-2026,11:59,08-04-2026,,,Reservation iDEAL,,EUR,"2000,00",EUR,"0,00",\n'
    '01-04-2026,15:30,01-04-2026,BETA,US2,DEGIRO Transactiekosten en/of kosten van derden,,EUR,"-2,00",EUR,"0,00",\n'
    '04-11-2025,20:21,31-10-2025,,,Flatex Interest Income,,EUR,"-0,50",EUR,"0,00",\n'
    '01-03-2021,09:00,01-03-2021,,,iDEAL Deposit,,EUR,"1000,00",EUR,"1000,00",\n'
)
TODAY = date(2026, 10, 28)


def _dir(*files):
    d = tempfile.mkdtemp()
    for i, text in enumerate(files):
        with open(os.path.join(d, f"Account{i}.csv"), "w") as f:
            f.write(text)
    return d


class StatementTests(unittest.TestCase):
    def test_summary_counts_real_movements_only(self):
        s = account_statement.summarize(account_statement.load(_dir(STATEMENT)), FX, TODAY)
        self.assertEqual(s["deposits_eur"], 5000.0)            # two identical €2,000 deposits both count
        self.assertEqual(s["withdrawals_eur"], 1000.0)         # refused-withdrawal pair ignored
        self.assertEqual(s["net_invested_eur"], 4000.0)
        self.assertEqual(s["usd_dividend_withholding_pct"], 15.0)
        self.assertEqual(s["data_fee_months"], ["2026-10"])
        self.assertAlmostEqual(s["last_12m"]["dividend"], 20 / 1.10, places=2)

    def test_overlapping_exports_not_double_counted(self):
        s = account_statement.summarize(account_statement.load(_dir(STATEMENT, STATEMENT)), FX, TODAY)
        self.assertEqual(s["deposits_eur"], 5000.0)

    def test_xirr(self):
        # €1,000 in, €1,100 back exactly one year later = 10% a year
        self.assertAlmostEqual(account_statement.xirr([("2025-10-28", -1000)], 1100, TODAY), 10.0, delta=0.1)
        self.assertIsNone(account_statement.xirr([], 1000, TODAY))


def holding(t, price, shares, value, weight, themes, ccy="USD", hist=None, compliant="Yes"):
    return Opportunity(ticker=t, name=t, price=price, currency=ccy, hist_prices=hist or [price] * 300,
                       shariah=ShariahStatus(compliant=compliant),
                       portfolio=PortfolioHolding(ticker=t, shares=shares, value_eur=value, weight_pct=weight,
                                                  themes=themes, asset_type="Stock"))


class KpiTests(unittest.TestCase):
    def test_drawdown(self):
        self.assertEqual(kpis.drawdown([100, 120, 60, 90]), (-50.0, -25.0))
        self.assertEqual(kpis.drawdown([1]), (None, None))

    def test_goal_pace_net_of_new_deposits(self):
        snaps = [{"_at": datetime(2026, 4, 28), "total_value_eur": 10000}]
        with mock.patch.dict(config.INVESTOR_PROFILE, {"start_date": "2026-04-28", "start_value_eur": None}):
            k = kpis.goal_pace(16000, snaps, [("2026-06-01", -2000)], TODAY)   # €2,000 added after the start
        self.assertEqual(k["num"], 40.0)                     # (16,000 − 2,000) / 10,000 − 1
        self.assertEqual(k["status"], "warn")                # on-track path after 6 months is +41%: just behind
        with mock.patch.dict(config.INVESTOR_PROFILE, {"start_date": "2026-04-28", "start_value_eur": None}):
            self.assertEqual(kpis.goal_pace(17000, snaps, [("2026-06-01", -2000)], TODAY)["status"], "good")
            self.assertEqual(kpis.goal_pace(11000, snaps, [("2026-06-01", -2000)], TODAY)["status"], "bad")

    def test_build_kpis_statuses(self):
        falling = [100 - i * 0.2 for i in range(300)]       # −60% over the year
        opps = [holding("AAA", 40, 10, 6000, 60, ["AI"], hist=falling),
                holding("BBB", 50, 10, 4000, 40, ["Software"], ccy="EUR", compliant="No")]
        exp = portfolio.exposure(opps)
        k = kpis.build_kpis(opps, exp, FX, cash=1000, runs_dir=tempfile.mkdtemp(), broker_dir=_dir(STATEMENT),
                            market_level="Normal", today=TODAY)
        by = {i["key"]: i for i in k["items"]}
        self.assertEqual(by["net_invested"]["num"], 4000.0)
        self.assertEqual(by["total_gain"]["num"], 7000.0)            # 11,000 value − 4,000 in
        self.assertEqual(by["largest_position"]["status"], "bad")    # 60% > 20% cap
        self.assertEqual(by["drawdown_max"]["status"], "bad")
        self.assertEqual(by["withholding"]["status"], "good")
        self.assertEqual(by["data_fees"]["status"], "warn")          # charged in the statement's last month
        self.assertEqual(by["debit_interest"]["status"], "warn")
        self.assertEqual(by["shariah_share"]["num"], 60.0)
        self.assertIn("Transactions", by["hit_rate"]["detail"])      # no Transactions export → says what to add
        self.assertEqual(kpis.numbers(k)["net_invested"], 4000.0)

    def test_missing_statement_says_what_to_add(self):
        k = kpis.build_kpis([], {}, FX, cash=0, runs_dir=tempfile.mkdtemp(), broker_dir=tempfile.mkdtemp(), today=TODAY)
        self.assertIn("account statement", next(i for i in k["items"] if i["key"] == "xirr")["detail"])

    def test_track_record_vs_benchmark(self):
        snaps = [{"_at": datetime(2026, 9, 1), "top10": ["A", "B", "C"], "benchmark_close": 100,
                  "tickers": [{"ticker": t, "price": 10.0, "currency": "USD"} for t in "ABC"]}]
        opps = [Opportunity(ticker=t, price=p, currency="USD") for t, p in (("A", 12.0), ("B", 11.0), ("C", 10.0))]
        rows = kpis.track_record(snaps, opps, 105.0, TODAY)
        self.assertEqual(rows[0]["num"], 10.0)                       # average +10% vs benchmark +5%
        self.assertEqual(rows[0]["status"], "good")


class KpiPageTests(unittest.TestCase):
    def test_page_renders(self):
        from tests.test_dashboard import sample_payload
        from dashboard.app import create_app
        payload = sample_payload()
        opps = [holding("AAA", 40, 10, 6000, 60, ["AI"])]
        payload["kpis"] = kpis.build_kpis(opps, portfolio.exposure(opps), FX, cash=1000, runs_dir=tempfile.mkdtemp(),
                                          broker_dir=_dir(STATEMENT), market_level="Normal", today=TODAY)
        reports = tempfile.mkdtemp()
        dashboard_data.write_latest(payload, os.path.join(reports, "latest.json"))
        client = create_app(reports, tempfile.mkdtemp(), run_cmd=[sys.executable, "-c", "pass"]).test_client()
        html = client.get("/kpis").get_data(as_text=True)
        for needle in ("Net money in", "Annual return on your money", "Largest position", "Money in and out per year"):
            self.assertIn(needle, html)
        self.assertIn(">KPIs", client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

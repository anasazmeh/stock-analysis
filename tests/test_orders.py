"""Open broker orders: distance to fill, value, checks against the Sell review, dashboard."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import orders, dashboard_data  # noqa: E402
from src.fx import parse_ecb_xml  # noqa: E402
from src.models import Opportunity, PortfolioHolding  # noqa: E402

FX = parse_ecb_xml("<Cube time='2026-10-19'><Cube currency='USD' rate='1.125'/></Cube>")


def holding(t, price, shares, bep, cur="USD", bep_cur="USD", price_in_bep=None, **kw):
    return Opportunity(ticker=t, name=t, price=price, currency=cur, portfolio=PortfolioHolding(
        ticker=t, shares=shares, bep=bep, bep_currency=bep_cur, price_in_bep=price_in_bep), **kw)


class EvaluateTests(unittest.TestCase):
    def test_distance_value_and_gain(self):
        r = orders.evaluate({"ticker": "TSM", "side": "Sell", "qty": 10, "limit": 490.0, "currency": "USD"},
                            holding("TSM", 412.61, 20, 150.25, target=480.0, w52_high=430.0), FX)
        self.assertEqual(r["distance_pct"], 18.8)
        self.assertEqual(r["status"], "Needs +19%")
        self.assertEqual(r["share_of_position_pct"], 50.0)
        self.assertAlmostEqual(r["value_eur"], 4900 / 1.125, places=2)
        self.assertEqual(r["gain_pct"], 226.1)
        self.assertTrue(any("analyst target" in c for c in r["checks"]))

    def test_limit_below_price_fills_now(self):
        r = orders.evaluate({"ticker": "AMZN", "side": "Sell", "qty": 10, "limit": 240.0, "currency": "USD"},
                            holding("AMZN", 250.0, 20, 167.12), FX)
        self.assertEqual(r["status"], "Fills now")

    def test_more_shares_than_held(self):
        r = orders.evaluate({"ticker": "TEM", "side": "Sell", "qty": 12, "limit": 69.0, "currency": "EUR"},
                            holding("TEM", 64.72, 10, 55.0, bep_cur="EUR", price_in_bep=57.5), FX)
        self.assertTrue(any("you hold 10" in c for c in r["checks"]))
        self.assertEqual(r["price"], 57.5)                         # EUR order priced from the EUR breakeven line
        self.assertTrue(any("check the EUR quote" in c for c in r["checks"]))

    def test_stop_the_loss_needs_a_stop_order(self):
        review = {"category": "Stop the loss", "metrics": {"trail_stop_price": 150.0}}
        r = orders.evaluate({"ticker": "X", "side": "Sell", "qty": 5, "limit": 220.0, "currency": "USD"},
                            holding("X", 180.0, 5, 200.0), FX, review)
        self.assertTrue(any("stop-loss order near the trailing stop" in c for c in r["checks"]))

    def test_take_profit_covered_by_order(self):
        o = holding("NVDA", 214.13, 30, 99.0)
        review = {"ticker": "NVDA", "category": "Take profit", "sell_units": 7.0, "action": "Sell 7 of 30 shares"}
        with mock.patch.object(orders, "load_orders",
                               return_value=[{"ticker": "NVDA", "side": "Sell", "qty": 10, "limit": 240.0, "currency": "USD"}]):
            rows = orders.evaluate_orders([o], FX, [review])
        self.assertIn("already covers this", review["action"])
        self.assertEqual(review["open_orders"][0]["qty"], 10)
        self.assertEqual(o.open_orders[0]["limit"], 240.0)
        self.assertEqual(orders.summary(rows)["count"], 1)

    def test_avoid_list_orders_ignored(self):
        import portfolio_data
        with mock.patch.object(portfolio_data, "OPEN_ORDERS", [{"ticker": "PLTR", "qty": 1, "limit": 1.0}]):
            self.assertEqual(orders.load_orders(), [])

    def test_portfolio_orders_load(self):
        loaded = orders.load_orders()
        self.assertTrue(all(o["qty"] > 0 and o["limit"] > 0 for o in loaded))


class DashboardOrdersTests(unittest.TestCase):
    def test_sell_and_cash_pages_show_orders(self):
        from tests.test_dashboard import sample_payload
        from dashboard.app import create_app
        payload = sample_payload()
        o = holding("NVDA", 180.0, 30, 99.0)
        with mock.patch.object(orders, "load_orders",
                               return_value=[{"ticker": "NVDA", "side": "Sell", "qty": 10, "limit": 240.0,
                                              "currency": "USD", "validity": "GTC", "placed": "2026-10-18"}]):
            rows = orders.evaluate_orders([o], FX, payload["sell_review"])
        payload["open_orders"] = rows
        payload["cash_plan"]["open_orders"] = orders.summary(rows)
        reports = tempfile.mkdtemp()
        dashboard_data.write_latest(payload, os.path.join(reports, "latest.json"))
        client = create_app(reports, tempfile.mkdtemp(), run_cmd=[sys.executable, "-c", "pass"]).test_client()
        sell = client.get("/sell").get_data(as_text=True)
        self.assertIn("Your open orders", sell)
        self.assertIn("Sell 10 NVDA", sell)
        self.assertIn("Open order: sell 10 @ 240.00 USD", sell)
        self.assertIn("open sell order(s) would add", client.get("/cash").get_data(as_text=True))
        self.assertIn("Open order", client.get("/stock/NVDA").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

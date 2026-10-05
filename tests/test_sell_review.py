import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.fx import parse_ecb_xml
from src.models import Opportunity, PortfolioHolding, RiskProfile, ShariahStatus, AnalysisResult
from src.sell_review import compute_exit_metrics, review_holdings, review_holding

FX = parse_ecb_xml("<Cube time='2026-10-02'><Cube currency='USD' rate='1.25'/></Cube>")


def holding(ticker="T", price=100.0, bep=100.0, shares=30, weight=8.0, prices=None, **kw):
    pl = (price / bep - 1) * 100
    value = shares * price / 1.25
    o = Opportunity(ticker=ticker, name=ticker, price=price, currency="USD", price_type="last close",
                    hist_prices=prices or [price] * 200, ma50=price, ma200=price, trend="Mixed",
                    risk=RiskProfile(volatility_30d=30.0, rsi_14=50), price_check="Verified",
                    shariah=ShariahStatus(compliant="Yes"),
                    portfolio=PortfolioHolding(ticker=ticker, shares=shares, bep=bep, bep_currency="USD", pl_pct=pl,
                                               value_eur=value, pl_value_eur=value - value / (1 + pl / 100),
                                               weight_pct=weight))
    for k, v in kw.items():
        setattr(o, k, v)
    compute_exit_metrics(o)
    return o


class ExitMetricsTests(unittest.TestCase):
    def test_trailing_stop_from_6m_high(self):
        prices = [100.0] * 100 + [150.0] + [120.0] * 50
        o = holding(price=120.0, prices=prices)
        m = o.exit_metrics
        self.assertEqual(m["high_6m"], 150.0)
        self.assertEqual(m["drawdown_from_high_pct"], -20.0)
        # 2 x 30% / sqrt(12) = 17.3% stop distance
        self.assertAlmostEqual(m["trail_stop_pct"], 17.3, places=1)
        self.assertTrue(m["trail_stop_hit"])

    def test_short_history_leaves_metrics_out(self):
        o = holding(prices=[100.0] * 20)
        self.assertNotIn("trail_stop_price", o.exit_metrics)


class SellReviewTests(unittest.TestCase):
    def test_strong_stop_loss_sells_all(self):
        o = holding(price=70.0, bep=100.0, trend="Downtrend", prices=[100.0] * 100 + [70.0] * 100)
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Stop the loss")
        self.assertEqual(r["strength"], "Strong")
        self.assertEqual(r["sell_units"], 30)
        self.assertAlmostEqual(r["proceeds_eur"], 30 * 70 / 1.25)
        self.assertLess(r["realised_pl_eur"], 0)

    def test_protect_gains_when_trend_breaks_in_profit(self):
        o = holding(price=150.0, bep=100.0, trend="Downtrend", prices=[100.0] * 50 + [190.0] * 100 + [150.0] * 50)
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Protect gains")

    def test_take_profit_at_target(self):
        o = holding(price=210.0, bep=100.0, target=200.0, adj_upside=-5.0, trend="Uptrend")
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Take profit")
        self.assertEqual(r["strength"], "Strong")
        self.assertEqual(r["sell_units"], 10)       # a third of 30
        self.assertTrue(r["keep"])                   # uptrend is listed as a reason to keep

    def test_trim_to_cap(self):
        o = holding(weight=24.0, trend="Uptrend")
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Trim to cap")
        self.assertEqual(r["sell_units"], 15)       # 1 - 12/24 = half

    def test_bad_data_gets_no_suggestion(self):
        o = holding(price=70.0, bep=100.0, trend="Downtrend", price_check="Mismatch", price_diff_pct=8.0)
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Check data first")
        self.assertNotIn("sell_units", r)
        r = review_holding(holding(ticker="X"), FX, broker_bad={"X"})
        self.assertEqual(r["category"], "Check data first")

    def test_shariah_is_listed_but_never_changes_the_verdict(self):
        o = holding(shariah=ShariahStatus(compliant="No", reasons=["debt 40%"]))
        r = review_holding(o, FX)
        self.assertEqual(r["category"], "Shariah review")
        self.assertEqual(r["strength"], "")
        self.assertNotIn("sell_units", r)
        weak = holding(price=88.0, bep=100.0, trend="Downtrend")
        no = holding(price=88.0, bep=100.0, trend="Downtrend", shariah=ShariahStatus(compliant="No"))
        self.assertEqual(review_holding(weak, FX)["score"], review_holding(no, FX)["score"])

    def test_hold_and_ordering_and_avoid_list(self):
        calm = holding(ticker="CALM", trend="Uptrend")
        bad = holding(ticker="BAD", price=70.0, bep=100.0, trend="Downtrend")
        avoid = holding(ticker=sorted(config.AVOID_LIST)[0], price=70.0, bep=100.0, trend="Downtrend")
        rows = review_holdings([calm, bad, avoid], FX)
        self.assertEqual([r["ticker"] for r in rows], ["BAD", "CALM"])
        self.assertEqual(rows[1]["category"], "Hold")
        self.assertEqual(bad.sell_review["category"], "Stop the loss")

    def test_claude_view_counts(self):
        o = holding(price=95.0, bep=100.0, analysis=AnalysisResult(holder_action="REVIEW_EXIT", confidence="high"))
        self.assertIn("Claude: review exit", " ".join(s["text"] for s in review_holding(o, FX)["signals"]))


if __name__ == "__main__":
    unittest.main()

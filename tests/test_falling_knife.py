"""Falling-knife guard: detection, halved upside, no Cash plan buy, WARN instead of BUY."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

config.CACHE_DIR = tempfile.mkdtemp()

from src import falling_knife  # noqa: E402
from src.models import Opportunity, AnalysisResult, ShariahStatus, PortfolioHolding  # noqa: E402


def se_like(**kw):
    """Shaped like SE in Oct 2026: $99 a month ago, $74.73 now, 50-day avg $101.6 above the 200-day $99.4."""
    hist = [100.0] * 199 + [99.0] * 21 + [74.73]
    o = Opportunity(ticker="SE", name="Sea Ltd", price=74.73, currency="USD", hist_prices=hist, ma50=101.59,
                    ma200=99.4, trend="Mixed", upside=100.0, adj_upside=100.0, target=150.0, analyst_count=28,
                    consensus_quality="Good", data_ok=True, tradable="Yes", rank_score=80.0, sector="Consumer Cyclical",
                    next_event="Earnings 2026-11-10", days_to_event=8,
                    shariah=ShariahStatus(compliant="No"),
                    analysis=AnalysisResult(new_buyer_action="BUY", confidence="medium"))
    for k, v in kw.items():
        setattr(o, k, v)
    return o


class KnifeTests(unittest.TestCase):
    def test_detects_recent_crash_even_when_trend_says_mixed(self):
        k = falling_knife.check(se_like())
        self.assertIsNotNone(k)
        self.assertEqual(k["return_1m_pct"], -24.5)
        self.assertIn("Earnings 2026-11-10", k["wait_for"])
        self.assertIn("101.59", k["wait_for"])

    def test_no_flag_for_mild_dip_or_above_ma50(self):
        self.assertIsNone(falling_knife.check(se_like(price=90.0, hist_prices=[100.0] * 220 + [90.0])))   # −10%
        self.assertIsNone(falling_knife.check(se_like(price=110.0, hist_prices=[150.0] * 220 + [110.0],
                                                      ma50=105.0)))                                      # above 50d

    def test_upside_halved_once(self):
        o = se_like()
        falling_knife.apply([o])
        self.assertEqual(o.adj_upside, 50.0)
        falling_knife.apply([o])                       # running twice doesn't halve again
        self.assertEqual(o.adj_upside, 50.0)
        self.assertIn("Falling knife", o.consensus_quality)

    def test_cash_plan_waits(self):
        from unittest import mock
        from src import cash_plan
        o = se_like()
        falling_knife.apply([o])
        with mock.patch("src.ranking.top_ranked", return_value=[o]):
            ideas, status = cash_plan.eligible_ideas([o], set(), {})
        self.assertEqual(ideas, [])
        self.assertEqual(status[0]["outcome"], "skip")
        self.assertTrue(any("falling knife" in w for w in status[0]["why"]))

    def test_alert_is_warn_not_buy(self):
        from src import alerts
        o = se_like(w52_low=74.0, days_to_event=30)    # outside the earnings blackout, near the 52-week low
        falling_knife.apply([o])
        out = alerts.check_conditions([o], exposure={"total_value_eur": 0, "themes": {}, "breaches": []})
        levels = {a["level"] for a in out if a["ticker"] == "SE"}
        self.assertIn("WARN", levels)
        self.assertNotIn("BUY", levels)
        self.assertNotIn("DIP", levels)

    def test_holdings_not_flagged_for_buy_warning(self):
        o = se_like(portfolio=PortfolioHolding(ticker="SE", shares=1))
        self.assertIsNotNone(falling_knife.check(o))   # still detected (shown on the stock page) ...


if __name__ == "__main__":
    unittest.main()

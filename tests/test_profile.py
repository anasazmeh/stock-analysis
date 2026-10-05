import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import ranking, intelligence
from src.models import Opportunity, RiskProfile


def stock(t, upside, rev, eps=0.0, risk=5.0, dd=30.0, trend="Uptrend"):
    return Opportunity(ticker=t, price=10, data_ok=True, tradable="Yes", adj_upside=upside, rev_growth=rev, eps_growth=eps,
                       trend=trend, risk=RiskProfile(composite_score=risk, max_drawdown_6mo=dd))


class ProfileTests(unittest.TestCase):
    def test_profile_settings(self):
        self.assertTrue(config.PROFILE_ON)
        self.assertEqual(config.INVESTOR_PROFILE["target_return_pct"], 100.0)
        self.assertEqual(config.POSITION_CAP_PCT, 20.0)
        self.assertEqual(config.SELL_STOP_LOSS_PCT, -35.0)
        self.assertEqual(config.SELL_TAKE_PROFIT_PCT, 100.0)

    def test_fast_grower_outranks_steady_name_with_profile(self):
        grower = stock("CRDO", upside=40, rev=150, eps=200, risk=7.5)      # volatile, very fast growth
        steady = stock("STEADY", upside=40, rev=4, eps=5, risk=2.0)        # calm, slow growth
        with mock.patch.object(config, "PROFILE_ON", True):
            self.assertGreater(ranking.rank_score(grower), ranking.rank_score(steady))
        with mock.patch.object(config, "PROFILE_ON", False):
            self.assertLess(ranking.rank_score(grower), ranking.rank_score(steady))   # balanced weights favour calm

    def test_growth_value_and_missing(self):
        self.assertIsNone(ranking.growth_value(stock("X", 10, 0.0, 0.0)))
        self.assertEqual(ranking.growth_value(stock("X", 10, 50.0, 100.0)), 1.0)

    def test_goal_fit_levels(self):
        self.assertEqual(ranking.goal_fit(stock("A", upside=70, rev=10))["level"], "Strong")
        self.assertEqual(ranking.goal_fit(stock("B", upside=35, rev=10))["level"], "Possible")
        self.assertEqual(ranking.goal_fit(stock("C", upside=10, rev=5))["level"], "Unlikely")
        g = ranking.goal_fit(stock("D", upside=80, rev=60, dd=65))
        self.assertEqual(g["level"], "Possible")                         # fell more than the accepted 50%
        self.assertTrue(any("more than the 50%" in n for n in g["notes"]))

    def test_claude_gets_the_goal(self):
        self.assertIn("+100% within 12 months", intelligence.SYSTEM)
        self.assertIn("drops of up to 50%", intelligence.SYSTEM)
        with mock.patch.dict(config.INVESTOR_PROFILE, {"enabled": False}):
            self.assertEqual(intelligence.profile_text(), "")


if __name__ == "__main__":
    unittest.main()

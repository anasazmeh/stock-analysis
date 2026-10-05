import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import cash_plan
from src.fx import parse_ecb_xml
from src.models import Opportunity, PortfolioHolding, RiskProfile, ShariahStatus, AnalysisResult, MacroContext

FX = parse_ecb_xml("<Cube time='2026-10-02'><Cube currency='USD' rate='1.25'/></Cube>")
CALM = MacroContext(vix=13.0, hy_spread=3.0, yield_spread=0.5, regime="risk-on")
STRESSED = MacroContext(vix=34.0, hy_spread=6.0, yield_spread=-0.3, regime="risk-off")
SPY_UP = [100 + i * 0.1 for i in range(260)]
SPY_DOWN = [130 - i * 0.12 for i in range(260)]


def idea(t, sector="Healthcare", score=70, vol=25.0, action="BUY", conf="high", price=100.0, **kw):
    o = Opportunity(ticker=t, name=t, sector=sector, price=price, currency="USD", data_ok=True, tradable="Yes",
                    price_check="Verified", trend="Uptrend", adj_upside=25.0, analyst_count=20, rank_score=score,
                    risk=RiskProfile(volatility_30d=vol), shariah=ShariahStatus(compliant="Yes"),
                    analysis=AnalysisResult(new_buyer_action=action, confidence=conf, holder_action="N/A"))
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def held(t, value, sector="Technology", **kw):
    o = idea(t, sector=sector, **kw)
    o.portfolio = PortfolioHolding(ticker=t, shares=10, value_eur=value, weight_pct=None)
    o.analysis.holder_action = "HOLD"
    o.analysis.new_buyer_action = "WATCH"
    return o


def sale(t, proceeds, realised, strength="Strong"):
    return {"ticker": t, "strength": strength, "sell_units": 5, "proceeds_eur": proceeds, "realised_pl_eur": realised,
            "currency": "USD", "action": "Sell 5 of 10 shares", "category": "Take profit"}


class MarketTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(cash_plan.assess_market(CALM, {"SPY": SPY_UP})["level"], "Calm")
        m = cash_plan.assess_market(STRESSED, {"SPY": SPY_DOWN})
        self.assertEqual(m["level"], "Stressed")
        self.assertTrue(any(s["name"] == "US high-yield spread" and s["points"] == 2 for s in m["signals"]))

    def test_missing_inputs_listed_not_guessed(self):
        m = cash_plan.assess_market(MacroContext(), {})
        self.assertEqual(m["level"], "Normal")
        self.assertTrue(any("VIX" in x for x in m["missing"]))

    def test_event_soon(self):
        macro = MacroContext(vix=13, events=[{"date": "2026-10-07", "name": "FOMC"}])
        m = cash_plan.assess_market(macro, {}, today=date(2026, 10, 5))
        self.assertEqual(m["events_soon"][0]["days"], 2)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(cash_plan, "cash_balances", return_value={"DEGIRO": 0.0}),
                  mock.patch.object(cash_plan, "planned_withdrawals", return_value=0.0),
                  mock.patch.object(config, "CAPITAL_GAINS_TAX_RATE", 0.0)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def plan(self, opps, rows, macro=CALM, spy=SPY_UP, total=20000.0):
        return cash_plan.build_cash_plan(opps, rows, macro, {"SPY": spy}, FX, {"total_value_eur": total},
                                         today=date(2026, 10, 5))

    def test_money_adds_up_and_reserve_kept(self):
        opps = [held("NVDA", 8000), idea("LLY", "Healthcare"), idea("JPM", "Financials", score=60)]
        s = self.plan(opps, [sale("NVDA", 4000, 1500)])["scenarios"][0]
        self.assertAlmostEqual(s["available_eur"], 4000 - s["sell_fees_eur"])
        self.assertAlmostEqual(s["keep_eur"] + s["invest_eur"] + s["unallocated_eur"], s["available_eur"], places=2)
        self.assertAlmostEqual(s["reserve_eur"], 0.05 * s["portfolio_after_eur"])   # Calm → 5%
        self.assertEqual({b["ticker"] for b in s["buys"]}, {"LLY", "JPM"})
        self.assertNotIn("NVDA", {b["ticker"] for b in s["buys"]})                  # never buy back what you sell

    def test_stressed_market_keeps_more_and_uses_tranches(self):
        opps = [held("NVDA", 8000), idea("LLY")]
        calm = self.plan(opps, [sale("NVDA", 4000, 1500)])["scenarios"][0]
        hot = self.plan(opps, [sale("NVDA", 4000, 1500)], STRESSED, SPY_DOWN)["scenarios"][0]
        self.assertGreater(hot["keep_eur"], calm["keep_eur"])
        self.assertEqual(len(hot["buys"][0]["tranches"]), 3)

    def test_no_good_ideas_means_cash(self):
        opps = [held("NVDA", 8000), idea("BAD", action="AVOID"), idea("DOWN", trend="Downtrend"),
                idea("NOTRADE", tradable="Watch only")]
        plan = self.plan(opps, [sale("NVDA", 4000, 1500)])
        s = plan["scenarios"][0]
        self.assertEqual(s["buys"], [])
        self.assertAlmostEqual(s["cash_end_eur"], s["available_eur"], places=2)
        self.assertTrue(any("stays in cash" in r for r in plan["reasoning"]))
        why = {t["ticker"]: t for t in s["top10_status"]}
        self.assertEqual(why["BAD"]["outcome"], "skip")
        self.assertIn("in a downtrend", why["DOWN"]["why"])
        self.assertNotIn("NOTRADE", why)        # watch-only names don't take a Top 10 place

    def test_tax_reserve_from_realised_gains(self):
        with mock.patch.object(config, "CAPITAL_GAINS_TAX_RATE", 0.25):
            s = self.plan([held("NVDA", 8000)], [sale("NVDA", 4000, 2000), sale("X", 1000, -400)])["scenarios"][0]
        self.assertAlmostEqual(s["tax_reserve_eur"], (2000 - 400) * 0.25)

    def test_position_cap_and_max_share(self):
        opps = [held("NVDA", 8000), idea("ONE")]
        s = self.plan(opps, [sale("NVDA", 6000, 1500)])["scenarios"][0]
        (b,) = s["buys"]
        self.assertLessEqual(b["eur"], config.REINVEST_MAX_SHARE * s["deployable_eur"] + 1)
        self.assertGreater(s["unallocated_eur"], 0)

    def test_follows_top10_order_and_rank_weights(self):
        opps = [held("NVDA", 8000, score=90)] + [idea(f"T{i}", score=80 - i) for i in range(12)]
        s = self.plan(opps, [sale("NVDA", 4000, 1500)], total=20000)["scenarios"][0]
        status = s["top10_status"]
        self.assertEqual([t["rank"] for t in status], list(range(1, 11)))      # exactly the Opportunities Top 10
        self.assertEqual(status[0]["ticker"], "NVDA")
        self.assertIn("you're selling it in this plan", status[0]["why"])
        bought = [b["ticker"] for b in s["buys"]]
        self.assertEqual(bought, ["T0", "T1", "T2", "T3", "T4"])               # first five eligible, in rank order
        self.assertNotIn("T10", bought)                                         # outside the Top 10: never bought
        eur = [b["eur"] for b in s["buys"]]
        self.assertEqual(eur, sorted(eur, reverse=True))                       # higher score, more money
        waits = [t for t in status if t["outcome"] == "wait"]
        self.assertTrue(all("at most" in t["why"][0] for t in waits))

    def test_reasoning_explains_skips_and_cash(self):
        opps = [held("NVDA", 8000, score=90), idea("W1", action="WATCH", score=85), idea("W2", trend="Downtrend", score=80),
                idea("OK", score=70)]
        plan = self.plan(opps, [sale("NVDA", 6000, 1500)])
        text = " ".join(plan["scenarios"][0]["reasoning"])
        self.assertIn("#2 W1", text)
        self.assertIn("#3 W2", text)
        self.assertIn("couldn't go into the Top 10: 1 idea(s) qualified", text)
        self.assertIn("Keep ready", text)

    def leftover(self, opps, macro=CALM, spy=SPY_UP, **bench):
        b = {"SPY": spy, **bench}
        return cash_plan.build_cash_plan(opps, [sale("NVDA", 6000, 1500)], macro, b, FX, {"total_value_eur": 20000.0},
                                         today=date(2026, 10, 5))["scenarios"][0]

    def test_leftover_ready_for_watched_names(self):
        s = self.leftover([held("NVDA", 8000, score=90), idea("W1", action="WATCH", score=85), idea("OK", score=70)])
        uses = {d["use"]: d for d in s["leftover_plan"]}
        self.assertEqual(uses["Keep ready"]["tickers"], ["W1"])
        self.assertGreater(s["ready_eur"], 0)
        self.assertAlmostEqual(s["keep_eur"] + s["invest_eur"] + s["unallocated_eur"], s["available_eur"], places=2)

    def test_leftover_held_in_nervous_market(self):
        s = self.leftover([held("NVDA", 8000, score=90), idea("OK", score=70)], STRESSED, SPY_DOWN,
                          **{"ISWD.L": [50.0] * 300})
        self.assertEqual([d["use"] for d in s["leftover_plan"]], ["Hold as cash"])
        self.assertFalse(any(b.get("parking") for b in s["buys"]))

    def test_leftover_next_in_line_then_etf_in_calm_market(self):
        opps = [held("NVDA", 8000, score=95)] + [idea(f"T{i}", score=90 - i, action="WATCH", adj_upside=5.0) for i in range(8)]
        opps += [idea("TOP", score=60), idea("NEXT", score=40), idea("NEXT2", score=39)]
        s = self.leftover(opps, **{"ISWD.L": [50.0] * 300})
        uses = [d["use"] for d in s["leftover_plan"]]
        self.assertIn("Next-in-line stocks", uses)
        self.assertIn("Broad Shariah ETF", uses)
        etf = next(b for b in s["buys"] if b.get("parking"))
        self.assertEqual(etf["ticker"], "ISWD.L")
        self.assertLessEqual(etf["weight_after_pct"], config.PARKING_MAX_PCT)
        self.assertTrue(all("share_pct" in b and "tranches" in b for b in s["buys"]))
        self.assertAlmostEqual(sum(b["share_pct"] for b in s["buys"]), 100, delta=0.5)
        self.assertAlmostEqual(s["keep_eur"] + s["invest_eur"] + s["unallocated_eur"], s["available_eur"], places=2)

    def test_leftover_policy_cash(self):
        with mock.patch.object(config, "LEFTOVER_POLICY", "cash"):
            s = self.leftover([held("NVDA", 8000, score=90), idea("OK", score=70)], **{"ISWD.L": [50.0] * 300})
        self.assertEqual([d["use"] for d in s["leftover_plan"]], ["Hold as cash"])

    def test_earnings_soon_waits(self):
        opps = [held("NVDA", 8000), idea("LLY", next_event="Earnings 2026-10-08", days_to_event=3)]
        s = self.plan(opps, [sale("NVDA", 4000, 1500)])["scenarios"][0]
        self.assertIn("after Earnings", s["buys"][0]["tranches"][0]["when"])

    def test_shariah_only_setting(self):
        opps = [held("NVDA", 8000), idea("NOPE", shariah=ShariahStatus(compliant="No"))]
        self.assertTrue(self.plan(opps, [sale("NVDA", 4000, 1500)])["scenarios"][0]["buys"])
        with mock.patch.object(config, "REINVEST_SHARIAH_ONLY", True):
            self.assertFalse(self.plan(opps, [sale("NVDA", 4000, 1500)])["scenarios"][0]["buys"])

    def test_existing_cash_fills_reserve_first_and_avoid_list(self):
        bad = sorted(config.AVOID_LIST)[0]
        opps = [held("NVDA", 8000), idea(bad), idea("LLY")]
        with mock.patch.object(cash_plan, "cash_balances", return_value={"DEGIRO": 3000.0}):
            s = self.plan(opps, [sale("NVDA", 1000, 300)])["scenarios"][0]
        self.assertEqual(s["existing_cash_eur"], 3000.0)
        self.assertNotIn(bad, {b["ticker"] for b in s["buys"]})

    def test_second_scenario_includes_consider(self):
        opps = [held("NVDA", 8000), held("SAP", 4000), idea("LLY")]
        plan = self.plan(opps, [sale("NVDA", 3000, 1000), sale("SAP", 1500, 100, "Consider")])
        a, b = plan["scenarios"]
        self.assertGreater(b["proceeds_eur"], a["proceeds_eur"])
        self.assertTrue(plan["data_gaps"])


if __name__ == "__main__":
    unittest.main()

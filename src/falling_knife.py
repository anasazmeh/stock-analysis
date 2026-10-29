"""
Falling-knife guard.

A stock that dropped hard in the last month and trades well below its 50-day
average often keeps falling, and its analyst targets were mostly set before the
drop, so "upside to target" overstates the opportunity. While the guard is on:

  - the quality-adjusted upside counts at KNIFE_UPSIDE_FACTOR (half) in the ranking;
  - the Cash plan doesn't buy it yet — it waits for the next results or a close
    back above the 50-day average;
  - BUY and DIP alerts become a WARN ("still falling");
  - Claude sees the flag in its evidence.

The guard clears by itself once the 1-month fall is smaller than KNIFE_1M_DROP_PCT
or the price closes back above its 50-day average. Holdings are unaffected
(the Sell review has its own stop rules).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

import config
from src.models import Opportunity

_1M = 21


def check(opp: Opportunity) -> Optional[dict]:
    prices = [p for p in (opp.hist_prices or []) if p and p > 0]
    if not opp.price or not opp.ma50 or len(prices) <= _1M:
        return None
    ret_1m = (opp.price / prices[-_1M - 1] - 1) * 100
    below_ma50 = (opp.price / opp.ma50 - 1) * 100
    if ret_1m > config.KNIFE_1M_DROP_PCT or below_ma50 >= 0:
        return None
    knife = {"return_1m_pct": round(ret_1m, 1), "below_ma50_pct": round(below_ma50, 1),
             "ma50": round(opp.ma50, 2), "below_ma200": bool(opp.ma200 and opp.price < opp.ma200)}
    when = []
    if opp.next_event and opp.days_to_event is not None and opp.days_to_event <= 45:
        when.append(f"after {opp.next_event}")
    when.append(f"a close above the 50-day average ({opp.ma50:,.2f} {opp.currency})")
    knife["wait_for"] = " or ".join(when)
    knife["text"] = (f"Falling knife: {ret_1m:+.0f}% in a month, {below_ma50:.0f}% below its 50-day average — "
                     f"analyst targets likely predate the drop. Wait for {knife['wait_for']}.")
    return knife


def apply(opportunities: list[Opportunity]) -> list[Opportunity]:
    flagged = []
    for opp in opportunities:
        prev = opp.falling_knife or {}
        base = prev.get("upside_before", opp.adj_upside)    # the upside before any earlier halving
        opp.falling_knife = check(opp)
        if opp.falling_knife and base is not None:
            opp.falling_knife["upside_before"] = base
            opp.adj_upside = round(base * config.KNIFE_UPSIDE_FACTOR, 1)
            if "Falling knife" not in (opp.consensus_quality or ""):
                opp.consensus_quality = f"{opp.consensus_quality} + Falling knife" if opp.consensus_quality else "Falling knife"
        elif prev.get("upside_before") is not None:          # cleared since the last check: undo the halving
            opp.adj_upside = prev["upside_before"]
        if opp.falling_knife:
            flagged.append(f"{opp.ticker} ({opp.falling_knife['return_1m_pct']:+.0f}% 1m)")
    if flagged:
        print(f"  [falling-knife] {len(flagged)} flagged — upside halved, no buys yet: {', '.join(flagged)}")
    return opportunities

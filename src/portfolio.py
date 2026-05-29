"""
Portfolio P&L tracker — attaches user holdings data to pipeline opportunities.
Holdings defined in portfolio_data.py at the project root.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import Opportunity, PortfolioHolding

try:
    from portfolio_data import HOLDINGS
except ImportError:
    HOLDINGS = []


def attach_portfolio(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Attach current P&L data to opportunities matching the user's holdings."""
    if not HOLDINGS:
        return opportunities

    holding_map = {h["ticker"]: h for h in HOLDINGS}
    matched = 0

    for opp in opportunities:
        if opp.ticker not in holding_map:
            continue
        h = holding_map[opp.ticker]

        pl_pct = pl_value = None
        if opp.price > 0 and h["bep"] > 0:
            pl_pct  = round((opp.price / h["bep"] - 1) * 100, 1)
            pl_value = round((opp.price - h["bep"]) * h["shares"], 2)

        opp.portfolio = PortfolioHolding(
            ticker=opp.ticker,
            shares=h["shares"],
            bep=h["bep"],
            bep_currency=h.get("bep_currency", "USD"),
            current_price=opp.price,
            pl_pct=pl_pct,
            pl_value=pl_value,
            status=h.get("status", ""),
        )
        matched += 1

    return opportunities


def get_portfolio_tickers() -> list[str]:
    """Return list of all portfolio ticker symbols."""
    return [h["ticker"] for h in HOLDINGS]

"""
Stage 5 — Risk Assessment
Computes quantitative risk metrics for each opportunity.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import config
from src.models import Opportunity, RiskProfile


def _compute_rsi(prices: list[float], period: int = 14) -> float:
    """Compute RSI(14) from a list of close prices."""
    if len(prices) < period + 1:
        return 50.0
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [max(c, 0) for c in changes[-period:]]
    losses = [max(-c, 0) for c in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _compute_volatility(prices: list[float], days: int = 30) -> float:
    """Compute annualized 30-day volatility from close prices."""
    if len(prices) < days + 1:
        return 0.0
    recent = prices[-(days+1):]
    returns = [(recent[i] / recent[i-1] - 1) for i in range(1, len(recent))]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 2)  # annualized %


def _compute_max_drawdown(prices: list[float]) -> float:
    """Compute max drawdown % over the price series."""
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            dd = (peak - p) / peak
            max_dd = max(max_dd, dd)
    return round(max_dd * 100, 2)  # as percentage


def _geo_score(country: str) -> float:
    """Convert geo exposure string to a 0-1 score."""
    level = config.GEO_EXPOSURE.get(country, "Medium")
    return {"Low": 0.2, "Medium": 0.5, "High": 0.9}.get(level, 0.5)


def _rsi_extreme_score(rsi: float) -> float:
    """Score based on RSI extremity (overbought/oversold risk)."""
    if rsi > 80:
        return 0.9   # very overbought
    if rsi > 70:
        return 0.6
    if rsi < 20:
        return 0.7   # very oversold (price risk)
    if rsi < 30:
        return 0.4
    return 0.2       # neutral zone


def compute_risk(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Compute risk profile for each opportunity."""
    for opp in opportunities:
        prices = opp.hist_prices

        beta_val    = opp.beta or 1.0
        vol         = _compute_volatility(prices)
        drawdown    = _compute_max_drawdown(prices)
        de          = opp.de or 0.0
        rsi         = _compute_rsi(prices)
        geo         = config.GEO_EXPOSURE.get(opp.country, "Medium")

        # Normalize each metric to 0-1 risk scale
        beta_score  = min(abs(beta_val) / 5.0, 1.0)
        vol_score   = min(vol / 100.0, 1.0)
        dd_score    = min(drawdown / 50.0, 1.0)
        debt_score  = min(de / 300.0, 1.0)   # D/E > 300 = max risk
        geo_score   = _geo_score(opp.country)
        rsi_score   = _rsi_extreme_score(rsi)

        w = config.RISK_WEIGHTS
        composite = (
            w["beta"]        * beta_score  +
            w["volatility"]  * vol_score   +
            w["drawdown"]    * dd_score    +
            w["debt"]        * debt_score  +
            w["geo"]         * geo_score   +
            w["rsi_extreme"] * rsi_score
        ) * 10.0  # scale to 1-10

        opp.risk = RiskProfile(
            beta=beta_val,
            volatility_30d=vol,
            max_drawdown_6mo=drawdown,
            debt_to_equity=de,
            rsi_14=rsi,
            geo_exposure=geo,
            composite_score=round(max(1.0, min(10.0, composite)), 2),
        )

    return opportunities

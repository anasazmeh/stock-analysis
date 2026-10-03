"""
Stage 5 — Risk and trend.

Risk metrics are None when there is not enough data; the composite only uses the
components that exist and records how much of the weight was covered.
Trend compares the price with its 50/200-day averages and with benchmark ETFs.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from typing import Optional

import config
from src.models import Opportunity, RiskProfile

_6M = 126  # trading days


def compute_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(len(prices) - period, len(prices))]
    avg_gain = sum(max(c, 0) for c in changes) / period
    avg_loss = sum(max(-c, 0) for c in changes) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def compute_volatility(prices: list[float], days: int = 30) -> Optional[float]:
    if len(prices) < days + 1:
        return None
    recent = prices[-(days + 1):]
    returns = [recent[i] / recent[i - 1] - 1 for i in range(1, len(recent)) if recent[i - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)


def compute_max_drawdown(prices: list[float], window: int = _6M) -> Optional[float]:
    series = prices[-window:]
    if len(series) < 60:
        return None
    peak, max_dd = series[0], 0.0
    for p in series:
        peak = max(peak, p)
        if peak > 0:
            max_dd = max(max_dd, (peak - p) / peak)
    return round(max_dd * 100, 2)


def _rsi_extreme_score(rsi: float) -> float:
    if rsi > 80: return 0.9
    if rsi > 70: return 0.6
    if rsi < 20: return 0.7
    if rsi < 30: return 0.4
    return 0.2


def geo_level(opp: Opportunity) -> tuple[str, list[str]]:
    """Headquarters risk, raised by supply-chain exposure (e.g. Taiwan fabs)."""
    level = config.GEO_EXPOSURE.get(opp.country, "Medium")
    notes = []
    if opp.ticker in config.SUPPLY_CHAIN_GEO:
        sc_level, why = config.SUPPLY_CHAIN_GEO[opp.ticker]
        order = ["Low", "Medium", "High"]
        if order.index(sc_level) > order.index(level):
            level = sc_level
        notes.append(why)
    return level, notes


def build_risk(opp: Opportunity) -> RiskProfile:
    prices = opp.hist_prices
    vol = compute_volatility(prices)
    dd = compute_max_drawdown(prices)
    rsi = compute_rsi(prices)
    geo, geo_notes = geo_level(opp)

    scores = {
        "beta":        min(abs(opp.beta) / 5.0, 1.0) if opp.beta is not None else None,
        "volatility":  min(vol / 100.0, 1.0) if vol is not None else None,
        "drawdown":    min(dd / 50.0, 1.0) if dd is not None else None,
        "debt":        min(opp.de / 300.0, 1.0) if opp.de is not None else None,
        "geo":         {"Low": 0.2, "Medium": 0.5, "High": 0.9}[geo],
        "rsi_extreme": _rsi_extreme_score(rsi) if rsi is not None else None,
    }
    w = config.RISK_WEIGHTS
    covered = sum(w[k] for k, s in scores.items() if s is not None)
    composite = None
    if covered >= 0.5:
        raw = sum(w[k] * s for k, s in scores.items() if s is not None) / covered
        composite = round(max(1.0, min(10.0, raw * 10.0)), 2)

    return RiskProfile(beta=opp.beta, volatility_30d=vol, max_drawdown_6mo=dd,
                       debt_to_equity=opp.de, rsi_14=rsi, geo_exposure=geo, geo_notes=geo_notes,
                       composite_score=composite, coverage=round(covered, 2))


def _sma(prices, n):
    return round(sum(prices[-n:]) / n, 4) if len(prices) >= n else None


def _return(prices, n=_6M):
    if len(prices) < n + 1 or prices[-n - 1] <= 0:
        return None
    return prices[-1] / prices[-n - 1] - 1


def compute_trend(opp: Opportunity, benchmarks: dict):
    prices = opp.hist_prices
    opp.ma50, opp.ma200 = _sma(prices, 50), _sma(prices, 200)
    last = prices[-1] if prices else None
    if last is None or opp.ma50 is None:
        opp.trend = "Unknown"
    elif opp.ma200 is None:
        opp.trend = "Uptrend" if last > opp.ma50 else "Downtrend"
    elif last > opp.ma50 > opp.ma200:
        opp.trend = "Uptrend"
    elif last < opp.ma50 < opp.ma200:
        opp.trend = "Downtrend"
    else:
        opp.trend = "Mixed"

    own = _return(prices)
    opp.rel_strength = {}
    for sym, series in benchmarks.items():
        bench = _return(series)
        if own is not None and bench is not None:
            opp.rel_strength[sym] = round((own - bench) * 100, 1)


def trend_score(opp: Opportunity) -> Optional[float]:
    """0..1 — trend state blended with 6-month strength vs the S&P 500."""
    base = {"Uptrend": 1.0, "Mixed": 0.5, "Downtrend": 0.0}.get(opp.trend)
    if base is None:
        return None
    rs = opp.rel_strength.get("SPY")
    if rs is None:
        return base
    return round((base + max(0.0, min(1.0, (rs + 30) / 60))) / 2, 3)


def compute_risk(opportunities: list[Opportunity], benchmarks: dict = None) -> list[Opportunity]:
    for opp in opportunities:
        if opp.price <= 0:
            continue
        opp.risk = build_risk(opp)
        compute_trend(opp, benchmarks or {})
    return opportunities

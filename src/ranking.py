"""
Ranking and analyst-consensus quality.

Missing components are dropped (never scored as favourable) and the final score
is scaled by how much of the weight was backed by real data.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

import config
from src.models import Opportunity
from src.risk import trend_score


def consensus_quality(opp: Opportunity) -> tuple[str, Optional[float]]:
    """Return (quality label, upside discounted for thin or dispersed coverage)."""
    if opp.upside is None or not opp.target:
        return "None", None
    thin = opp.analyst_count is not None and opp.analyst_count < config.MIN_ANALYSTS
    unknown_count = opp.analyst_count is None
    wide = False
    if opp.target_high and opp.target_low and opp.target:
        wide = (opp.target_high - opp.target_low) / opp.target > config.MAX_TARGET_SPREAD
    factor = 1.0
    label = "Good"
    if thin or unknown_count:
        factor *= 0.5
        label = "Thin" if thin else "Unknown count"
    if wide:
        factor *= 0.6
        label = "Wide" if label == "Good" else f"{label} + Wide"
    rc = opp.rating_changes_90d or {}
    if rc.get("down", 0) > rc.get("up", 0) + 1:
        factor *= 0.8
        label = "Downgrades" if label == "Good" else f"{label} + Downgrades"
    return label, round(opp.upside * factor, 1)


def apply_consensus_quality(opportunities: list[Opportunity]) -> list[Opportunity]:
    for opp in opportunities:
        opp.consensus_quality, opp.adj_upside = consensus_quality(opp)
    return opportunities


def count_rating_changes(df, today=None) -> dict:
    """Upgrades/downgrades in the last 90 days from a yfinance upgrades_downgrades frame."""
    import pandas as pd
    if df is None or getattr(df, "empty", True) or "Action" not in df.columns:
        return {}
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.now()
    idx = pd.to_datetime(df.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    recent = df[idx >= today - pd.Timedelta(days=90)]
    actions = recent["Action"].astype(str).str.lower()
    return {"up": int((actions == "up").sum()), "down": int((actions == "down").sum())}


def fetch_rating_changes(opportunities: list[Opportunity], limit: int = 40) -> None:
    """Yahoo upgrade/downgrade counts for holdings and the strongest candidates."""
    import src.cache as cache
    targets = sorted([o for o in opportunities if o.price > 0 and o.target],
                     key=lambda o: (0 if o.portfolio else 1, -(o.adj_upside or 0)))[:limit]
    for opp in targets:
        key = f"yahoo:ratings:{opp.ticker}"
        cached = cache.get(key, config.TTL_EARNINGS)
        if cached is not None:
            opp.rating_changes_90d = cached
            continue
        try:
            import yfinance as yf
            opp.rating_changes_90d = count_rating_changes(yf.Ticker(opp.ticker).upgrades_downgrades)
        except Exception:
            continue
        cache.set(key, opp.rating_changes_90d)


def sentiment_value(opp: Opportunity) -> Optional[float]:
    """-10..+10: Claude, else FinBERT, else keyword score."""
    if opp.analysis and opp.analysis.sentiment_score is not None:
        return float(opp.analysis.sentiment_score)
    if opp.finbert_score is not None:
        return opp.finbert_score
    if opp.news_sentiment_score:
        return opp.news_sentiment_score
    return None


def components(opp: Opportunity) -> dict:
    upside = opp.adj_upside if opp.adj_upside is not None else (
        None if opp.consensus_quality else opp.upside)
    sent = sentiment_value(opp)
    risk = opp.risk.composite_score if opp.risk else None
    return {
        "upside":    min(max(upside, 0) / 100.0, 1.0) if upside is not None else None,
        "sentiment": (sent + 10) / 20.0 if sent is not None else None,
        "risk_adj":  (10 - risk) / 10.0 if risk is not None else None,
        "trend":     trend_score(opp),
        "shariah":   {"Yes": 1.0, "Review": 0.5}.get(opp.shariah.compliant, 0.0) if opp.shariah else None,
    }


def rank_score(opp: Opportunity) -> float:
    """0..100. Weighted average of available components x (0.5 + 0.5 x coverage)."""
    w = config.RANK_WEIGHTS
    comps = {k: v for k, v in components(opp).items() if w.get(k, 0) > 0}
    total_w = sum(w[k] for k in comps)
    avail = {k: v for k, v in comps.items() if v is not None}
    covered = sum(w[k] for k in avail)
    if not covered or not total_w:
        return 0.0
    avg = sum(w[k] * v for k, v in avail.items()) / covered
    coverage = covered / total_w
    return round(avg * (0.5 + 0.5 * coverage) * 100, 2)


def top_ranked(opportunities: list[Opportunity], n: int = 10) -> list[Opportunity]:
    """The Top 10 shown on the Opportunities tab and in the report: priced, passed the data gate, by rank score."""
    ranked = sorted([o for o in opportunities if o.price > 0 and o.data_ok], key=lambda o: o.rank_score, reverse=True)
    return ranked[:n]

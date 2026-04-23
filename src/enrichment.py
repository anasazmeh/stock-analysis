"""
Stage 2 — Enrichment
Fetches fundamentals + 6-month historical prices for each ticker.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import config
import src.cache as cache
from src.models import Opportunity


def _safe_float(val, scale=1.0) -> float:
    """Convert to float safely, returning 0.0 on failure."""
    try:
        return round(float(val) * scale, 4) if val else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fetch_one(ticker: str) -> Opportunity:
    """Fetch fundamentals for a single ticker from yfinance."""
    cache_key = f"enrich:{ticker}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return Opportunity(**cached)

    try:
        info = yf.Ticker(ticker).info
    except Exception as e:
        print(f"  [enrich] {ticker} ERROR: {e}")
        return Opportunity(ticker=ticker)

    price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    target = info.get("targetMeanPrice") or 0

    opp = Opportunity(
        ticker=ticker,
        name=str(info.get("shortName", ticker))[:32],
        sector=info.get("sector", "N/A") or "N/A",
        industry=info.get("industry", "N/A") or "N/A",
        country=info.get("country", "N/A") or "N/A",
        price=_safe_float(price),
        target=_safe_float(target),
        upside=round((target / price - 1) * 100, 1) if price and target else None,
        fpe=round(info.get("forwardPE") or 0, 1) or None,
        rev_growth=_safe_float(info.get("revenueGrowth"), 100),
        eps_growth=_safe_float(info.get("earningsGrowth"), 100),
        beta=round(info.get("beta") or 0, 2) or None,
        de=round(info.get("debtToEquity") or 0, 1) or None,
        gross_margin=_safe_float(info.get("grossMargins"), 100),
        op_margin=_safe_float(info.get("operatingMargins"), 100),
        w52_low=info.get("fiftyTwoWeekLow"),
        w52_high=info.get("fiftyTwoWeekHigh"),
        rec=info.get("recommendationKey", "N/A") or "N/A",
        mcap=info.get("marketCap") or 0,
        # Shariah / Risk fields
        total_debt=_safe_float(info.get("totalDebt")),
        total_cash=_safe_float(info.get("totalCash")),
        total_revenue=_safe_float(info.get("totalRevenue")),
        interest_expense=_safe_float(info.get("interestExpense")),
        total_assets=_safe_float(info.get("totalAssets")),
        accounts_receivable=_safe_float(info.get("netReceivables")),
        interest_income=_safe_float(info.get("interestIncome")),
        short_ratio=info.get("shortRatio"),
        peg_ratio=info.get("pegRatio"),
        price_to_book=info.get("priceToBook"),
    )

    # Cache as dict (Opportunity is a dataclass)
    import dataclasses
    cache.set(cache_key, dataclasses.asdict(opp))

    return opp


def _fetch_historical(tickers: list[str]) -> dict[str, list[float]]:
    """
    Fetch 6-month daily closing prices for all tickers in one bulk call.
    Returns dict: ticker -> list of close prices (oldest first).
    """
    cache_key = f"hist:{'_'.join(sorted(tickers))[:80]}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return cached

    try:
        df = yf.download(tickers, period="6mo", auto_adjust=True, progress=False)
        close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
        result = {}
        for t in tickers:
            try:
                col = close[t] if t in close.columns else close.iloc[:, 0]
                result[t] = [round(v, 4) for v in col.dropna().tolist()]
            except Exception:
                result[t] = []
    except Exception as e:
        print(f"  [enrich] Historical download failed: {e}")
        result = {t: [] for t in tickers}

    cache.set(cache_key, result)
    return result


def enrich_tickers(tickers: list[str]) -> list[Opportunity]:
    """
    Fetch fundamentals + historical prices for all tickers.
    Returns list of Opportunity objects.
    """
    print(f"  [enrich] Fetching fundamentals for {len(tickers)} tickers...")
    opportunities = []

    with ThreadPoolExecutor(max_workers=config.ENRICH_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            t = futures[future]
            try:
                opp = future.result()
                opportunities.append(opp)
                print(f"  \u2713 {t:<6}  ${opp.price:,.2f}")
            except Exception as e:
                print(f"  \u2717 {t:<6}  ERROR: {e}")
                opportunities.append(Opportunity(ticker=t))

    # Attach historical prices
    print(f"  [enrich] Fetching 6-month price history...")
    hist = _fetch_historical(tickers)
    for opp in opportunities:
        opp.hist_prices = hist.get(opp.ticker, [])

    return opportunities

"""
Stage 2 — Enrichment
Fundamentals, price provenance, analyst consensus detail, Shariah statement inputs
and 2 years of daily history (plus benchmark ETFs) from Yahoo Finance.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dataclasses
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import src.cache as cache
from src.models import Opportunity

# Yahoo quotes some listings in minor units (pence, cents, agorot)
_MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}
_LIVE_STATES = {"REGULAR"}


def _num(val, scale=1.0):
    """Float or None — missing data stays missing."""
    try:
        if val is None or val == "":
            return None
        f = float(val)
        if f != f:  # NaN
            return None
        return round(f * scale, 4)
    except (TypeError, ValueError):
        return None


def _statement_value(df, labels) -> tuple:
    """Most recent value of the first matching row label, with its period."""
    if df is None or getattr(df, "empty", True):
        return None, ""
    for label in labels:
        if label in df.index:
            row = df.loc[label].dropna()
            if len(row):
                col = row.index[0]
                period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                return _num(row.iloc[0]), period
    return None, ""


_BALANCE_ROWS = {
    "interest_bearing_debt": ["Total Debt"],
    "cash_and_securities": ["Cash Cash Equivalents And Short Term Investments",
                            "Cash And Cash Equivalents"],
    "receivables": ["Accounts Receivable", "Receivables", "Net Receivables"],
    "total_assets": ["Total Assets"],
}
_INCOME_ROWS = {
    "interest_income": ["Interest Income", "Interest Income Non Operating"],
    "revenue": ["Total Revenue", "Operating Revenue"],
}


def statement_inputs(ticker_obj) -> dict:
    """Shariah ratio inputs from the latest annual statements (values in financial currency)."""
    out = {}
    periods = set()
    try:
        bs = ticker_obj.balance_sheet
        inc = ticker_obj.income_stmt
    except Exception:
        return out
    for key, labels in _BALANCE_ROWS.items():
        out[key], period = _statement_value(bs, labels)
        if period:
            periods.add(period)
    for key, labels in _INCOME_ROWS.items():
        out[key], period = _statement_value(inc, labels)
        if period:
            periods.add(period)
    out["period"] = max(periods) if periods else ""
    out["source"] = "Yahoo annual statements" if periods else ""
    return out


def build_opportunity(ticker: str, info: dict) -> Opportunity:
    """Map a yfinance .info dict to an Opportunity, keeping missing values as None."""
    currency = info.get("currency") or ""
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or 0.0
    target = _num(info.get("targetMeanPrice"))
    t_high, t_low, t_med = (_num(info.get(k)) for k in ("targetHighPrice", "targetLowPrice", "targetMedianPrice"))
    w52_low, w52_high = _num(info.get("fiftyTwoWeekLow")), _num(info.get("fiftyTwoWeekHigh"))

    if currency in _MINOR_UNITS:
        currency, div = _MINOR_UNITS[currency]
        price = price / div
        target, t_high, t_low, t_med, w52_low, w52_high = (
            v / div if v else v for v in (target, t_high, t_low, t_med, w52_low, w52_high))
    currency = currency.upper() or "USD"

    ts = info.get("regularMarketTime")
    price_time = (datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                  if isinstance(ts, (int, float)) and ts else "")
    state = info.get("marketState", "") or ""
    country = info.get("country") or "N/A"

    return Opportunity(
        ticker=ticker,
        name=str(info.get("shortName") or info.get("longName") or ticker)[:40],
        sector=info.get("sector") or "N/A",
        industry=info.get("industry") or "N/A",
        country=country,
        currency=currency,
        region=config.REGION_MAP.get(country, "🌐 Other"),
        price=price,
        price_source="Yahoo Finance" if price else "",
        price_time=price_time,
        price_type=("live (delayed)" if state in _LIVE_STATES else "last close") if price else "",
        market_state=state,
        exchange=info.get("exchange") or "",
        quote_type=info.get("quoteType") or "",
        financial_currency=(info.get("financialCurrency") or currency).upper(),
        avg_volume=_num(info.get("averageVolume")),
        dividend_rate=_num(info.get("dividendRate")),
        short_pct_float=_num(info.get("shortPercentOfFloat"), 100),
        target=target or 0.0,
        target_high=t_high,
        target_low=t_low,
        target_median=t_med,
        target_source="Yahoo consensus" if target else "",
        analyst_count=int(info["numberOfAnalystOpinions"]) if info.get("numberOfAnalystOpinions") else None,
        upside=round((target / price - 1) * 100, 1) if price and target else None,
        fpe=_num(info.get("forwardPE")),
        rev_growth=_num(info.get("revenueGrowth"), 100) or 0.0,
        eps_growth=_num(info.get("earningsGrowth"), 100) or 0.0,
        beta=_num(info.get("beta")),
        de=_num(info.get("debtToEquity")),
        gross_margin=_num(info.get("grossMargins"), 100) or 0.0,
        op_margin=_num(info.get("operatingMargins"), 100) or 0.0,
        w52_low=w52_low,
        w52_high=w52_high,
        rec=info.get("recommendationKey") or "N/A",
        mcap=_num(info.get("marketCap")) or 0.0,
        total_debt=_num(info.get("totalDebt")) or 0.0,
        total_cash=_num(info.get("totalCash")) or 0.0,
        total_revenue=_num(info.get("totalRevenue")) or 0.0,
        short_ratio=_num(info.get("shortRatio")),
        peg_ratio=_num(info.get("pegRatio")),
        price_to_book=_num(info.get("priceToBook")),
    )


def _fetch_one(ticker: str) -> Opportunity:
    cache_key = f"enrich:v2:{ticker}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return Opportunity(**cached)

    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        print(f"  [enrich] {ticker} failed: {type(e).__name__}: {str(e)[:80]}")
        return Opportunity(ticker=ticker)

    opp = build_opportunity(ticker, info)
    if opp.price > 0 and opp.quote_type != "ETF":
        opp.shariah_inputs = statement_inputs(t)
        if opp.shariah_inputs:
            opp.shariah_inputs["currency"] = opp.financial_currency

    if opp.price > 0:  # never cache failed or empty payloads
        cache.set(cache_key, dataclasses.asdict(opp))
    return opp


def _fetch_historical(tickers: list[str]) -> dict:
    """2 years of daily closes for all tickers in one bulk call (oldest first)."""
    digest = hashlib.md5(",".join(sorted(tickers)).encode()).hexdigest()
    cache_key = f"hist:2y:{digest}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return cached

    import yfinance as yf
    import pandas as pd
    result = {t: [] for t in tickers}
    try:
        df = yf.download(tickers, period=config.HISTORY_PERIOD, auto_adjust=True,
                         progress=False, group_by="column")
        close = df["Close"]
        if isinstance(close, pd.Series):  # single ticker
            close = close.to_frame(name=tickers[0])
        for t in tickers:
            if t in close.columns:
                result[t] = [round(float(v), 4) for v in close[t].dropna().tolist()]
    except Exception as e:
        print(f"  [enrich] Historical download failed: {type(e).__name__}: {str(e)[:80]}")
        return result

    if any(result.values()):
        cache.set(cache_key, result)
    return result


def enrich_tickers(tickers: list[str]) -> tuple[list[Opportunity], dict]:
    """
    Fetch fundamentals + history for all tickers.
    Returns (opportunities, benchmark_history) where benchmark_history maps
    each config.BENCHMARKS symbol to its close series.
    """
    print(f"  [enrich] Fetching fundamentals for {len(tickers)} tickers...")
    opportunities = []
    with ThreadPoolExecutor(max_workers=config.ENRICH_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            t = futures[future]
            try:
                opp = future.result()
            except Exception as e:
                print(f"  ✗ {t:<10} {type(e).__name__}")
                opp = Opportunity(ticker=t)
            opportunities.append(opp)
            if opp.price > 0:
                print(f"  ✓ {t:<10} {opp.price:,.2f} {opp.currency} ({opp.price_type})")
            else:
                print(f"  ✗ {t:<10} no price")

    benchmarks = list(config.BENCHMARKS)
    print(f"  [enrich] Fetching {config.HISTORY_PERIOD} price history (+{len(benchmarks)} benchmarks)...")
    hist = _fetch_historical(sorted(set(tickers) | set(benchmarks)))
    for opp in opportunities:
        opp.hist_prices = hist.get(opp.ticker, [])
    return opportunities, {b: hist.get(b, []) for b in benchmarks}

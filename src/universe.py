"""
Index + Shariah ETF universe for discovery (free, no key).

- Index constituents come from Wikipedia tables (config.UNIVERSE_INDICES).
- Shariah ETF holdings come from CSV files the user downloads from the issuer's
  site into config.SHARIAH_ETF_DIR (e.g. data/universe/SPUS.csv). Issuers block
  automated downloads, so these are refreshed by hand.

Membership is attached to each opportunity as a label (opp.universe_tags);
it never filters anything out.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import glob
import hashlib
import re
from io import StringIO

import requests
import config
import src.cache as cache
from src.models import Opportunity

_HEADERS = {"User-Agent": "stock-analysis/1.0 (personal research script)"}
_TICKER_COLUMNS = ("ticker", "symbol", "ticker symbol", "holding ticker", "code")
_NOT_TICKERS = {"", "-", "--", "CASH", "USD", "EUR", "N/A", "NA"}


def _normalize(sym: str) -> str:
    """Convert a listing symbol to Yahoo format (BRK.B -> BRK-B)."""
    sym = str(sym).strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}\.[A-Z]", sym):
        sym = sym.replace(".", "-")
    return sym


def _is_ticker(sym: str) -> bool:
    return sym not in _NOT_TICKERS and len(sym) <= 15 and bool(re.fullmatch(r"[A-Z0-9.\-]+", sym))


def parse_index_html(html: str) -> list[str]:
    """Return tickers from the first HTML table that has a Symbol/Ticker column."""
    import pandas as pd
    for table in pd.read_html(StringIO(html)):
        cols = {str(c).strip().lower(): c for c in table.columns}
        col = next((cols[c] for c in _TICKER_COLUMNS if c in cols), None)
        if col is None:
            continue
        tickers = [_normalize(s) for s in table[col].dropna()]
        tickers = [t for t in tickers if _is_ticker(t)]
        if len(tickers) >= 20:
            return tickers
    return []


def fetch_index_constituents(name: str, url: str) -> list[str]:
    cache_key = f"universe:index:{name}"
    cached = cache.get(cache_key, config.TTL_UNIVERSE)
    if cached:
        return cached
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        tickers = parse_index_html(resp.text)
    except Exception as e:
        print(f"  [universe] {name} constituents failed: {e}")
        return []
    if tickers:
        cache.set(cache_key, tickers)
    else:
        print(f"  [universe] {name}: no ticker table found (page layout changed?)")
    return tickers


def parse_holdings_csv(text: str) -> list[str]:
    """Parse an ETF holdings CSV; skips issuer preamble lines before the header row."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        header = [h.strip().strip('"').lower() for h in next(csv.reader([line]), [])]
        idx = next((header.index(c) for c in _TICKER_COLUMNS if c in header), None)
        if idx is None:
            continue
        tickers = []
        for row in csv.reader(lines[i + 1:]):
            if len(row) > idx:
                sym = _normalize(row[idx])
                if _is_ticker(sym):
                    tickers.append(sym)
        return tickers
    return []


def load_shariah_etf_holdings() -> dict[str, list[str]]:
    """Return {ETF label: [tickers]} from CSV files in SHARIAH_ETF_DIR."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        config.SHARIAH_ETF_DIR)
    holdings = {}
    for path in sorted(glob.glob(os.path.join(base, "*.csv"))):
        label = os.path.splitext(os.path.basename(path))[0].upper()
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                tickers = parse_holdings_csv(f.read())
        except OSError as e:
            print(f"  [universe] {path}: {e}")
            continue
        if tickers:
            holdings[label] = tickers
    return holdings


def get_universe_tags() -> dict[str, list[str]]:
    """Map ticker -> list of index / Shariah ETF labels it belongs to."""
    tags: dict[str, list[str]] = {}
    sources = {name: fetch_index_constituents(name, url)
               for name, url in config.UNIVERSE_INDICES.items()}
    sources.update(load_shariah_etf_holdings())
    for label, tickers in sources.items():
        for t in tickers:
            tags.setdefault(t, []).append(label)
    return tags


def pick_by_momentum(tickers: list[str], n: int) -> list[str]:
    """Pick the n tickers with the best 6-month return (one bulk yfinance download)."""
    if not tickers or n <= 0:
        return []
    digest = hashlib.md5(",".join(sorted(tickers)).encode()).hexdigest()
    cache_key = f"universe:momentum:{n}:{digest}"
    cached = cache.get(cache_key, config.TTL_SCREENER)
    if cached:
        return cached
    try:
        import yfinance as yf
        closes = yf.download(tickers, period="6mo", interval="1d",
                             progress=False, auto_adjust=True, threads=True)["Close"]
    except Exception as e:
        print(f"  [universe] momentum download failed: {e}")
        return []
    returns = {}
    for t in closes.columns:
        series = closes[t].dropna()
        if len(series) >= 60 and series.iloc[0] > 0:
            returns[t] = series.iloc[-1] / series.iloc[0] - 1
    picks = [t for t, _ in sorted(returns.items(), key=lambda kv: kv[1], reverse=True)[:n]]
    if picks:
        cache.set(cache_key, picks)
    return picks


def universe_candidates(exclude: set[str]) -> list[str]:
    """Index + Shariah ETF names not already covered, ranked by momentum."""
    pool = sorted(set(get_universe_tags()) - exclude - config.AVOID_LIST)
    if not pool:
        return []
    picks = pick_by_momentum(pool, config.UNIVERSE_TOP_N)
    print(f"  [universe] {len(pool)} index/ETF names screened → {len(picks)} added by momentum")
    return picks


def attach_universe_tags(opportunities: list[Opportunity]) -> list[Opportunity]:
    tags = get_universe_tags()
    for opp in opportunities:
        opp.universe_tags = tags.get(opp.ticker, [])
    return opportunities

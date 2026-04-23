"""
Stage 3 — News & Macro
Fetches per-ticker news and macro context from free sources.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import feedparser
import config
import src.cache as cache
from src.models import Opportunity, MacroContext

# Google News RSS base URL
_GNEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"

MACRO_QUERIES = [
    "global stock market today",
    "Federal Reserve interest rate policy",
    "AI technology sector stocks",
    "semiconductor supply chain",
    "geopolitical risk financial markets",
    "emerging markets investment outlook",
]


def _fetch_ticker_news(ticker: str, limit: int = 5) -> list[dict]:
    """Fetch recent news for a ticker via yfinance."""
    cache_key = f"news:ticker:{ticker}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached

    articles = []
    try:
        raw = yf.Ticker(ticker).news or []
        for item in raw[:limit]:
            articles.append({
                "title":   item.get("title", ""),
                "summary": item.get("summary", item.get("title", "")),
                "source":  item.get("publisher", ""),
                "url":     item.get("link", ""),
            })
    except Exception as e:
        print(f"  [news] {ticker} news failed: {e}")

    cache.set(cache_key, articles)
    return articles


def _fetch_rss_news(query: str, limit: int = 5) -> list[dict]:
    """Fetch news articles from Google News RSS for a query."""
    cache_key = f"news:rss:{query}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached

    articles = []
    try:
        url = _GNEWS_URL.format(query=query.replace(" ", "+"))
        feed = feedparser.parse(url)
        for entry in feed.entries[:limit]:
            articles.append({
                "title":   entry.get("title", ""),
                "summary": entry.get("summary", entry.get("title", "")),
                "source":  entry.get("source", {}).get("title", "Google News") if hasattr(entry.get("source", {}), "get") else "Google News",
                "url":     entry.get("link", ""),
            })
    except Exception as e:
        print(f"  [news] RSS query '{query}' failed: {e}")

    cache.set(cache_key, articles)
    return articles


def _fetch_fred_indicators() -> dict:
    """
    Fetch key macro indicators from FRED (requires FRED_API_KEY).
    Falls back to empty dict if key not set or request fails.
    """
    if not config.FRED_API_KEY:
        return {}

    cache_key = "macro:fred"
    cached = cache.get(cache_key, config.TTL_FRED)
    if cached:
        return cached

    indicators = {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=config.FRED_API_KEY)
        series = {
            "fed_rate":    "FEDFUNDS",     # Federal Funds Rate
            "cpi":         "CPIAUCSL",     # CPI
            "unemployment":"UNRATE",       # Unemployment Rate
            "t10y2y":      "T10Y2Y",       # 10Y-2Y Yield Spread
            "vix":         "VIXCLS",       # VIX
        }
        for key, series_id in series.items():
            try:
                data = fred.get_series(series_id, observation_start="2024-01-01")
                if not data.empty:
                    indicators[key] = round(float(data.iloc[-1]), 3)
            except Exception:
                pass
    except Exception as e:
        print(f"  [news] FRED fetch failed: {e}")

    cache.set(cache_key, indicators)
    return indicators


def _fetch_finnhub_news(ticker: str, limit: int = 5) -> list[dict]:
    """Fetch company news from Finnhub (supplementary source). Requires FINNHUB_API_KEY."""
    if not config.FINNHUB_API_KEY:
        return []

    cache_key = f"news:finnhub:{ticker}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached

    articles = []
    try:
        import requests
        from datetime import date, timedelta
        end   = date.today().isoformat()
        start = (date.today() - timedelta(days=7)).isoformat()
        url   = (
            f"https://finnhub.io/api/v1/company-news"
            f"?symbol={ticker}&from={start}&to={end}&token={config.FINNHUB_API_KEY}"
        )
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            for item in resp.json()[:limit]:
                articles.append({
                    "title":   item.get("headline", ""),
                    "summary": item.get("summary", item.get("headline", "")),
                    "source":  item.get("source", "Finnhub"),
                    "url":     item.get("url", ""),
                })
    except Exception as e:
        print(f"  [news] Finnhub {ticker} failed: {e}")

    cache.set(cache_key, articles)
    return articles


def attach_news(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Attach per-ticker news to each opportunity (yfinance primary, Finnhub supplementary)."""
    print(f"  [news] Fetching news for {len(opportunities)} tickers...")
    for opp in opportunities:
        primary = _fetch_ticker_news(opp.ticker)
        supplementary = _fetch_finnhub_news(opp.ticker) if config.FINNHUB_API_KEY else []
        # Merge, deduplicate by title
        seen = {a["title"] for a in primary}
        extra = [a for a in supplementary if a["title"] not in seen]
        opp.news = (primary + extra)[:8]  # cap at 8 articles per ticker
    return opportunities


def build_macro_context() -> MacroContext:
    """Build macro context from FRED + Google News RSS."""
    print(f"  [news] Building macro context...")

    fred = _fetch_fred_indicators()

    macro_news = []
    for query in MACRO_QUERIES:
        articles = _fetch_rss_news(query, limit=3)
        macro_news.extend(articles)

    return MacroContext(
        fed_rate=fred.get("fed_rate"),
        vix=fred.get("vix"),
        yield_spread=fred.get("t10y2y"),
        macro_news=macro_news,
        # regime and themes will be filled in by intelligence.py
    )

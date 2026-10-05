"""
Stage 3 — News & Macro.

Per-ticker news: Yahoo Finance (current nested 'content' schema), Finnhub for US
symbols, Google News RSS as a fallback when both are empty. After every source
has run (incl. GDELT/NewsAPI), normalize_news() dedupes, drops stale and
law-firm "investor alert" items and orders by source quality and date.

Macro: FRED indicators (Fed funds, CPI YoY, unemployment, 10Y-2Y, VIX, EUR/USD)
and Google News RSS queries balanced across regions.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import config
import src.cache as cache
from src.models import Opportunity, MacroContext

_GNEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"

MACRO_QUERIES = {
    "Global":      ["global stock market", "Federal Reserve interest rates", "geopolitical risk markets"],
    "Tech / AI":   ["AI semiconductor demand", "TSMC Nvidia chip export controls"],
    "Europe":      ["ECB interest rates eurozone", "European stocks STOXX 600"],
    "Asia":        ["China economy stocks", "India stock market Nifty", "Bank of Japan policy"],
    "Middle East": ["Saudi Tadawul TASI", "UAE ADX DFM stocks", "OPEC oil price"],
}

_SPAM_PATTERNS = re.compile(
    r"class action|investor alert|shareholder alert|investors? (who|with) losses|"
    r"law firm|securities fraud (lawsuit|investigation)|deadline alert|rosen law|pomerantz",
    re.IGNORECASE)


def _iso_date(value) -> str:
    """Best-effort YYYY-MM-DD from ISO strings, RFC-822 strings or epoch seconds."""
    if not value:
        return ""
    try:
        if isinstance(value, (int, float)):
            return datetime.utcfromtimestamp(value).strftime("%Y-%m-%d")
        if re.match(r"\d{4}-\d{2}-\d{2}", str(value)):
            return str(value)[:10]
        return parsedate_to_datetime(str(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return ""


def parse_yahoo_news(raw: list, limit: int = 5) -> list[dict]:
    """Handle both the current nested schema and the legacy flat one."""
    articles = []
    for item in raw or []:
        c = item.get("content") if isinstance(item.get("content"), dict) else item
        title = (c.get("title") or "").strip()
        if not title:
            continue
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link") or "")
        provider = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else None
        articles.append({
            "title":    title,
            "summary":  (c.get("summary") or c.get("description") or title).strip(),
            "source":   provider or c.get("publisher") or "Yahoo Finance",
            "url":      url,
            "date":     _iso_date(c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime")),
            "provider": "Yahoo",
        })
        if len(articles) >= limit:
            break
    return articles


def _fetch_ticker_news(ticker: str, limit: int = 5) -> list[dict]:
    cache_key = f"news:ticker:v2:{ticker}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached
    try:
        import yfinance as yf
        articles = parse_yahoo_news(yf.Ticker(ticker).news, limit)
    except Exception as e:
        print(f"  [news] {ticker} Yahoo news failed: {type(e).__name__}")
        return []
    if articles:
        cache.set(cache_key, articles)
    return articles


def _fetch_rss_news(query: str, limit: int = 5, when: str = "") -> list[dict]:
    """Google News RSS search. `when` like '2d' limits to recent items."""
    q = f"{query} when:{when}" if when else query
    cache_key = f"news:rss:{q}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached
    try:
        import feedparser
    except ImportError:
        print("  [news] feedparser not installed — Google News RSS skipped")
        return []
    articles = []
    try:
        feed = feedparser.parse(_GNEWS_URL.format(query=quote_plus(q)))
        for entry in feed.entries[:limit]:
            src = entry.get("source")
            articles.append({
                "title":    entry.get("title", ""),
                "summary":  entry.get("summary", entry.get("title", "")),
                "source":   src.get("title", "Google News") if hasattr(src, "get") else "Google News",
                "url":      entry.get("link", ""),
                "date":     _iso_date(entry.get("published")),
                "provider": "Google News",
            })
    except Exception as e:
        print(f"  [news] RSS query '{query}' failed: {type(e).__name__}")
        return []
    if articles:
        cache.set(cache_key, articles)
    return articles


def _fetch_fred_indicators() -> dict:
    """Fed funds, CPI YoY, unemployment, 10Y-2Y, VIX, EUR/USD, high-yield spread (needs FRED_API_KEY)."""
    if not config.FRED_API_KEY:
        return {}
    cached = cache.get("macro:fred:v3", config.TTL_FRED)
    if cached:
        return cached
    out = {}
    try:
        from fredapi import Fred
        fred = Fred(api_key=config.FRED_API_KEY)
        start = (date.today() - timedelta(days=500)).isoformat()
        for key, series_id in {"fed_rate": "FEDFUNDS", "unemployment": "UNRATE",
                               "t10y2y": "T10Y2Y", "vix": "VIXCLS", "eurusd": "DEXUSEU",
                               "hy_spread": "BAMLH0A0HYM2"}.items():   # US high-yield credit spread, %
            try:
                s = fred.get_series(series_id, observation_start=start).dropna()
                if not s.empty:
                    out[key] = round(float(s.iloc[-1]), 3)
            except Exception:
                continue
        try:
            cpi = fred.get_series("CPIAUCSL", observation_start=start).dropna()
            if len(cpi) >= 13:
                out["cpi_yoy"] = round((float(cpi.iloc[-1]) / float(cpi.iloc[-13]) - 1) * 100, 2)
        except Exception:
            pass
    except Exception as e:
        print(f"  [news] FRED fetch failed: {type(e).__name__}")
        return {}
    if out:
        cache.set("macro:fred:v3", out)
    return out


def _fetch_finnhub_news(ticker: str, limit: int = 5) -> list[dict]:
    """Finnhub company news — North American symbols only."""
    if not config.FINNHUB_API_KEY or "." in ticker:
        return []
    cache_key = f"news:finnhub:{ticker}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached
    articles = []
    try:
        import requests
        resp = requests.get("https://finnhub.io/api/v1/company-news", timeout=8, params={
            "symbol": ticker.replace("-", "."),
            "from": (date.today() - timedelta(days=7)).isoformat(),
            "to": date.today().isoformat(),
        }, headers={"X-Finnhub-Token": config.FINNHUB_API_KEY})
        if resp.status_code == 200:
            for item in resp.json()[:limit]:
                if not item.get("headline"):
                    continue
                articles.append({
                    "title":    item["headline"],
                    "summary":  item.get("summary") or item["headline"],
                    "source":   item.get("source", "Finnhub"),
                    "url":      item.get("url", ""),
                    "date":     _iso_date(item.get("datetime")),
                    "provider": "Finnhub",
                })
    except Exception as e:
        print(f"  [news] Finnhub {ticker} failed: {type(e).__name__}")  # no URL: it holds the key
        return []
    if articles:
        cache.set(cache_key, articles)
    return articles


def attach_news(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Yahoo + Finnhub per ticker; Google News RSS when both are empty."""
    print(f"  [news] Fetching news for {len(opportunities)} tickers...")
    for opp in opportunities:
        if opp.price <= 0:
            continue
        articles = _fetch_ticker_news(opp.ticker) + _fetch_finnhub_news(opp.ticker)
        if not articles:
            name = opp.name if opp.name and opp.name != opp.ticker else opp.ticker.split(".")[0]
            articles = _fetch_rss_news(f'"{name}" stock', limit=5, when="7d")
        opp.news = articles
    return opportunities


def _title_key(title: str) -> str:
    title = re.sub(r"\s+[-|–]\s+[^-|–]{2,40}$", "", title.lower())  # strip " - Reuters"
    return re.sub(r"[^a-z0-9 ]", "", title)[:70].strip()


def _domain_tier(article: dict) -> int:
    hay = f"{article.get('url', '')} {article.get('source', '')}".lower()
    for tier, names in config.NEWS_SOURCE_TIERS.items():
        if any(n in hay for n in names):
            return tier
    return 3


def normalize_articles(articles: list[dict], today: date = None, max_items: int = 10) -> list[dict]:
    today = today or date.today()
    cutoff = (today - timedelta(days=config.NEWS_MAX_AGE_DAYS)).isoformat()
    seen, spam_kept, out = set(), 0, []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        if a.get("date") and a["date"] < cutoff:
            continue
        key = _title_key(title)
        if key in seen:
            continue
        if _SPAM_PATTERNS.search(title):
            if spam_kept >= 1:
                continue
            spam_kept += 1
        seen.add(key)
        a["tier"] = _domain_tier(a)
        out.append(a)
    # stable sorts: newest first, then better source tier first
    out.sort(key=lambda a: a.get("date") or "", reverse=True)
    out.sort(key=lambda a: a["tier"])
    return out[:max_items]


def normalize_news(opportunities: list[Opportunity]) -> list[Opportunity]:
    for opp in opportunities:
        opp.news = normalize_articles(opp.news)
    return opportunities


def build_macro_context() -> MacroContext:
    """FRED indicators + recent Google News headlines, 3 per region."""
    print("  [news] Building macro context...")
    fred = _fetch_fred_indicators()
    macro_news = []
    for region, queries in MACRO_QUERIES.items():
        regional = []
        for q in queries:
            regional.extend(_fetch_rss_news(q, limit=3, when="2d"))
        for a in normalize_articles(regional, max_items=3):
            a["region"] = region
            macro_news.append(a)
    return MacroContext(
        fed_rate=fred.get("fed_rate"),
        vix=fred.get("vix"),
        yield_spread=fred.get("t10y2y"),
        cpi_yoy=fred.get("cpi_yoy"),
        unemployment=fred.get("unemployment"),
        eurusd=fred.get("eurusd"),
        hy_spread=fred.get("hy_spread"),
        macro_news=macro_news,
    )

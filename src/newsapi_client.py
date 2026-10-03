"""
NewsAPI.org integration — richer article sourcing + financial keyword sentiment scoring.
Free tier: 100 req/day, English articles from last 30 days.
Set NEWSAPI_KEY environment variable to enable (get key at newsapi.org).

Sentiment scoring uses a financial keyword dictionary so it works without Claude.
The score (-10..+10) feeds into ranking as a fallback when Claude AI is unavailable.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config
import src.cache as cache
from src.models import Opportunity

_BASE = "https://newsapi.org/v2/everything"

# Financial sentiment vocabulary (case-insensitive word matching)
_POSITIVE = {
    "beat", "beats", "surge", "surged", "surges", "gain", "gains", "gained",
    "record", "growth", "grows", "grew", "upgrade", "upgraded", "outperform",
    "outperforms", "bullish", "profit", "profits", "exceed", "exceeds", "exceeded",
    "breakthrough", "acquisition", "dividend", "expansion", "approved", "approval",
    "partnership", "contract", "deal", "strong", "rally", "rallies", "rallied",
    "rebound", "buy", "overweight", "positive", "robust", "momentum", "milestone",
    "launch", "launches", "wins", "won", "raise", "raised", "boost", "boosted",
    "accelerate", "accelerates", "innovation", "leadership", "dominates",
}

_NEGATIVE = {
    "miss", "misses", "missed", "decline", "declined", "declines", "fall", "falls",
    "fell", "cut", "cuts", "downgrade", "downgraded", "underperform", "underperforms",
    "bearish", "loss", "losses", "layoff", "layoffs", "warning", "investigation",
    "lawsuit", "fraud", "recall", "fine", "penalty", "bankruptcy", "delay", "delays",
    "weak", "disappoint", "disappoints", "disappointed", "below", "sell", "underweight",
    "concern", "concerns", "uncertainty", "drop", "drops", "dropped", "slump",
    "slumps", "slumped", "crash", "crashes", "crashed", "halt", "halted", "probe",
    "shortfall", "deficit", "writedown", "impairment", "breach", "violation",
}


_NEGATORS = {"not", "no", "never", "without", "fails", "failed", "despite"}
# Phrases whose words would otherwise score the wrong way
_PHRASES = {
    "cut losses": 1, "cuts losses": 1, "narrowed loss": 1, "narrows loss": 1, "loss narrowed": 1,
    "beat expectations": 1, "price cut": -1, "guidance cut": -1, "cuts guidance": -1,
    "record loss": -1, "sell-off": -1, "selloff": -1, "buyback": 1,
}


def _score_text(text: str) -> float:
    """Sentiment in [-10, +10] from a financial keyword list, with negation and phrase handling.
    Only a fallback: FinBERT and Claude scores take priority in the ranking."""
    if not text:
        return 0.0
    import re
    low = text.lower()
    pos = neg = 0
    for phrase, sign in _PHRASES.items():
        n = low.count(phrase)
        if n:
            pos += n if sign > 0 else 0
            neg += n if sign < 0 else 0
            low = low.replace(phrase, " ")
    tokens = re.findall(r"[a-z][a-z'-]*", low)
    for i, tok in enumerate(tokens):
        sign = 1 if tok in _POSITIVE else (-1 if tok in _NEGATIVE else 0)
        if not sign:
            continue
        if any(t in _NEGATORS for t in tokens[max(0, i - 2):i]):
            sign = -sign
        if sign > 0:
            pos += 1
        else:
            neg += 1
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total * 10, 2)


def fetch_ticker_news(ticker: str, company_name: str = "", limit: int = 5) -> list[dict]:
    """Fetch and sentiment-score news articles for a single ticker from NewsAPI."""
    if not config.NEWSAPI_KEY:
        return []

    cache_key = f"newsapi:{ticker}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached:
        return cached

    # Use company name for more precise results (strip exchange suffixes for generic names)
    query = company_name[:50] if (company_name and company_name != ticker) else ticker.split(".")[0]

    articles = []
    try:
        resp = requests.get(_BASE, params={
            "q":        query,
            "language": "en",
            "sortBy":   "publishedAt",
            "pageSize": limit,
        }, headers={"X-Api-Key": config.NEWSAPI_KEY}, timeout=12)

        if resp.status_code == 200:
            for item in resp.json().get("articles", []):
                title   = item.get("title", "") or ""
                desc    = item.get("description", "") or ""
                content = item.get("content", "") or ""
                score   = _score_text(f"{title} {desc} {content}")
                articles.append({
                    "title":     title,
                    "summary":   desc or title,
                    "source":    (item.get("source") or {}).get("name", "NewsAPI"),
                    "url":       item.get("url", ""),
                    "date":      (item.get("publishedAt") or "")[:10],
                    "provider":  "NewsAPI (free plan: 24h delayed)",
                    "sentiment": score,
                })
        elif resp.status_code == 426:
            print(f"  [newsapi] API key requires upgrade for this query")
        elif resp.status_code == 429:
            print(f"  [newsapi] rate limited — daily quota may be exhausted")
        elif resp.status_code != 200:
            print(f"  [newsapi] {ticker}: HTTP {resp.status_code}")

    except Exception as e:
        print(f"  [newsapi] {ticker} failed: {type(e).__name__}")

    cache.set(cache_key, articles)
    return articles


def attach_news_sentiment(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Enrich each opportunity with NewsAPI articles and a keyword sentiment score.
    Merges new articles with existing news (deduplicated by title).
    Sets opp.news_sentiment_score to the average article sentiment (-10..+10).
    """
    if not config.NEWSAPI_KEY:
        return opportunities

    print(f"  [newsapi] Fetching and scoring news for {len(opportunities)} tickers...")
    for opp in opportunities:
        articles = fetch_ticker_news(opp.ticker, opp.name)
        if not articles:
            continue

        # Merge without duplicating headlines already in opp.news
        existing_titles = {a.get("title", "") for a in opp.news}
        new_articles    = [a for a in articles if a.get("title") not in existing_titles]
        opp.news        = (opp.news + new_articles)[:10]

        # Aggregate sentiment score from the NewsAPI batch
        scored = [a["sentiment"] for a in articles if "sentiment" in a]
        if scored:
            opp.news_sentiment_score = round(sum(scored) / len(scored), 1)

    return opportunities

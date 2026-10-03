"""
Full-article reading (Trafilatura) + FinBERT sentiment.

1. For holdings first (up to config.FULLTEXT_MAX_TICKERS), download the top
   articles and extract the main text with Trafilatura.
2. Score every English article with FinBERT (ProsusAI/finbert): title + text
   when available, headline only otherwise. Score = (P(positive) - P(negative)) x 10.

FinBERT needs `pip install -r requirements-ml.txt` (transformers + torch). Without
it, text extraction still runs and scoring is skipped.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import src.cache as cache
from src.models import Opportunity

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) stock-analysis/1.0"}
_SKIP_HOSTS = ("news.google.com",)  # JS redirects, no article body
_TEXT_CHARS = 4000
_classifier = None
_classifier_failed = False


def extract_text(html: str) -> str:
    import trafilatura
    return (trafilatura.extract(html, include_comments=False, include_tables=False) or "").strip()


def fetch_article_text(url: str) -> str:
    if not url or any(h in url for h in _SKIP_HOSTS):
        return ""
    cache_key = f"fulltext:{url}"
    cached = cache.get(cache_key, config.TTL_FULLTEXT)
    if cached is not None:
        return cached
    try:
        import requests
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        text = extract_text(resp.text)[:_TEXT_CHARS] if resp.status_code == 200 else ""
    except ImportError:
        print("  [fulltext] trafilatura not installed — pip install trafilatura")
        return ""
    except Exception:
        text = ""
    cache.set(cache_key, text)
    return text


def _get_classifier():
    global _classifier, _classifier_failed
    if _classifier is None and not _classifier_failed:
        try:
            from transformers import pipeline
            _classifier = pipeline("text-classification", model=config.FINBERT_MODEL, top_k=None)
        except Exception as e:
            _classifier_failed = True
            print(f"  [finbert] unavailable ({type(e).__name__}) — "
                  f"install with: pip install -r requirements-ml.txt")
    return _classifier


def score_from_probs(probs: list[dict]) -> float:
    p = {d["label"].lower(): d["score"] for d in probs}
    return round((p.get("positive", 0.0) - p.get("negative", 0.0)) * 10, 2)


def _is_english(article: dict) -> bool:
    lang = (article.get("language") or "English").lower()
    return lang in ("english", "en", "eng")


def score_articles(articles: list[dict]) -> list[float]:
    clf = _get_classifier()
    if clf is None:
        return []
    batch = [a for a in articles if _is_english(a) and a.get("title")]
    if not batch:
        return []
    texts = [f"{a['title']}. {a.get('text', '')[:1500]}".strip() for a in batch]
    results = clf(texts, truncation=True, max_length=512)
    scores = []
    for article, probs in zip(batch, results):
        article["finbert"] = score_from_probs(probs)
        scores.append(article["finbert"])
    return scores


def attach_fulltext_sentiment(opportunities: list[Opportunity]) -> list[Opportunity]:
    if not config.FULLTEXT_ENABLED:
        return opportunities
    ranked = sorted(opportunities, key=lambda o: 0 if o.portfolio else 1)
    readers = ranked[:config.FULLTEXT_MAX_TICKERS]
    print(f"  [fulltext] Reading up to {config.FULLTEXT_PER_TICKER} articles each "
          f"for {len(readers)} tickers (holdings first)")
    fetched = 0
    for opp in readers:
        for article in opp.news[:config.FULLTEXT_PER_TICKER]:
            if not article.get("text"):
                article["text"] = fetch_article_text(article.get("url", ""))
                fetched += bool(article["text"])
    print(f"  [fulltext] Extracted {fetched} article bodies")

    scored = 0
    for opp in opportunities:
        scores = score_articles(opp.news)
        if scores:
            opp.finbert_score = round(sum(scores) / len(scores), 1)
            scored += 1
        elif _classifier_failed:
            break
    if scored:
        print(f"  [finbert] Scored news for {scored} tickers")
    return opportunities

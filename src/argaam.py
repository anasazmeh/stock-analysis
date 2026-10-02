"""
Argaam — Saudi Tadawul (.SR) analyst targets. OPT-IN (config.ARGAAM_ENABLED).

The endpoint below is not a documented public API; Argaam's terms may require a
licence for automated use. It is off by default. When enabled, only targets
issued within config.ARGAAM_MAX_TARGET_AGE_DAYS are used, and the analyst count
and target range are recorded for the consensus-quality check.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import requests
import config
import src.cache as cache
from src.models import Opportunity

_BASE = "https://www.argaam.com/api/v1.0/json/stocks/en/{code}/analyst-recommendations"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-analysis/1.0)", "Accept": "application/json"}
_DATE_KEYS = ("date", "Date", "recommendationDate", "RecommendationDate", "publishDate")
_TARGET_KEYS = ("targetPrice", "TargetPrice", "target_price")


def _fetch(code: str):
    cache_key = f"argaam:{code}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return cached
    try:
        resp = requests.get(_BASE.format(code=code), headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            print(f"  [argaam] {code}: HTTP {resp.status_code}")
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  [argaam] {code} failed: {type(e).__name__}")
        return None
    cache.set(cache_key, data)
    return data


def recent_targets(recs: list, today: date = None) -> list[float]:
    """Targets issued within the age limit; undated targets are dropped."""
    today = today or date.today()
    cutoff = (today - timedelta(days=config.ARGAAM_MAX_TARGET_AGE_DAYS)).isoformat()
    out = []
    for rec in recs or []:
        tp = next((rec.get(k) for k in _TARGET_KEYS if rec.get(k)), None)
        when = next((str(rec.get(k))[:10] for k in _DATE_KEYS if rec.get(k)), "")
        if not tp or not when or when < cutoff:
            continue
        try:
            out.append(float(tp))
        except (TypeError, ValueError):
            continue
    return out


def enrich_saudi_targets(opportunities: list[Opportunity]) -> list[Opportunity]:
    if not config.ARGAAM_ENABLED:
        return opportunities
    for opp in opportunities:
        if not opp.ticker.endswith(".SR") or opp.target or not opp.price:
            continue
        data = _fetch(opp.ticker.replace(".SR", ""))
        recs = data if isinstance(data, list) else (data or {}).get("data", (data or {}).get("recommendations", []))
        targets = recent_targets(recs)
        if not targets:
            continue
        opp.target = round(sum(targets) / len(targets), 2)
        opp.upside = round((opp.target / opp.price - 1) * 100, 1)
        opp.analyst_count = len(targets)
        opp.target_high, opp.target_low = max(targets), min(targets)
        opp.target_source = "Argaam"
    return opportunities

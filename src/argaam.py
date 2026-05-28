"""
Argaam enrichment — Saudi Tadawul (.SR) analyst targets + recommendations.
Argaam provides free JSON data for Saudi-listed companies.

Endpoint: https://www.argaam.com/api/v1.0/json/stocks/en/{code}/analyst-recommendations
where {code} is the numeric part of the ticker (e.g. "2222" from "2222.SR").
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config
import src.cache as cache
from src.models import Opportunity

_BASE = "https://www.argaam.com/api/v1.0/json/stocks/en/{code}/analyst-recommendations"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; stock-analysis-bot/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.argaam.com/",
}


def _fetch_analyst_data(code: str) -> dict | None:
    """Fetch Argaam analyst consensus for a Saudi stock code (numeric part only)."""
    cache_key = f"argaam:{code}"
    cached = cache.get(cache_key, config.TTL_FUNDAMENTALS)
    if cached:
        return cached

    try:
        url = _BASE.format(code=code)
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            cache.set(cache_key, data)
            return data
        else:
            print(f"  [argaam] {code}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [argaam] {code} failed: {e}")

    return None


def enrich_saudi_targets(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Fill missing analyst targets for .SR tickers using Argaam.
    Only processes opportunities where target == 0 or upside is None.
    """
    saudi_opps = [
        o for o in opportunities
        if o.ticker.endswith(".SR") and (o.target == 0 or o.upside is None)
    ]
    if not saudi_opps:
        return opportunities

    print(f"  [argaam] Enriching {len(saudi_opps)} Saudi tickers...")

    for opp in saudi_opps:
        code = opp.ticker.replace(".SR", "")
        data = _fetch_analyst_data(code)
        if not data:
            continue

        try:
            # Argaam returns a list of analyst recommendations with target prices
            recs = data if isinstance(data, list) else data.get("data", data.get("recommendations", []))
            if not recs:
                continue

            targets = []
            for rec in recs:
                tp = rec.get("targetPrice") or rec.get("TargetPrice") or rec.get("target_price")
                if tp:
                    try:
                        targets.append(float(tp))
                    except (TypeError, ValueError):
                        pass

            if targets and opp.price:
                consensus = round(sum(targets) / len(targets), 2)
                opp.target = consensus
                opp.upside = round((consensus / opp.price - 1) * 100, 1)
                print(f"  [argaam] {opp.ticker}: consensus target {consensus:.2f} SAR "
                      f"(upside {opp.upside:+.1f}%, n={len(targets)})")
        except Exception as e:
            print(f"  [argaam] {opp.ticker} parse error: {e}")

    return opportunities

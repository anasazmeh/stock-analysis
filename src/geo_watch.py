"""
Regulatory / geopolitical watch mapped to holdings (free, no key).

Queries the US Federal Register for recent Bureau of Industry and Security (BIS)
documents per theme in config.GEO_THEMES (chip export controls, Entity List).
A theme with a document in the last config.GEO_LOOKBACK_DAYS days is "active":
its tickers get a geo note (and a risk bump to High) and the report shows the
share of the portfolio exposed.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

import requests
import config
import src.cache as cache
from src.models import Opportunity, MacroContext

_API = "https://www.federalregister.gov/api/v1/documents.json"
STATUS = {"failed_queries": 0}


def fetch_documents(term: str, agency: str, since: date) -> list[dict]:
    key = f"fedreg:{agency}:{term}:{since}"
    cached = cache.get(key, 12 * 3600)
    if cached is not None:
        return cached
    params = {"conditions[term]": term, "conditions[agencies][]": agency,
              "conditions[publication_date][gte]": since.isoformat(),
              "order": "newest", "per_page": 10}
    try:
        resp = requests.get(_API, params=params, timeout=15)
        rows = resp.json().get("results", []) if resp.status_code == 200 else None
    except (requests.RequestException, ValueError) as e:
        print(f"  [geo] Federal Register query failed: {type(e).__name__}")
        STATUS["failed_queries"] += 1
        return []
    if rows is None:
        STATUS["failed_queries"] += 1
        return []
    docs = [{"title": r.get("title", ""), "date": r.get("publication_date", ""),
             "url": r.get("html_url", ""), "type": r.get("type", "")} for r in rows]
    cache.set(key, docs)
    return docs


def apply_geo_watch(opportunities: list[Opportunity], macro: MacroContext, today: date = None) -> MacroContext:
    today = today or date.today()
    since = today - timedelta(days=config.GEO_LOOKBACK_DAYS)
    by_ticker = {o.ticker: o for o in opportunities}
    held = [o for o in opportunities if o.portfolio and o.portfolio.value_eur]
    total = sum(o.portfolio.value_eur for o in held)
    macro.geo_themes = []
    for theme, spec in config.GEO_THEMES.items():
        docs = fetch_documents(spec["term"], spec.get("agency", "industry-and-security-bureau"), since)
        if not docs:
            continue
        latest = docs[0]
        exposed = sum(o.portfolio.value_eur for o in held if o.ticker in spec["tickers"])
        macro.geo_themes.append({
            "theme": theme, "latest": latest, "documents": len(docs),
            "portfolio_exposed_pct": round(exposed / total * 100, 1) if total else None,
        })
        for t in spec["tickers"]:
            opp = by_ticker.get(t)
            if opp and opp.risk:
                opp.risk.geo_notes.append(f"{theme}: {latest['title'][:90]} ({latest['date']})")
                opp.risk.geo_exposure = "High"
    return macro

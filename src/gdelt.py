"""
GDELT DOC 2.0 news (free, no key). Worldwide coverage updated every 15 minutes,
searched across machine-translated text in 65 languages, so English queries also
find Arabic coverage of Saudi/UAE companies.

GDELT asks clients to send at most one request every 5 seconds, so per-ticker
queries are capped at config.GDELT_MAX_TICKERS (holdings first). A rate-limited
query (HTTP 429) is retried once after a pause; if GDELT keeps refusing, the rest
of the run skips it instead of logging dozens of 429s.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import time
from datetime import datetime

import requests
import config
import src.cache as cache
from src.models import Opportunity, MacroContext
from src.symbols import clean_name

_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_MIN_INTERVAL = 6.0      # measured from the end of the previous request
_RETRY_WAIT = 15
_MAX_REFUSALS = 3        # rate-limited queries (after the retry) before GDELT is paused for the run
_last_request = 0.0
STATE = {"refused": 0, "paused": False, "skipped": 0}
_GCC_SUFFIXES = (".SR", ".AD", ".DU", ".AE")
_NAME_SUFFIXES = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|n\.?v|s\.?a|se|ag|"
    r"p\.?j\.?s\.?c|p\.?s\.?c|s\.?j\.?s\.?c|holdings?|group|class [a-c]|adr|ordinary shares)\.?$",
    re.IGNORECASE,
)


def company_query(name: str, ticker: str) -> str:
    """Build a GDELT query from a company name, e.g. 'NVIDIA Corporation' -> '"NVIDIA"'."""
    clean = clean_name(name)
    if not clean or clean == ticker:
        clean = ticker.split(".")[0]
    clean = clean.replace(".com", "")
    prev = None
    while prev != clean:
        prev = clean
        clean = _NAME_SUFFIXES.sub("", clean).strip(" ,.")
    clean = clean.replace('"', "")
    query = f'"{clean}"' if " " in clean else clean
    if len(clean) <= 4:
        # Short names (BYD, NIO, SAP) are ambiguous, and GDELT rejects a quoted phrase that short,
        # so search for the name next to a market word instead
        query = f'("{clean} shares" OR "{clean} stock" OR "{clean} earnings")'
    if not ticker.upper().endswith(_GCC_SUFFIXES):
        query += " sourcelang:english"
    return query


def _parse_seendate(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def parse_artlist(payload: dict, limit: int) -> list[dict]:
    articles = []
    for item in (payload or {}).get("articles", [])[:limit]:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        articles.append({
            "title":    title,
            "summary":  title,
            "source":   item.get("domain", "GDELT"),
            "url":      item.get("url", ""),
            "date":     _parse_seendate(item.get("seendate", "")),
            "language": item.get("language", ""),
            "provider": "GDELT",
        })
    return articles


def _get(params: dict):
    global _last_request
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        return requests.get(_API, params=params, timeout=20)
    finally:
        _last_request = time.monotonic()


def search(query: str, limit: int = 8, timespan: str = "7d") -> list[dict]:
    cache_key = f"gdelt:{timespan}:{limit}:{query}"
    cached = cache.get(cache_key, config.TTL_NEWS)
    if cached is not None:
        return cached
    if STATE["paused"]:
        STATE["skipped"] += 1
        return []

    params = {"query": query, "mode": "ArtList", "format": "json",
              "maxrecords": limit, "timespan": timespan, "sort": "DateDesc"}
    try:
        resp = _get(params)
        if resp.status_code == 429:
            time.sleep(_RETRY_WAIT)
            resp = _get(params)
        if resp.status_code == 429:
            STATE["refused"] += 1
            if STATE["refused"] >= _MAX_REFUSALS:
                STATE["paused"] = True
                print("  [gdelt] GDELT keeps rate-limiting (HTTP 429) — skipping it for the rest of this run")
            return []
        if resp.status_code != 200:
            print(f"  [gdelt] '{query}': HTTP {resp.status_code}")
            return []
        try:
            payload = resp.json()
        except ValueError:
            # GDELT reports query errors and rate limiting as plain text
            print(f"  [gdelt] '{query}': {resp.text.strip()[:120]}")
            return []
    except Exception as e:
        print(f"  [gdelt] '{query}' failed: {e}")
        return []

    articles = parse_artlist(payload, limit)
    cache.set(cache_key, articles)
    return articles


def _priority_order(opportunities: list[Opportunity]) -> list[Opportunity]:
    def rank(o):
        if o.portfolio:
            return 0
        return 1 if o.ticker in config.CURATED_WATCHLIST else 2
    return sorted(opportunities, key=rank)


def _merge(existing: list[dict], new: list[dict], cap: int) -> list[dict]:
    seen = {a.get("title", "").strip().lower() for a in existing}
    merged = list(existing)
    for a in new:
        key = a["title"].strip().lower()
        if key not in seen:
            merged.append(a)
            seen.add(key)
    return merged[:cap]


def attach_gdelt_news(opportunities: list[Opportunity]) -> list[Opportunity]:
    if not config.GDELT_ENABLED:
        return opportunities
    targets = _priority_order([o for o in opportunities if o.price > 0])[:config.GDELT_MAX_TICKERS]
    skipped = len([o for o in opportunities if o.price > 0]) - len(targets)
    print(f"  [gdelt] Searching news for {len(targets)} tickers (~{len(targets) * 6}s)"
          + (f"; {skipped} lower-priority tickers skipped" if skipped > 0 else ""))
    for opp in targets:
        articles = search(company_query(opp.name, opp.ticker),
                          config.GDELT_ARTICLES, config.GDELT_TIMESPAN)
        opp.news = _merge(opp.news, articles, cap=12)
    if STATE["skipped"]:
        print(f"  [gdelt] {STATE['skipped']} tickers without GDELT news this run (rate-limited); "
              f"other news sources still apply")
    return opportunities


def add_gdelt_macro(macro: MacroContext) -> MacroContext:
    if not config.GDELT_ENABLED:
        return macro
    fresh = []
    for query in config.GDELT_MACRO_QUERIES:
        fresh.extend(search(query + " sourcelang:english", limit=4, timespan="3d"))
    # GDELT items go first: they are minutes old, RSS items can be days old
    macro.macro_news = _merge(fresh, macro.macro_news or [], cap=80)
    return macro

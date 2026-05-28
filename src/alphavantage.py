"""
Alpha Vantage enrichment — fills gaps left by yfinance.
  • Missing analyst price targets  (OVERVIEW endpoint)
  • Next earnings date             (EARNINGS_CALENDAR endpoint)
  • Last-quarter EPS surprise      (EARNINGS endpoint)

Requires ALPHA_VANTAGE_API_KEY (free tier: 25 req/day, 5 req/min).
All functions are no-ops when the key is absent.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import csv
import io
import time
import config
import src.cache as cache
from src.models import Opportunity

_BASE = "https://www.alphavantage.co/query"
_RATE_DELAY = 12  # seconds between calls to stay under 5 req/min on free tier


def _get(params: dict) -> dict | list | None:
    """GET Alpha Vantage with retry on rate-limit (HTTP 429 or empty JSON note)."""
    params["apikey"] = config.ALPHA_VANTAGE_API_KEY
    for attempt in range(3):
        try:
            resp = requests.get(_BASE, params=params, timeout=15)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            data = resp.json()
            if isinstance(data, dict) and "Note" in data:
                time.sleep(60)
                continue
            return data
        except Exception as e:
            print(f"  [av] request failed ({attempt+1}/3): {e}")
            time.sleep(5)
    return None


def enrich_missing_targets(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Fill analyst price targets that yfinance left as 0.
    Only calls Alpha Vantage for US-listed tickers (no exchange suffix).
    """
    if not config.ALPHA_VANTAGE_API_KEY:
        return opportunities

    needs_target = [
        o for o in opportunities
        if (o.target == 0 or o.upside is None) and "." not in o.ticker
    ]
    if not needs_target:
        return opportunities

    print(f"  [av] Filling missing targets for {len(needs_target)} tickers...")
    for opp in needs_target:
        cache_key = f"av:overview:{opp.ticker}"
        data = cache.get(cache_key, config.TTL_FUNDAMENTALS)
        if not data:
            data = _get({"function": "OVERVIEW", "symbol": opp.ticker})
            if data:
                cache.set(cache_key, data)
            time.sleep(_RATE_DELAY)

        if not data:
            continue
        try:
            target = float(data.get("AnalystTargetPrice") or 0)
            if target and opp.price:
                opp.target = round(target, 2)
                opp.upside = round((target / opp.price - 1) * 100, 1)
                print(f"  [av] {opp.ticker}: target ${target:.2f} (upside {opp.upside:+.1f}%)")
        except (TypeError, ValueError):
            pass

    return opportunities


def fetch_earnings_dates(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Populate earnings_date (next scheduled earnings) for US tickers.
    Uses the EARNINGS_CALENDAR CSV endpoint (no per-ticker call — one bulk download).
    """
    if not config.ALPHA_VANTAGE_API_KEY:
        return opportunities

    us_opps = {o.ticker: o for o in opportunities if "." not in o.ticker}
    if not us_opps:
        return opportunities

    cache_key = "av:earnings_calendar"
    rows = cache.get(cache_key, config.TTL_EARNINGS)

    if not rows:
        print("  [av] Downloading earnings calendar...")
        try:
            params = {
                "function": "EARNINGS_CALENDAR",
                "horizon":  "3month",
                "apikey":   config.ALPHA_VANTAGE_API_KEY,
            }
            resp = requests.get(_BASE, params=params, timeout=20)
            if resp.status_code == 200 and resp.text.strip():
                reader = csv.DictReader(io.StringIO(resp.text))
                rows = [r for r in reader]
                cache.set(cache_key, rows)
        except Exception as e:
            print(f"  [av] earnings calendar failed: {e}")
            rows = []

    for row in (rows or []):
        ticker = row.get("symbol", "")
        if ticker in us_opps and not us_opps[ticker].earnings_date:
            date_str = row.get("reportDate", "")
            if date_str:
                us_opps[ticker].earnings_date = date_str

    return opportunities


def fetch_earnings_surprises(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Populate eps_surprise (last quarter EPS surprise %) for US tickers.
    Calls EARNINGS endpoint per ticker — only for tickers without a value yet.
    """
    if not config.ALPHA_VANTAGE_API_KEY:
        return opportunities

    needs = [
        o for o in opportunities
        if o.eps_surprise is None and "." not in o.ticker
    ]
    if not needs:
        return opportunities

    print(f"  [av] Fetching EPS surprises for {len(needs)} tickers...")
    for opp in needs:
        cache_key = f"av:earnings:{opp.ticker}"
        data = cache.get(cache_key, config.TTL_EARNINGS)
        if not data:
            data = _get({"function": "EARNINGS", "symbol": opp.ticker})
            if data:
                cache.set(cache_key, data)
            time.sleep(_RATE_DELAY)

        if not data:
            continue
        try:
            quarterly = data.get("quarterlyEarnings", [])
            if quarterly:
                latest = quarterly[0]
                surprise_pct = float(latest.get("surprisePercentage") or 0)
                opp.eps_surprise = round(surprise_pct, 1)
        except (TypeError, ValueError, IndexError):
            pass

    return opportunities

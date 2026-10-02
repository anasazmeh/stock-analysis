"""
Alpha Vantage enrichment (free key: 25 requests/day, 5/minute).

  1. EARNINGS_CALENDAR  — one bulk CSV call, next earnings dates
  2. EARNINGS           — last-quarter EPS surprise, holdings first
  3. OVERVIEW           — analyst target where Yahoo has none, holdings first

A daily call budget (config.AV_DAILY_BUDGET) is persisted so repeated runs on the
same day don't exhaust the quota. Replies containing "Information", "Note" or
"Error Message" are quota/usage errors and are never cached.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import io
import time
from datetime import date

import requests
import config
import src.cache as cache
from src.models import Opportunity

_BASE = "https://www.alphavantage.co/query"
_RATE_DELAY = 12.5  # 5 calls/minute
_ERROR_KEYS = ("Information", "Note", "Error Message")
_CALENDAR_HEADER = {"symbol", "reportDate"}


class QuotaExhausted(Exception):
    pass


def _budget_key() -> str:
    return f"av:budget:{date.today().isoformat()}"


def calls_used() -> int:
    return cache.get(_budget_key(), 86400, ignore_disabled=True) or 0


def _spend():
    used = calls_used()
    if used >= config.AV_DAILY_BUDGET:
        raise QuotaExhausted()
    cache.set(_budget_key(), used + 1)


def is_error_reply(data) -> str:
    """Return the AV error text if this reply is a quota/usage message, else ''."""
    if isinstance(data, dict):
        for k in _ERROR_KEYS:
            if k in data:
                return str(data[k])[:120]
    return ""


def _get(params: dict):
    _spend()
    try:
        resp = requests.get(_BASE, params={**params, "apikey": config.ALPHA_VANTAGE_API_KEY}, timeout=20)
    except requests.RequestException as e:
        print(f"  [av] request failed: {type(e).__name__}")  # no URL: it contains the key
        return None
    finally:
        time.sleep(_RATE_DELAY)
    if resp.status_code != 200:
        print(f"  [av] HTTP {resp.status_code}")
        return None
    if params.get("function") == "EARNINGS_CALENDAR":
        return resp.text
    try:
        data = resp.json()
    except ValueError:
        return None
    err = is_error_reply(data)
    if err:
        print(f"  [av] {err}")
        if "rate limit" in err.lower() or "25 requests" in err or "premium" in err.lower():
            raise QuotaExhausted()
        return None
    return data


def parse_calendar(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text or ""))
    if not reader.fieldnames or not _CALENDAR_HEADER <= set(reader.fieldnames):
        return []  # an error message, not the CSV
    return [r for r in reader]


def _priority(opportunities: list[Opportunity]) -> list[Opportunity]:
    return sorted(opportunities, key=lambda o: (0 if o.portfolio else 1, -(o.mcap or 0)))


def run_alpha_vantage(opportunities: list[Opportunity]) -> dict:
    """Run the three steps within today's budget. Returns counts for the run log."""
    stats = {"earnings_dates": 0, "eps_surprises": 0, "targets": 0, "budget_left": 0, "stopped": ""}
    if not config.ALPHA_VANTAGE_API_KEY:
        return stats
    us = [o for o in opportunities if o.price > 0 and "." not in o.ticker]
    try:
        # 1. Earnings calendar (one call)
        rows = cache.get("av:earnings_calendar", config.TTL_EARNINGS)
        if not rows:
            rows = parse_calendar(_get({"function": "EARNINGS_CALENDAR", "horizon": "3month"}))
            if rows:
                cache.set("av:earnings_calendar", rows)
        by_ticker = {o.ticker: o for o in us}
        for row in rows or []:
            o = by_ticker.get(row.get("symbol", ""))
            if o and not o.earnings_date and row.get("reportDate"):
                o.earnings_date = row["reportDate"]
                stats["earnings_dates"] += 1

        # 2. EPS surprise, holdings first
        for opp in _priority([o for o in us if o.eps_surprise is None]):
            data = cache.get(f"av:earnings:{opp.ticker}", config.TTL_EARNINGS)
            if not data:
                data = _get({"function": "EARNINGS", "symbol": opp.ticker})
                if data:
                    cache.set(f"av:earnings:{opp.ticker}", data)
            q = (data or {}).get("quarterlyEarnings") or []
            if q and q[0].get("surprisePercentage") not in (None, "None", ""):
                try:
                    opp.eps_surprise = round(float(q[0]["surprisePercentage"]), 1)
                    stats["eps_surprises"] += 1
                except (TypeError, ValueError):
                    pass
            if not opp.portfolio and calls_used() >= config.AV_DAILY_BUDGET - config.AV_RESERVE_FOR_TARGETS:
                break

        # 3. Missing analyst targets
        for opp in _priority([o for o in us if not o.target]):
            data = cache.get(f"av:overview:{opp.ticker}", config.TTL_FUNDAMENTALS)
            if not data:
                data = _get({"function": "OVERVIEW", "symbol": opp.ticker})
                if data:
                    cache.set(f"av:overview:{opp.ticker}", data)
            try:
                target = float((data or {}).get("AnalystTargetPrice") or 0)
            except (TypeError, ValueError):
                target = 0
            if target and opp.price:
                opp.target = round(target, 2)
                opp.upside = round((target / opp.price - 1) * 100, 1)
                opp.target_source = "Alpha Vantage"
                opp.analyst_count = None  # AV gives no count → consensus marked "Unknown count"
                stats["targets"] += 1
    except QuotaExhausted:
        stats["stopped"] = "daily budget reached"
        print(f"  [av] Daily budget of {config.AV_DAILY_BUDGET} calls reached — remaining tickers skipped")
    stats["budget_left"] = max(0, config.AV_DAILY_BUDGET - calls_used())
    return stats

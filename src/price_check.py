"""
Price cross-check: compares each Yahoo Finance price with a Finnhub quote.

Finnhub's free tier covers US listings (incl. ADRs such as TSM, ASML, SAP) at
60 calls/minute. A Yahoo price counts as verified if it is within
config.PRICE_CHECK_TOLERANCE_PCT of Finnhub's live price or previous close
(Yahoo often serves the prior close outside market hours).

Statuses: Verified · Mismatch · Single source (non-US / no key) · Unchecked (call failed)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime, timezone

import requests
import config
import src.cache as cache
from src.models import Opportunity
from src.portfolio import get_portfolio_tickers

_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_MIN_INTERVAL = 1.05  # free tier: 60 calls/minute
_last_call = 0.0


class RateLimited(Exception):
    pass


def fetch_quote(ticker: str) -> dict:
    """Return {'price', 'prev_close', 'as_of'} from Finnhub, or {} if unavailable."""
    global _last_call
    cache_key = f"finnhub:quote:{ticker}"
    cached = cache.get(cache_key, config.TTL_PRICE_CHECK)
    if cached is not None:
        return cached

    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    try:
        resp = requests.get(_QUOTE_URL, params={"symbol": ticker.replace("-", ".")},  # BRK-B -> BRK.B
                            headers={"X-Finnhub-Token": config.FINNHUB_API_KEY}, timeout=10)
    except requests.RequestException as e:
        # don't print the exception: its message can contain the URL with the API key
        print(f"  [price-check] {ticker}: request failed ({type(e).__name__})")
        return {}
    if resp.status_code == 429:
        raise RateLimited()
    if resp.status_code != 200:
        print(f"  [price-check] {ticker}: HTTP {resp.status_code}")
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}

    quote = parse_quote(data)
    cache.set(cache_key, quote)
    return quote


def parse_quote(data: dict) -> dict:
    """Finnhub returns c=0 for symbols it doesn't cover."""
    price = data.get("c") or 0
    if not price:
        return {}
    ts = data.get("t") or 0
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else ""
    return {"price": float(price), "prev_close": float(data.get("pc") or 0), "as_of": as_of}


def compare(yahoo_price: float, quote: dict, tolerance_pct: float) -> tuple[str, float]:
    """Return (status, diff_pct vs Finnhub live price)."""
    live = quote["price"]
    diff_live = abs(yahoo_price / live - 1) * 100
    prev = quote.get("prev_close") or 0
    diff_prev = abs(yahoo_price / prev - 1) * 100 if prev else float("inf")
    status = "Verified" if min(diff_live, diff_prev) <= tolerance_pct else "Mismatch"
    return status, round((yahoo_price / live - 1) * 100, 2)


def cross_check_prices(opportunities: list[Opportunity]) -> list[Opportunity]:
    valid = [o for o in opportunities if o.price > 0]
    us = [o for o in valid if "." not in o.ticker]
    for o in valid:
        o.price_check = "Single source"

    if not config.FINNHUB_API_KEY:
        print("  [price-check] FINNHUB_API_KEY not set — all prices single-source")
        return opportunities

    held = set(get_portfolio_tickers())
    us.sort(key=lambda o: 0 if o.ticker in held else 1)
    print(f"  [price-check] Checking {len(us)} US prices against Finnhub "
          f"(~{int(len(us) * _MIN_INTERVAL)}s); {len(valid) - len(us)} non-US stay single-source")
    for i, opp in enumerate(us):
        try:
            quote = fetch_quote(opp.ticker)
        except RateLimited:
            print(f"  [price-check] Finnhub rate limit hit — {len(us) - i} tickers left unchecked")
            for rest in us[i:]:
                rest.price_check = "Unchecked"
            break
        if not quote:
            opp.price_check = "Unchecked"
            continue
        opp.price_check, opp.price_diff_pct = compare(opp.price, quote,
                                                      config.PRICE_CHECK_TOLERANCE_PCT)
        opp.price_alt = quote["price"]
        opp.price_as_of = quote["as_of"]
        if opp.price_check == "Mismatch":
            print(f"  [price-check] {opp.ticker}: MISMATCH Yahoo {opp.price:.2f} vs "
                  f"Finnhub {quote['price']:.2f} ({opp.price_diff_pct:+.1f}%)")
    return opportunities

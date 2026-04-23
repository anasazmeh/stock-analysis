"""
Stage 1 — Discovery
Finds candidate tickers via yfinance screeners + curated watchlist.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import config
import src.cache as cache

def discover_candidates() -> list[str]:
    """
    Return a deduplicated list of ticker symbols (up to MAX_TICKERS).
    Sources: yfinance screeners + curated watchlist.
    Results cached for TTL_SCREENER seconds.
    """
    cache_key = "discovery:screeners"
    cached = cache.get(cache_key, config.TTL_SCREENER)
    if cached:
        return cached

    tickers: set[str] = set()

    # 1. Always include curated watchlist
    tickers.update(config.CURATED_WATCHLIST.keys())

    # 2. Run yfinance screeners
    for screener_name in config.SCREENERS:
        try:
            result = yf.screen(screener_name, size=25)
            if result and "quotes" in result:
                for q in result["quotes"]:
                    sym = q.get("symbol", "")
                    if sym:
                        tickers.add(sym)
        except Exception as e:
            print(f"  [discovery] screener '{screener_name}' failed: {e}")

    # 3. Cap and sort
    result_list = sorted(tickers)[:config.MAX_TICKERS]

    cache.set(cache_key, result_list)
    print(f"  [discovery] Found {len(result_list)} candidates")
    return result_list

"""
Stage 1 — Discovery
Curated watchlist (always kept) + index/Shariah-ETF universe picks + yfinance screeners.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import src.cache as cache
from src.universe import universe_candidates


def _screener_tickers() -> list[str]:
    import yfinance as yf
    found = []
    for screener_name in config.SCREENERS:
        try:
            result = yf.screen(screener_name, size=25)
            for q in (result or {}).get("quotes", []):
                sym = q.get("symbol", "")
                if sym and sym not in found:
                    found.append(sym)
        except Exception as e:
            print(f"  [discovery] screener '{screener_name}' failed: {e}")
    return found


def discover_candidates() -> list[str]:
    """
    Return the curated watchlist plus up to MAX_DISCOVERED extra names
    (index/ETF momentum picks first, then screener hits). Cached for TTL_SCREENER.
    """
    cache_key = "discovery:candidates"
    cached = cache.get(cache_key, config.TTL_SCREENER)
    if cached:
        return cached

    curated = [t for t in config.CURATED_WATCHLIST if t not in config.AVOID_LIST]
    seen = set(curated)

    extras = []
    for sym in universe_candidates(exclude=seen) + _screener_tickers():
        if sym not in seen and sym not in config.AVOID_LIST:
            extras.append(sym)
            seen.add(sym)
    dropped = max(0, len(extras) - config.MAX_DISCOVERED)
    extras = extras[:config.MAX_DISCOVERED]

    result_list = curated + extras
    print(f"  [discovery] {len(curated)} curated + {len(extras)} discovered"
          + (f" ({dropped} more cut by MAX_DISCOVERED)" if dropped else ""))
    if extras:
        cache.set(cache_key, result_list)  # don't cache a run where every source failed
    return result_list

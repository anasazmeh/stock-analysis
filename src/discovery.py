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


def _regional_tickers() -> list[str]:
    """Largest companies per region (Saudi, UAE, Germany, Netherlands, France)."""
    import yfinance as yf
    found = []
    for region, size in config.REGIONAL_SCREENS.items():
        try:
            q = yf.EquityQuery("and", [yf.EquityQuery("eq", ["region", region]),
                                       yf.EquityQuery("gt", ["intradaymarketcap", config.REGIONAL_MIN_MCAP])])
            result = yf.screen(q, size=size, sortField="intradaymarketcap", sortAsc=False)
            found += [q_["symbol"] for q_ in (result or {}).get("quotes", []) if q_.get("symbol")]
        except Exception as e:
            print(f"  [discovery] regional screen '{region}' failed: {type(e).__name__}")
    return found


def _config_hash() -> str:
    import hashlib
    parts = [sorted(config.CURATED_WATCHLIST), config.SCREENERS, config.REGIONAL_SCREENS,
             config.MAX_DISCOVERED, config.UNIVERSE_TOP_N, sorted(config.AVOID_LIST)]
    return hashlib.md5(repr(parts).encode()).hexdigest()[:10]


def discover_candidates() -> list[str]:
    """
    Return the curated watchlist plus up to MAX_DISCOVERED extra names
    (index/ETF momentum picks first, then regional and screener hits). Cached for TTL_SCREENER.
    """
    cache_key = f"discovery:candidates:{_config_hash()}"
    cached = cache.get(cache_key, config.TTL_SCREENER)
    if cached:
        return cached

    curated = [t for t in config.CURATED_WATCHLIST if t not in config.AVOID_LIST]
    seen = set(curated)

    extras = []
    for sym in universe_candidates(exclude=seen) + _regional_tickers() + _screener_tickers():
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

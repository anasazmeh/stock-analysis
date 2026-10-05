"""
Symbol resolver — finds the Yahoo symbol that actually returns a quote.

Exchanges and data vendors disagree on suffixes: Abu Dhabi stocks appear as
".AD" in some places and ".AE" on Yahoo, Dubai moved from ".DU" to ".AE", and
Hong Kong codes need four digits ("0700.HK", not "700.HK"). For each ticker we
try the known variants, then Yahoo's search by company name, and cache the
answer for a month (a miss for a week) so the 404s don't repeat every run.

When a symbol changes, its config entries (watchlist text, Shariah overrides,
Islamic-financials list, tradability overrides) are copied to the new symbol.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import re

import config
from src import cache

_TTL_HIT = 30 * 24 * 3600
_TTL_MISS = 7 * 24 * 3600
_UAE = (".AD", ".AE", ".DU")
STATUS = {"resolved": {}, "missing": []}


def quiet_yfinance():
    """yfinance logs every 404 itself. src/runlog.py sends library logs to the log file and the
    technical-debt backlog, not the screen; without it, keep the screen quiet."""
    from src import runlog
    logging.getLogger("yfinance").setLevel(logging.WARNING if "streams" in runlog._state else logging.CRITICAL)


def normalize(ticker: str) -> str:
    m = re.fullmatch(r"(\d{1,3})\.HK", ticker, re.I)
    return f"{int(m.group(1)):04d}.HK" if m else ticker


def candidates(ticker: str) -> list[str]:
    t = normalize(ticker)
    out = [t]
    base, dot, suffix = t.rpartition(".")
    if dot and "." + suffix.upper() in _UAE:
        out += [f"{base}{s}" for s in (".AE", ".AD") if f"{base}{s}" not in out]
    if t != ticker:
        out.append(ticker)
    return out


def _has_quote(symbol: str) -> bool:
    import yfinance as yf
    try:
        h = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
        return h is not None and not h.empty
    except Exception:
        return False


def _search(name: str, ticker: str):
    """Yahoo search by company name; keep a result on the same market as the original suffix."""
    import yfinance as yf
    suffix = "." + ticker.rpartition(".")[2].upper() if "." in ticker else ""
    same_market = _UAE if suffix in _UAE else (suffix,)
    try:
        quotes = yf.Search(name, max_results=8).quotes
    except Exception:
        return None
    for q in quotes:
        sym = q.get("symbol", "")
        if suffix and any(sym.upper().endswith(s) for s in same_market) and _has_quote(sym):
            return sym
    return None


def _name_hint(ticker: str) -> str:
    desc = config.CURATED_WATCHLIST.get(ticker, ("", ""))[1]
    return desc.split(" — ")[0].strip() if desc else ""


def resolve(ticker: str, probe=_has_quote, search=_search) -> str | None:
    key = f"symbol:v1:{ticker}"
    hit = cache.get(key, _TTL_HIT)
    if hit and hit.get("symbol"):
        return hit["symbol"]
    miss = cache.get(key + ":miss", _TTL_MISS)
    if miss:
        return None
    for c in candidates(ticker):
        if probe(c):
            cache.set(key, {"symbol": c})
            return c
    name = _name_hint(ticker)
    found = search(name, ticker) if name else None
    if found:
        cache.set(key, {"symbol": found})
        return found
    cache.set(key + ":miss", {"symbol": None})
    return None


def register_alias(old: str, new: str):
    for table in (config.CURATED_WATCHLIST, config.SHARIAH_OVERRIDES, config.ISLAMIC_FINANCIALS,
                  config.TRADABILITY_OVERRIDES):
        if old in table and new not in table:
            table[new] = table[old]


def resolve_tickers(tickers: list[str], keep: set = frozenset(), probe=_has_quote, search=_search) -> list[str]:
    """
    Return the list with each symbol replaced by one that has a Yahoo quote.
    Only symbols that need it are probed: those whose form is known to be wrong
    (3-digit HK, .AD/.DU) or that failed before. Tickers in `keep` (your holdings)
    are never renamed, only reported. Symbols with no quote anywhere are dropped.
    """
    quiet_yfinance()
    STATUS["resolved"], STATUS["missing"] = {}, []
    out = []
    for t in tickers:
        suspect = normalize(t) != t or t.upper().endswith((".AD", ".DU")) or cache.get(f"symbol:v1:{t}:checked", _TTL_HIT)
        if not suspect or t in keep:
            out.append(t)
            continue
        new = resolve(t, probe, search)
        if new is None:
            STATUS["missing"].append(t)
            continue
        if new != t:
            STATUS["resolved"][t] = new
            register_alias(t, new)
        out.append(new)
    if STATUS["resolved"]:
        print("  [symbols] " + ", ".join(f"{a} → {b}" for a, b in STATUS["resolved"].items()))
    if STATUS["missing"]:
        print(f"  [symbols] no Yahoo quote found for {', '.join(STATUS['missing'])} — skipped "
              f"(fix the symbol in config.py; checked again in a week)")
    return out


def mark_failed(tickers: list[str]):
    """Tickers that returned no price this run get probed for a better symbol next run."""
    for t in tickers:
        cache.invalidate(f"symbol:v1:{t}")
        cache.set(f"symbol:v1:{t}:checked", {"failed": True})


# ── One listing per company ───────────────────────────────────────────────
# Regional screens sort by market value, so the "largest German companies" include
# US giants' German secondary lines (Apple as APC.F on Frankfurt and APC.DE on Xetra).
# Same company, same shares — they must not take several Top 10 places.
SUFFIX_COUNTRY = {"": "United States", ".DE": "Germany", ".F": "Germany", ".PA": "France", ".AS": "Netherlands",
                  ".L": "United Kingdom", ".SR": "Saudi Arabia", ".AE": "United Arab Emirates", ".AD": "United Arab Emirates",
                  ".HK": "Hong Kong", ".T": "Japan", ".KS": "South Korea", ".NS": "India", ".MI": "Italy", ".MC": "Spain",
                  ".SW": "Switzerland", ".TO": "Canada", ".BR": "Belgium", ".CO": "Denmark", ".ST": "Sweden", ".OL": "Norway"}
_LEGAL = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|plc|ag|se|sa|nv|n\.v|ltd|limited|holdings?|group|"
                    r"class [a-c]|cl [a-c]|the|adr|ads|reg|registered|shares?|ord|common)\b\.?")


def company_key(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = _LEGAL.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    words = n.split()
    while len(words) > 1 and len(words[-1]) == 1:   # "Apple Inc. R" (registered share class marker), "... A"
        words.pop()
    return " ".join(words)


def _suffix(ticker: str) -> str:
    return "." + ticker.rpartition(".")[2].upper() if "." in ticker else ""


def dedupe_listings(opportunities: list, keep: set = frozenset()) -> tuple[list, dict]:
    """
    Keep one listing per company. Preference: a listing you hold, then the curated
    watchlist, then one you can trade at your brokers, then the home-market listing
    (exchange country = company country), then the most traded. Returns (opportunities, {dropped ticker: kept ticker}).
    """
    groups = {}
    for o in opportunities:
        key = company_key(o.name) if o.price > 0 else ""
        if not key or key == company_key(o.ticker):
            key = "ticker:" + o.ticker
        groups.setdefault(key, []).append(o)
    kept, dropped = [], {}
    for group in groups.values():
        if len(group) == 1:
            kept += group
            continue

        def rank(o):
            from src.data_quality import tradability
            home = SUFFIX_COUNTRY.get(_suffix(o.ticker)) == (o.country or "")
            return (o.ticker in keep or bool(o.portfolio), o.ticker in config.CURATED_WATCHLIST,
                    tradability(o.ticker) == "Yes", home, o.avg_volume or 0)
        group.sort(key=rank, reverse=True)
        best = group[0]
        kept.append(best)
        for o in group[1:]:
            if o.ticker in keep or o.portfolio:     # never drop something you hold
                kept.append(o)
            else:
                dropped[o.ticker] = best.ticker
    if dropped:
        print("  [symbols] same company, one listing kept: " + ", ".join(f"{a} → {b}" for a, b in dropped.items()))
    return kept, dropped

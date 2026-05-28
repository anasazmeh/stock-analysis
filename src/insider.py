"""
SEC EDGAR Form 4 insider trading signal (US tickers only, no API key needed).
Classifies 30-day insider activity as Bullish / Bearish / Neutral.

Data flow:
  1. Load company_tickers.json  → ticker → CIK mapping
  2. Fetch submissions JSON     → recent Form 4 filing accession numbers
  3. Parse each Form 4 XML      → extract nonDerivativeTransaction P/S codes + share counts
  4. Compute net signal         → Bullish if net buys > 0, Bearish if net sells dominate
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import xml.etree.ElementTree as ET
from datetime import date, timedelta
import config
import src.cache as cache
from src.models import Opportunity

_HEADERS = {"User-Agent": "stock-analysis-bot contact@example.com"}
_EDGAR_BASE = "https://data.sec.gov"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Minimum net shares to call a signal non-neutral
_BULLISH_THRESHOLD = 1_000
_BEARISH_THRESHOLD = -5_000  # sales are more common, use higher bar


def _load_ticker_cik_map() -> dict[str, str]:
    """Load SEC ticker→CIK mapping (cached 24h)."""
    cache_key = "edgar:ticker_cik_map"
    cached = cache.get(cache_key, 86400)
    if cached:
        return cached

    try:
        resp = requests.get(_TICKERS_URL, headers=_HEADERS, timeout=20)
        raw = resp.json()
        mapping = {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in raw.values()
        }
        cache.set(cache_key, mapping)
        return mapping
    except Exception as e:
        print(f"  [insider] CIK map load failed: {e}")
        return {}


def _get_recent_form4_filings(cik: str, days: int = 30) -> list[dict]:
    """Return recent Form 4 filing accession numbers for a given CIK."""
    cache_key = f"edgar:filings:{cik}"
    cached = cache.get(cache_key, config.TTL_INSIDER)
    if cached:
        return cached

    filings = []
    try:
        url = f"{_EDGAR_BASE}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        forms   = recent.get("form", [])
        dates   = recent.get("filingDate", [])
        accnos  = recent.get("accessionNumber", [])
        docs    = recent.get("primaryDocument", [])

        cutoff = (date.today() - timedelta(days=days)).isoformat()

        for form, filed, accno, doc in zip(forms, dates, accnos, docs):
            if form == "4" and filed >= cutoff:
                filings.append({
                    "accession": accno.replace("-", ""),
                    "document":  doc,
                    "date":      filed,
                })

        cache.set(cache_key, filings)
    except Exception as e:
        print(f"  [insider] filings fetch CIK {cik} failed: {e}")

    return filings


def _parse_form4_xml(cik: str, accession: str, document: str) -> list[dict]:
    """
    Download and parse a Form 4 XML filing.
    Returns list of {code, shares} where code is 'P' (purchase) or 'S' (sale).
    """
    url = f"{_EDGAR_BASE}/Archives/edgar/data/{int(cik)}/{accession}/{document}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    transactions = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        try:
            code_el  = txn.find("transactionCoding/transactionCode")
            shares_el = txn.find("transactionAmounts/transactionShares/value")
            if code_el is None or shares_el is None:
                continue
            code   = code_el.text.strip().upper()
            shares = abs(float(shares_el.text.strip()))
            if code in ("P", "S"):
                transactions.append({"code": code, "shares": shares})
        except (AttributeError, ValueError):
            continue

    return transactions


def _compute_signal(transactions: list[dict]) -> tuple[str, int]:
    """Derive signal from aggregated Form 4 transactions."""
    bought = sum(t["shares"] for t in transactions if t["code"] == "P")
    sold   = sum(t["shares"] for t in transactions if t["code"] == "S")
    net    = int(bought - sold)

    if net >= _BULLISH_THRESHOLD:
        return "Bullish", net
    elif net <= _BEARISH_THRESHOLD:
        return "Bearish", net
    return "Neutral", net


def fetch_insider_trades(opportunities: list[Opportunity]) -> list[Opportunity]:
    """
    Attach 30-day insider trading signal to each US-listed opportunity.
    Skips non-US tickers (those with a '.' in ticker, e.g. '2222.SR').
    """
    us_opps = [o for o in opportunities if "." not in o.ticker]
    if not us_opps:
        return opportunities

    print(f"  [insider] Loading SEC CIK map...")
    cik_map = _load_ticker_cik_map()
    if not cik_map:
        print("  [insider] CIK map unavailable — skipping insider signals")
        return opportunities

    found = sum(1 for o in us_opps if o.ticker in cik_map)
    print(f"  [insider] Fetching Form 4 data for {found} US tickers...")

    for opp in us_opps:
        cik = cik_map.get(opp.ticker)
        if not cik:
            continue

        filings = _get_recent_form4_filings(cik)
        if not filings:
            continue

        all_txns = []
        for filing in filings[:10]:  # cap to 10 most-recent Form 4s
            txns = _parse_form4_xml(cik, filing["accession"], filing["document"])
            all_txns.extend(txns)

        if all_txns:
            signal, net = _compute_signal(all_txns)
            opp.insider_signal     = signal
            opp.insider_net_shares = net
            if signal != "Neutral":
                direction = "bought" if net > 0 else "sold"
                print(f"  [insider] {opp.ticker}: {signal} — insiders {direction} "
                      f"{abs(net):,} net shares (30d)")

    return opportunities

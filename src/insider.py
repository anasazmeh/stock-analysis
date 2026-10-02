"""
SEC EDGAR Form 4 insider trading signal (US filers only, no API key).

Signal over the last 30 days: Bullish (net open-market buys >= 1,000 shares),
Bearish (net sells >= 5,000), Neutral, or N/A for foreign private issuers
(TSM, ASML, SAP, NIO ...), which do not file Form 4.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests
import config
import src.cache as cache
from src.models import Opportunity
from src.sec import (HEADERS, ARCHIVE_URL, load_ticker_cik_map, cik_for,
                     get_recent_submissions, is_foreign_issuer, raw_document)

_BULLISH_THRESHOLD = 1_000
_BEARISH_THRESHOLD = -5_000

# kept for modules that imported the old name
_load_ticker_cik_map = load_ticker_cik_map


def recent_form4(recent: dict, days: int = 30) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for form, filed, accno, doc in zip(recent.get("form", []), recent.get("filingDate", []),
                                       recent.get("accessionNumber", []), recent.get("primaryDocument", [])):
        if form == "4" and filed >= cutoff:
            out.append({"accession": accno.replace("-", ""), "document": raw_document(doc), "date": filed})
    return out


def parse_form4_xml(content: bytes) -> list[dict]:
    """Open-market purchases (P) and sales (S) from a Form 4 XML document."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    txns = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = txn.findtext("transactionCoding/transactionCode", "").strip().upper()
        shares = txn.findtext("transactionAmounts/transactionShares/value", "").strip()
        if code in ("P", "S") and shares:
            try:
                txns.append({"code": code, "shares": abs(float(shares))})
            except ValueError:
                continue
    return txns


def _fetch_form4(cik: str, filing: dict) -> list[dict]:
    cache_key = f"edgar:form4:{filing['accession']}"
    cached = cache.get(cache_key, 30 * 86400)
    if cached is not None:
        return cached
    url = ARCHIVE_URL.format(cik=int(cik), accession=filing["accession"], document=filing["document"])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        time.sleep(0.12)  # SEC fair access: 10 requests/second
        if resp.status_code != 200:
            return []
    except requests.RequestException:
        return []
    txns = parse_form4_xml(resp.content)
    cache.set(cache_key, txns)
    return txns


def compute_signal(transactions: list[dict]) -> tuple[str, int]:
    bought = sum(t["shares"] for t in transactions if t["code"] == "P")
    sold = sum(t["shares"] for t in transactions if t["code"] == "S")
    net = int(bought - sold)
    if net >= _BULLISH_THRESHOLD:
        return "Bullish", net
    if net <= _BEARISH_THRESHOLD:
        return "Bearish", net
    return "Neutral", net


def fetch_insider_trades(opportunities: list[Opportunity]) -> list[Opportunity]:
    us_opps = [o for o in opportunities if o.price > 0 and "." not in o.ticker]
    for o in opportunities:
        if "." in o.ticker:
            o.insider_signal = "N/A"
    if not us_opps:
        return opportunities
    cik_map = load_ticker_cik_map()
    if not cik_map:
        print("  [insider] CIK map unavailable — insider signals skipped")
        for o in us_opps:
            o.insider_signal = "Unavailable"
        return opportunities

    for opp in us_opps:
        cik = cik_for(opp.ticker, cik_map)
        if not cik:
            opp.insider_signal = "N/A"
            continue
        recent = get_recent_submissions(cik)
        if not recent:
            opp.insider_signal = "Unavailable"
            continue
        if is_foreign_issuer(recent):
            opp.insider_signal = "N/A"
            continue
        txns = []
        for filing in recent_form4(recent)[:15]:
            txns.extend(_fetch_form4(cik, filing))
        opp.insider_signal, opp.insider_net_shares = compute_signal(txns)
        if opp.insider_signal != "Neutral":
            print(f"  [insider] {opp.ticker}: {opp.insider_signal} — net {opp.insider_net_shares:+,} shares (30d)")
    return opportunities

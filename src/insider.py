"""
SEC EDGAR Form 4 insider trading signal (US filers only, no API key).

Signal over the last 30 days: Bullish (net open-market buys >= 1,000 shares),
Bearish (net discretionary sells >= 5,000 shares and >= 0.05% of the shares
outstanding), Neutral, or N/A for foreign private issuers (TSM, ASML, SAP, NIO ...),
which do not file Form 4.

Sales under a pre-set Rule 10b5-1 trading plan (the filing's 10b5-1 box) are
scheduled months ahead, so they are reported separately and don't count as a
bearish signal. Executives of large companies sell stock every month as pay; the
size test stops 7,000 shares of Microsoft from looking like a warning.
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
_BEARISH_SHARE_OF_COMPANY = 0.0005   # 0.05% of shares outstanding in 30 days

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
    """Open-market purchases (P) and sales (S) from a Form 4 XML document; plan=True for 10b5-1 plan trades."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    plan = root.findtext("aff10b5One", "").strip().lower() in ("1", "true")
    txns = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = txn.findtext("transactionCoding/transactionCode", "").strip().upper()
        shares = txn.findtext("transactionAmounts/transactionShares/value", "").strip()
        if code in ("P", "S") and shares:
            try:
                txns.append({"code": code, "shares": abs(float(shares)), "plan": plan})
            except ValueError:
                continue
    return txns


def _fetch_form4(cik: str, filing: dict) -> list[dict]:
    cache_key = f"edgar:form4:v2:{filing['accession']}"
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


def planned_sales(transactions: list[dict]) -> int:
    return int(sum(t["shares"] for t in transactions if t["code"] == "S" and t.get("plan")))


def compute_signal(transactions: list[dict], shares_outstanding: float = 0) -> tuple[str, int]:
    """(signal, net discretionary shares). 10b5-1 plan sales are left out of the net."""
    bought = sum(t["shares"] for t in transactions if t["code"] == "P")
    sold = sum(t["shares"] for t in transactions if t["code"] == "S" and not t.get("plan"))
    net = int(bought - sold)
    if net >= _BULLISH_THRESHOLD:
        return "Bullish", net
    material = not shares_outstanding or -net >= shares_outstanding * _BEARISH_SHARE_OF_COMPANY
    if net <= _BEARISH_THRESHOLD and material:
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

    quiet = 0
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
        shares_out = opp.mcap / opp.price if opp.mcap and opp.price else 0
        opp.insider_signal, opp.insider_net_shares = compute_signal(txns, shares_out)
        opp.insider_planned_shares = planned_sales(txns)
        if opp.insider_signal != "Neutral":
            share = f" ({-opp.insider_net_shares / shares_out:.2%} of the company)" if shares_out and opp.insider_net_shares < 0 else ""
            print(f"  [insider] {opp.ticker}: {opp.insider_signal} — net {opp.insider_net_shares:+,} shares (30d){share}")
        else:
            quiet += 1
    if quiet:
        print(f"  [insider] {quiet} US companies Neutral — small routine sales and pre-planned 10b5-1 sales don't count")
    return opportunities

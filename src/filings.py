"""
SEC EDGAR filings watch (free, no key) for US-listed tickers, including ADRs
such as TSM, ASML, SAP and NIO that file 6-K / 20-F.

Reads each company's submissions JSON and keeps recent filings of the forms in
config.FILINGS_FORMS, labelling 8-K items and flagging red-flag events
(bankruptcy, delisting notice, restated financials, auditor change, late filing).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import date, timedelta

import requests
import config
import src.cache as cache
from src.models import Opportunity
from src.insider import _load_ticker_cik_map

_HEADERS = {"User-Agent": config.SEC_USER_AGENT}
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

ITEM_LABELS = {
    "1.01": "Material agreement",
    "1.02": "Agreement terminated",
    "1.03": "Bankruptcy",
    "2.01": "Acquisition or disposal",
    "2.02": "Results",
    "2.03": "New debt obligation",
    "2.04": "Debt acceleration",
    "2.05": "Restructuring costs",
    "2.06": "Impairment",
    "3.01": "Delisting notice",
    "3.02": "Unregistered share sale",
    "3.03": "Shareholder rights changed",
    "4.01": "Auditor change",
    "4.02": "Prior financials unreliable",
    "5.01": "Change in control",
    "5.02": "Director or officer change",
    "5.07": "Shareholder vote",
    "7.01": "Reg FD disclosure",
    "8.01": "Other event",
}
RED_FLAG_ITEMS = {"1.03", "2.04", "2.06", "3.01", "4.01", "4.02"}
FORM_LABELS = {
    "6-K": "Foreign issuer report",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "20-F": "Annual report (foreign)",
    "S-1": "IPO / share registration",
    "F-1": "IPO / share registration (foreign)",
    "424B4": "Final prospectus (priced offering)",
    "S-3": "Shelf registration (possible share sale)",
    "F-3": "Shelf registration (possible share sale)",
    "SC 13D": "Activist stake >5%",
    "SCHEDULE 13D": "Activist stake >5%",
    "SC 13G": "Passive stake >5%",
    "SCHEDULE 13G": "Passive stake >5%",
    "144": "Insider intends to sell",
    "DEF 14A": "Proxy statement",
    "NT 10-K": "Late annual report",
    "NT 10-Q": "Late quarterly report",
}
RED_FLAG_FORMS = {"NT 10-K", "NT 10-Q"}


def _get_recent_submissions(cik: str) -> dict:
    cache_key = f"edgar:submissions:{cik}"
    cached = cache.get(cache_key, config.TTL_FILINGS)
    if cached:
        return cached
    try:
        resp = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  [filings] CIK {cik}: HTTP {resp.status_code}")
            return {}
        recent = resp.json().get("filings", {}).get("recent", {})
    except Exception as e:
        print(f"  [filings] CIK {cik} failed: {e}")
        return {}
    cache.set(cache_key, recent)
    return recent


def parse_recent_filings(cik: str, recent: dict, days: int, forms: set) -> list[dict]:
    """Turn the submissions 'recent' arrays into labelled filing dicts, newest first."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    n = len(recent.get("form", []))

    def col(name):
        values = recent.get(name) or []
        return values if len(values) == n else [""] * n

    rows = zip(col("form"), col("filingDate"), col("accessionNumber"),
               col("primaryDocument"), col("items"))
    filings = []
    for form, filed, accession, document, items in rows:
        if form not in forms or not filed or filed < cutoff:
            continue
        item_codes = [i.strip() for i in (items or "").split(",") if i.strip() and i.strip() != "9.01"]
        if form == "8-K":
            labels = [ITEM_LABELS.get(i, f"Item {i}") for i in item_codes] or ["Current report"]
        else:
            labels = [FORM_LABELS.get(form, form)]
        filings.append({
            "form":     form,
            "date":     filed,
            "items":    item_codes,
            "labels":   labels,
            "red_flag": form in RED_FLAG_FORMS or any(i in RED_FLAG_ITEMS for i in item_codes),
            "url":      _ARCHIVE_URL.format(cik=int(cik), accession=accession.replace("-", ""),
                                            document=document),
        })
    filings.sort(key=lambda f: f["date"], reverse=True)
    return filings


def fetch_recent_filings(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Attach recent SEC filings to US-listed opportunities (tickers without a '.')."""
    us_opps = [o for o in opportunities if "." not in o.ticker]
    if not us_opps:
        return opportunities
    cik_map = _load_ticker_cik_map()
    if not cik_map:
        print("  [filings] SEC CIK map unavailable — skipping filings watch")
        return opportunities

    for opp in us_opps:
        cik = cik_map.get(opp.ticker.replace("-", "."), cik_map.get(opp.ticker))
        if not cik:
            continue
        recent = _get_recent_submissions(cik)
        time.sleep(0.12)  # SEC fair-access limit is 10 requests/second
        opp.filings = parse_recent_filings(cik, recent, config.FILINGS_DAYS,
                                           config.FILINGS_FORMS)[:10]
        for f in opp.filings:
            if f["red_flag"]:
                print(f"  [filings] {opp.ticker}: RED FLAG {f['form']} {f['date']} — "
                      f"{', '.join(f['labels'])}")
    return opportunities

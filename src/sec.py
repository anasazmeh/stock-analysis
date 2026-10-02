"""Shared SEC EDGAR helpers: ticker→CIK map and per-company submissions."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config
import src.cache as cache

HEADERS = {"User-Agent": config.SEC_USER_AGENT}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
FOREIGN_ISSUER_FORMS = {"20-F", "40-F", "6-K"}
STATUS = {"cik_map": "not run"}   # read by main.py for Data Health


def load_ticker_cik_map() -> dict:
    cached = cache.get("edgar:ticker_cik_map", 86400)
    if cached:
        STATUS["cik_map"] = "ok"
        return cached
    try:
        resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        mapping = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in resp.json().values()}
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"  [sec] CIK map load failed: {type(e).__name__}")
        STATUS["cik_map"] = "failed"
        return {}
    cache.set("edgar:ticker_cik_map", mapping)
    STATUS["cik_map"] = "ok"
    return mapping


def cik_for(ticker: str, cik_map: dict) -> str:
    return cik_map.get(ticker.replace("-", "."), cik_map.get(ticker, ""))


def get_recent_submissions(cik: str) -> dict:
    """The 'recent' filings arrays (form, filingDate, accessionNumber, primaryDocument, items)."""
    cache_key = f"edgar:submissions:{cik}"
    cached = cache.get(cache_key, config.TTL_FILINGS)
    if cached:
        return cached
    try:
        resp = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  [sec] CIK {cik}: HTTP {resp.status_code}")
            return {}
        recent = resp.json().get("filings", {}).get("recent", {})
    except (requests.RequestException, ValueError) as e:
        print(f"  [sec] CIK {cik} failed: {type(e).__name__}")
        return {}
    if recent:
        cache.set(cache_key, recent)
    return recent


def is_foreign_issuer(recent: dict) -> bool:
    forms = set(recent.get("form", []))
    return bool(forms & FOREIGN_ISSUER_FORMS) and "10-K" not in forms and "10-Q" not in forms


def raw_document(document: str) -> str:
    """Form 4 primaryDocument often points at the XSL-rendered HTML ('xslF345X05/x.xml')."""
    return document.split("/", 1)[1] if document.lower().startswith("xsl") and "/" in document else document

"""
SEC XBRL "companyfacts" (free, no key): official annual-report values for SEC filers,
including foreign issuers filing 20-F under IFRS (TSM, ASML, SAP, NIO).

Used only to fill Shariah inputs that the Yahoo statements are missing.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import config
import src.cache as cache

_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

CONCEPTS = {
    "interest_income": [("us-gaap", "InvestmentIncomeInterest"), ("us-gaap", "InterestIncomeOther"),
                        ("us-gaap", "InvestmentIncomeInterestAndDividend"),
                        ("ifrs-full", "InterestIncome"), ("ifrs-full", "FinanceIncome")],
    "receivables":     [("us-gaap", "AccountsReceivableNetCurrent"),
                        ("ifrs-full", "TradeAndOtherCurrentReceivables"),
                        ("ifrs-full", "CurrentTradeReceivables")],
    "revenue":         [("us-gaap", "Revenues"),
                        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
                        ("ifrs-full", "Revenue")],
    "cash_and_securities": [("us-gaap", "CashCashEquivalentsAndShortTermInvestments"),
                            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
                            ("ifrs-full", "CashAndCashEquivalents")],
}


def latest_annual(facts: dict, taxonomy: str, concept: str):
    """(value, currency, period_end) of the latest annual filing for a concept, or None."""
    units = facts.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {})
    for unit, rows in units.items():
        if len(unit) != 3 or not unit.isupper():
            continue
        annual = [r for r in rows if r.get("form") in _ANNUAL_FORMS and r.get("fp") == "FY"]
        if annual:
            r = max(annual, key=lambda r: (r.get("end", ""), r.get("filed", "")))
            return float(r["val"]), unit, r.get("end", "")
    return None


def fill_missing(cik: str, inputs: dict) -> dict:
    """Fill None fields in `inputs` from companyfacts; records the source when used."""
    missing = [k for k in CONCEPTS if inputs.get(k) is None]
    if not missing:
        return inputs
    facts = _get_facts(cik)
    if not facts:
        return inputs
    used = False
    for key in missing:
        for taxonomy, concept in CONCEPTS[key]:
            found = latest_annual(facts, taxonomy, concept)
            if found:
                value, unit, end = found
                if inputs.get("currency") and unit != inputs["currency"]:
                    continue  # don't mix currencies within one company's inputs
                inputs[key] = value
                inputs.setdefault("currency", unit)
                inputs["period"] = inputs.get("period") or end
                used = True
                break
    if used:
        inputs["source"] = (inputs.get("source", "") + " + SEC XBRL").strip(" +")
    return inputs


def fill_from_sec(opportunities) -> int:
    """Fill missing Shariah inputs for US-listed tickers. Returns how many were filled."""
    from src.sec import load_ticker_cik_map, cik_for
    targets = [o for o in opportunities if o.price > 0 and "." not in o.ticker
               and o.quote_type != "ETF"
               and any((o.shariah_inputs or {}).get(k) is None for k in CONCEPTS)]
    if not targets:
        return 0
    cik_map = load_ticker_cik_map()
    filled = 0
    for opp in targets:
        cik = cik_for(opp.ticker, cik_map)
        if not cik:
            continue
        before = dict(opp.shariah_inputs or {})
        opp.shariah_inputs = fill_missing(cik, dict(before))
        filled += opp.shariah_inputs != before
    return filled


def _get_facts(cik: str) -> dict:
    cache_key = f"xbrl:{cik}"
    cached = cache.get(cache_key, 7 * 24 * 3600)
    if cached:
        return cached
    try:
        resp = requests.get(_URL.format(cik=cik), headers={"User-Agent": config.SEC_USER_AGENT}, timeout=20)
        if resp.status_code != 200:
            return {}
        facts = resp.json()
    except (requests.RequestException, ValueError):
        return {}
    cache.set(cache_key, facts)
    return facts

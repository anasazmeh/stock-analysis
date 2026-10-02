"""
Shariah compliance label (AAOIFI Shariah Standard No. 21 by default).

This is a LABEL shown next to every stock — it never removes a stock from the
analysis or the ranking. It aims to be accurate:
  - a failed ratio is "No", not "Partial";
  - missing inputs give "Unknown", never "Yes";
  - ambiguous activities, new debt filings and conglomerates give "Review";
  - statement values are converted to the market-cap currency before dividing.

Status history is kept in data/shariah_history.jsonl so changes can be alerted.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
from datetime import date

import config
from src.fx import FxTable
from src.models import Opportunity, ShariahStatus

# Industry labels are normalised (dashes unified, lower-case) before matching
_DENIED_INDUSTRIES = {
    "banks - diversified": "conventional banking (interest)",
    "banks - regional": "conventional banking (interest)",
    "credit services": "interest-based lending",
    "mortgage finance": "interest-based lending",
    "capital markets": "conventional brokerage / investment banking",
    "insurance - diversified": "conventional insurance",
    "insurance - life": "conventional insurance",
    "insurance - property & casualty": "conventional insurance",
    "insurance - reinsurance": "conventional insurance",
    "insurance - specialty": "conventional insurance",
    "insurance brokers": "conventional insurance",
    "gambling": "gambling",
    "resorts & casinos": "gambling",
    "beverages - brewers": "alcohol",
    "beverages - wineries & distilleries": "alcohol",
    "tobacco": "tobacco",
}
_REVIEW_INDUSTRIES = {
    "aerospace & defense": "possible weapons revenue",
    "asset management": "depends on the funds managed",
    "financial conglomerates": "mixed financial activities",
    "lodging": "hotels often earn alcohol revenue",
    "entertainment": "content may be impermissible",
}
_REVIEW_SECTOR_KEYWORDS = {"reit": "REIT — check tenant activities and leverage"}
_DENIED_SECTORS = {"financial services": "conventional financial services"}

_HISTORY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "data", "shariah_history.jsonl")


def _norm(label: str) -> str:
    return re.sub(r"\s*[—–-]\s*", " - ", (label or "").strip().lower())


def activity_screen(ticker: str, sector: str, industry: str) -> tuple[str, list[str]]:
    """Return (Pass / Fail / Review, reasons)."""
    if ticker in config.SHARIAH_OVERRIDES:
        status, why = config.SHARIAH_OVERRIDES[ticker]
        return {"No": "Fail", "Yes": "Pass"}.get(status, "Review"), [f"Manual override: {why}"]
    if ticker in config.ISLAMIC_FINANCIALS:
        return "Pass", [f"Islamic financial institution ({config.ISLAMIC_FINANCIALS[ticker]})"]

    ind, sec = _norm(industry), _norm(sector)
    if ind in _DENIED_INDUSTRIES:
        return "Fail", [f"Industry '{industry}': {_DENIED_INDUSTRIES[ind]}"]
    if ind in _REVIEW_INDUSTRIES:
        return "Review", [f"Industry '{industry}': {_REVIEW_INDUSTRIES[ind]} — review required"]
    for kw, why in _REVIEW_SECTOR_KEYWORDS.items():
        if kw in ind or kw in sec:
            return "Review", [why]
    if sec in _DENIED_SECTORS:
        return "Fail", [f"Sector '{sector}': {_DENIED_SECTORS[sec]}"]
    return "Pass", []


def financial_ratios(opp: Opportunity, fx: FxTable) -> tuple[dict, list[str], list[str]]:
    """
    Compute AAOIFI ratios. Returns (ratios, failures, missing) where values are None
    when an input is missing or cannot be converted to the market-cap currency.
    """
    inp = opp.shariah_inputs or {}
    limits = config.SHARIAH_METHODOLOGIES[config.SHARIAH_METHODOLOGY]
    ratios = {"debt": None, "cash": None, "receivables": None, "income": None}
    failures, missing = [], []

    mcap = opp.mcap if opp.mcap and opp.mcap > 0 else None
    if mcap is None:
        missing.append("market cap")
    stmt_ccy = (inp.get("currency") or opp.financial_currency or opp.currency).upper()

    def to_mcap_ccy(value):
        if value is None:
            return None
        return fx.convert(value, stmt_ccy, opp.currency)

    if mcap and stmt_ccy != opp.currency and fx.rate(stmt_ccy, opp.currency) is None:
        missing.append(f"FX rate {stmt_ccy}->{opp.currency}")

    for key, field, label in (("debt", "interest_bearing_debt", "interest-bearing debt"),
                              ("cash", "cash_and_securities", "cash + interest-bearing securities"),
                              ("receivables", "receivables", "receivables")):
        if limits.get(key) is None:
            continue
        value = to_mcap_ccy(inp.get(field))
        if value is None or mcap is None:
            missing.append(label)
            continue
        ratios[key] = round(value / mcap, 4)
        if ratios[key] >= limits[key]:
            failures.append(f"{label.capitalize()} {ratios[key]:.1%} of market cap "
                            f"(limit {limits[key]:.0%})")

    interest, revenue = inp.get("interest_income"), inp.get("revenue")
    if interest is None or revenue is None:
        missing.append("interest income" if interest is None else "revenue")
    else:
        total_income = max(revenue, 0) + max(interest, 0)
        if total_income > 0:
            ratios["income"] = round(max(interest, 0) / total_income, 4)
            if ratios["income"] >= limits["income"]:
                note = " (pre-revenue: interest dominates income)" if revenue <= 0 else ""
                failures.append(f"Non-permissible (interest) income {ratios['income']:.1%} of income "
                                f"(limit {limits['income']:.0%}){note}")
        else:
            missing.append("revenue")
    return ratios, failures, missing


_DEBT_EVENT_ITEMS = {"2.03": "new debt obligation", "2.01": "acquisition or disposal"}
_DEBT_EVENT_FORMS = {"S-3": "shelf registration", "F-3": "shelf registration", "424B4": "priced offering"}


def debt_events(opp: Opportunity) -> list[str]:
    """Recent filings that can change the ratios before the statements catch up."""
    events = []
    for f in opp.filings:
        for item in f.get("items", []):
            if item in _DEBT_EVENT_ITEMS:
                events.append(f"{f['form']} {f['date']}: {_DEBT_EVENT_ITEMS[item]}")
        if f["form"] in _DEBT_EVENT_FORMS:
            events.append(f"{f['form']} {f['date']}: {_DEBT_EVENT_FORMS[f['form']]}")
    return events


def second_opinion_links(ticker: str) -> dict:
    if "." in ticker:
        return {}
    sym = ticker.replace("-", ".")
    return {"Musaffa": f"https://musaffa.com/stock/{sym}", "Zoya": f"https://zoya.finance/stocks/{sym.lower()}"}


def screen(opp: Opportunity, fx: FxTable) -> ShariahStatus:
    activity, reasons = activity_screen(opp.ticker, opp.sector, opp.industry)
    ratios, failures, missing = financial_ratios(opp, fx)
    events = debt_events(opp)
    reasons = reasons + failures

    if activity == "Fail" or failures:
        status = "No"
    elif activity == "Review":
        status = "Review"
    elif missing:
        status = "Unknown"
        reasons.append("Missing inputs: " + ", ".join(dict.fromkeys(missing)))
    elif events:
        status = "Review"
    else:
        status = "Yes"
    if events and status in ("Yes", "Review"):
        reasons.append("Recent filing may change the ratios: " + "; ".join(events[:2]))

    inp = opp.shariah_inputs or {}
    source = inp.get("source", "")
    if inp.get("period"):
        source += f" (period {inp['period']})"
    return ShariahStatus(
        compliant=status,
        methodology=config.SHARIAH_METHODOLOGY,
        debt_ratio=ratios["debt"],
        cash_ratio=ratios["cash"],
        receivables_ratio=ratios["receivables"],
        income_ratio=ratios["income"],
        activity_screen=activity,
        reasons=reasons,
        inputs_source=source,
        second_opinion=second_opinion_links(opp.ticker),
    )


def load_last_statuses(path: str = None) -> dict:
    path = path or _HISTORY_PATH
    last = {}
    if not os.path.exists(path):
        return last
    with open(path) as f:
        for line in f:
            try:
                row = json.loads(line)
                last[row["ticker"]] = row["status"]
            except (ValueError, KeyError):
                continue
    return last


def record_statuses(opportunities: list[Opportunity], path: str = None):
    """Append today's status for tickers whose status changed (or is new)."""
    path = path or _HISTORY_PATH
    last = load_last_statuses(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = date.today().isoformat()
    with open(path, "a") as f:
        for opp in opportunities:
            if opp.shariah and last.get(opp.ticker) != opp.shariah.compliant:
                f.write(json.dumps({"date": today, "ticker": opp.ticker,
                                    "status": opp.shariah.compliant}) + "\n")


def check_shariah(opportunities: list[Opportunity], fx: FxTable,
                  history_path: str = None) -> list[Opportunity]:
    """Attach a ShariahStatus label to every priced opportunity and record changes."""
    last = load_last_statuses(history_path)
    for opp in opportunities:
        if opp.price <= 0:
            continue
        if opp.quote_type == "ETF":
            opp.shariah = ShariahStatus(compliant="Review", methodology=config.SHARIAH_METHODOLOGY,
                                        reasons=["Fund — check that it follows a Shariah index methodology"])
        else:
            opp.shariah = screen(opp, fx)
        opp.shariah.previous = last.get(opp.ticker, "")
    record_statuses(opportunities, history_path)
    return opportunities

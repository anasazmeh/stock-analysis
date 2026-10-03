"""
IPO dossier: `python3 main.py --ipo "SpaceX" --broker-price 162 [--ticker SPCX] [--amount 2000]`

Collects the facts needed before subscribing to or trading an IPO, each labelled
with its source: offer price and lock-up from the SEC prospectus (424B4, else
S-1/F-1), the current market quote (Yahoo, if a ticker is given), the price you
see at your broker, a Shariah activity checklist from the prospectus text, and
Musaffa/Zoya links. It refuses to give a single "price" when sources disagree.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import date

import requests
import config
from src.sec import HEADERS

_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{file}"

ACTIVITY_TERMS = {
    "interest income / lending": r"\binterest income\b|\blending\b|\bloans? receivable\b",
    "alcohol": r"\balcohol|\bbeer\b|\bwine\b|\bspirits\b",
    "gambling": r"\bgambling\b|\bcasino|\bbetting\b",
    "weapons / defence": r"\bweapons?\b|\bmunitions?\b|\bmissile|\bdefen[cs]e contracts?\b",
    "pork": r"\bpork\b",
    "adult content": r"\badult entertainment\b",
    "conventional insurance": r"\binsurance (premiums|underwriting)\b",
}


def find_prospectus(name: str) -> dict:
    """Most recent 424B4 (final, priced) else S-1/F-1 for a company name."""
    for forms in ("424B4", "S-1,F-1,S-1/A,F-1/A"):
        try:
            resp = requests.get(_SEARCH, params={"q": f'"{name}"', "forms": forms},
                                headers=HEADERS, timeout=20)
            hits = resp.json().get("hits", {}).get("hits", []) if resp.status_code == 200 else []
        except (requests.RequestException, ValueError):
            hits = []
        if not hits:
            continue
        hits.sort(key=lambda h: h.get("_source", {}).get("file_date", ""), reverse=True)
        h = hits[0]
        src = h.get("_source", {})
        adsh, _, filename = h.get("_id", "").partition(":")
        cik = (src.get("ciks") or [""])[0].lstrip("0")
        if adsh and filename and cik:
            return {"form": src.get("form", forms.split(",")[0]), "date": src.get("file_date", ""),
                    "company": (src.get("display_names") or [name])[0],
                    "url": _DOC.format(cik=cik, adsh=adsh.replace("-", ""), file=filename)}
    return {}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&#160;", " ").replace("&nbsp;", " ")


def extract_terms(text: str) -> dict:
    out = {}
    m = re.search(r"initial public offering price (?:is|of|will be)\s*\$\s?([\d,]+(?:\.\d+)?)\s*per (?:share|ADS)",
                  text, re.IGNORECASE)
    if m:
        out["offer_price"] = float(m.group(1).replace(",", ""))
    m = re.search(r"between \$\s?([\d.]+) and \$\s?([\d.]+) per (?:share|ADS)", text, re.IGNORECASE)
    if m:
        out["price_range"] = (float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d{2,3})\s*days after the date of this prospectus", text, re.IGNORECASE)
    if m:
        out["lockup_days"] = int(m.group(1))
    m = re.search(r"([\d,]{6,}) (?:shares of (?:our )?Class A common stock|shares|ADSs) (?:are being )?offered",
                  text, re.IGNORECASE)
    if m:
        out["shares_offered"] = int(m.group(1).replace(",", ""))
    return out


def activity_checklist(text: str) -> dict:
    """Count mentions of activities that need a Shariah review."""
    return {label: len(re.findall(pat, text, re.IGNORECASE)) for label, pat in ACTIVITY_TERMS.items()}


def market_quote(ticker: str) -> dict:
    if not ticker:
        return {}
    try:
        import yfinance as yf
        from src.enrichment import build_opportunity
        o = build_opportunity(ticker, yf.Ticker(ticker).info or {})
        return {"price": o.price, "currency": o.currency, "time": o.price_time, "type": o.price_type} if o.price else {}
    except Exception:
        return {}


def build_dossier(name: str, broker_price: float = None, ticker: str = "", amount: float = None) -> str:
    today = date.today().isoformat()
    pros = find_prospectus(name)
    text = ""
    if pros:
        try:
            resp = requests.get(pros["url"], headers=HEADERS, timeout=30)
            text = _plain(resp.text) if resp.status_code == 200 else ""
        except requests.RequestException:
            text = ""
    terms = extract_terms(text) if text else {}
    quote = market_quote(ticker)

    prices = []
    if terms.get("offer_price"):
        prices.append(("IPO offer price", terms["offer_price"], f"{pros['form']} filed {pros['date']}"))
    if quote:
        prices.append((f"Market quote ({quote['type']})", quote["price"], f"Yahoo {quote['time']}"))
    if broker_price:
        prices.append(("Your broker's quote", broker_price, f"entered by you, {today}"))

    lines = [f"# IPO dossier — {name}", f"*{today} · not financial advice*", "", "## Prices (each labelled — they are different things)", ""]
    if prices:
        lines += ["| Price | Value | Source |", "|---|---:|---|"] + [f"| {a} | {b:,.2f} | {c} |" for a, b, c in prices]
    else:
        lines.append("No price found. Enter the broker quote with --broker-price.")
    market = [p for p in prices if not p[0].startswith("IPO offer")]
    if len(market) == 2 and abs(market[0][1] / market[1][1] - 1) > config.PRICE_CHECK_TOLERANCE_PCT / 100:
        lines += ["", f"⚠️ The market quote and your broker's quote differ by more than "
                      f"{config.PRICE_CHECK_TOLERANCE_PCT:g}% — no single price is given. Re-check both before acting."]
    if terms.get("offer_price") and market:
        prem = (market[-1][1] / terms["offer_price"] - 1) * 100
        lines += ["", f"Current quote is **{prem:+.1f}%** vs the IPO offer price. Buying now is a secondary-market "
                      f"purchase, not an IPO allocation."]

    lines += ["", "## Offering terms", ""]
    if pros:
        lines.append(f"- Prospectus: [{pros['form']} · {pros['company']} · {pros['date']}]({pros['url']})")
        for k, label in (("price_range", "Marketed price range"), ("shares_offered", "Shares offered"),
                         ("lockup_days", "Insider lock-up (days after prospectus)")):
            if k in terms:
                lines.append(f"- {label}: {terms[k]}")
    else:
        lines.append("- No SEC prospectus found (non-US listing, or name differs). Check the broker's IPO page.")

    lines += ["", "## Shariah pre-screen (prospectus text)", ""]
    if text:
        for label, n in activity_checklist(text).items():
            lines.append(f"- {label}: {'⚠️ ' if n else ''}{n} mention(s)")
        lines.append("- Financial ratios need the balance sheet in the prospectus — new listings stay "
                     "Shariah **Unknown** in the main report until statements are available.")
    sym = (ticker or "").replace("-", ".")
    if sym:
        lines.append(f"- Second opinion: [Musaffa](https://musaffa.com/stock/{sym}) · "
                     f"[Zoya](https://zoya.finance/stocks/{sym.lower()})")

    if amount:
        ref = terms.get("offer_price") or broker_price
        lines += ["", "## Subscription", "",
                  f"- Cash reserved until allocation: {amount:,.2f} (not available for other trades)."]
        if ref:
            lines.append(f"- Allocation range: 0 to {int(amount // ref)} shares at {ref:,.2f} — allocation is not guaranteed.")
    if terms.get("lockup_days"):
        lines.append(f"- Insider lock-up ends about {terms['lockup_days']} days after the prospectus date — "
                     f"add it to data/events.json to get an alert.")
    lines += ["", "> ⚠️ Not financial advice."]
    return "\n".join(lines)

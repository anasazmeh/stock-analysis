"""
DEGIRO account statement (cash movements): deposits, withdrawals, dividends,
dividend tax, fees and interest. Files in data/broker/ (git-ignored):

  DEGIRO → Inbox → Account statement → export as CSV (Account.csv) or Excel (.xls/.xlsx)

Descriptions are matched in Dutch and English. Amounts in other currencies
(USD dividends) are converted at the FX table passed in, so they are approximate.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import glob
import io
import re
from datetime import date

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "broker")

# (kind, pattern) — first match wins; order matters ("Dividendbelasting" before "Dividend")
_KINDS = [
    ("ignore",     r"Terugstorting geweigerd|Withdrawal (?:rejected|refused)|Reservation iDEAL|iDEAL Reservation"),
    ("deposit",    r"iDEAL Deposit|iDEAL storting|^Storting|^Deposit|flatex Deposit|SOFORT Deposit|Bank transfer deposit"),
    ("withdrawal", r"Withdrawal|terugstorting|Terugstorting|Opname"),
    ("div_tax",    r"^Dividendbelasting|^Dividend Tax"),
    ("dividend",   r"^Dividend|^Kapitaalsuitkering|^Capital return"),
    ("data_fee",   r"Real-?[Tt]ime Koersen Kosten|Real-?time price|Market data"),
    ("connect_fee", r"Aansluitingskosten|Connection fee|Exchange Connectivity"),
    ("adr_fee",    r"ADR/GDR"),
    ("trade_fee",  r"Transactiekosten|Transaction and/or third party fees|Transaction costs"),
    ("interest",   r"Interest|Rente|Debetrente"),
]
_COMPILED = [(k, re.compile(p)) for k, p in _KINDS]


def classify(description: str) -> str:
    for kind, pat in _COMPILED:
        if pat.search(description or ""):
            return kind
    return ""


def _num(text) -> float:
    if isinstance(text, (int, float)):
        return float(text)
    text = re.sub(r"[^\d,.\-]", "", str(text or ""))
    if text.count(",") and text.count("."):
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif text.count(","):
        text = text.replace(",", ".")
    return float(text) if text not in ("", "-", ".") else 0.0


def _date(text: str):
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", str(text or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _rows_from_table(table: list[list]) -> list[dict]:
    """Header: Date, Time, Value date, Product, ISIN, Description, FX, Change, <amount>, Balance, <amount>, Order Id."""
    if not table:
        return []
    header = [str(c or "").strip() for c in table[0]]
    if "Description" not in header or "Change" not in header:
        return []
    i_date, i_desc, i_ccy = header.index("Date"), header.index("Description"), header.index("Change")
    i_prod = header.index("Product") if "Product" in header else None
    out = []
    for r in table[1:]:
        if len(r) <= i_ccy + 1 or not _date(r[i_date]):
            continue
        amount = r[i_ccy + 1]
        if amount in (None, ""):
            continue
        desc = str(r[i_desc] or "")
        out.append({"date": _date(r[i_date]), "description": desc, "kind": classify(desc),
                    "currency": str(r[i_ccy] or "EUR").upper(), "amount": _num(amount),
                    "product": str(r[i_prod] or "") if i_prod is not None else ""})
    return out


def parse_csv(text: str) -> list[dict]:
    return _rows_from_table(list(csv.reader(text.splitlines())))


def parse_xlsx(path: str) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        print("  [account] openpyxl not installed — export the account statement as CSV instead")
        return []
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with open(path, "rb") as f:   # a file object: openpyxl rejects the ".xls" name DEGIRO gives it
            wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
    return _rows_from_table([list(r) for r in wb.worksheets[0].iter_rows(values_only=True)])


def load(folder: str = None) -> list[dict]:
    """All cash movements from account statements in data/broker/, de-duplicated across overlapping exports."""
    folder = folder or _DIR
    # Two identical lines in one file are two real movements (e.g. two €2,000 deposits on one day);
    # the same line in two overlapping exports is one. Keep each line as often as the file that has it most.
    best = {}
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        low = path.lower()
        if low.endswith(".csv"):
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                parsed = parse_csv(f.read())
        elif low.endswith((".xls", ".xlsx")):
            # DEGIRO's ".xls" download is really an .xlsx workbook
            try:
                parsed = parse_xlsx(path)
            except Exception as e:
                print(f"  [account] {os.path.basename(path)} unreadable ({type(e).__name__}) — export it as CSV")
                parsed = []
        else:
            continue
        groups = {}
        for r in parsed:
            key = (r["date"], r["description"], r["currency"], round(r["amount"], 2), r["product"])
            groups.setdefault(key, []).append(r)
        for key, items in groups.items():
            if len(items) > len(best.get(key, [])):
                best[key] = items
    rows = [r for items in best.values() for r in items]
    rows.sort(key=lambda r: r["date"])
    return rows


def _eur(r: dict, fx) -> float:
    if r["currency"] == "EUR":
        return r["amount"]
    v = fx.convert(r["amount"], r["currency"], "EUR") if fx is not None else None
    return v if v is not None else 0.0


def summarize(rows: list[dict], fx=None, today: date = None) -> dict | None:
    """Money in/out, income and costs in EUR, in total, per year and over the last 12 months."""
    if not rows:
        return None
    today = today or date.today()
    year_ago = date(today.year - 1, today.month, min(today.day, 28))
    tot, last12, years = {}, {}, {}
    flows = []   # (date, EUR) from your side: deposit -, withdrawal +
    usd_div, usd_tax = 0.0, 0.0
    for r in rows:
        k = r["kind"]
        if not k or k == "ignore":
            continue
        v = _eur(r, fx)
        tot[k] = tot.get(k, 0.0) + v
        years.setdefault(r["date"].year, {}).setdefault(k, 0.0)
        years[r["date"].year][k] += v
        if r["date"] >= year_ago:
            last12[k] = last12.get(k, 0.0) + v
        if k in ("deposit", "withdrawal"):
            flows.append((r["date"], -v))
        if r["currency"] == "USD" and k == "dividend":
            usd_div += r["amount"]
        if r["currency"] == "USD" and k == "div_tax":
            usd_tax += -r["amount"]
    data_months = sorted({(r["date"].year, r["date"].month) for r in rows if r["kind"] == "data_fee"})
    rnd = lambda d: {k: round(v, 2) for k, v in d.items()}
    deposits, withdrawals = tot.get("deposit", 0.0), -tot.get("withdrawal", 0.0)
    return {
        "first_date": rows[0]["date"].isoformat(), "last_date": rows[-1]["date"].isoformat(),
        "deposits_eur": round(deposits, 2), "withdrawals_eur": round(withdrawals, 2),
        "net_invested_eur": round(deposits - withdrawals, 2),
        "flows": [(d.isoformat(), round(v, 2)) for d, v in flows],
        "totals": rnd(tot), "last_12m": rnd(last12), "years": {y: rnd(v) for y, v in sorted(years.items())},
        "usd_dividend_withholding_pct": round(100 * usd_tax / usd_div, 1) if usd_div > 0 else None,
        "data_fee_months": [f"{y}-{m:02d}" for y, m in data_months],
    }


def xirr(flows: list[tuple], final_value: float, today: date = None) -> float | None:
    """Annual money-weighted return. flows: [(iso date, EUR)] from your side (deposit negative)."""
    today = today or date.today()
    cfs = [(date.fromisoformat(d) if isinstance(d, str) else d, v) for d, v in flows if v]
    cfs.append((today, final_value))
    if not any(v < 0 for _, v in cfs) or not any(v > 0 for _, v in cfs):
        return None
    t0 = min(d for d, _ in cfs)
    years = [((d - t0).days / 365.25, v) for d, v in cfs]
    npv = lambda r: sum(v / (1 + r) ** t for t, v in years)
    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return round(100 * (lo + hi) / 2, 1)

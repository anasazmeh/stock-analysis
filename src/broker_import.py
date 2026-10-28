"""
Broker CSV reconciliation (DEGIRO + Revolut), files in data/broker/ (git-ignored).

  data/broker/degiro_transactions.csv   DEGIRO → Activity → Transactions → Export CSV
  data/broker/revolut_*.csv             Revolut → Stocks → Statements → Account statement (CSV)

Positions and average cost are rebuilt from the transactions (oldest first — DEGIRO
lists the newest first) and compared with portfolio_data.py, matched by ISIN.
Realised P&L per sold position comes from DEGIRO's "Total EUR" column, so it
includes fees and the exchange rate you actually got. Holdings that disagree are flagged so their P&L alerts are
held back until portfolio_data.py is corrected.

Column names follow the English exports; adjust _DEGIRO_COLS / _REVOLUT_COLS if
your export language differs.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import csv
import glob
import re
from dataclasses import dataclass, field

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "broker")
_DEGIRO_COLS = {"product": "Product", "isin": "ISIN", "qty": "Quantity", "price": "Price"}
_DEGIRO_OPTIONAL = {"date": "Date", "time": "Time", "total_eur": "Total EUR", "order_id": "Order ID"}
_REVOLUT_COLS = {"ticker": "Ticker", "type": "Type", "qty": "Quantity", "price": "Price per share",
                 "currency": "Currency"}


@dataclass
class Position:
    key: str                  # ISIN (DEGIRO) or ticker (Revolut)
    name: str = ""
    shares: float = 0.0
    cost: float = 0.0         # total cost of the open position, in `currency`
    currency: str = ""
    broker: str = ""
    trades: list = field(default_factory=list)
    cost_eur: float = 0.0     # EUR paid for the open shares, fees and FX included (DEGIRO)
    realised_eur: float = 0.0  # EUR gained (+) or lost (-) on shares already sold
    last_sale: str = ""
    opened: str = ""           # first buy of the current holding period
    period_realised: float = 0.0
    periods: list = field(default_factory=list)   # closed holding periods: {opened, closed, realised_eur}

    @property
    def avg_cost(self):
        return round(self.cost / self.shares, 4) if self.shares > 1e-9 else None

    def apply(self, qty: float, price: float, total_eur: float = None, when: str = "",
              corporate: bool = False, carried_eur: float = None) -> float:
        """One trade. corporate=True for a split / ISIN change (no order ID): the EUR cost moves to
        the new line instead of being booked as a sale. Returns the EUR cost handed over."""
        handed = 0.0
        if qty > 0:
            if self.shares < 1e-9 and not self.opened:
                self.opened = when
            self.cost += qty * price
            self.shares += qty
            if carried_eur is not None:
                self.cost_eur += carried_eur
            elif total_eur is not None:
                self.cost_eur += -total_eur
        elif self.shares > 0:  # sale reduces cost at the average price
            sold = min(-qty, self.shares)
            part = sold / self.shares
            if corporate and total_eur:
                handed = self.cost_eur * part
            elif total_eur is not None:   # a sale; a zero-value write-off (delisting, leftover fraction) is a loss
                gain = total_eur - self.cost_eur * part
                self.realised_eur += gain
                self.period_realised += gain
                self.last_sale = when
            self.cost_eur -= self.cost_eur * part
            self.cost -= self.cost / self.shares * sold
            self.shares -= sold
        if self.shares < 1e-9:
            if qty < 0 and not (corporate and total_eur) and self.opened:
                self.periods.append({"opened": self.opened[:10], "closed": when[:10],
                                     "realised_eur": round(self.period_realised, 2)})
            if not (corporate and total_eur):   # a split/ISIN change hands the period over to the new line
                self.opened, self.period_realised = "", 0.0
            self.shares = self.cost = self.cost_eur = 0.0
        return handed


def _num(text: str) -> float:
    text = re.sub(r"[^\d,.\-]", "", str(text or ""))
    if text.count(",") and text.count("."):
        text = text.replace(",", "")
    elif text.count(","):
        text = text.replace(",", ".")
    return float(text) if text not in ("", "-", ".") else 0.0


def _when(row, idx) -> str:
    """'27-10-2026' + '14:33' -> '2026-10-27 14:33' (sortable)."""
    d = row[idx["date"]] if "date" in idx else ""
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", d)
    t = row[idx["time"]] if "time" in idx else ""
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)} {t}" if m else ""


def parse_degiro(text: str, include_closed: bool = False) -> dict:
    reader = csv.reader(text.splitlines())
    header = next(reader, [])
    idx = {k: header.index(v) for k, v in _DEGIRO_COLS.items() if v in header}
    if len(idx) < len(_DEGIRO_COLS):
        return {}
    idx.update({k: header.index(v) for k, v in _DEGIRO_OPTIONAL.items() if v in header})
    ccy_idx = idx["price"] + 1  # the unnamed column after "Price" holds its currency
    rows = [r for r in reader if len(r) > max(idx.values())]

    def corporate(r):   # splits and ISIN changes have no order ID
        return "order_id" in idx and not r[idx["order_id"]].strip()

    # The export is newest first. Replay oldest first; on a split / ISIN-change day the old line
    # leaves before the new one arrives, so its cost can be carried over.
    rows = sorted(reversed(rows), key=lambda r: (_when(r, idx)[:10], corporate(r) and _num(r[idx["qty"]]) > 0,
                                                 _when(r, idx)))
    positions, carry = {}, {}
    for row in rows:
        key = row[idx["isin"]] or row[idx["product"]]
        pos = positions.setdefault(key, Position(key=key, name=row[idx["product"]], broker="DEGIRO",
                                                 currency=row[ccy_idx] if len(row) > ccy_idx else ""))
        pos.name = row[idx["product"]] or pos.name
        total = _num(row[idx["total_eur"]]) if "total_eur" in idx and row[idx["total_eur"]].strip() else None
        qty, day, corp = _num(row[idx["qty"]]), _when(row, idx)[:10], corporate(row)
        incoming = carry.pop(day, None) if corp and qty > 0 else None
        if incoming and pos.shares < 1e-9:
            pos.opened, pos.period_realised = incoming["opened"] or pos.opened, incoming["realised"]
        opened, period = pos.opened, pos.period_realised
        handed = pos.apply(qty, _num(row[idx["price"]]), total, _when(row, idx), corp,
                           incoming["cost"] if incoming else None)
        if handed:
            c = carry.setdefault(day, {"cost": 0.0, "opened": opened, "realised": period})
            c["cost"] += handed
            if pos.shares < 1e-9:
                pos.opened, pos.period_realised = "", 0.0
    return {k: p for k, p in positions.items() if include_closed or p.shares > 1e-6}


def parse_revolut(text: str) -> dict:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or not set(_REVOLUT_COLS.values()) <= set(reader.fieldnames):
        return {}
    positions = {}
    for row in reader:
        kind = (row[_REVOLUT_COLS["type"]] or "").upper()
        if not kind.startswith(("BUY", "SELL")) or not row[_REVOLUT_COLS["ticker"]]:
            continue
        qty = _num(row[_REVOLUT_COLS["qty"]]) * (-1 if kind.startswith("SELL") else 1)
        t = row[_REVOLUT_COLS["ticker"]]
        pos = positions.setdefault(t, Position(key=t, name=t, broker="Revolut",
                                               currency=row[_REVOLUT_COLS["currency"]]))
        pos.apply(qty, _num(row[_REVOLUT_COLS["price"]]))
    return {k: p for k, p in positions.items() if p.shares > 1e-6}


def load_positions(folder: str = None) -> list[Position]:
    folder = folder or _DIR
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        parsed = parse_degiro(text) or parse_revolut(text)
        out.extend(parsed.values())
    return out


def trade_costs(text: str) -> list[tuple]:
    """[(iso date, EUR)] currency-conversion (AutoFX) costs from a DEGIRO Transactions export."""
    reader = csv.reader(text.splitlines())
    header = next(reader, [])
    if "AutoFX Fee" not in header or "Date" not in header:
        return []
    i_fx, i_d = header.index("AutoFX Fee"), header.index("Date")
    out = []
    for r in reader:
        if len(r) > i_fx and r[i_fx].strip():
            m = re.match(r"(\d{2})-(\d{2})-(\d{4})", r[i_d])
            if m and _num(r[i_fx]):
                out.append((f"{m.group(3)}-{m.group(2)}-{m.group(1)}", -abs(_num(r[i_fx]))))
    return out


def realised_summary(folder: str = None) -> dict | None:
    """Realised P&L in EUR (fees and FX included) from the DEGIRO export(s), per company and in total."""
    folder = folder or _DIR
    rows, periods, fx_costs = [], [], set()
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        parsed = parse_degiro(text, include_closed=True)
        fx_costs |= set(trade_costs(text))
        periods += [{**pr, "name": p.name} for p in parsed.values() for pr in p.periods]
        rows += [{"name": p.name, "isin": p.key, "realised_eur": round(p.realised_eur, 2), "last_sale": p.last_sale[:10],
                  "still_held": p.shares > 1e-6} for p in parsed.values() if abs(p.realised_eur) >= 0.005]
    from src.output_gate import find_violations
    rows = [r for r in rows if not find_violations(f"{r['name']} {r['isin']}")]
    periods = _merge_periods([p for p in periods if not find_violations(p["name"])])
    if not rows:
        return None
    rows.sort(key=lambda r: r["last_sale"], reverse=True)
    return {"total_eur": round(sum(r["realised_eur"] for r in rows), 2),
            "gains_eur": round(sum(r["realised_eur"] for r in rows if r["realised_eur"] > 0), 2),
            "losses_eur": round(sum(r["realised_eur"] for r in rows if r["realised_eur"] < 0), 2),
            "this_year_eur": round(sum(r["realised_eur"] for r in rows if r["last_sale"][:4] == _year()), 2),
            "positions": rows, "periods": periods,
            "fx_costs": sorted(fx_costs)}


def _merge_periods(periods: list[dict]) -> list[dict]:
    """A reverse split can leave a write-off on the old ISIN: same company, same start → one holding period."""
    merged = {}
    for p in sorted(periods, key=lambda p: p["closed"]):
        key = (p["opened"], (p["name"].split() or [""])[0].lower().strip(",."))
        if key in merged:
            m = merged[key]
            m["realised_eur"] = round(m["realised_eur"] + p["realised_eur"], 2)
            m["closed"] = max(m["closed"], p["closed"])
        else:
            merged[key] = dict(p)
    return sorted(merged.values(), key=lambda p: p["closed"], reverse=True)


def _year() -> str:
    from datetime import date
    return str(date.today().year)


def reconcile(holdings: list[dict], positions: list[Position], tolerance: float = 0.01) -> list[dict]:
    """Compare portfolio_data.py with broker positions. Returns a list of differences."""
    diffs = []
    matched = set()
    for h in holdings:
        keys = {h.get("isin"), h.get("ticker"), h.get("name")} - {None, ""}
        pos = next((p for p in positions if p.key in keys or p.name in keys), None)
        if pos is None:
            diffs.append({"ticker": h.get("ticker") or h.get("name"), "issue": "not found in broker exports"})
            continue
        matched.add(id(pos))
        if abs(pos.shares - h["shares"]) > tolerance * max(1, h["shares"]):
            diffs.append({"ticker": h.get("ticker") or h.get("name"),
                          "issue": f"shares {h['shares']:g} in portfolio_data.py vs {pos.shares:g} at {pos.broker}"})
        if pos.avg_cost and h.get("bep") and pos.currency == h.get("bep_currency") and \
                abs(pos.avg_cost / h["bep"] - 1) > 0.02:
            diffs.append({"ticker": h.get("ticker") or h.get("name"),
                          "issue": f"breakeven {h['bep']} vs average cost {pos.avg_cost} {pos.currency} at {pos.broker}"})
    for p in positions:
        if id(p) not in matched:
            diffs.append({"ticker": p.name or p.key, "issue": f"held at {p.broker} ({p.shares:g}) but missing from portfolio_data.py"})
    return diffs


def run_reconciliation(holdings: list[dict]) -> list[dict] | None:
    """None when there are no broker files; otherwise the list of differences."""
    positions = load_positions()
    if not positions:
        return None
    return reconcile(holdings, positions)

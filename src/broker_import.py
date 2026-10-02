"""
Broker CSV reconciliation (DEGIRO + Revolut), files in data/broker/ (git-ignored).

  data/broker/degiro_transactions.csv   DEGIRO → Activity → Transactions → Export CSV
  data/broker/revolut_*.csv             Revolut → Stocks → Statements → Account statement (CSV)

Positions and average cost are rebuilt from the transactions and compared with
portfolio_data.py. Holdings that disagree are flagged so their P&L alerts are
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

    @property
    def avg_cost(self):
        return round(self.cost / self.shares, 4) if self.shares > 1e-9 else None

    def apply(self, qty: float, price: float):
        if qty > 0:
            self.cost += qty * price
            self.shares += qty
        elif self.shares > 0:  # sale reduces cost at the average price
            sold = min(-qty, self.shares)
            self.cost -= self.cost / self.shares * sold
            self.shares -= sold


def _num(text: str) -> float:
    text = re.sub(r"[^\d,.\-]", "", str(text or ""))
    if text.count(",") and text.count("."):
        text = text.replace(",", "")
    elif text.count(","):
        text = text.replace(",", ".")
    return float(text) if text not in ("", "-", ".") else 0.0


def parse_degiro(text: str) -> dict:
    reader = csv.reader(text.splitlines())
    header = next(reader, [])
    idx = {k: header.index(v) for k, v in _DEGIRO_COLS.items() if v in header}
    if len(idx) < len(_DEGIRO_COLS):
        return {}
    ccy_idx = idx["price"] + 1  # the unnamed column after "Price" holds its currency
    positions = {}
    for row in reader:
        if len(row) <= max(idx.values()):
            continue
        key = row[idx["isin"]] or row[idx["product"]]
        pos = positions.setdefault(key, Position(key=key, name=row[idx["product"]], broker="DEGIRO",
                                                 currency=row[ccy_idx] if len(row) > ccy_idx else ""))
        pos.apply(_num(row[idx["qty"]]), _num(row[idx["price"]]))
    return {k: p for k, p in positions.items() if p.shares > 1e-6}


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

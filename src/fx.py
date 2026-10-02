"""
FX reference rates (free, no key), fetched once per run and cached for the day.

Primary: ECB euro reference rates (daily XML). Fallback: Frankfurter API, which
republishes the ECB rates. The ECB does not publish SAR, AED or TWD: SAR and AED
are derived from their fixed USD pegs; TWD stays unavailable, so TWD conversions
return None instead of guessing.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from dataclasses import dataclass, field
from typing import Optional

import requests
import config
import src.cache as cache

_ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
_USD_PEGS = {"SAR": 3.75, "AED": 3.6725}


@dataclass
class FxTable:
    rates: dict = field(default_factory=dict)   # units of currency per 1 EUR
    date: str = ""
    source: str = ""

    def rate(self, frm: str, to: str) -> Optional[float]:
        """Units of `to` per 1 unit of `frm`, or None if either currency is unknown."""
        frm, to = frm.upper(), to.upper()
        if frm == to:
            return 1.0
        a, b = self.rates.get(frm), self.rates.get(to)
        if not a or not b:
            return None
        return b / a

    def convert(self, amount: Optional[float], frm: str, to: str) -> Optional[float]:
        r = self.rate(frm, to)
        return None if amount is None or r is None else amount * r


def parse_ecb_xml(xml: str) -> FxTable:
    date = re.search(r"time=['\"](\d{4}-\d{2}-\d{2})['\"]", xml)
    rates = {c: float(r) for c, r in
             re.findall(r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([\d.]+)['\"]", xml)}
    return _finish(rates, date.group(1) if date else "", "ECB")


def _finish(rates: dict, date: str, source: str) -> FxTable:
    rates = dict(rates)
    rates["EUR"] = 1.0
    if "USD" in rates:
        for ccy, peg in _USD_PEGS.items():
            rates.setdefault(ccy, rates["USD"] * peg)
    return FxTable(rates=rates, date=date, source=source)


def get_fx() -> FxTable:
    """Return today's FX table. Empty table (every conversion None) if both sources fail."""
    cached = cache.get("fx:eur", config.TTL_FX)
    if cached:
        return FxTable(**cached)

    table = FxTable()
    try:
        resp = requests.get(_ECB_URL, timeout=15)
        if resp.status_code == 200:
            table = parse_ecb_xml(resp.text)
    except requests.RequestException as e:
        print(f"  [fx] ECB rates failed ({type(e).__name__}) — trying Frankfurter")

    if "USD" not in table.rates:
        try:
            resp = requests.get(_FRANKFURTER_URL, params={"base": "EUR"}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                table = _finish(data.get("rates", {}), data.get("date", ""), "Frankfurter (ECB)")
        except (requests.RequestException, ValueError) as e:
            print(f"  [fx] Frankfurter failed ({type(e).__name__})")

    if "USD" not in table.rates:
        print("  [fx] ⚠️ NO FX RATES — cross-currency P&L will show as N/A")
        return FxTable()

    cache.set("fx:eur", {"rates": table.rates, "date": table.date, "source": table.source})
    print(f"  [fx] {table.source} rates for {table.date}: 1 EUR = {table.rates['USD']:.4f} USD")
    return table

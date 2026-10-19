"""
Open orders you have placed at your broker (portfolio_data.OPEN_ORDERS).

For each open sell order the pipeline works out how far the price must move for it
to fill, what it would bring in (EUR, before fees) and the gain it would lock in,
and checks it against this run's Sell review:

  - a limit at or below the price fills straight away;
  - a limit above the analyst target or far above the 52-week high may never fill;
  - a limit sell above the price does not protect you when the review says
    "Stop the loss" / "Protect gains" — that needs a stop order;
  - a Take profit / Trim suggestion already covered by your order is not repeated.

Orders are not filled cash: the Cash plan lists them separately and never counts them.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional

import config
from src.models import Opportunity

FAR_ABOVE_HIGH_PCT = 15     # limit this far above the 52-week high: "may not fill for a long time"
CLOSE_PCT = 3               # within this distance: "may fill soon"


def load_orders() -> list[dict]:
    try:
        import portfolio_data
    except ImportError:
        return []
    out = []
    for o in getattr(portfolio_data, "OPEN_ORDERS", []) or []:
        if o.get("ticker") and o.get("ticker") not in config.AVOID_LIST and o.get("qty") and o.get("limit"):
            out.append({"side": "Sell", "type": "Limit", "validity": "GTC", **o})
    return out


def _price_in(opp: Opportunity, currency: str, fx) -> Optional[float]:
    if not opp.price:
        return None
    if currency == opp.currency:
        return opp.price
    p = opp.portfolio
    if p is not None and currency == p.bep_currency and p.price_in_bep:
        return p.price_in_bep
    return fx.convert(opp.price, opp.currency, currency) if fx is not None else None


def evaluate(order: dict, opp: Optional[Opportunity], fx=None, review: dict = None) -> dict:
    """One open order with distance to fill, value if filled and checks. review = this holding's Sell review row."""
    cur = order.get("currency") or (opp.currency if opp else "USD")
    qty, limit = float(order["qty"]), float(order["limit"])
    row = {**order, "currency": cur, "qty": qty, "limit": limit, "price": None, "distance_pct": None,
           "value_eur": fx.convert(qty * limit, cur, "EUR") if fx is not None else None,
           "gain_pct": None, "gain_eur": None, "share_of_position_pct": None, "status": "", "checks": []}
    checks = row["checks"]
    if opp is None or not opp.price:
        row["status"] = "No price this run"
        return row
    price = _price_in(opp, cur, fx)
    row["price"] = round(price, 4) if price else None
    approx = cur != opp.currency
    p = opp.portfolio
    if p is not None and p.shares:
        row["share_of_position_pct"] = round(100 * qty / p.shares, 1)
        if qty > p.shares + 1e-9:
            checks.append(f"Order is for {qty:g} shares but you hold {p.shares:g} — the broker will reject or part-fill it.")
        if p.bep and cur == p.bep_currency:
            row["gain_pct"] = round(100 * (limit / p.bep - 1), 1)
            row["gain_eur"] = fx.convert(qty * (limit - p.bep), cur, "EUR") if fx is not None else None
    if price:
        dist = 100 * (limit / price - 1)
        row["distance_pct"] = round(dist, 1)
        if order["side"] == "Sell":
            if dist <= 0:
                row["status"] = "Fills now"
                checks.append("The limit is at or below the current price — it should fill when the market opens.")
            elif dist <= CLOSE_PCT:
                row["status"] = "Close"
            else:
                row["status"] = f"Needs +{dist:.0f}%"
    if order["side"] == "Sell" and price:
        if opp.target and opp.currency == cur and limit > opp.target:
            checks.append(f"Above the analyst target ({opp.target:,.2f} {cur}) — analysts don't expect this price within 12 months.")
        high = opp.w52_high if not approx else (fx.convert(opp.w52_high, opp.currency, cur) if fx is not None and opp.w52_high else None)
        if high and limit > high * (1 + FAR_ABOVE_HIGH_PCT / 100):
            checks.append(f"{100 * (limit / high - 1):.0f}% above the 52-week high ({high:,.2f}) — it may not fill for a long time.")
    if review and order["side"] == "Sell":
        cat = review.get("category")
        if cat in ("Stop the loss", "Protect gains") and (row["distance_pct"] or 0) > 0:
            stop = (review.get("metrics") or {}).get("trail_stop_price")
            checks.append(f"Sell review says {cat}: a limit above the price only sells on a rise. To limit the downside "
                          f"use a stop-loss order" + (f" near the trailing stop ({stop:,.2f} {opp.currency})." if stop else "."))
        elif cat in ("Take profit", "Trim to cap") and review.get("sell_units"):
            if qty >= review["sell_units"]:
                checks.append(f"Covers the suggested {cat.lower()} ({review['sell_units']:g} shares) — once it fills, no further sale is needed.")
            else:
                checks.append(f"Sell review suggests {review['sell_units']:g} shares; this order sells {qty:g}.")
        elif cat == "Hold":
            checks.append("No sell signal this run — the order is your own profit target"
                          + (f" (+{row['gain_pct']:.0f}% on your breakeven)." if row["gain_pct"] is not None else "."))
    if approx and row["price"]:
        checks.append(f"Price converted from the {opp.currency} listing — check the {cur} quote at your broker.")
    return row


def evaluate_orders(opportunities: list[Opportunity], fx=None, sell_rows: list = None) -> list[dict]:
    by_ticker = {o.ticker: o for o in opportunities}
    reviews = {r["ticker"]: r for r in (sell_rows or [])}
    rows = [evaluate(o, by_ticker.get(o["ticker"]), fx, reviews.get(o["ticker"])) for o in load_orders()]
    rows.sort(key=lambda r: (r["distance_pct"] is None, r["distance_pct"] if r["distance_pct"] is not None else 0))
    for r in rows:
        rev = reviews.get(r["ticker"])
        if rev is not None:
            rev.setdefault("open_orders", []).append({k: r[k] for k in ("side", "qty", "limit", "currency", "distance_pct", "status")})
            if r["side"] == "Sell" and rev.get("sell_units") and r["qty"] >= rev["sell_units"]:
                rev["action"] = f"{rev['action']} — your open order ({r['qty']:g} @ {r['limit']:,.2f} {r['currency']}) already covers this"
    by = {o.ticker: o for o in opportunities}
    for r in rows:
        if r["ticker"] in by:
            by[r["ticker"]].open_orders = [x for x in rows if x["ticker"] == r["ticker"]]
    return rows


def summary(rows: list[dict]) -> dict:
    sells = [r for r in rows if r["side"] == "Sell"]
    return {"count": len(sells), "value_eur": round(sum(r["value_eur"] or 0 for r in sells), 2),
            "fills_now": sum(r["status"] == "Fills now" for r in sells),
            "close": sum(r["status"] == "Close" for r in sells)}

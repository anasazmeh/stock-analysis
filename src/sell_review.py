"""
Sell review — for each holding, whether to cut a loss, protect a gain, take
profit or trim, and roughly what a sale would mean in euros.

Two steps:
  compute_exit_metrics(opp)  adds the price facts a sell decision needs and the
                             rest of the pipeline did not have: the drop from the
                             6-month high, a volatility-based trailing stop and the
                             3-month return. Runs before the Claude stage so the
                             holder view sees them too.
  review_holdings(...)       weighs the signals into a verdict per holding.

A holding whose data failed a check (no price, data gate, price mismatch with
Finnhub, broker export disagreeing with portfolio_data.py, no breakeven P&L) gets
"Check data first" and no suggestion: a sell idea built on a wrong price is worse
than none. Shariah status is listed as a signal but never counts toward the
verdict or its strength — it stays a label.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from typing import Optional

import config
from src.models import Opportunity

_6M, _3M = 126, 63

# Short, cautious notes per tax residence. Always followed by "check with a tax adviser".
TAX_NOTES = {
    "NL": "Netherlands (Box 3): a sale itself is not taxed and a loss is not deductible — "
          "tax follows your wealth on 1 January under the current rules.",
    "DE": "Germany: gains are taxed at about 26.4% (plus church tax if it applies) above the "
          "€1,000 allowance; share losses only offset share gains.",
    "FR": "France: gains fall under the 30% flat tax by default; losses can offset gains for 10 years.",
    "BE": "Belgium: capital-gains rules for private investors changed recently — check the current "
          "rate and annual exemption before selling.",
}

CATEGORIES = ("Stop the loss", "Protect gains", "Take profit", "Trim to cap")


def compute_exit_metrics(opp: Opportunity) -> dict:
    """Drawdown from the 6-month high, trailing stop and 3-month return. Missing data → keys left out."""
    prices = [p for p in (opp.hist_prices or []) if p and p > 0]
    m = {}
    if opp.price > 0 and len(prices) >= 60:
        window = prices[-_6M:]
        peak = max(max(window), opp.price)
        m["high_6m"] = round(peak, 4)
        m["drawdown_from_high_pct"] = round((opp.price / peak - 1) * 100, 1)
        vol = opp.risk.volatility_30d if opp.risk else None
        # Stop distance: 2 × one-month volatility, kept between the configured floor and ceiling.
        dist = config.TRAIL_STOP_MIN_PCT if vol is None else \
            min(config.TRAIL_STOP_MAX_PCT, max(config.TRAIL_STOP_MIN_PCT, config.TRAIL_STOP_VOL_MULT * vol / math.sqrt(12)))
        m["trail_stop_pct"] = round(dist, 1)
        m["trail_stop_price"] = round(peak * (1 - dist / 100), 4)
        m["trail_stop_hit"] = opp.price <= m["trail_stop_price"]
    if opp.price > 0 and len(prices) > _3M and prices[-_3M - 1] > 0:
        m["return_3m_pct"] = round((opp.price / prices[-_3M - 1] - 1) * 100, 1)
    if opp.price > 0 and opp.ma200:
        m["vs_ma200_pct"] = round((opp.price / opp.ma200 - 1) * 100, 1)
    opp.exit_metrics = m
    return m


def apply_exit_metrics(opportunities: list[Opportunity]) -> list[Opportunity]:
    for opp in opportunities:
        if opp.portfolio:
            compute_exit_metrics(opp)
    return opportunities


def tax_note() -> str:
    base = TAX_NOTES.get((config.TAX_RESIDENCE or "").upper(),
                         "Set TAX_RESIDENCE in config.py — whether a sale is taxed and whether a loss "
                         "can be offset depends on your country.")
    return base + " Check with a tax adviser."


def _data_problems(opp: Opportunity, broker_bad: set) -> list[str]:
    p = opp.portfolio
    out = []
    if opp.price <= 0:
        out.append("no price this run")
    if opp.price_check == "Mismatch":
        out.append(f"Yahoo and Finnhub prices differ by {opp.price_diff_pct:+.1f}%")
    if not opp.data_ok:
        out.append("data gaps: " + ", ".join(opp.data_flags))
    if opp.ticker in broker_bad:
        out.append("broker export disagrees with portfolio_data.py")
    if p and p.pl_pct is None:
        out.append(p.note or "no P&L against your breakeven")
    return out


def _signals(opp: Opportunity) -> tuple[list[dict], list[str]]:
    """Return (signals, reasons to keep). Each signal: {side: stop|profit|trim|shariah, strength 1-3, text}."""
    p, m, a = opp.portfolio, opp.exit_metrics or {}, opp.analysis
    pl = p.pl_pct
    sig, keep = [], []

    def add(side, strength, text):
        sig.append({"side": side, "strength": strength, "text": text})

    # ── Losses and broken trends ──
    if pl <= config.SELL_STOP_LOSS_PCT:
        add("stop", 3, f"Down {pl:.1f}% from your breakeven (limit {config.SELL_STOP_LOSS_PCT:g}%)")
    elif pl <= config.SELL_STOP_LOSS_PCT / 2:
        add("stop", 1, f"Down {pl:.1f}% from your breakeven")
    if m.get("trail_stop_hit"):
        add("stop", 2, f"{-m['drawdown_from_high_pct']:.1f}% below its 6-month high "
                       f"({m['high_6m']:.2f}) — past the {m['trail_stop_pct']:g}% trailing stop at {m['trail_stop_price']:.2f}")
    if opp.trend == "Downtrend":
        add("stop", 2, "Downtrend: price below its 50-day average, which is below the 200-day")
    elif m.get("vs_ma200_pct") is not None and m["vs_ma200_pct"] < -5:
        add("stop", 1, f"{m['vs_ma200_pct']:.1f}% below its 200-day average")
    if opp.thesis_status == "Broken":
        add("stop", 3, "Your thesis is broken: " + "; ".join(n for n in opp.thesis_notes if not n.startswith("Thesis:"))[:200])
    elif opp.thesis_status == "Review":
        add("stop", 1, "Thesis needs review: " + "; ".join(n for n in opp.thesis_notes if not n.startswith("Thesis:"))[:200])
    if opp.adj_upside is not None and opp.adj_upside < 0 and pl < 0:
        add("stop", 2, f"Analyst consensus target {opp.target:.2f} is below the price ({opp.adj_upside:+.0f}% quality-adjusted)")
    ups, downs = (opp.rating_changes_90d or {}).get("up", 0), (opp.rating_changes_90d or {}).get("down", 0)
    if downs - ups >= 2:
        add("stop", 1, f"{downs} analyst downgrades vs {ups} upgrades in 90 days")
    if opp.insider_signal == "Bearish":
        add("stop", 1, f"Insiders net sellers: {opp.insider_net_shares:,} shares in 30 days")
    red = [f for f in opp.filings if f.get("red_flag")]
    if red:
        add("stop", 2, f"SEC red flag: {red[0]['form']} {red[0]['date']} — {', '.join(red[0]['labels'])}")
    if opp.eps_surprise is not None and opp.eps_surprise <= -10:
        add("stop", 1, f"Missed EPS by {opp.eps_surprise:.0f}% last quarter")
    rs = opp.rel_strength.get("SPY")
    if rs is not None and rs < -25:
        add("stop", 1, f"Lagging the S&P 500 by {-rs:.0f} pts over 6 months")

    # ── Gains worth locking in ──
    if pl >= config.SELL_TAKE_PROFIT_PCT * 2:
        add("profit", 2, f"Up {pl:.0f}% from your breakeven")
    elif pl >= config.SELL_TAKE_PROFIT_PCT:
        add("profit", 1, f"Up {pl:.0f}% from your breakeven")
    if pl > 0 and opp.adj_upside is not None:
        if opp.adj_upside <= 0:
            add("profit", 2, f"Price is at or above the analyst target {opp.target:.2f} ({opp.adj_upside:+.0f}% quality-adjusted)")
        elif opp.adj_upside < 5:
            add("profit", 1, f"Only {opp.adj_upside:.0f}% quality-adjusted upside left to the analyst target")
    rsi = opp.risk.rsi_14 if opp.risk else None
    if pl > 0 and rsi is not None and rsi > 75:
        add("profit", 1, f"RSI {rsi:.0f}: overbought after a fast rise")
    if p.weight_pct is not None and p.weight_pct > config.POSITION_CAP_PCT:
        add("trim", 2, f"{p.weight_pct:.1f}% of your portfolio — above the {config.POSITION_CAP_PCT:g}% position cap")

    # ── Claude's holder view (built on the same evidence) ──
    if a and a.status == "OK":
        if a.holder_action == "REVIEW_EXIT":
            add("stop" if pl < 0 or opp.trend == "Downtrend" else "profit", 2, f"Claude: review exit ({a.confidence} confidence)")
        elif a.holder_action == "TRIM":
            add("profit" if pl > 0 else "stop", 1, f"Claude: trim ({a.confidence} confidence)")
        elif a.holder_action in ("HOLD", "ADD"):
            keep.append(f"Claude: {a.holder_action.lower()} ({a.confidence} confidence)")

    # ── Shariah (a label: shown, never forced) ──
    if opp.shariah and opp.shariah.compliant == "No":
        add("shariah", 2, "Shariah screen: not compliant — " + "; ".join(opp.shariah.reasons[:2]))

    # ── Reasons to keep, so the view is balanced ──
    if opp.trend == "Uptrend":
        keep.append("Uptrend: price above its 50-day and 200-day averages")
    if opp.adj_upside is not None and opp.adj_upside >= 20:
        keep.append(f"{opp.adj_upside:.0f}% quality-adjusted upside to the analyst target")
    if opp.thesis_status == "On track":
        keep.append("Thesis on track")
    if opp.insider_signal == "Bullish":
        keep.append("Insiders net buyers")
    if ups - downs >= 2:
        keep.append(f"{ups} analyst upgrades vs {downs} downgrades in 90 days")
    return sig, keep


def _score(sig, side):
    return sum(s["strength"] for s in sig if s["side"] == side)


def _units(shares: float, fraction: float) -> float:
    """Whole shares to sell, at least one when you hold at least one."""
    if shares < 1:
        return round(shares * fraction, 4)
    return float(max(1, min(shares, math.floor(shares * fraction))))


def review_holding(opp: Opportunity, fx=None, broker_bad: set = frozenset()) -> dict:
    p = opp.portfolio
    row = {"ticker": opp.ticker, "name": opp.name or p.name, "price": opp.price, "currency": opp.currency,
           "price_type": opp.price_type, "shares": p.shares, "bep": p.bep, "bep_currency": p.bep_currency,
           "pl_pct": p.pl_pct, "pl_value_eur": p.pl_value_eur, "value_eur": p.value_eur, "weight_pct": p.weight_pct,
           "shariah": opp.shariah.compliant if opp.shariah else "Unknown", "trend": opp.trend,
           "metrics": opp.exit_metrics or {}, "signals": [], "keep": [], "notes": []}
    problems = _data_problems(opp, broker_bad)
    if problems:
        row.update(category="Check data first", strength="", action="No suggestion until the data is fixed",
                   problems=problems, score=0)
        return row

    sig, keep = _signals(opp)
    stop, profit, trim, shariah = (_score(sig, s) for s in ("stop", "profit", "trim", "shariah"))
    pl = p.pl_pct
    fraction, category, score = 0.0, "Hold", 0
    if stop >= 2:
        category = "Stop the loss" if pl < 0 else "Protect gains"
        score = stop
        fraction = 1.0 if score >= config.SELL_STRONG_SCORE else 0.5
    elif profit >= 2:
        category, score = "Take profit", profit
        fraction = 1 / 3 if score >= config.SELL_STRONG_SCORE else 1 / 4
    if trim and category in ("Hold", "Take profit"):
        # Selling down to the cap is the smallest sale that fixes the concentration.
        cap_fraction = 1 - config.POSITION_CAP_PCT / p.weight_pct
        if category == "Hold" or cap_fraction > fraction:
            category, fraction, score = ("Trim to cap" if category == "Hold" else category), cap_fraction, max(score, trim + profit)
    if category == "Hold" and shariah:
        category, score, fraction = "Shariah review", shariah, 0.0
    strength = "" if category in ("Hold", "Shariah review") else \
        ("Strong" if score >= config.SELL_STRONG_SCORE else "Consider")

    units = _units(p.shares, fraction) if fraction else 0
    row.update(category=category, strength=strength, score=score, signals=sig, keep=keep, problems=[])
    if units:
        part = units / p.shares
        proceeds = fx.convert(units * opp.price, opp.currency, "EUR") if fx is not None else None
        realised = p.pl_value_eur * part if p.pl_value_eur is not None else None
        row.update(sell_units=units, sell_fraction=round(part, 3), proceeds_eur=proceeds, realised_pl_eur=realised)
        what = "all" if units >= p.shares else f"{units:g} of {p.shares:g}"
        row["action"] = f"Sell {what} shares"
        if opp.days_to_event is not None and opp.days_to_event <= config.EARNINGS_BLACKOUT_DAYS:
            row["notes"].append(f"{opp.next_event} in {opp.days_to_event} trading days — decide before the results "
                                "on purpose, not by accident.")
        if opp.price_type and "close" in opp.price_type:
            row["notes"].append("Price is the last close — use a limit order near the live price at your broker.")
        if opp.shariah and opp.shariah.compliant != "Yes" and (realised or 0) > 0:
            row["notes"].append("If you follow the Shariah screen, consider purifying the part of the gain earned "
                                "while the stock was not compliant.")
    else:
        row["action"] = {"Shariah review": "Your call: the Shariah screen flags it, the price signals don't",
                         "Hold": "No sell signal"}.get(category, "Watch")
    return row


def review_holdings(opportunities: list[Opportunity], fx=None, broker_diffs: list = None) -> list[dict]:
    """One row per priced or unpriced stock holding, most urgent first. Avoid-list tickers never appear."""
    broker_bad = {d["ticker"] for d in (broker_diffs or [])}
    rows = [review_holding(o, fx, broker_bad) for o in opportunities
            if o.portfolio and o.ticker not in config.AVOID_LIST]
    order = {"Strong": 0, "Consider": 1}
    cat_order = {c: i for i, c in enumerate(CATEGORIES + ("Shariah review", "Check data first", "Hold"))}
    rows.sort(key=lambda r: (order.get(r["strength"], 2), cat_order.get(r["category"], 9), -r["score"]))
    for opp in opportunities:
        if opp.portfolio:
            match = next((r for r in rows if r["ticker"] == opp.ticker), None)
            if match:
                opp.sell_review = {k: match[k] for k in ("category", "strength", "action")}
    return rows

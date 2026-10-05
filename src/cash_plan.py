"""
Cash plan — what to do with the money a sale frees up.

Every sale raises the same question: keep the cash, or put it to work in the
opportunities? This module answers it with numbers, in four steps.

1. Market risk level (assess_market). Points from the data we have:
     VIX (fear gauge), US high-yield credit spread (stress in company borrowing),
     S&P 500 below its 200-day average and its drop from the 52-week high,
     an inverted yield curve, and Claude's risk-on/risk-off read.
   → Calm / Normal / Elevated / Stressed. Missing inputs are listed, not guessed.

2. Cash reserve. Keep config.CASH_TARGET_PCT[level] of the whole portfolio as
   cash, plus money you need within 12 months, plus tax set aside on realised
   gains. Cash you already hold counts first.

3. Ideas. Only opportunities that pass every check get money: data verified,
   tradable at DEGIRO/Revolut, not just sold, Claude says BUY (or enough upside
   and no downtrend when Claude is off), no earnings in the next days (those wait
   for the results), and the buy keeps you under the position cap. Weights favour
   higher rank scores, lower volatility and sectors you're light in. If there
   aren't enough good ideas, the rest stays cash — money is never forced in.

4. Timing. In Elevated/Stressed markets or right before a big macro event,
   buys are split into tranches instead of going in at once.

Two scenarios: only the Strong sell suggestions, and Strong + Consider.
Shariah status is shown on every idea; it filters only if REINVEST_SHARIAH_ONLY.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from datetime import date, datetime

import config
from src.models import Opportunity, MacroContext

try:
    import portfolio_data as _pd
except ImportError:     # pragma: no cover
    _pd = None

LEVELS = ["Calm", "Normal", "Elevated", "Stressed"]


# ── 1. Market risk ────────────────────────────────────────────────────────
def _series_stats(series: list) -> dict:
    out = {}
    if len(series) >= 200:
        ma200 = sum(series[-200:]) / 200
        out["vs_ma200_pct"] = round((series[-1] / ma200 - 1) * 100, 1)
    if len(series) >= 60:
        high = max(series[-252:])
        out["from_high_pct"] = round((series[-1] / high - 1) * 100, 1)
    return out


def assess_market(macro: MacroContext, benchmarks: dict, today: date = None) -> dict:
    today = today or date.today()
    signals, missing, points = [], [], 0

    def sig(name, value, pts, reading):
        nonlocal points
        points += pts
        signals.append({"name": name, "value": value, "points": pts, "reading": reading})

    v = macro.vix
    if v is None:
        missing.append("VIX (needs FRED_API_KEY)")
    else:
        pts = 0 if v < 15 else 1 if v < 20 else 2 if v < 30 else 3
        sig("VIX", f"{v:.1f}", pts, ["calm", "normal", "nervous", "fearful"][pts])
    hy = macro.hy_spread
    if hy is None:
        missing.append("High-yield credit spread (needs FRED_API_KEY)")
    else:
        pts = 0 if hy < 3.5 else 1 if hy < 5 else 2 if hy < 7 else 3
        sig("US high-yield spread", f"{hy:.2f}%", pts, ["tight — lenders relaxed", "normal", "widening — stress", "crisis-level"][pts])
    spy = _series_stats(benchmarks.get("SPY") or [])
    if "vs_ma200_pct" in spy:
        below = spy["vs_ma200_pct"] < 0
        sig("S&P 500 vs 200-day average", f"{spy['vs_ma200_pct']:+.1f}%", 2 if below else 0,
            "below — downtrend" if below else "above — uptrend")
    else:
        missing.append("S&P 500 price history")
    if "from_high_pct" in spy:
        dd = spy["from_high_pct"]
        sig("S&P 500 from 52-week high", f"{dd:+.1f}%", 2 if dd <= -20 else 1 if dd <= -10 else 0,
            "bear market" if dd <= -20 else "correction" if dd <= -10 else "near highs")
    if macro.yield_spread is not None:
        inv = macro.yield_spread < 0
        sig("US 10Y–2Y yield curve", f"{macro.yield_spread:+.2f}%", 1 if inv else 0, "inverted — recession signal" if inv else "normal")
    if macro.regime in ("risk-on", "risk-off", "neutral"):
        sig("Claude's market read", macro.regime, 1 if macro.regime == "risk-off" else 0, macro.regime)
    else:
        missing.append("Claude market read (AI stage off)")

    level = "Calm" if points <= 1 else "Normal" if points <= 3 else "Elevated" if points <= 5 else "Stressed"
    if not signals:
        level = "Normal"
    soon = []
    for e in macro.events or []:
        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if 0 <= (d - today).days <= 7:
            soon.append({"date": e["date"], "name": e["name"], "days": (d - today).days})
    return {"level": level, "points": points, "signals": signals, "missing": missing, "events_soon": soon,
            "coverage": f"{len(signals)} of 6 market signals available"}


# ── 2. Inputs about you ───────────────────────────────────────────────────
def cash_balances() -> dict:
    return dict(getattr(_pd, "CASH_EUR", {}) or {})


def planned_withdrawals() -> float:
    return float(getattr(_pd, "PLANNED_WITHDRAWALS_EUR", 0.0) or 0.0)


def tax_rate() -> tuple[float, str]:
    if config.CAPITAL_GAINS_TAX_RATE is not None:
        return config.CAPITAL_GAINS_TAX_RATE, "your CAPITAL_GAINS_TAX_RATE"
    res = (config.TAX_RESIDENCE or "").upper()
    if res in config.TAX_RATE_BY_RESIDENCE:
        return config.TAX_RATE_BY_RESIDENCE[res], f"default for {res}"
    return 0.0, "unknown — set TAX_RESIDENCE or CAPITAL_GAINS_TAX_RATE"


def _fees(amount_eur: float, currency: str) -> float:
    fx = amount_eur * config.FX_FEE_PCT / 100 if currency and currency.upper() != "EUR" else 0.0
    return config.BROKER_FEE_EUR + fx


# ── 3. Ideas ──────────────────────────────────────────────────────────────
def _sector_weights(opportunities: list[Opportunity]) -> dict:
    held = [o for o in opportunities if o.portfolio and o.portfolio.value_eur]
    total = sum(o.portfolio.value_eur for o in held)
    out = {}
    if not total:
        return out
    for o in held:
        key = o.sector or "Unknown"
        out[key] = out.get(key, 0) + o.portfolio.value_eur / total * 100
    return out


def eligible_ideas(opportunities: list[Opportunity], sold: set, sectors: dict) -> tuple[list, list]:
    """
    Walk the Opportunities tab's Top 10 in rank order. Return (ideas, top10_status):
    ideas are the Top 10 names that pass the buy checks, still in rank order and
    weighted by the same rank score; top10_status says for every Top 10 name what
    the plan does with it and why.
    """
    from src.events import earnings_blackout
    from src.ranking import top_ranked
    ideas, status = [], []
    for rank, o in enumerate(top_ranked(opportunities, 10), 1):
        a = o.analysis if o.analysis and o.analysis.status == "OK" else None
        up = o.adj_upside
        why_not = []
        if o.ticker in config.AVOID_LIST:
            continue
        if o.ticker in sold:
            why_not.append("you're selling it in this plan")
        if o.price_check == "Mismatch":
            why_not.append("price check failed")
        if o.tradable != "Yes":
            why_not.append("not tradable at DEGIRO/Revolut")
        if a and a.new_buyer_action == "AVOID":
            why_not.append("Claude: avoid")
        elif a and a.new_buyer_action != "BUY" and a.holder_action != "ADD":
            why_not.append(f"Claude: {(a.new_buyer_action or 'no buy').lower()} — not a buy yet")
        if not a and (up is None or up < config.REINVEST_MIN_UPSIDE):
            why_not.append(f"upside below {config.REINVEST_MIN_UPSIDE:g}% (no Claude view)")
        if o.trend == "Downtrend":
            why_not.append("in a downtrend")
        if o.portfolio and (o.sell_review or {}).get("category") not in (None, "Hold", "Shariah review"):
            why_not.append(f"Sell review says {o.sell_review['category'].lower()}")
        if config.REINVEST_SHARIAH_ONLY and (not o.shariah or o.shariah.compliant != "Yes"):
            why_not.append("Shariah-only setting is on")
        entry = {"rank": rank, "ticker": o.ticker, "name": o.name, "rank_score": o.rank_score,
                 "shariah": o.shariah.compliant if o.shariah else "Unknown", "held": bool(o.portfolio)}
        if why_not:
            status.append({**entry, "outcome": "skip", "why": why_not})
            continue
        sector_w = sectors.get(o.sector or "Unknown", 0)
        reasons = [f"#{rank} on Opportunities (score {o.rank_score:.1f})"]
        if a:
            reasons.append(f"Claude: {'add' if o.portfolio and a.holder_action == 'ADD' else 'buy'} ({a.confidence} confidence)")
        if up is not None:
            reasons.append(f"{up:+.0f}% quality-adjusted upside")
        if sector_w > config.SECTOR_SOFT_CAP_PCT:
            reasons.append(f"note: {o.sector} is already {sector_w:.0f}% of your portfolio")
        ideas.append({"ticker": o.ticker, "name": o.name, "opp": o, "score": max(o.rank_score, 1), "rank": rank,
                      "reasons": reasons, "blackout": earnings_blackout(o), "next_event": o.next_event,
                      "days_to_event": o.days_to_event, "shariah": entry["shariah"], "sector": o.sector,
                      "held": bool(o.portfolio), "rank_score": o.rank_score})
        status.append({**entry, "outcome": "candidate", "why": []})
    return ideas, status


def _allocate(amount: float, ideas: list, exposure: dict, new_total: float, fx) -> tuple[list, float]:
    """Split `amount` (EUR) over the ideas. Returns (buys, leftover kept as cash)."""
    picks = ideas[:config.REINVEST_MAX_IDEAS]
    if amount < config.REINVEST_MIN_TICKET or not picks:
        return [], amount
    cap = config.POSITION_CAP_PCT / 100 * new_total
    room = {i["ticker"]: max(0.0, cap - ((i["opp"].portfolio.value_eur or 0) if i["held"] else 0)) for i in picks}
    limit = {t: min(r, config.REINVEST_MAX_SHARE * amount) for t, r in room.items()}
    alloc = {i["ticker"]: 0.0 for i in picks}
    remaining, active = amount, [i for i in picks if limit[i["ticker"]] > 0]
    for _ in range(10):   # water-filling: hand out by score, respect each idea's limit
        total_score = sum(i["score"] for i in active)
        if remaining < 1 or not active or total_score <= 0:
            break
        spent, nxt = 0.0, []
        for i in active:
            t = i["ticker"]
            give = min(remaining * i["score"] / total_score, limit[t] - alloc[t])
            alloc[t] += give
            spent += give
            if limit[t] - alloc[t] > 1:
                nxt.append(i)
        remaining -= spent
        active = nxt
    buys = []
    for i in picks:
        eur = alloc[i["ticker"]]
        if eur < config.REINVEST_MIN_TICKET:
            continue
        o = i["opp"]
        price_eur = fx.convert(o.price, o.currency, "EUR") if fx is not None else None
        if not price_eur:
            continue
        fee = _fees(eur, o.currency)
        units = (eur - fee) / price_eur
        units = round(units, 4) if config.ALLOW_FRACTIONAL else math.floor(units)
        if units <= 0:
            continue
        cost = units * price_eur + fee
        after = ((o.portfolio.value_eur or 0) if i["held"] else 0) + units * price_eur
        buys.append({**{k: v for k, v in i.items() if k != "opp"}, "eur": round(cost, 2), "units": units,
                     "price": o.price, "currency": o.currency, "price_eur": round(price_eur, 4), "fee_eur": round(fee, 2),
                     "weight_after_pct": round(after / new_total * 100, 1) if new_total else None})
    # Whole shares leave money over: add single shares, best idea first, while each stays under its limit.
    left = amount - sum(b["eur"] for b in buys)
    for _ in range(50):
        added = False
        for b in buys:
            step = b["price_eur"] * (1 if not config.ALLOW_FRACTIONAL else 0.1)
            if step <= left and b["eur"] + step <= limit[b["ticker"]] + 1:
                b["units"] = round(b["units"] + (1 if not config.ALLOW_FRACTIONAL else 0.1), 4)
                b["eur"] = round(b["eur"] + step, 2)
                left -= step
                added = True
        if not added:
            break
    for b in buys:
        held_value = next((i["opp"].portfolio.value_eur or 0) for i in picks if i["ticker"] == b["ticker"]) if b["held"] else 0
        b["weight_after_pct"] = round((held_value + b["units"] * b["price_eur"]) / new_total * 100, 1) if new_total else None
    used = sum(b["eur"] for b in buys)
    total_used = used or 1
    for b in buys:
        b["share_pct"] = round(b["eur"] / total_used * 100, 1)
    return buys, amount - used


def _tranches(buy: dict, market: dict) -> list:
    if buy["blackout"]:
        return [{"when": f"after {buy['next_event']} (in {buy['days_to_event']} trading days)", "pct": 100}]
    if market["level"] in ("Elevated", "Stressed"):
        return [{"when": "now", "pct": 40}, {"when": "in 2 weeks", "pct": 30}, {"when": "in 4 weeks", "pct": 30}]
    if market["events_soon"]:
        e = market["events_soon"][0]
        return [{"when": "now", "pct": 50}, {"when": f"after {e['name']} ({e['date']})", "pct": 50}]
    return [{"when": "now", "pct": 100}]


# ── 4. The plan ───────────────────────────────────────────────────────────
def _scenario(name, rows, ideas, market, exposure, fx, existing_cash):
    rate, rate_src = tax_rate()
    proceeds = sum(r.get("proceeds_eur") or 0 for r in rows)
    sell_fees = sum(_fees(r.get("proceeds_eur") or 0, r.get("currency")) for r in rows)
    gains = sum(max(0.0, r.get("realised_pl_eur") or 0) for r in rows)
    losses = sum(min(0.0, r.get("realised_pl_eur") or 0) for r in rows)
    tax = max(0.0, gains + losses) * rate
    net = proceeds - sell_fees
    available = existing_cash + net
    invested = (exposure.get("total_value_eur") or 0) - proceeds
    portfolio_after = invested + available
    target_pct = config.CASH_TARGET_PCT[market["level"]]
    reserve = target_pct / 100 * portfolio_after
    needs = planned_withdrawals()
    keep_target = reserve + needs + tax
    keep = min(available, keep_target)
    deployable = max(0.0, available - keep)
    buys, leftover = _allocate(deployable, ideas, exposure, portfolio_after, fx)
    for b in buys:
        b["tranches"] = _tranches(b, market)
    cash_end = keep + leftover
    return {
        "name": name, "sales": [{"ticker": r["ticker"], "action": r["action"], "proceeds_eur": r.get("proceeds_eur"),
                                 "realised_pl_eur": r.get("realised_pl_eur"), "category": r["category"]} for r in rows],
        "proceeds_eur": proceeds, "sell_fees_eur": sell_fees, "net_proceeds_eur": net,
        "realised_gain_eur": gains, "realised_loss_eur": losses, "tax_rate": rate, "tax_rate_source": rate_src,
        "tax_reserve_eur": tax, "existing_cash_eur": existing_cash, "available_eur": available,
        "portfolio_after_eur": portfolio_after, "target_cash_pct": target_pct, "reserve_eur": reserve,
        "planned_withdrawals_eur": needs, "keep_eur": keep, "deployable_eur": deployable,
        "buys": buys, "invest_eur": sum(b["eur"] for b in buys), "unallocated_eur": leftover,
        "cash_end_eur": cash_end, "cash_end_pct": round(cash_end / portfolio_after * 100, 1) if portfolio_after else None,
        "shortfall_eur": max(0.0, keep_target - available),
    }


def _reasoning(s: dict, market: dict, ideas: list) -> list:
    out = [f"Market risk is **{market['level']}** ({market['points']} points from {market['coverage']}), so the plan "
           f"keeps {s['target_cash_pct']:g}% of the portfolio as cash."]
    hot = [x for x in market["signals"] if x["points"] >= 2]
    if hot:
        out.append("What raises the risk level: " + "; ".join(f"{x['name']} {x['value']} ({x['reading']})" for x in hot) + ".")
    if s["existing_cash_eur"]:
        out.append(f"You already hold €{s['existing_cash_eur']:,.0f} in cash; it counts toward the reserve before any sale.")
    if s["tax_reserve_eur"]:
        out.append(f"€{s['tax_reserve_eur']:,.0f} is set aside for tax on realised gains ({s['tax_rate'] * 100:.1f}%, {s['tax_rate_source']}).")
    if s["planned_withdrawals_eur"]:
        out.append(f"€{s['planned_withdrawals_eur']:,.0f} stays in cash for the withdrawals you planned within 12 months.")
    if s["shortfall_eur"] > 1:
        out.append(f"Your cash is €{s['shortfall_eur']:,.0f} below the target reserve, so nothing is reinvested in this scenario.")
    if s["buys"]:
        out.append(f"The buys follow the Top 10 on the Opportunities tab, in the same order: {len(ideas)} of them pass the buy checks "
                   f"and the money goes to the first {len(s['buys'])}, in proportion to their rank score. "
                   "The Top 10 table below shows why the others are skipped.")
    elif s["deployable_eur"] >= config.REINVEST_MIN_TICKET:
        out.append("None of the Top 10 opportunities passes the buy checks this run, so the money stays in cash until one does. "
                   "Holding cash is a position too — it keeps your options open.")
    if s["unallocated_eur"] >= config.REINVEST_MIN_TICKET and s["buys"]:
        out.append(f"€{s['unallocated_eur']:,.0f} stays cash: the ideas that qualify are already at the "
                   f"{config.POSITION_CAP_PCT:g}% position cap or the {config.REINVEST_MAX_SHARE * 100:.0f}% per-idea limit. "
                   "Spreading it over weaker ideas would lower the quality of the portfolio.")
    if market["level"] in ("Elevated", "Stressed"):
        out.append("Buys are split into three tranches over four weeks: in nervous markets prices can fall further after you buy, "
                   "and spreading entries lowers the cost of being early.")
    elif market["events_soon"]:
        e = market["events_soon"][0]
        out.append(f"{e['name']} is on {e['date']}: half of each buy waits until after it.")
    if any(b["blackout"] for b in s["buys"]):
        out.append("Ideas reporting earnings within days wait for the results — a miss can move the price 10% overnight.")
    out.append("Re-run after you trade: the plan updates with your new cash and weights.")
    return out


def _data_gaps(market: dict, plan: dict, opportunities: list) -> list:
    gaps = []
    if not any(cash_balances().values()):
        gaps.append({"what": "Your cash balance", "why": "the reserve counts existing cash first; it's 0 now",
                     "how": "Set CASH_EUR in portfolio_data.py (or export the DEGIRO 'Account' CSV — import planned)"})
    for m in market["missing"]:
        how = ("Free key at fred.stlouisfed.org — run bash scripts/setup.sh" if "FRED" in m else
               "Log in to Claude Code and run without --no-ai" if "Claude" in m else "Check Data Health")
        gaps.append({"what": m, "why": "one of the market-risk signals that set the cash target", "how": how})
    if "unknown" in tax_rate()[1]:
        gaps.append({"what": "Tax rate on gains", "why": "decides how much of a profitable sale must stay as cash for tax",
                     "how": "Set TAX_RESIDENCE (e.g. \"NL\") or CAPITAL_GAINS_TAX_RATE in config.py"})
    if not any(o.analysis for o in opportunities):
        gaps.append({"what": "Claude's buy/avoid view", "why": "without it ideas qualify on analyst upside alone",
                     "how": "Install and log in to Claude Code; the pipeline uses your subscription"})
    unpriced = [h for h in getattr(_pd, "HOLDINGS", []) if not h.get("ticker")]
    if unpriced:
        gaps.append({"what": f"{len(unpriced)} fund(s) without a Yahoo ticker", "why": "they're left out of the portfolio total, so "
                     "the cash target is computed on a smaller base", "how": "Set their tickers in portfolio_data.py"})
    gaps.append({"what": "Optional: market breadth and sentiment", "why": "would sharpen the risk level (share of stocks above their "
                 "200-day average, AAII bull/bear survey)", "how": "Not connected — free sources exist (AAII weekly CSV, "
                 "Finnhub index constituents); say if you want them added"})
    return gaps


def build_cash_plan(opportunities: list[Opportunity], sell_rows: list, macro: MacroContext, benchmarks: dict,
                    fx, exposure: dict, today: date = None) -> dict:
    market = assess_market(macro, benchmarks or {}, today)
    existing = sum(v for v in cash_balances().values() if v)
    strong = [r for r in sell_rows if r.get("strength") == "Strong" and r.get("sell_units")]
    consider = [r for r in sell_rows if r.get("strength") == "Consider" and r.get("sell_units")]
    sectors = _sector_weights(opportunities)
    plan = {"market": market, "sector_weights": {k: round(v, 1) for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])},
            "cash_balances": cash_balances(), "scenarios": []}
    for name, rows in (("Strong sell signals only", strong), ("Strong + Consider", strong + consider)):
        sold = {r["ticker"] for r in rows}
        ideas, status = eligible_ideas(opportunities, sold, sectors)
        sc = _scenario(name, rows, ideas, market, exposure, fx, existing)
        bought = {b["ticker"]: b for b in sc["buys"]}
        for st in status:
            if st["outcome"] != "candidate":
                continue
            if st["ticker"] in bought:
                st.update(outcome="buy", eur=bought[st["ticker"]]["eur"], units=bought[st["ticker"]]["units"])
            elif sc["deployable_eur"] < config.REINVEST_MIN_TICKET:
                st.update(outcome="wait", why=["no money left to invest after the cash reserve"])
            elif st["rank"] > max([b["rank"] for b in sc["buys"]] + [0]) and len(sc["buys"]) >= config.REINVEST_MAX_IDEAS:
                st.update(outcome="wait", why=[f"the plan spreads money over at most {config.REINVEST_MAX_IDEAS} ideas"])
            else:
                st.update(outcome="wait", why=["already at the position cap, or the amount is below the minimum ticket"])
        sc["ideas_count"], sc["top10_status"] = len(ideas), status
        sc["reasoning"] = _reasoning(sc, market, ideas)
        plan["scenarios"].append(sc)
    plan["reasoning"] = plan["scenarios"][0]["reasoning"]
    plan["data_gaps"] = _data_gaps(market, plan, opportunities)
    plan["shariah_cash_note"] = ("Cash waiting to be invested: interest on it isn't permissible under the Shariah screen — "
                                 "keep it in a non-interest account or a Shariah money-market/sukuk fund, and give away any "
                                 "interest your broker credits.")
    return plan

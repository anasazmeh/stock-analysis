"""
Portfolio KPIs — the numbers a financial adviser would track, each with a
good / watch / act status against your investor profile (config.INVESTOR_PROFILE)
and the caps in config.py.

Groups: Return · Risk · Costs · Decisions · Readiness. A KPI whose data is missing
says what to add (e.g. the DEGIRO account statement in data/broker/) instead of
guessing. Each run stores the numbers in its snapshot, so the page can show the
change against about a month ago.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob
import json
import math
import statistics
from datetime import date, datetime

import config

GROUPS = ("Return", "Risk", "Costs", "Decisions", "Readiness")
_NO_STATEMENT = "Add your DEGIRO account statement (Inbox → Account statement, CSV or Excel) to data/broker/."
_NO_TRANSACTIONS = "Add your DEGIRO Transactions export to data/broker/."


def _k(key, group, name, value, status="na", detail="", num=None, target=""):
    return {"key": key, "group": group, "name": name, "value": value, "status": status,
            "detail": detail, "num": num, "target": target}


def _eur(v, sign=False):
    if v is None:
        return "–"
    s = f"€{abs(v):,.0f}"
    return (("+" if v >= 0 else "−") + s) if sign else (("−" if v < 0 else "") + s)


def _pct(v, sign=True, digits=1):
    return "–" if v is None else (f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%")


def _snapshots(runs_dir: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        try:
            with open(path) as f:
                s = json.load(f)
            s["_at"] = datetime.fromisoformat(s["run_at"])
            out.append(s)
        except (OSError, ValueError, KeyError):
            continue
    return out


# ── Return ────────────────────────────────────────────────────────────────
def goal_pace(total_now: float, snaps: list, flows: list, today: date) -> dict:
    """Progress towards the profile target since its start, net of money added since then."""
    prof = config.INVESTOR_PROFILE
    target, months = prof.get("target_return_pct", 100.0) / 100, prof.get("horizon_months", 12)
    start = date.fromisoformat(prof.get("start_date") or today.isoformat())
    base = prof.get("start_value_eur")
    if not base:
        first = next((s for s in snaps if s["_at"].date() >= start and s.get("total_value_eur")), None)
        if first:
            base, start = first["total_value_eur"], first["_at"].date()
    if not base or not total_now:
        return _k("goal_pace", "Return", f"Goal: +{target * 100:.0f}% in {months} months", "starts with this run",
                  "na", "The first run after setting the profile is the starting value.")
    added = sum(-v for d, v in flows if date.fromisoformat(d) > start)   # deposits after the start (+)
    progress = (total_now - added) / base - 1
    elapsed = max(0.0, (today - start).days / 30.44)
    left = max(0.5, months - elapsed)
    need_value = base * (1 + target) + added
    monthly_needed = (need_value / total_now) ** (1 / left) - 1 if total_now > 0 else None
    expected = (1 + target) ** (min(elapsed, months) / months) - 1
    if elapsed < 1:
        status = "na"
    elif progress >= expected:
        status = "good"
    else:
        status = "warn" if progress >= expected - 0.10 else "bad"
    detail = (f"From {_eur(base)} on {start.isoformat()}: {_pct(progress * 100)} so far "
              f"(on-track path: {_pct(expected * 100)} after {elapsed:.1f} months). "
              f"Needed from here: {_pct(monthly_needed * 100) if monthly_needed is not None else '–'} a month "
              f"for {left:.1f} months.")
    return _k("goal_pace", "Return", f"Goal: +{target * 100:.0f}% in {months} months",
              _pct(progress * 100), status, detail, round(progress * 100, 1),
              f"{_pct(monthly_needed * 100) if monthly_needed is not None else '–'} / month needed")


def return_kpis(total_now, holdings_value, cash, account, realised, scorecard, snaps, today):
    from src.account_statement import xirr
    out = []
    if account:
        net = account["net_invested_eur"]
        gain = total_now - net
        out.append(_k("net_invested", "Return", "Net money in", _eur(net), "na",
                      f"Deposited {_eur(account['deposits_eur'])} − withdrawn {_eur(account['withdrawals_eur'])} "
                      f"(since {account['first_date']}).", net))
        out.append(_k("total_gain", "Return", "Gain on your money", _eur(gain, True),
                      "good" if gain >= 0 else "bad",
                      f"Value {_eur(total_now)} (holdings {_eur(holdings_value)} + cash {_eur(cash)}) vs net money in — "
                      f"{_pct(100 * gain / net) if net > 0 else '–'}. Prices, dividends, fees and FX all included.",
                      round(gain, 2)))
        rate = xirr(account["flows"], total_now, today)
        out.append(_k("xirr", "Return", "Annual return on your money (XIRR)", _pct(rate),
                      "na" if rate is None else ("good" if rate >= 10 else "warn" if rate >= 0 else "bad"),
                      "Counts when each deposit arrived. For comparison, world stocks have returned about 7–10% a year "
                      "over the long run.", rate, "≥ 10% / year"))
    else:
        out.append(_k("xirr", "Return", "Annual return on your money (XIRR)", "–", "na", _NO_STATEMENT))
    out.append(goal_pace(total_now, snaps, account["flows"] if account else [], today))
    if scorecard:
        d = scorecard["difference_pts"]
        out.append(_k("vs_benchmark", "Return", f"vs {scorecard['benchmark']} (since {scorecard['since']})",
                      f"{d:+.1f} pts", "good" if d >= 0 else "warn" if d >= -5 else "bad",
                      f"Holdings {_pct(scorecard['portfolio_pct'])} vs benchmark {_pct(scorecard['benchmark_pct'])}. "
                      "Approximate: trades in between move the portfolio figure.", d, "≥ 0"))
    else:
        out.append(_k("vs_benchmark", "Return", "vs benchmark", "–", "na",
                      f"Needs a run snapshot at least {config.SCORECARD_DAYS} days old."))
    if realised:
        out.append(_k("realised_year", "Return", f"Realised this year ({today.year})", _eur(realised["this_year_eur"], True),
                      "good" if realised["this_year_eur"] >= 0 else "warn",
                      f"All years: {_eur(realised['total_eur'], True)}. Fees and FX included.", realised["this_year_eur"]))
    if account:
        net_div = account["last_12m"].get("dividend", 0) + account["last_12m"].get("div_tax", 0)
        out.append(_k("dividends_12m", "Return", "Dividends, last 12 months (after tax)", _eur(net_div), "na",
                      f"{_pct(100 * net_div / total_now, False, 2) if total_now else '–'} of the portfolio.", round(net_div, 2)))
    return out


# ── Risk ──────────────────────────────────────────────────────────────────
def value_series(opportunities, days: int = 252) -> list[float]:
    """Daily EUR value of today's holdings over the past year (today's share counts and FX)."""
    series = []
    for o in opportunities:
        p = o.portfolio
        if not p or not p.value_eur or not o.price or len(o.hist_prices or []) < 20:
            continue
        scale = p.value_eur / o.price        # EUR per unit of listing price, for this position
        hist = [h * scale for h in o.hist_prices[-days:]]
        series.append(hist)
    if not series:
        return []
    n = min(len(s) for s in series)
    return [sum(s[-n + i] for s in series) for i in range(n)]


def drawdown(values: list[float]) -> tuple:
    if len(values) < 2:
        return None, None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return round(100 * worst, 1), round(100 * (values[-1] / max(values) - 1), 1)


def risk_kpis(opportunities, exposure):
    out, limit = [], config.INVESTOR_PROFILE.get("max_drawdown_pct", 50.0)
    values = value_series(opportunities)
    worst, current = drawdown(values)
    if worst is not None:
        st = lambda dd: "good" if -dd < limit * 0.5 else "warn" if -dd < limit * 0.8 else "bad"
        out.append(_k("drawdown_now", "Risk", "Below the 1-year peak now", _pct(current), st(current),
                      f"Today's holdings priced over the past year. Your limit: −{limit:.0f}%.", current, f"> −{limit * 0.5:.0f}%"))
        out.append(_k("drawdown_max", "Risk", "Worst drop in the past year", _pct(worst), st(worst),
                      f"Largest fall from a high, same basis. Act if it nears −{limit:.0f}%.", worst, f"> −{limit * 0.5:.0f}%"))
        rets = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1]]
        if len(rets) > 20:
            vol = statistics.pstdev(rets) * math.sqrt(252) * 100
            out.append(_k("volatility", "Risk", "Volatility (yearly)", _pct(vol, False, 0),
                          "good" if vol < 25 else "warn" if vol < 40 else "bad",
                          f"Typical yearly swing. A one-in-six bad year is roughly −{vol:.0f}%; world stocks ≈ 15%.",
                          round(vol, 1), "< 25%"))
    else:
        out.append(_k("drawdown_now", "Risk", "Below the 1-year peak now", "–", "na", "Needs price history for your holdings."))
    held = [o for o in opportunities if o.portfolio and o.portfolio.weight_pct]
    if held:
        top = max(held, key=lambda o: o.portfolio.weight_pct)
        w, cap = top.portfolio.weight_pct, config.POSITION_CAP_PCT
        out.append(_k("largest_position", "Risk", "Largest position", f"{top.ticker} {w:.0f}%",
                      "good" if w <= cap * 0.8 else "warn" if w <= cap else "bad",
                      f"Cap {cap:g}% per stock.", round(w, 1), f"≤ {cap:g}%"))
    themes = (exposure or {}).get("themes") or {}
    if themes:
        t, w = next(iter(themes.items()))
        cap = config.THEME_CAP_PCT
        out.append(_k("largest_theme", "Risk", "Largest theme", f"{t} {w:.0f}%",
                      "good" if w <= cap * 0.75 else "warn" if w <= cap else "bad",
                      f"Cap {cap:g}% per theme. One bad year for this theme hits all of these at once.",
                      round(w, 1), f"≤ {cap:g}%"))
    ccy = (exposure or {}).get("currencies") or {}
    if ccy:
        usd = ccy.get("USD", 0.0)
        out.append(_k("usd_share", "Risk", "In US dollars", _pct(usd, False, 0),
                      "good" if usd <= 50 else "warn" if usd <= 75 else "bad",
                      f"A 10% fall in the dollar costs about {usd / 10:.0f}% of the portfolio, even if the stocks don't move.",
                      round(usd, 1), "≤ 50%"))
    return out


# ── Costs ─────────────────────────────────────────────────────────────────
def cost_kpis(account, realised, total_now, today):
    out = []
    if not account:
        return [_k("costs_12m", "Costs", "All-in costs, last 12 months", "–", "na", _NO_STATEMENT)]
    l12 = account["last_12m"]
    fx12 = 0.0
    if realised:
        cutoff = date(today.year - 1, today.month, min(today.day, 28)).isoformat()
        fx12 = sum(v for d, v in realised.get("fx_costs", []) if d >= cutoff)
    parts = {"trading": l12.get("trade_fee", 0), "currency conversion": fx12, "price subscriptions": l12.get("data_fee", 0),
             "exchange connection": l12.get("connect_fee", 0), "ADR": l12.get("adr_fee", 0)}
    cost = -sum(parts.values())
    pct = 100 * cost / total_now if total_now else None
    out.append(_k("costs_12m", "Costs", "All-in costs, last 12 months", f"{_eur(cost)} · {_pct(pct, False, 2)}",
                  "na" if pct is None else ("good" if pct < 0.5 else "warn" if pct < 1 else "bad"),
                  " · ".join(f"{k} {_eur(-v)}" for k, v in parts.items() if v)
                  + ("" if realised else f". Currency costs need the Transactions export."), round(pct or 0, 2), "< 0.5% / year"))
    months = account.get("data_fee_months") or []
    if months:
        # DEGIRO charges on the 1st–2nd for the month ahead: a statement month without a charge means they're off
        last, until = months[-1], account["last_date"][:7]
        active = last >= until
        out.append(_k("data_fees", "Costs", "Real-time price subscriptions",
                      f"last charged {last}", "warn" if active else "good",
                      f"{len(months)} months charged since {months[0]} ({_eur(-account['totals'].get('data_fee', 0))}). "
                      + (f"Charged in {until}, the last month of your statement. If you've switched them off "
                         "(DEGIRO → Settings → Real-time quotes), the next statement shows no charge." if active
                         else f"No charge in {until} — switched off."), len(months)))
    w = account.get("usd_dividend_withholding_pct")
    if w is not None:
        out.append(_k("withholding", "Costs", "US dividend tax withheld", _pct(w, False),
                      "good" if w <= 16 else "warn" if w <= 20 else "bad",
                      "Should be 15% with a valid W-8BEN at your broker; more means the form is missing or expired.",
                      w, "15%"))
    interest = l12.get("interest", 0)
    out.append(_k("debit_interest", "Costs", "Interest paid (debit balance), 12 months",
                  f"€{-interest:,.2f}" if interest else "€0",
                  "good" if interest >= 0 else "warn",
                  "Charged when your cash goes below zero (fees before cash arrives). Interest is riba — keep a small "
                  "cash buffer and ask your broker to switch off margin." if interest < 0 else "None.", round(-interest, 2)))
    return out


# ── Decisions ─────────────────────────────────────────────────────────────
def decision_kpis(realised, snaps, opportunities, bench_now, today):
    out = []
    periods = (realised or {}).get("periods") or []
    if periods:
        wins = [p for p in periods if p["realised_eur"] > 0]
        losses = [p for p in periods if p["realised_eur"] <= 0]
        hit = 100 * len(wins) / len(periods)
        out.append(_k("hit_rate", "Decisions", "Sold at a profit (hit rate)", f"{len(wins)} of {len(periods)} · {hit:.0f}%",
                      "good" if hit >= 50 else "warn" if hit >= 35 else "bad",
                      "Each buy-to-sell holding period counts once.", round(hit, 1), "≥ 50%"))
        if wins and losses:
            aw = sum(p["realised_eur"] for p in wins) / len(wins)
            al = -sum(p["realised_eur"] for p in losses) / len(losses)
            ratio = aw / al if al else None
            out.append(_k("payoff", "Decisions", "Average win vs average loss",
                          f"{ratio:.1f}×" if ratio else "–", "na" if ratio is None else
                          ("good" if ratio >= 1.5 else "warn" if ratio >= 1 else "bad"),
                          f"Average win {_eur(aw)} vs average loss {_eur(al)}. Above 1.5× you can be wrong half the time "
                          "and still grow.", round(ratio, 2) if ratio else None, "≥ 1.5×"))
            days = lambda p: (date.fromisoformat(p["closed"]) - date.fromisoformat(p["opened"])).days
            dw, dl = statistics.median(days(p) for p in wins), statistics.median(days(p) for p in losses)
            out.append(_k("holding_time", "Decisions", "Holding time: losers vs winners",
                          f"{dl / 30.44:.0f} vs {dw / 30.44:.0f} months",
                          "good" if dl <= dw else "warn" if dl <= 1.5 * dw else "bad",
                          "Median months held. Holding losers much longer than winners is the classic "
                          "'sell winners early, hope on losers' habit.", round(dl / max(dw, 1), 2), "losers ≤ winners"))
    else:
        out.append(_k("hit_rate", "Decisions", "Sold at a profit (hit rate)", "–", "na", _NO_TRANSACTIONS))
    out += track_record(snaps, opportunities, bench_now, today)
    return out


def track_record(snaps, opportunities, bench_now, today, horizons=(30, 90, 180)) -> list:
    """How this app's Top 10 did since past runs, against the benchmark."""
    price_now = {o.ticker: (o.price, o.currency) for o in opportunities if o.price}
    out = []
    for h in horizons:
        old = [s for s in snaps if (today - s["_at"].date()).days >= h]
        if not old:
            continue
        s = old[-1]
        then = {t["ticker"]: (t.get("price"), t.get("currency")) for t in s.get("tickers", [])}
        rets = []
        for t in s.get("top10", []):
            p0, c0 = then.get(t, (None, None))
            p1, c1 = price_now.get(t, (None, None))
            if p0 and p1 and c0 == c1:
                rets.append(100 * (p1 / p0 - 1))
        if len(rets) < 3:
            continue
        avg = sum(rets) / len(rets)
        bench = 100 * (bench_now / s["benchmark_close"] - 1) if bench_now and s.get("benchmark_close") else None
        diff = avg - bench if bench is not None else None
        out.append(_k(f"top10_{h}d", "Decisions", f"App's Top 10 since {s['_at'].date().isoformat()}", _pct(avg),
                      "na" if diff is None else ("good" if diff >= 0 else "warn" if diff >= -5 else "bad"),
                      f"Average of {len(rets)} picks, in their own currency"
                      + (f"; benchmark {_pct(bench)} ({diff:+.1f} pts)." if bench is not None else "."), round(avg, 1)))
    if not out:
        out.append(_k("top10_30d", "Decisions", "App's Top 10 track record", "–", "na",
                      "Appears once runs are at least 30 days old."))
    return out


# ── Readiness ─────────────────────────────────────────────────────────────
def readiness_kpis(opportunities, total_now, cash, orders, market_level, pur_rows):
    out = []
    target = config.CASH_TARGET_PCT.get(market_level or "Normal", 10.0)
    cp = 100 * cash / total_now if total_now else None
    if cp is not None:
        out.append(_k("cash_pct", "Readiness", "Cash", f"{_eur(cash)} · {_pct(cp, False, 0)}",
                      "good" if abs(cp - target) <= 5 else "warn" if abs(cp - target) <= 15 else "bad",
                      f"Target {target:g}% for a {market_level or 'Normal'} market (Cash plan).", round(cp, 1), f"≈ {target:g}%"))
    if orders and orders.get("count"):
        out.append(_k("open_orders", "Readiness", "Open sell orders", f"{orders['count']} · {_eur(orders['value_eur'])}",
                      "na", f"Value if all fill; {orders.get('fills_now', 0)} at or below today's price. Not counted as cash.",
                      orders["value_eur"]))
    held = [o for o in opportunities if o.portfolio and o.portfolio.value_eur]
    total_h = sum(o.portfolio.value_eur for o in held)
    if total_h:
        share = {}
        for o in held:
            s = o.shariah.compliant if o.shariah else ("Fund" if o.portfolio.asset_type in ("ETF", "ETC") else "Unknown")
            share[s] = share.get(s, 0) + o.portfolio.value_eur
        yes = 100 * share.get("Yes", 0) / total_h
        out.append(_k("shariah_share", "Readiness", "Holdings labelled Shariah compliant", _pct(yes, False, 0), "na",
                      " · ".join(f"{k} {100 * v / total_h:.0f}%" for k, v in sorted(share.items(), key=lambda kv: -kv[1]))
                      + ". A label only — it never filters.", round(yes, 1)))
    due = sum((r or {}).get("amount_eur") or 0 for _, r in (pur_rows or []))
    if pur_rows:
        out.append(_k("purification", "Readiness", "Dividend purification due (estimate)", _eur(due), "na",
                      "Share of dividends from non-compliant income, to give to charity if you follow the screen.", round(due, 2)))
    return out


# ── All together ──────────────────────────────────────────────────────────
def build_kpis(opportunities, exposure, fx, *, cash: float, orders: dict = None, scorecard: dict = None,
               benchmarks: dict = None, market_level: str = "", purification_rows=None, runs_dir: str = None,
               broker_dir: str = None, today: date = None) -> dict:
    from src import account_statement, broker_import
    from src.journal import RUNS_DIR
    today = today or date.today()
    snaps = _snapshots(runs_dir or RUNS_DIR)
    holdings = (exposure or {}).get("total_value_eur") or 0.0
    total = holdings + (cash or 0.0)
    try:
        account = account_statement.summarize(account_statement.load(broker_dir), fx, today)
    except Exception as e:      # a malformed export must not stop the run
        print(f"  [kpis] account statement skipped: {type(e).__name__}")
        account = None
    try:
        realised = broker_import.realised_summary(broker_dir)
    except Exception as e:
        print(f"  [kpis] transactions skipped: {type(e).__name__}")
        realised = None
    bench_series = (benchmarks or {}).get(config.SCORECARD_BENCHMARK) or []
    items = (return_kpis(total, holdings, cash or 0.0, account, realised, scorecard, snaps, today)
             + risk_kpis(opportunities, exposure)
             + cost_kpis(account, realised, total, today)
             + decision_kpis(realised, snaps, opportunities, bench_series[-1] if bench_series else None, today)
             + readiness_kpis(opportunities, total, cash or 0.0, orders, market_level, purification_rows))
    # change vs the snapshot closest to 30 days ago
    month_ago = [s for s in snaps if (today - s["_at"].date()).days >= 25 and s.get("kpis")]
    prev = month_ago[-1] if month_ago else None
    for k in items:
        if prev and k["num"] is not None and prev["kpis"].get(k["key"]) is not None:
            k["prev"], k["prev_date"] = prev["kpis"][k["key"]], prev["_at"].date().isoformat()
    counts = {s: sum(k["status"] == s for k in items) for s in ("good", "warn", "bad")}
    return {"items": items, "counts": counts, "total_value_eur": round(total, 2), "holdings_eur": round(holdings, 2),
            "cash_eur": round(cash or 0.0, 2), "net_invested_eur": account["net_invested_eur"] if account else None,
            "account_years": account["years"] if account else {}, "statement_until": account["last_date"] if account else None}


def numbers(kpis: dict) -> dict:
    """{key: number} for the run snapshot."""
    return {k["key"]: k["num"] for k in (kpis or {}).get("items", []) if k["num"] is not None}

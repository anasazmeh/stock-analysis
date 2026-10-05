"""
Event calendar: company earnings + macro events that move the portfolio.

Earnings dates: Finnhub earnings calendar (one call, free key) → Yahoo
Ticker.calendar (holdings and top names) → Alpha Vantage calendar (already
attached earlier). Macro: config.MACRO_EVENTS (FOMC, ECB, US CPI), TSMC's monthly
revenue release, and your own events in data/events.json, e.g.
  [{"date": "2026-12-15", "name": "SpaceX lock-up ends", "tickers": ["SPCX"]}]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date, timedelta

import requests
import config
import src.cache as cache
from src.models import Opportunity, MacroContext

_USER_EVENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "events.json")


def trading_days_between(start: date, end: date) -> int:
    """Weekdays from start (exclusive) to end (inclusive); ignores holidays."""
    if end <= start:
        return 0
    days, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def _finnhub_calendar(start: date, end: date) -> dict:
    if not config.FINNHUB_API_KEY:
        return {}
    key = f"finnhub:earnings:{start}:{end}"
    cached = cache.get(key, config.TTL_EARNINGS)
    if cached:
        return cached
    try:
        resp = requests.get("https://finnhub.io/api/v1/calendar/earnings", timeout=15,
                            params={"from": start.isoformat(), "to": end.isoformat()},
                            headers={"X-Finnhub-Token": config.FINNHUB_API_KEY})
        rows = resp.json().get("earningsCalendar", []) if resp.status_code == 200 else []
    except (requests.RequestException, ValueError) as e:
        print(f"  [events] Finnhub calendar failed: {type(e).__name__}")
        return {}
    out = {}
    for r in rows:
        sym, d = r.get("symbol"), r.get("date")
        if sym and d and (sym not in out or d < out[sym]):
            out[sym] = d
    if out:
        cache.set(key, out)
    return out


def _yahoo_earnings_date(ticker: str, today: date) -> str:
    key = f"yahoo:calendar:{ticker}"
    cached = cache.get(key, config.TTL_EARNINGS)
    if cached is not None:
        return cached
    found = ""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar or {}
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        future = sorted(str(d)[:10] for d in (dates or []) if str(d)[:10] >= today.isoformat())
        found = future[0] if future else ""
    except Exception:
        return ""
    cache.set(key, found)
    return found


def load_user_events(path: str = None) -> list[dict]:
    path = path or _USER_EVENTS
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            rows = json.load(f)
        return [r for r in rows if r.get("date") and r.get("name")]
    except (OSError, ValueError) as e:
        print(f"  [events] {path} unreadable: {e}")
        return []


def tsmc_revenue_dates(today: date, months: int = 2) -> list[dict]:
    """TSMC publishes monthly revenue around the 10th."""
    out, y, m = [], today.year, today.month
    for _ in range(months + 1):
        d = date(y, m, 10)
        if d >= today:
            out.append({"date": d.isoformat(), "name": "TSMC monthly revenue (around this date)",
                        "tickers": ["TSM"], "themes": ["AI / Semiconductors"]})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out[:months]


def calendar_status(today: date = None, warn_days: int = 90) -> tuple[str, str]:
    """(status, detail) for Data Health: warn before config.MACRO_EVENTS runs out."""
    today = today or date.today()
    upcoming = sorted(e["date"] for e in config.MACRO_EVENTS if e["date"] >= today.isoformat())
    if not upcoming:
        return "failed", "no macro events left — add the next Fed / ECB / CPI dates to MACRO_EVENTS in config.py"
    last = upcoming[-1]
    if last < (today + timedelta(days=warn_days)).isoformat():
        return "partial", f"MACRO_EVENTS ends {last} — add the next dates to config.py"
    cpi = [d for d in upcoming if d <= (today + timedelta(days=warn_days)).isoformat()]
    has_cpi = any(e["date"] in cpi and "CPI" in e["name"] for e in config.MACRO_EVENTS)
    return ("ok" if has_cpi else "partial",
            f"{len(upcoming)} upcoming, last {last}" + ("" if has_cpi else
            " — no US CPI date in the next 90 days (BLS publishes the next year's dates in late autumn)"))


def macro_events(today: date, horizon_days: int = 45) -> list[dict]:
    end = (today + timedelta(days=horizon_days)).isoformat()
    events = [e for e in config.MACRO_EVENTS + tsmc_revenue_dates(today) + load_user_events()
              if today.isoformat() <= e["date"] <= end]
    return sorted(events, key=lambda e: e["date"])


def attach_events(opportunities: list[Opportunity], macro: MacroContext, today: date = None) -> MacroContext:
    today = today or date.today()
    priced = [o for o in opportunities if o.price > 0]
    finnhub = _finnhub_calendar(today, today + timedelta(days=90))
    for opp in priced:
        if not opp.earnings_date and opp.ticker in finnhub:
            opp.earnings_date = finnhub[opp.ticker]

    lookups = sorted([o for o in priced if not o.earnings_date],
                     key=lambda o: (0 if o.portfolio else 1, -(o.rank_score or 0)))
    for opp in lookups[:config.EARNINGS_LOOKUP_MAX]:
        opp.earnings_date = _yahoo_earnings_date(opp.ticker, today) or None

    macro.events = macro_events(today)
    user_by_ticker = {}
    for e in macro.events:
        for t in e.get("tickers", []):
            user_by_ticker.setdefault(t, e)

    for opp in priced:
        candidates = []
        if opp.earnings_date and opp.earnings_date >= today.isoformat():
            candidates.append((opp.earnings_date, "Earnings"))
        if opp.ticker in user_by_ticker:
            e = user_by_ticker[opp.ticker]
            candidates.append((e["date"], e["name"]))
        if candidates:
            when, name = min(candidates)
            opp.next_event = f"{name} {when}"
            opp.days_to_event = trading_days_between(today, date.fromisoformat(when))
    return macro


def earnings_blackout(opp: Opportunity) -> bool:
    """True when new BUY/ADD signals should wait: earnings within N trading days."""
    return (opp.days_to_event is not None and opp.next_event.startswith("Earnings")
            and opp.days_to_event <= config.EARNINGS_BLACKOUT_DAYS)

"""
Data-quality gate and run health.

Each ticker gets flags for missing or stale data. Tickers with a critical flag are
kept in the report (listed under "Data gaps") but skip the Claude stage and are
left out of the Top 10 and of action alerts. The run is DEGRADED when a priced
holding has no usable data or too many tickers fail.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
from src.models import Opportunity

CRITICAL = ("no price", "stale quote", "short history", "no market cap", "wrong listing")


def suffix_of(ticker: str) -> str:
    return "." + ticker.rsplit(".", 1)[1] if "." in ticker else ""


def tradability(ticker: str) -> str:
    if ticker in config.TRADABILITY_OVERRIDES:
        return config.TRADABILITY_OVERRIDES[ticker]
    return "Yes" if suffix_of(ticker) in config.BROKER_MARKETS else "Watch only"


@dataclass
class RunHealth:
    sources: dict = field(default_factory=dict)   # name -> (status, detail)
    degraded: bool = False
    degraded_reasons: list = field(default_factory=list)
    started: str = ""

    def record(self, source: str, status: str, detail: str = ""):
        """status: ok / partial / failed / skipped"""
        self.sources[source] = (status, detail)


HEALTH = RunHealth()


def _quote_age_days(price_time: str, now: datetime) -> float:
    try:
        t = datetime.strptime(price_time, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - t).total_seconds() / 86400


def check_ticker(opp: Opportunity, now: datetime) -> list[str]:
    flags = []
    if opp.price <= 0:
        return ["no price"]
    age = _quote_age_days(opp.price_time, now) if opp.price_time else None
    if age is not None and age > config.MAX_QUOTE_AGE_DAYS:
        flags.append("stale quote")
    if not opp.price_time:
        flags.append("no quote time")
    if len(opp.hist_prices) < 60:
        flags.append("short history")
    if opp.quote_type != "ETF" and not opp.mcap:
        flags.append("no market cap")
    if not opp.financial_currency:
        flags.append("no statement currency")
    if opp.target and (opp.analyst_count or 0) < 3:
        flags.append("fewer than 3 analysts")
    if opp.price_check == "Mismatch":
        flags.append("price mismatch")
    expected = config.SUFFIX_CURRENCY.get(suffix_of(opp.ticker))
    if expected and opp.currency != expected:
        flags.append("wrong listing")
    if opp.avg_volume is not None and opp.avg_volume * opp.price < config.MIN_DAILY_VALUE_TRADED:
        flags.append("low liquidity")
    return flags


def apply_gate(opportunities: list[Opportunity], held_tickers: list[str],
               now: datetime = None) -> RunHealth:
    now = now or datetime.now(timezone.utc)
    for opp in opportunities:
        opp.data_flags = check_ticker(opp, now)
        opp.data_ok = not any(f in CRITICAL for f in opp.data_flags)
        opp.tradable = tradability(opp.ticker)

    by_ticker = {o.ticker: o for o in opportunities}
    missing_held = [t for t in held_tickers if t not in by_ticker or not by_ticker[t].data_ok]
    failed = [o for o in opportunities if not o.data_ok]
    share = len(failed) / len(opportunities) if opportunities else 1.0

    HEALTH.degraded_reasons = []
    if missing_held:
        HEALTH.degraded_reasons.append("Holdings without usable data: " + ", ".join(missing_held))
    if share > config.MAX_FAILED_SHARE:
        HEALTH.degraded_reasons.append(f"{share:.0%} of tickers failed the data check "
                                       f"(limit {config.MAX_FAILED_SHARE:.0%})")
    HEALTH.degraded = bool(HEALTH.degraded_reasons)
    HEALTH.record("Data-quality gate", "failed" if HEALTH.degraded else "ok",
                  f"{len(opportunities) - len(failed)}/{len(opportunities)} tickers usable")
    return HEALTH
